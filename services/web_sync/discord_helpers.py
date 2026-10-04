from __future__ import annotations

from typing import Any

import discord

from services.orders import _to_int


PREFERRED_DISPATCH_FIELD_ORDER = [
    "下單用戶",
    "訂單類別",
    "訂單項目",
    "數量",
    "付款方式",
    "指定選項",
    "接單人員",
    "來源票口",
    "接單狀態",
]

RECEIVER_FIELD_NAMES = {
    "目前接單",
    "接單人員",
    "接單狀態",
    "打手接單",
    "陪玩接單",
    "已接人員",
}


def normalize_dispatch_embed_field_order(embed: discord.Embed) -> discord.Embed:
    """Normalize dispatch panel field names/order to the Discord Bot format."""
    fields: list[dict[str, Any]] = []

    for field in embed.fields:
        name = str(field.name or "").strip()
        value = str(field.value or "").strip()

        if name in {"目前接單", "目前接單人", "接單人員"}:
            name = "接單人員"

        if name == "目前狀態":
            name = "接單狀態"

        fields.append(
            {
                "name": name,
                "value": value or "—",
                "inline": field.inline,
            }
        )

    embed.clear_fields()
    used = [False] * len(fields)

    for preferred_name in PREFERRED_DISPATCH_FIELD_ORDER:
        for index, field in enumerate(fields):
            if used[index] or field["name"] != preferred_name:
                continue

            inline = field["inline"]
            if preferred_name in {"訂單類別", "訂單項目", "數量"}:
                inline = True
            else:
                inline = False

            embed.add_field(
                name=preferred_name,
                value=field["value"],
                inline=inline,
            )
            used[index] = True

    for index, field in enumerate(fields):
        if used[index]:
            continue

        embed.add_field(
            name=field["name"],
            value=field["value"],
            inline=field["inline"],
        )

    return embed


def embed_without_receiver_fields(embed: discord.Embed) -> discord.Embed:
    old_fields = list(embed.fields)
    embed.clear_fields()

    for field in old_fields:
        if str(field.name).strip() in RECEIVER_FIELD_NAMES:
            continue

        embed.add_field(
            name=field.name,
            value=field.value,
            inline=field.inline,
        )

    return embed


async def get_member(
    guild: discord.Guild,
    customer_id: int,
):
    member = guild.get_member(int(customer_id))
    if member is not None:
        return member

    try:
        return await guild.fetch_member(int(customer_id))
    except Exception as exc:
        raise RuntimeError(
            f"找不到網站下單顧客 Discord 成員：{customer_id}"
        ) from exc


async def get_channel(
    guild: discord.Guild,
    channel_id: Any,
):
    parsed_id = _to_int(channel_id, None)
    if parsed_id is None:
        return None

    channel = guild.get_channel(parsed_id)
    if channel is not None:
        return channel

    try:
        return await guild.fetch_channel(parsed_id)
    except Exception:
        return None


async def find_ticket(
    guild: discord.Guild,
    order_id: int,
    stored_channel_id: Any,
):
    channel = await get_channel(guild, stored_channel_id)

    if isinstance(channel, discord.TextChannel):
        return channel

    marker = f"web_order_id={order_id}"

    for candidate in guild.text_channels:
        topic = str(candidate.topic or "")
        if marker in topic:
            return candidate

    return None


async def has_footer(
    channel: discord.TextChannel,
    footer_text: str,
    *,
    limit: int = 25,
) -> bool:
    try:
        async for message in channel.history(limit=int(limit)):
            for embed in message.embeds:
                footer = getattr(embed, "footer", None)
                text = str(
                    getattr(footer, "text", "")
                    or ""
                )

                if footer_text in text:
                    return True

    except discord.HTTPException:
        return False

    return False
