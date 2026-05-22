from __future__ import annotations

import discord
from discord.ext import commands
from discord import app_commands

from core.time_utils import get_taipei_now, get_taipei_now_iso
from core.permissions import has_role, is_customer_staff
from core.database import save_bot_data
from services.logging_service import send_order_log
from services.rewards import (
    get_customer_reward_data,
    get_customer_notes,
    format_customer_notes_for_staff,
)


class CustomerCommands(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    def require_customer_staff_or_manager(self, interaction: discord.Interaction) -> bool:
        manager_role_id = int(getattr(self.bot, "manager_role_id_value", 0) or 0)
        return (
            isinstance(interaction.user, discord.Member)
            and (
                is_customer_staff(interaction.user)
                or has_role(interaction.user, manager_role_id)
                or interaction.user.guild_permissions.administrator
            )
        )

    @app_commands.command(
        name="add_customer_note",
        description="客服新增顧客備註或黑名單紀錄",
    )
    @app_commands.describe(
        customer="要新增備註的顧客",
        note="備註內容",
        blacklist="是否標記為黑名單 / 高風險備註",
    )
    async def add_customer_note(
        self,
        interaction: discord.Interaction,
        customer: discord.Member,
        note: str,
        blacklist: bool = False,
    ):
        if not self.require_customer_staff_or_manager(interaction):
            await interaction.response.send_message("只有客服、店長或管理員可以新增顧客備註。", ephemeral=True)
            return

        content = note.strip()[:500]
        if not content:
            await interaction.response.send_message("備註內容不能空白。", ephemeral=True)
            return

        data = get_customer_reward_data(customer.id)
        notes = data.setdefault("notes", [])
        notes.append({
            "content": content,
            "is_blacklist": bool(blacklist),
            "operator_id": interaction.user.id,
            "created_at": get_taipei_now_iso(),
        })
        save_bot_data()

        await send_order_log(
            interaction.guild,
            title="新增顧客備註",
            fields=[
                ("顧客", customer.mention, True),
                ("類型", "黑名單 / 高風險" if blacklist else "一般備註", True),
                ("操作人員", interaction.user.mention, True),
                ("內容", content, False),
            ],
            color=discord.Color.red() if blacklist else discord.Color.blue(),
        )

        await interaction.response.send_message(
            f"已新增 {'黑名單 / 高風險' if blacklist else '一般'}備註給 {customer.mention}。",
            ephemeral=True,
            allowed_mentions=discord.AllowedMentions(users=True, roles=False, everyone=False),
        )

    @app_commands.command(
        name="customer_notes",
        description="客服查詢顧客備註 / 黑名單紀錄",
    )
    @app_commands.describe(customer="要查詢備註的顧客")
    async def customer_notes(self, interaction: discord.Interaction, customer: discord.Member):
        if not self.require_customer_staff_or_manager(interaction):
            await interaction.response.send_message("只有客服、店長或管理員可以查詢顧客備註。", ephemeral=True)
            return

        embed = discord.Embed(
            title="顧客備註 / 黑名單紀錄",
            description=format_customer_notes_for_staff(customer.id, limit=15),
            color=discord.Color.red() if any(n.get("is_blacklist") for n in get_customer_notes(customer.id)) else discord.Color.blue(),
            timestamp=get_taipei_now(),
        )
        embed.add_field(name="顧客", value=customer.mention, inline=False)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(
        name="remove_customer_note",
        description="客服刪除顧客備註，index 請看 /customer_notes 的編號",
    )
    @app_commands.describe(
        customer="要刪除備註的顧客",
        index="要刪除第幾筆備註，從 1 開始",
    )
    async def remove_customer_note(self, interaction: discord.Interaction, customer: discord.Member, index: int):
        if not self.require_customer_staff_or_manager(interaction):
            await interaction.response.send_message("只有客服、店長或管理員可以刪除顧客備註。", ephemeral=True)
            return

        data = get_customer_reward_data(customer.id)
        notes = data.setdefault("notes", [])
        if index < 1 or index > len(notes):
            await interaction.response.send_message("找不到這個備註編號，請先用 /customer_notes 查看。", ephemeral=True)
            return

        removed = notes.pop(index - 1)
        save_bot_data()

        await send_order_log(
            interaction.guild,
            title="刪除顧客備註",
            fields=[
                ("顧客", customer.mention, True),
                ("操作人員", interaction.user.mention, True),
                ("刪除內容", str(removed.get("content") or "未填寫"), False),
            ],
            color=discord.Color.dark_grey(),
        )

        await interaction.response.send_message(f"已刪除 {customer.mention} 的第 {index} 筆備註。", ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(CustomerCommands(bot))
