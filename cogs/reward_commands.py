from __future__ import annotations

import discord
from discord.ext import commands
from discord import app_commands

from core.time_utils import get_taipei_now_iso
from core.database import save_bot_data
from core.permissions import has_role, is_customer_staff, is_manager_or_admin
from services.logging_service import send_order_log
from services.rewards import (
    get_customer_reward_data,
    build_member_info_embed,
    adjust_customer_points,
    add_manual_purchase,
    format_t_amount,
    parse_manual_purchase_date,
    get_current_reward_points,
    ensure_reward_member_benefits,
)


class RewardCommands(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    def manager_role_id(self) -> int:
        return int(getattr(self.bot, "manager_role_id_value", 0) or 0)

    def can_customer_staff(self, member: discord.Member) -> bool:
        return is_customer_staff(member) or has_role(member, self.manager_role_id()) or member.guild_permissions.administrator

    @app_commands.command(
        name="my_points",
        description="查詢自己的魔丸會員資料",
    )
    async def my_points(self, interaction: discord.Interaction):
        data = get_customer_reward_data(interaction.user.id)
        embed = build_member_info_embed(interaction.user, data, show_points=True)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(
        name="customer_points",
        description="客服查詢指定顧客的魔丸會員資料",
    )
    @app_commands.describe(customer="要查詢的顧客")
    @app_commands.default_permissions(manage_messages=True)
    async def customer_points(self, interaction: discord.Interaction, customer: discord.Member):
        if not isinstance(interaction.user, discord.Member):
            await interaction.response.send_message("無法確認你的身分組。", ephemeral=True)
            return

        if not self.can_customer_staff(interaction.user):
            await interaction.response.send_message("只有客服或店長可以查詢顧客會員資料。", ephemeral=True)
            return

        data = get_customer_reward_data(customer.id)
        embed = build_member_info_embed(customer, data, show_points=True)
        embed.title = "顧客會員資料"
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(
        name="adjust_points",
        description="客服調整顧客魔丸點數，可輸入正數加點或負數扣點",
    )
    @app_commands.describe(
        customer="要調整點數的顧客",
        points="調整點數，正數為加點，負數為扣點，例如 10 或 -10",
        reason="調整原因，可不填",
    )
    @app_commands.default_permissions(manage_messages=True)
    async def adjust_points(
        self,
        interaction: discord.Interaction,
        customer: discord.Member,
        points: int,
        reason: str | None = None,
    ):
        if not isinstance(interaction.user, discord.Member):
            await interaction.response.send_message("無法確認你的身分組。", ephemeral=True)
            return

        if not self.can_customer_staff(interaction.user):
            await interaction.response.send_message("只有客服或店長可以調整顧客點數。", ephemeral=True)
            return

        ok, message = await adjust_customer_points(
            customer_id=customer.id,
            delta_points=points,
            operator_id=interaction.user.id,
            reason=reason,
        )

        if ok:
            await send_order_log(
                interaction.guild,
                title="會員點數已調整",
                fields=[
                    ("顧客", customer.mention, True),
                    ("操作人員", interaction.user.mention, True),
                    ("點數變動", f"{points:+,} 點", True),
                    ("原因", reason or "未填寫", False),
                ],
                color=discord.Color.orange(),
            )

        await interaction.response.send_message(message, ephemeral=True)

    @app_commands.command(
        name="add_purchase",
        description="客服補登單筆顧客歷史消費",
    )
    @app_commands.describe(
        customer="要補登的顧客",
        amount="消費金額，例如 900",
        date="完成日期，例如 20260512、2026/05/12 或 2026-05-12",
        note="備註，可不填",
    )
    @app_commands.default_permissions(manage_messages=True)
    async def add_purchase(
        self,
        interaction: discord.Interaction,
        customer: discord.Member,
        amount: int,
        date: str,
        note: str | None = None,
    ):
        if not isinstance(interaction.user, discord.Member):
            await interaction.response.send_message("無法確認你的身分組。", ephemeral=True)
            return

        if not self.can_customer_staff(interaction.user):
            await interaction.response.send_message("只有客服或店長可以補登會員消費。", ephemeral=True)
            return

        guild = interaction.guild
        if guild is None:
            await interaction.response.send_message("這個功能只能在伺服器內使用。", ephemeral=True)
            return

        ok, message = await add_manual_purchase(
            guild=guild,
            customer_id=customer.id,
            amount=amount,
            date_text=date,
            operator_id=interaction.user.id,
            note=note,
        )

        if ok:
            await send_order_log(
                guild,
                title="歷史消費已補登",
                fields=[
                    ("顧客", customer.mention, True),
                    ("操作人員", interaction.user.mention, True),
                    ("金額", format_t_amount(amount), True),
                    ("日期", date, True),
                    ("備註", note or "未填寫", False),
                ],
                color=discord.Color.blue(),
            )

        await interaction.response.send_message(message, ephemeral=True)

    @app_commands.command(
        name="import_purchases",
        description="客服批量補登歷史消費，多行格式：顧客ID,金額,日期,備註",
    )
    @app_commands.describe(records="每行一筆：顧客ID,金額,日期,備註；備註可省略")
    @app_commands.default_permissions(manage_messages=True)
    async def import_purchases(self, interaction: discord.Interaction, records: str):
        if not isinstance(interaction.user, discord.Member):
            await interaction.response.send_message("無法確認你的身分組。", ephemeral=True)
            return

        if not self.can_customer_staff(interaction.user):
            await interaction.response.send_message("只有客服或店長可以批量補登會員消費。", ephemeral=True)
            return

        guild = interaction.guild
        if guild is None:
            await interaction.response.send_message("這個功能只能在伺服器內使用。", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True, thinking=True)

        success_count = 0
        skipped_count = 0
        result_lines = []

        for line_number, raw_line in enumerate(records.splitlines(), start=1):
            line = raw_line.strip()
            if not line:
                continue

            parts = [part.strip() for part in line.split(",")]
            if len(parts) < 3:
                skipped_count += 1
                result_lines.append(f"第 {line_number} 行失敗：格式不足，請用 顧客ID,金額,日期,備註")
                continue

            customer_text, amount_text, date_text = parts[0], parts[1], parts[2]
            note = ",".join(parts[3:]).strip() if len(parts) >= 4 else None
            customer_text = customer_text.replace("<@", "").replace(">", "").replace("!", "")

            try:
                customer_id = int(customer_text)
                amount = int(amount_text.replace("T", "").replace("t", "").replace(",", ""))
            except ValueError:
                skipped_count += 1
                result_lines.append(f"第 {line_number} 行失敗：顧客 ID 或金額不是數字。")
                continue

            ok, message = await add_manual_purchase(
                guild=guild,
                customer_id=customer_id,
                amount=amount,
                date_text=date_text,
                operator_id=interaction.user.id,
                note=note,
            )

            if ok:
                success_count += 1
            else:
                skipped_count += 1

            result_lines.append(message)

        summary = f"批量補登完成：成功 {success_count} 筆，跳過/失敗 {skipped_count} 筆。"
        detail = "\n".join(result_lines)
        if len(detail) > 1700:
            detail = detail[:1700] + "\n...（結果太長，已截斷）"

        await interaction.followup.send(f"{summary}\n\n{detail}", ephemeral=True)

    @app_commands.command(
        name="set_customer_rewards",
        description="管理員手動修正顧客會員資料",
    )
    @app_commands.describe(
        customer="要修正的顧客",
        total_spent="累積消費總額，不填則不修改",
        order_count="完成訂單數，不填則不修改",
        last_order_date="最後下單日期，例如 20260512、2026/05/12；不填則不修改",
        point_adjustment="額外點數修正值，可正可負；不填則不修改",
        reason="修正原因，可不填",
    )
    @app_commands.default_permissions(manage_messages=True)
    async def set_customer_rewards(
        self,
        interaction: discord.Interaction,
        customer: discord.Member,
        total_spent: int | None = None,
        order_count: int | None = None,
        last_order_date: str | None = None,
        point_adjustment: int | None = None,
        reason: str | None = None,
    ):
        if not isinstance(interaction.user, discord.Member):
            await interaction.response.send_message("無法確認你的身分組。", ephemeral=True)
            return

        if not is_manager_or_admin(interaction.user):
            await interaction.response.send_message("只有管理員或店長可以手動修正顧客會員資料。", ephemeral=True)
            return

        if total_spent is None and order_count is None and last_order_date is None and point_adjustment is None:
            await interaction.response.send_message("請至少填一個要修正的欄位。", ephemeral=True)
            return

        if total_spent is not None and total_spent < 0:
            await interaction.response.send_message("累積消費不能小於 0。", ephemeral=True)
            return

        if order_count is not None and order_count < 0:
            await interaction.response.send_message("完成訂單數不能小於 0。", ephemeral=True)
            return

        date_iso = None
        if last_order_date is not None:
            date_iso, _display_date = parse_manual_purchase_date(last_order_date)
            if date_iso is None:
                await interaction.response.send_message("最後下單日期格式錯誤，請用 20260512、2026/05/12 或 2026-05-12。", ephemeral=True)
                return

        data = get_customer_reward_data(customer.id)

        if total_spent is not None:
            data["total_spent"] = total_spent
        if order_count is not None:
            data["order_count"] = order_count
        if date_iso is not None:
            data["last_order_at"] = date_iso
        if point_adjustment is not None:
            data["point_adjustment"] = point_adjustment

        data["points"] = get_current_reward_points(data)
        data["last_manual_fixed_at"] = get_taipei_now_iso()
        data["last_manual_fixed_by"] = interaction.user.id
        data["last_manual_fixed_reason"] = (reason or "").strip()

        benefit_notices = await ensure_reward_member_benefits(interaction.guild, customer, data) if interaction.guild else []
        save_bot_data()

        after_embed = build_member_info_embed(customer, data, show_points=True)
        after_embed.title = "顧客會員資料已修正"
        if reason:
            after_embed.add_field(name="修正原因", value=reason, inline=False)
        if benefit_notices:
            after_embed.add_field(name="會員權益處理", value="\n".join(benefit_notices), inline=False)

        await send_order_log(
            interaction.guild,
            title="顧客會員資料已手動修正",
            fields=[
                ("顧客", customer.mention, True),
                ("操作人員", interaction.user.mention, True),
                ("累積消費", format_t_amount(int(data.get("total_spent", 0) or 0)), True),
                ("完成訂單", f"{int(data.get('order_count', 0) or 0)} 單", True),
                ("目前點數", f"{get_current_reward_points(data):,} 點", True),
                ("原因", reason or "未填寫", False),
            ],
            color=discord.Color.orange(),
        )

        await interaction.response.send_message(embed=after_embed, ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(RewardCommands(bot))
    guild_id = int(getattr(bot, "guild_id_value", 0) or 0)
    if guild_id:
        bot.tree.copy_global_to(guild=discord.Object(id=guild_id))
