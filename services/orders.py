from __future__ import annotations

from typing import Callable, Any

import discord


def _to_int(value, default: int | None = None) -> int | None:
    try:
        if value is None or value == "":
            return default
        return int(value)
    except (TypeError, ValueError):
        return default


ORDER_CATEGORY_LABELS = {
    "basic": "?箇???,
    "fun": "頞???,
    "farm": "隞?圾隞??",
    "season": "鞈賢迤??瘣餃?",
    "valorant": "Valorant",
}

ORDER_ITEMS_BY_CATEGORY = {
    # 雿輻??瘙銝銝??隞乩???憿舐內??擃??桅?憪?銝??唳硃?
    "basic": [
        "擃???,
        "憡???,
        "?銵",
        "靽???,
        "鞈剔???,
        "瘝寥???,
    ],
    "fun": [
        "鞊芸雿???,
        "???嗅",
        "??暻潮野瑽?,
        "?喳??芸楛??,
    ],
    "farm": [
        "鞈賢迤3x3",
        "蝝?隞???井撟?,
    ],
    "season": [
        "?????,
        "S9?怠蔗?????,
    ],
    "valorant": [
        "?芣?",
        "隞??",
    ],
}

ORDER_ITEM_TO_CATEGORY = {
    item: category
    for category, items in ORDER_ITEMS_BY_CATEGORY.items()
    for item in items
}

SPECIAL_COMPANION_ITEMS = {
    "憡???,
    "?銵",
    "靽???,
    "?芣?",
}

QUANTITY_SELECT_ITEMS = {
    "憡???,
    "?銵",
    "?芣?",
    "隞??",
}

QUANTITY_OPTIONS = list(range(1, 9))


_ORDER_SELECTIONS: dict[int, dict] = {}
_PARSE_RECEIPT_AMOUNT = None
_GUILD_ID = 0
_DISPATCH_CHANNEL_ID = 0
_FORMAT_AMOUNT: Callable[[int], str] | None = None
_GET_NOW: Callable[[], Any] | None = None


def _format_amount(amount: int) -> str:
    if _FORMAT_AMOUNT is not None:
        return _FORMAT_AMOUNT(amount)
    return f"{int(amount or 0):,}T"


def configure_order_helpers(
    order_selections: dict[int, dict],
    parse_receipt_amount_func=None,
    *,
    guild_id: int = 0,
    dispatch_channel_id: int = 0,
    format_amount_func: Callable[[int], str] | None = None,
    get_now_func: Callable[[], Any] | None = None,
) -> None:
    global _ORDER_SELECTIONS, _PARSE_RECEIPT_AMOUNT, _GUILD_ID, _DISPATCH_CHANNEL_ID, _FORMAT_AMOUNT, _GET_NOW
    _ORDER_SELECTIONS = order_selections
    _PARSE_RECEIPT_AMOUNT = parse_receipt_amount_func
    _GUILD_ID = int(guild_id or 0)
    _DISPATCH_CHANNEL_ID = int(dispatch_channel_id or 0)
    _FORMAT_AMOUNT = format_amount_func
    _GET_NOW = get_now_func


def find_order_by_identifier(identifier: str) -> tuple[int | None, dict | None]:
    """?刻??桃楊??蟡典 ID 敺??園?閮鞈??曉??""
    key = str(identifier or "").strip()
    if not key:
        return None, None

    channel_id = _to_int(key)
    if channel_id is not None and channel_id in _ORDER_SELECTIONS:
        data = _ORDER_SELECTIONS.get(channel_id)
        if isinstance(data, dict):
            return channel_id, data

    key_lower = key.lower()
    for order_channel_id, data in _ORDER_SELECTIONS.items():
        if not isinstance(data, dict):
            continue
        candidates = [
            data.get("order_no"),
            data.get("receipt_id"),
            str(order_channel_id),
        ]
        if any(str(value or "").strip().lower() == key_lower for value in candidates):
            return int(order_channel_id), data

    return None, None


def is_order_closed_for_rewards(data: dict) -> bool:
    status = str(data.get("status") or "").lower()
    return bool(data.get("reward_counted") or data.get("closed") or status == "closed")


def get_order_amount_for_maintenance(data: dict) -> int:
    """Safely parse order amount for maintenance commands."""
    if not isinstance(data, dict):
        return 0

    for key in ("amount", "total_amount", "reward_amount"):
        value = data.get(key)
        if value is None or value == "":
            continue
        try:
            return max(0, int(value))
        except (TypeError, ValueError):
            if _PARSE_RECEIPT_AMOUNT is not None:
                parsed = _PARSE_RECEIPT_AMOUNT(str(value))
                if parsed is not None:
                    return max(0, int(parsed))

    return 0

def get_order_amount_for_stats(data: dict) -> int:
    """Safely parse order amount for sales/statistics reports."""
    if not isinstance(data, dict):
        return 0

    for key in ("reward_amount", "amount", "total_amount"):
        value = data.get(key)
        if value is None:
            continue
        try:
            return int(value)
        except (TypeError, ValueError):
            if _PARSE_RECEIPT_AMOUNT is not None:
                parsed = _PARSE_RECEIPT_AMOUNT(str(value))
                if parsed is not None:
                    return int(parsed)
    return 0


def is_closed_order_for_stats(data: dict) -> bool:
    """Return whether an order should count as completed in sales stats."""
    if not isinstance(data, dict):
        return False
    return bool(data.get("closed")) or str(data.get("status", "")).lower() == "closed"


def is_stored_order_for_stats(data: dict) -> bool:
    """Return whether an order is currently stored/paused."""
    if not isinstance(data, dict):
        return False
    return str(data.get("status", "")).lower() == "stored"


def is_cancelled_order_for_stats(data: dict) -> bool:
    """Return whether an order is cancelled, accepting both spellings."""
    if not isinstance(data, dict):
        return False
    return str(data.get("status", "")).lower() in {"cancelled", "canceled"}

def get_order_summary_from_channel(channel_id: int) -> tuple[str, str]:
    """
    敺?拐??格摮???敺?摰寡?隞狡?孵???    ?批捆?窒?券???芸銝?Ｘ?貊?憿???株????賊???    """
    data = _ORDER_SELECTIONS.get(channel_id, {})

    category = data.get("category")
    item = data.get("item")
    quantity = _to_int(data.get("quantity"), 1) or 1
    companion_preference = data.get("companion_preference")
    payment_method = data.get("payment_method", "?芰???)

    if item is None:
        return "?芰???拐??桀摰?, payment_method

    parts = []

    if category is not None:
        parts.append(ORDER_CATEGORY_LABELS.get(category, category))

    parts.append(item)
    parts.append(f"?賊?嚗quantity} ??)

    if companion_preference is not None:
        parts.append(companion_preference)

    return "嚚?.join(parts), payment_method


def build_self_service_order_embed(
    customer_mention: str,
    category_label: str,
    item: str,
    quantity: int,
    payment_method: str,
    source_channel: discord.TextChannel,
    companion_preference: str | None = None,
    receiver_text: str | None = None,
) -> discord.Embed:
    embed = discord.Embed(
        title="?啗?拐???,
        color=discord.Color.blue(),
    )

    embed.add_field(name="銝?冽", value=customer_mention, inline=False)
    embed.add_field(name="閮憿", value=category_label, inline=True)
    embed.add_field(name="閮?", value=item, inline=True)
    embed.add_field(name="?賊?", value=f"{quantity} ??, inline=True)
    embed.add_field(name="隞狡?孵?", value=payment_method, inline=True)

    if companion_preference is not None:
        embed.add_field(name="???賊?", value=companion_preference, inline=False)

    if receiver_text is not None:
        embed.add_field(name="?亙鈭箏", value=receiver_text, inline=False)

    embed.add_field(name="靘?蟡典", value=source_channel.mention, inline=False)
    return embed


def get_stored_order_records(limit: int = 25) -> list[tuple[int, dict]]:
    """??桀?閮擃葉???殷?靘??格???啗?????""
    records: list[tuple[int, dict]] = []

    for channel_id, data in _ORDER_SELECTIONS.items():
        if not isinstance(data, dict):
            continue
        if str(data.get("status", "")).lower() != "stored":
            continue
        records.append((int(channel_id), data))

    records.sort(
        key=lambda item: str(item[1].get("stored_at") or item[1].get("created_at") or ""),
        reverse=True,
    )
    return records[:max(1, min(int(limit or 25), 25))]


def format_stored_order_option_label(channel_id: int, data: dict) -> str:
    item = str(data.get("item") or "?芰???)[:30]
    customer_id = data.get("customer_id") or "?芰???
    amount = _to_int(data.get("amount"), 0) or 0
    amount_text = f"{amount}T" if amount else "?芰???憿?
    return f"{item}嚚customer_id}嚚amount_text}"[:100]


def format_stored_order_option_description(channel_id: int, data: dict) -> str:
    quantity = _to_int(data.get("quantity"), 1) or 1
    stored_at = str(data.get("stored_at") or "?芰?????)[:19]
    reason = str(data.get("stored_reason") or data.get("store_reason") or "?芸‵撖怠???)[:35]
    return f"{quantity} ?殷?{stored_at}嚚reason}"[:100]


def build_stored_order_detail_embed(
    guild: discord.Guild | None,
    channel_id: int | None,
    data: dict | None,
    total_count: int,
) -> discord.Embed:
    embed = discord.Embed(
        title="摮蝞∠??Ｘ",
        color=discord.Color.gold(),
        timestamp=_GET_NOW() if _GET_NOW is not None else None,
    )

    if channel_id is None or not data:
        embed.description = "?桀?瘝?摮??
        embed.add_field(name="摮?賊?", value="0 蝑?, inline=True)
        return embed

    customer_id = data.get("customer_id")
    ticket_channel = guild.get_channel(channel_id) if guild is not None else None
    dispatch_channel_id = _to_int(data.get("dispatch_channel_id"), _DISPATCH_CHANNEL_ID) or _DISPATCH_CHANNEL_ID
    dispatch_message_id = _to_int(data.get("dispatch_message_id"))
    dispatch_channel = guild.get_channel(dispatch_channel_id) if guild is not None and dispatch_channel_id else None

    ticket_text = ticket_channel.mention if isinstance(ticket_channel, discord.TextChannel) else f"蟡典 ID嚗channel_id}"
    if isinstance(dispatch_channel, discord.TextChannel) and dispatch_message_id is not None:
        dispatch_text = f"https://discord.com/channels/{_GUILD_ID}/{dispatch_channel.id}/{dispatch_message_id}"
    elif dispatch_message_id is not None:
        dispatch_text = f"瘣曉閮 ID嚗dispatch_message_id}"
    else:
        dispatch_text = "?芰???

    amount = _to_int(data.get("amount"), 0) or 0
    quantity = _to_int(data.get("quantity"), 1) or 1
    item = data.get("item") or "?芰???
    category = data.get("category")
    category_label = ORDER_CATEGORY_LABELS.get(category, data.get("category_label") or category or "?芰???)

    embed.description = f"?桀??望? **{total_count}** 蝑??柴?????殷???銝??????
    embed.add_field(name="憿批恥", value=f"<@{customer_id}>" if customer_id else "?芰???, inline=True)
    embed.add_field(name="蟡典", value=ticket_text, inline=True)
    embed.add_field(name="???, value=str(data.get("status") or "stored"), inline=True)
    embed.add_field(name="閮", value=f"{category_label}嚚item} x{quantity}", inline=False)
    embed.add_field(name="??", value=_format_amount(amount) if amount else "?芰???, inline=True)
    embed.add_field(name="隞狡?孵?", value=str(data.get("payment_method") or "?芰???), inline=True)
    embed.add_field(name="摮??", value=str(data.get("stored_at") or "?芰???), inline=False)
    embed.add_field(name="摮??", value=str(data.get("stored_reason") or data.get("store_reason") or "?芸‵撖?), inline=False)
    embed.add_field(name="???Ｗ儔", value=str(data.get("stored_expected_time") or data.get("resume_at") or "?芸‵撖?), inline=True)
    embed.add_field(name="摮?酉", value=str(data.get("stored_note") or data.get("note") or "??)[:1024], inline=False)
    embed.add_field(name="瘣曉閮", value=dispatch_text, inline=False)
    return embed


