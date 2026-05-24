from __future__ import annotations

import io

import discord
from discord.ext import commands
from discord import app_commands

from core.permissions import has_role, is_customer_staff
from core.time_utils import get_taipei_now
from services.audit import build_audit_data_report
from services.logging_service import send_order_log


class AuditCommands(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    def manager_role_id(self) -> int:
        return int(getattr(self.bot, "manager_role_id_value", 0) or 0)

    def can_customer_staff(self, member: discord.Member) -> bool:
        return (
            is_customer_staff(member)
            or has_role(member, self.manager_role_id())
            or member.guild_permissions.administrator
        )

    @app_commands.command(
        name="audit_data",
        description="客服檢查訂單、會員累積、存單與接單面板資料是否異常",
    )
    @app_commands.describe(limit="每一類最多顯示幾筆明細，預設 10，最高 25")
    @app_commands.default_permissions(manage_messages=True)
    async def audit_data(self, interaction: discord.Interaction, limit: int = 10):
        if not isinstance(interaction.user, discord.Member) or not self.can_customer_staff(interaction.user):
            await interaction.response.send_message("只有客服、店長或管理員可以檢查資料庫健康狀態。", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)
        started_at = get_taipei_now()

        try:
            embed, full_report = build_audit_data_report(limit=limit)
        except Exception as e:
            error_text = f"/audit_data 執行失敗：{type(e).__name__}: {e}"
            await interaction.followup.send(error_text, ephemeral=True)
            await send_order_log(
                interaction.guild,
                title="資料庫健康檢查失敗",
                description=f"操作人員：{interaction.user.mention}\n```text\n{error_text[:1500]}\n```",
                color=discord.Color.red(),
            )
            return

        elapsed = (get_taipei_now() - started_at).total_seconds()
        embed.add_field(name="檢查耗時", value=f"{elapsed:.2f} 秒", inline=True)

        if len(full_report) <= 3500:
            embed.add_field(
                name="檢查明細",
                value=f"```text\n{full_report[:1000]}\n```" if len(full_report) <= 1000 else "明細較長，請看下方文字。",
                inline=False,
            )
            await interaction.followup.send(
                embed=embed,
                content=f"```text\n{full_report[:1900]}\n```" if len(full_report) <= 1900 else None,
                ephemeral=True,
                allowed_mentions=discord.AllowedMentions(users=True, roles=False, everyone=False),
            )
        else:
            report_file = discord.File(
                io.BytesIO(full_report.encode("utf-8")),
                filename=f"audit_data_{get_taipei_now().strftime('%Y%m%d_%H%M%S')}.txt",
            )
            await interaction.followup.send(
                embed=embed,
                file=report_file,
                ephemeral=True,
                allowed_mentions=discord.AllowedMentions(users=True, roles=False, everyone=False),
            )

        await send_order_log(
            interaction.guild,
            title="資料庫健康檢查",
            description=f"操作人員：{interaction.user.mention}\n耗時：{elapsed:.2f} 秒\n{embed.description}",
            color=embed.color,
        )


async def setup(bot: commands.Bot):
    await bot.add_cog(AuditCommands(bot))
