from __future__ import annotations

from datetime import timedelta

import discord
from discord.ext import commands
from discord import app_commands

from core.permissions import has_role, is_customer_staff
from core.time_utils import get_taipei_now
from services.logging_service import send_order_log
from services.rewards import (
    format_t_amount,
    get_effective_member_level,
    iter_customer_reward_items,
    run_vip_downgrade_check,
)
from services.stats import build_sales_stats_embed


class StatsCommands(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    def manager_role_id(self) -> int:
        return int(getattr(self.bot, "manager_role_id_value", 0) or 0)

    def vip_maintain_min_monthly_spend(self) -> int:
        return int(getattr(self.bot, "vip_maintain_min_monthly_spend_value", 500) or 500)

    def can_customer_staff(self, member: discord.Member) -> bool:
        return (
            is_customer_staff(member)
            or has_role(member, self.manager_role_id())
            or member.guild_permissions.administrator
        )

    @app_commands.command(
        name="stats_today",
        description="客服查詢今日營運統計",
    )
    @app_commands.default_permissions(manage_messages=True)
    async def stats_today(self, interaction: discord.Interaction):
        if not isinstance(interaction.user, discord.Member) or not self.can_customer_staff(interaction.user):
            await interaction.response.send_message("只有客服、店長或管理員可以查詢營運統計。", ephemeral=True)
            return

        now = get_taipei_now()
        start_dt = now.replace(hour=0, minute=0, second=0, microsecond=0)
        end_dt = start_dt + timedelta(days=1)
        embed = build_sales_stats_embed("今日營運統計", start_dt, end_dt)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(
        name="stats_month",
        description="客服查詢本月營運統計",
    )
    @app_commands.default_permissions(manage_messages=True)
    async def stats_month(self, interaction: discord.Interaction):
        if not isinstance(interaction.user, discord.Member) or not self.can_customer_staff(interaction.user):
            await interaction.response.send_message("只有客服、店長或管理員可以查詢營運統計。", ephemeral=True)
            return

        now = get_taipei_now()
        start_dt = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        if start_dt.month == 12:
            end_dt = start_dt.replace(year=start_dt.year + 1, month=1)
        else:
            end_dt = start_dt.replace(month=start_dt.month + 1)
        embed = build_sales_stats_embed("本月營運統計", start_dt, end_dt)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(
        name="top_customers",
        description="客服查詢顧客累積消費排行前 10 名",
    )
    @app_commands.default_permissions(manage_messages=True)
    async def top_customers(self, interaction: discord.Interaction):
        if not isinstance(interaction.user, discord.Member) or not self.can_customer_staff(interaction.user):
            await interaction.response.send_message("只有客服、店長或管理員可以查詢顧客排行。", ephemeral=True)
            return

        ranked = []
        for user_id, data in iter_customer_reward_items():
            if not isinstance(data, dict):
                continue
            total_spent = int(data.get("total_spent", 0) or 0)
            if total_spent <= 0:
                continue
            ranked.append(
                (
                    int(user_id),
                    total_spent,
                    int(data.get("order_count", 0) or 0),
                    get_effective_member_level(data)["name"],
                )
            )

        ranked.sort(key=lambda row: row[1], reverse=True)
        top_rows = ranked[:10]

        embed = discord.Embed(
            title="顧客消費排行 TOP 10",
            color=discord.Color.gold(),
            timestamp=get_taipei_now(),
        )

        if not top_rows:
            embed.description = "目前還沒有可排行的顧客消費資料。"
        else:
            lines = []
            medals = ["🥇", "🥈", "🥉"]
            for index, (user_id, total_spent, order_count, level_name) in enumerate(top_rows, start=1):
                prefix = medals[index - 1] if index <= 3 else f"#{index}"
                lines.append(
                    f"{prefix} <@{user_id}>｜{format_t_amount(total_spent)}｜{order_count:,} 單｜{level_name}"
                )
            embed.description = "\n".join(lines)

        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(
        name="check_vip_downgrades",
        description="管理員手動檢查 VIP 維持條件並執行降階",
    )
    @app_commands.describe(force="是否強制重新檢查本月，預設否")
    @app_commands.default_permissions(manage_messages=True)
    async def check_vip_downgrades(self, interaction: discord.Interaction, force: bool = False):
        if not isinstance(interaction.user, discord.Member) or not self.can_customer_staff(interaction.user):
            await interaction.response.send_message("只有客服、店長或管理員可以檢查 VIP 降階。", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)
        maintain_spend = self.vip_maintain_min_monthly_spend()
        changed_count, messages = await run_vip_downgrade_check(
            interaction.guild,
            force=force,
            maintain_min_monthly_spend=maintain_spend,
            send_log_func=send_order_log,
        )

        if changed_count == 0:
            await interaction.followup.send(
                f"檢查完成，目前沒有需要降階的會員。維持條件：上月消費滿 {format_t_amount(maintain_spend)}。",
                ephemeral=True,
            )
            return

        preview = "\n".join(messages[:10])
        if len(messages) > 10:
            preview += f"\n…還有 {len(messages) - 10} 位"

        await interaction.followup.send(
            f"VIP 降階檢查完成，已降階 {changed_count} 位會員。\n{preview}",
            ephemeral=True,
            allowed_mentions=discord.AllowedMentions(users=True, roles=False, everyone=False),
        )


async def setup(bot: commands.Bot):
    await bot.add_cog(StatsCommands(bot))
