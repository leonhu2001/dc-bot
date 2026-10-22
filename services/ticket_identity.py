from __future__ import annotations

import re

import discord

from core.time_utils import get_taipei_now


_RECRUIT_APPLICANT_ROLE_ID = 0

_ORDER_TICKET_STATUS_EMOJI = {
    "created": "🟢",
    "pending_cs_dispatch": "🟡",
    "waiting_acceptance": "🟡",
    "accepted_pending_pay": "🟡",
    "paid": "🟢",
    "active": "🟢",
    "stored": "🟠",
    "closed": "⚫",
    "cancelled": "🔴",
    "canceled": "🔴",
}


def configure_ticket_identity(*, recruit_applicant_role_id: int) -> None:
    global _RECRUIT_APPLICANT_ROLE_ID
    _RECRUIT_APPLICANT_ROLE_ID = int(recruit_applicant_role_id or 0)


def _clean_ticket_channel_part(value: str, *, fallback: str = "user") -> str:
    clean = "".join(ch.lower() if ch.isalnum() else "-" for ch in str(value))
    clean = re.sub(r"-+", "-", clean).strip("-")
    return clean or fallback


def _order_status_emoji_from_prefix(prefix: str) -> str:
    text = str(prefix or "").strip().lower()

    for emoji in ("🔴", "⚫", "🟠", "🟡", "🟢", "⚪"):
        if emoji in text:
            return emoji

    if any(token in text for token in ("取消", "cancel")):
        return "🔴"
    if any(token in text for token in ("結單", "closed")):
        return "⚫"
    if any(token in text for token in ("存單", "stored", "暫存")):
        return "🟠"
    if any(token in text for token in ("等待", "待付款", "待接單", "pending", "acceptance")):
        return "🟡"
    return "🟢"


def _is_order_creation_prefix(prefix: str) -> bool:
    text = str(prefix or "").strip().lower()
    return any(token in text for token in ("下單", "點單", "訂單", "客服中心"))


def order_ticket_channel_name_for_status(status: str | None) -> str:
    normalized = str(status or "created").strip().lower()
    emoji = _ORDER_TICKET_STATUS_EMOJI.get(normalized, "🟢")
    return f"{emoji}・客服中心"


def build_ticket_channel_name(
    prefix: str,
    member: discord.Member | None = None,
    *,
    display_name: str | None = None,
) -> str:
    # New order tickets are intentionally anonymous in the channel list. The
    # customer identity remains in the channel topic / order data.
    if _is_order_creation_prefix(prefix):
        return f"{_order_status_emoji_from_prefix(prefix)}・客服中心"

    raw_name = (
        display_name
        or (member.display_name if member is not None else None)
        or "user"
    )
    prefix_part = _clean_ticket_channel_part(prefix, fallback="ticket")
    name_part = _clean_ticket_channel_part(raw_name, fallback="user")
    date_part = get_taipei_now().strftime("%m%d")
    return f"{prefix_part}-{name_part}-{date_part}"[:90]


def safe_channel_name(prefix: str, member: discord.Member) -> str:
    return build_ticket_channel_name(prefix, member)


async def rename_ticket_channel(
    channel: discord.abc.GuildChannel | None,
    prefix: str,
    member: discord.Member | None = None,
    *,
    display_name: str | None = None,
) -> None:
    if not isinstance(channel, discord.TextChannel):
        return

    # Status-only naming applies strictly to order tickets. Recruitment and other
    # support tickets keep their existing prefix/name/date format.
    if "order_customer_id=" in str(channel.topic or ""):
        new_name = f"{_order_status_emoji_from_prefix(prefix)}・客服中心"
    else:
        new_name = build_ticket_channel_name(prefix, member, display_name=display_name)

    if channel.name == new_name:
        return

    try:
        await channel.edit(name=new_name, reason=f"Ticket status changed: {prefix}")
    except discord.Forbidden:
        print(f"Bot 權限不足，無法更改票口名稱：{channel.id} -> {new_name}")
    except discord.HTTPException as exc:
        print(f"更改票口名稱失敗：{channel.id} -> {new_name}：{exc}")


def is_agree_answer(text: str) -> bool:
    answer = text.strip().lower()
    agree_words = {
        "是",
        "有",
        "已詳閱",
        "已詳讀",
        "已閱讀",
        "我已詳閱",
        "我已詳讀",
        "我已閱讀",
        "同意",
        "yes",
        "y",
        "ok",
        "okay",
    }
    return answer in agree_words


def _topic_values(channel: discord.TextChannel) -> dict[str, str]:
    if not channel.topic:
        return {}

    data: dict[str, str] = {}
    for part in channel.topic.split(";"):
        if "=" not in part:
            continue
        key, value = part.split("=", 1)
        data[key.strip()] = value.strip()
    return data


def get_recruit_info_from_channel(channel: discord.TextChannel) -> tuple[str, str]:
    data = _topic_values(channel)
    return (
        data.get("recruit_nickname", "未紀錄暱稱"),
        data.get("recruit_position", "未紀錄職位"),
    )


def get_recruit_member_id_from_channel(channel: discord.TextChannel) -> int | None:
    recruit_member_id = _topic_values(channel).get("recruit_member_id")
    if recruit_member_id is None:
        return None

    try:
        return int(recruit_member_id)
    except ValueError:
        return None


async def remove_recruit_applicant_role(
    guild: discord.Guild | None,
    channel: discord.abc.GuildChannel | None,
) -> None:
    if guild is None or not isinstance(channel, discord.TextChannel):
        return

    recruit_member_id = get_recruit_member_id_from_channel(channel)
    if recruit_member_id is None:
        return

    member = guild.get_member(recruit_member_id)
    role = guild.get_role(_RECRUIT_APPLICANT_ROLE_ID)
    if member is None or role is None or role not in member.roles:
        return

    try:
        await member.remove_roles(role, reason="Recruit ticket closed")
    except discord.Forbidden:
        print("Bot 權限不足，無法收回入職申請暫時身分組。請確認 Bot 身分組位置高於該身分組。")
    except discord.HTTPException as exc:
        print(f"收回入職申請暫時身分組失敗：{exc}")


def get_order_customer_id_from_channel(channel: discord.TextChannel) -> int | None:
    """Resolve order customer ID from topic, falling back to legacy channel name."""
    customer_id = _topic_values(channel).get("order_customer_id")
    if customer_id is not None:
        try:
            return int(customer_id)
        except ValueError:
            pass

    try:
        return int(channel.name.rsplit("-", 1)[-1])
    except ValueError:
        return None
