from __future__ import annotations

import io

import discord
from discord.ext import commands
from discord import app_commands

from core.permissions import has_role, is_customer_staff
from core.time_utils import get_taipei_now
from services.audit import build_audit_data_report
from services.logging_service import send_order_log


STAFF_COMMAND_TRANSLATIONS = {
    "order_search": "訂單查詢",
    "stored_orders": "存單查詢",
    "fix_order_amount": "修正訂單金額",
    "fix_order_customer": "修正訂單顧客",
    "resend_dispatch": "重新派單",
    "reward": "會員",
    "customer_points": "點數查詢",
    "adjust_points": "調整點數",
    "add_purchase": "補登消費",
    "customer": "顧客",
    "notes": "備註查詢",
    "add_note": "新增備註",
    "remove_note": "刪除備註",
    "wallet_history": "錢包流水",
    "wallet_add": "錢包加值",
    "wallet_adjust": "錢包調整",
    "wallet_refund": "錢包退款",
    "stats": "營運",
    "today": "今日",
    "month": "本月",
    "top_customers": "消費排行",
    "audit": "系統",
    "data": "資料檢查",
}


STAFF_COMMAND_PATHS = (
    "order_search",
    "stored_orders",
    "fix_order_amount",
    "fix_order_customer",
    "resend_dispatch",
    "reward customer_points",
    "reward adjust_points",
    "reward add_purchase",
    "customer notes",
    "customer add_note",
    "customer remove_note",
    "wallet_history",
    "wallet_add",
    "wallet_adjust",
    "wallet_refund",
    "stats today",
    "stats month",
    "stats top_customers",
    "audit data",
)


class StaffCommandTranslator(app_commands.Translator):
    async def translate(
        self,
        string: app_commands.locale_str,
        locale: discord.Locale,
        context: app_commands.TranslationContext,
    ) -> str | None:
        if locale is not discord.Locale.taiwan_chinese:
            return None
        return STAFF_COMMAND_TRANSLATIONS.get(string.message)


def _resolve_staff_command(
    tree: app_commands.CommandTree,
    path: str,
    guild_id: int | None,
):
    parts = [part for part in path.split() if part]
    if not parts:
        return None

    command = None
    if guild_id:
        command = tree.get_command(
            parts[0],
            guild=discord.Object(id=int(guild_id)),
        )

    if command is None:
        command = tree.get_command(parts[0])

    if command is None:
        return None

    for part in parts[1:]:
        getter = getattr(command, "get_command", None)
        if getter is None:
            return None
        command = getter(part)
        if command is None:
            return None

    return command


async def _staff_command_check(interaction: discord.Interaction) -> bool:
    member = interaction.user
    if not isinstance(member, discord.Member):
        return False

    return bool(
        is_customer_staff(member)
        or member.guild_permissions.administrator
    )


def _install_staff_command_guards(bot: commands.Bot) -> None:
    guild_id = int(getattr(bot, "guild_id_value", 0) or 0) or None

    for path in STAFF_COMMAND_PATHS:
        command = _resolve_staff_command(bot.tree, path, guild_id)
        if command is None:
            continue

        checks = getattr(command, "checks", ())
        if _staff_command_check not in checks:
            command.add_check(_staff_command_check)


class AuditCommands(commands.Cog):
    audit = app_commands.Group(name="audit", description="資料稽核")

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

    @audit.command(
        name="data",
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
    await bot.tree.set_translator(StaffCommandTranslator())
    _install_staff_command_guards(bot)
