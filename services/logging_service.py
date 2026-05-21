from __future__ import annotations

from collections.abc import Callable

import discord

_ORDER_LOG_CHANNEL_NAME: str | None = None
_ORDER_LOG_CATEGORY_ID: int | None = None
_get_now: Callable[[], object] | None = None


def configure_order_logging(
    *,
    order_log_channel_name: str,
    order_log_category_id: int,
    get_now_func: Callable[[], object],
) -> None:
    global _ORDER_LOG_CHANNEL_NAME, _ORDER_LOG_CATEGORY_ID, _get_now
    _ORDER_LOG_CHANNEL_NAME = str(order_log_channel_name)
    _ORDER_LOG_CATEGORY_ID = int(order_log_category_id)
    _get_now = get_now_func


def _ensure_configured() -> tuple[str, int, Callable[[], object]]:
    if _ORDER_LOG_CHANNEL_NAME is None or _ORDER_LOG_CATEGORY_ID is None or _get_now is None:
        raise RuntimeError("order logging is not configured")
    return _ORDER_LOG_CHANNEL_NAME, _ORDER_LOG_CATEGORY_ID, _get_now


def get_or_create_order_log_channel_sync_hint() -> str:
    channel_name, category_id, _ = _ensure_configured()
    return f"{channel_name}（類別 ID：{category_id}）"


async def get_or_create_order_log_channel(guild: discord.Guild) -> discord.TextChannel | None:
    channel_name, category_id, _ = _ensure_configured()

    category = guild.get_channel(category_id)
    if not isinstance(category, discord.CategoryChannel):
        return None

    for channel in category.text_channels:
        if channel.name == channel_name:
            return channel

    try:
        return await guild.create_text_channel(
            name=channel_name,
            category=category,
            reason="Create order log channel",
        )
    except (discord.Forbidden, discord.HTTPException) as e:
        print(f"建立機器人日誌頻道失敗：{e}")
        return None


async def send_order_log(
    guild: discord.Guild | None,
    title: str,
    description: str | None = None,
    fields: list[tuple[str, str, bool]] | None = None,
    color: discord.Color | None = None,
) -> None:
    if guild is None:
        return

    _, _, get_now = _ensure_configured()
    channel = await get_or_create_order_log_channel(guild)
    if channel is None:
        print(f"找不到或無法建立機器人日誌頻道：{get_or_create_order_log_channel_sync_hint()}")
        return

    embed = discord.Embed(
        title=title,
        description=description or "",
        color=color or discord.Color.blurple(),
        timestamp=get_now(),
    )

    for name, value, inline in fields or []:
        embed.add_field(name=name, value=value if value else "未紀錄", inline=inline)

    try:
        await channel.send(embed=embed, allowed_mentions=discord.AllowedMentions.none())
    except discord.HTTPException as e:
        print(f"送出機器人日誌失敗：{e}")
