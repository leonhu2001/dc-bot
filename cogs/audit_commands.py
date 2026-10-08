from __future__ import annotations

import io

import discord
from discord.ext import commands
from discord import app_commands

from core.permissions import has_role, is_customer_staff
from core.time_utils import get_taipei_now
from services.audit import build_audit_data_report
from services.logging_service import send_order_log


# Discord zh-TW 顯示名稱。只改顯示，不改內部 command key，避免既有 Panel / callback 失效。
STAFF_COMMAND_TRANSLATIONS = {
    # top-level / groups
    "order": "訂單",
    "vip": "會員",
    "member": "會員",
    "reward": "會員管理",
    "customer": "顧客",
    "stats": "營運",
    "audit": "系統",
    "setup": "設定",
    "lottery": "抽獎",
    "staff": "人員",

    # public / member commands
    "my_favorites": "我的收藏",
    "browse_staff_profiles": "瀏覽個人牆",
    "my_wallet_history": "我的錢包流水",
    "my_info": "我的會員資料",
    "points": "我的會員資料",

    # staff profile / repair tools
    "fix_acceptance_payment_panel": "補送付款面板",
    "staff_profile_panel": "建立個人牆面板",
    "refresh_staff_profile_panel": "更新個人牆面板",
    "reward_redeem_panel": "點數兌換面板",
    "set_customer_level": "設定會員等級",

    # order tools
    '訂單查詢': "訂單查詢",
    '存單查詢': "存單查詢",
    "check_stored_orders": "檢查逾期存單",
    "delete_order": "刪除訂單",
    '修正訂單金額': "修正訂單金額",
    '修正訂單顧客': "修正訂單顧客",
    '重新派單': "重新派單",
    "delete_dispatch_panel": "刪除派單面板",

    # wallet
    '錢包流水': "錢包流水",
    '錢包加值': "錢包加值",
    '錢包調整': "錢包調整",
    '錢包退款': "錢包退款",
    "wallet_refund_order": "訂單退款至錢包",

    # rewards / customer
    "customer_points": "會員資料查詢",
    "adjust_points": "調整點數",
    "add_purchase": "補登消費",
    "import_purchases": "批量補登消費",
    "set_customer_rewards": "修正會員資料",
    "notes": "備註查詢",
    "add_note": "新增備註",
    "remove_note": "刪除備註",

    # stats / audit
    "today": "今日",
    "month": "本月",
    "top_customers": "消費排行",
    "check_vip_downgrades": "檢查會員降階",
    "data": "資料檢查",

    # setup
    "panel": "建立面板",
    "staff_panel": "客服管理面板",
    "topup_panel": "儲值面板",
    "complaint_panel": "客訴面板",
    "feedback_panel": "意見箱面板",
    "play_voice": "陪玩語音",
    "vip_voice": "會員語音",
    "public_voice": "公共語音",

    # lottery / sync
    "status": "查看狀態",
    "draw": "開獎",
    "sync_members": "同步人員",

    # common parameter names
    "keyword": "關鍵字",
    "limit": "顯示筆數",
    "channel": "頻道",
    "message_id": "訊息ID",
    "order_channel_id": "票口ID",
    "customer": "顧客",
    "amount": "金額",
    "order": "訂單",
    "adjust_customer": "同步會員累積",
    "delete_dispatch_panel": "刪除派單面板",
    "note": "備註",
    "blacklist": "黑名單",
    "index": "編號",
    "points": "點數",
    "reason": "原因",
    "date": "日期",
    "records": "紀錄",
    "total_spent": "累積消費",
    "order_count": "完成訂單數",
    "last_order_date": "最後下單日期",
    "point_adjustment": "點數修正",
    "force": "強制檢查",
    "prize": "獎品",
    "description": "說明",
    "winners": "得獎人數",
}


# 沒有特別列到的 command / group / parameter 名稱，以 token 組合做保底翻譯。
# 目的不是翻譯一般文字，而是避免新增 snake_case Slash 指令後直接露出英文。
_IDENTIFIER_TOKENS = {
    "my": "我的",
    "order": "訂單",
    "orders": "訂單",
    "stored": "存單",
    "search": "查詢",
    "check": "檢查",
    "delete": "刪除",
    "fix": "修正",
    "amount": "金額",
    "customer": "顧客",
    "customers": "顧客",
    "resend": "重送",
    "dispatch": "派單",
    "panel": "面板",
    "acceptance": "接單",
    "payment": "付款",
    "wallet": "錢包",
    "history": "流水",
    "refund": "退款",
    "add": "新增",
    "adjust": "調整",
    "reward": "會員",
    "redeem": "兌換",
    "member": "會員",
    "points": "點數",
    "purchase": "消費",
    "purchases": "消費",
    "import": "批量匯入",
    "set": "設定",
    "level": "等級",
    "info": "資料",
    "favorites": "收藏",
    "browse": "瀏覽",
    "staff": "人員",
    "profile": "個人牆",
    "profiles": "個人牆",
    "refresh": "更新",
    "notes": "備註",
    "note": "備註",
    "remove": "刪除",
    "stats": "營運",
    "today": "今日",
    "month": "本月",
    "top": "排行",
    "audit": "系統",
    "data": "資料",
    "setup": "設定",
    "topup": "儲值",
    "complaint": "客訴",
    "feedback": "意見",
    "play": "陪玩",
    "voice": "語音",
    "vip": "會員",
    "public": "公共",
    "lottery": "抽獎",
    "status": "狀態",
    "draw": "開獎",
    "sync": "同步",
    "members": "人員",
    "keyword": "關鍵字",
    "limit": "筆數",
    "channel": "頻道",
    "message": "訊息",
    "id": "ID",
    "blacklist": "黑名單",
    "index": "編號",
    "reason": "原因",
    "date": "日期",
    "records": "紀錄",
    "total": "累積",
    "spent": "消費",
    "count": "數量",
    "last": "最後",
    "point": "點數",
    "force": "強制",
    "prize": "獎品",
    "description": "說明",
    "winners": "得獎人數",
}


STAFF_COMMAND_PATHS = (
    '訂單查詢',
    '存單查詢',
    '修正訂單金額',
    '修正訂單顧客',
    '重新派單',
    '會員管理 會員資料',
    '會員管理 調整點數',
    '會員管理 補登消費',
    '顧客管理 備註查詢',
    '顧客管理 新增備註',
    '顧客管理 刪除備註',
    '錢包流水',
    '錢包加值',
    '錢包調整',
    '錢包退款',
    '營運 今日',
    '營運 本月',
    '營運 消費排行',
    '系統 資料檢查',
)


def _translate_identifier(value: str) -> str | None:
    raw = str(value or "").strip()
    if not raw:
        return None

    explicit = STAFF_COMMAND_TRANSLATIONS.get(raw)
    if explicit:
        return explicit

    parts = [part for part in raw.lower().split("_") if part]
    if not parts:
        return None

    translated = []
    for part in parts:
        text = _IDENTIFIER_TOKENS.get(part)
        if text is None:
            return None
        translated.append(text)

    result = "".join(translated)
    return result[:32] if result else None


class StaffCommandTranslator(app_commands.Translator):
    async def translate(
        self,
        string: app_commands.locale_str,
        locale: discord.Locale,
        context: app_commands.TranslationContext,
    ) -> str | None:
        if locale is not discord.Locale.taiwan_chinese:
            return None

        # 指令、群組與參數的名稱才做 identifier 翻譯；描述本身原本就是中文。
        if context.location in {
            app_commands.TranslationContextLocation.command_name,
            app_commands.TranslationContextLocation.group_name,
            app_commands.TranslationContextLocation.parameter_name,
        }:
            return _translate_identifier(string.message)

        return None


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
    audit = app_commands.Group(name='系統', description="資料稽核")

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
        name='資料檢查',
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
