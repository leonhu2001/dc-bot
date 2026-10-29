from __future__ import annotations

import asyncio
import re

import discord

from core.time_utils import get_taipei_now


_RECRUIT_APPLICANT_ROLE_ID = 0
_BACKGROUND_RENAME_TASKS: set[asyncio.Task] = set()


def configure_ticket_identity(*, recruit_applicant_role_id: int) -> None:
    global _RECRUIT_APPLICANT_ROLE_ID
    _RECRUIT_APPLICANT_ROLE_ID = int(recruit_applicant_role_id or 0)


def _clean_ticket_channel_part(value: str, *, fallback: str = "user") -> str:
    clean = "".join(ch.lower() if ch.isalnum() else "-" for ch in str(value))
    clean = re.sub(r"-+", "-", clean).strip("-")
    return clean or fallback


def build_ticket_channel_name(
    prefix: str,
    member: discord.Member | None = None,
    *,
    display_name: str | None = None,
) -> str:
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

    new_name = build_ticket_channel_name(prefix, member, display_name=display_name)
    if channel.name == new_name:
        return

    async def _apply_rename() -> None:
        try:
            await channel.edit(name=new_name, reason=f"Ticket status changed: {prefix}")
        except discord.Forbidden:
            print(f"Bot 權限不足，無法更改票口名稱：{channel.id} -> {new_name}")
        except discord.HTTPException as exc:
            print(f"更改票口名稱失敗：{channel.id} -> {new_name}：{exc}")

    # Discord 對頻道改名有獨立且偏嚴格的 rate limit。存單流程若直接 await，
    # discord.py 會在 429 時自動等待，導致「已存單」通知與 interaction followup
    # 一起被卡住。存單改名改為背景執行；真正的改名仍會在限流解除後完成。
    if str(prefix).startswith("存單-"):
        task = asyncio.create_task(_apply_rename())
        _BACKGROUND_RENAME_TASKS.add(task)
        task.add_done_callback(_BACKGROUND_RENAME_TASKS.discard)
        return

    await _apply_rename()


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
