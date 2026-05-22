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
    "basic": "基礎單",
    "fun": "趣味單",
    "farm": "代解代肝",
    "season": "賽季限定活動",
    "valorant": "Valorant",
}

ORDER_ITEMS_BY_CATEGORY = {
    # 使用者要求「由下到上」，所以下拉式顯示會從體驗單開始往上排到油鍋單
    "basic": [
        "體驗單",
        "娛樂陪",
        "技術陪",
        "保底單",
        "賭約單",
        "油鍋單",
    ],
    "fun": [
        "豪到你了嗎",
        "瘋狗嘶咬",
        "這什麼鳥槍",
        "想吃自己打",
    ],
    "farm": [
        "賽季3x3",
        "純綠代肝哈夫幣",
    ],
    "season": [
        "勇敢者行動",
        "S9炫彩勇敢者行動",
    ],
    "valorant": [
        "陪打",
        "代打",
    ],
}

ORDER_ITEM_TO_CATEGORY = {
    item: category
    for category, items in ORDER_ITEMS_BY_CATEGORY.items()
    for item in items
}

SPECIAL_COMPANION_ITEMS = {
    "娛樂陪",
    "技術陪",
    "保底單",
    "陪打",
}

QUANTITY_SELECT_ITEMS = {
    "娛樂陪",
    "技術陪",
    "陪打",
    "代打",
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
    """用訂單編號或票口 ID 從記憶體訂單資料找單。"""
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
    從自助下單暫存資料取得收據內容與付款方式。
    內容會沿用闆闆在自助下單面板選的類別、項目與指定選項。
    """
    data = _ORDER_SELECTIONS.get(channel_id, {})

    category = data.get("category")
    item = data.get("item")
    quantity = _to_int(data.get("quantity"), 1) or 1
    companion_preference = data.get("companion_preference")
    payment_method = data.get("payment_method", "未紀錄")

    if item is None:
        return "未紀錄自助下單內容", payment_method

    parts = []

    if category is not None:
        parts.append(ORDER_CATEGORY_LABELS.get(category, category))

    parts.append(item)
    parts.append(f"數量：{quantity} 單")

    if companion_preference is not None:
        parts.append(companion_preference)

    return "｜".join(parts), payment_method


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
        title="新自助下單",
        color=discord.Color.blue(),
    )

    embed.add_field(name="下單用戶", value=customer_mention, inline=False)
    embed.add_field(name="訂單類別", value=category_label, inline=True)
    embed.add_field(name="訂單項目", value=item, inline=True)
    embed.add_field(name="數量", value=f"{quantity} 單", inline=True)
    embed.add_field(name="付款方式", value=payment_method, inline=True)

    if companion_preference is not None:
        embed.add_field(name="指定選項", value=companion_preference, inline=False)

    if receiver_text is not None:
        embed.add_field(name="接單人員", value=receiver_text, inline=False)

    embed.add_field(name="來源票口", value=source_channel.mention, inline=False)
    return embed


def get_stored_order_records(limit: int = 25) -> list[tuple[int, dict]]:
    """回傳目前記憶體中的存單，依存單時間新到舊排序。"""
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
    item = str(data.get("item") or "未紀錄")[:30]
    customer_id = data.get("customer_id") or "未紀錄"
    amount = _to_int(data.get("amount"), 0) or 0
    amount_text = f"{amount}T" if amount else "未紀錄金額"
    return f"{item}｜{customer_id}｜{amount_text}"[:100]


def format_stored_order_option_description(channel_id: int, data: dict) -> str:
    quantity = _to_int(data.get("quantity"), 1) or 1
    stored_at = str(data.get("stored_at") or "未紀錄時間")[:19]
    reason = str(data.get("stored_reason") or data.get("store_reason") or "未填寫原因")[:35]
    return f"{quantity} 單｜{stored_at}｜{reason}"[:100]


def build_stored_order_detail_embed(
    guild: discord.Guild | None,
    channel_id: int | None,
    data: dict | None,
    total_count: int,
) -> discord.Embed:
    embed = discord.Embed(
        title="存單管理面板",
        color=discord.Color.gold(),
        timestamp=_GET_NOW() if _GET_NOW is not None else None,
    )

    if channel_id is None or not data:
        embed.description = "目前沒有存單。"
        embed.add_field(name="存單數量", value="0 筆", inline=True)
        return embed

    customer_id = data.get("customer_id")
    ticket_channel = guild.get_channel(channel_id) if guild is not None else None
    dispatch_channel_id = _to_int(data.get("dispatch_channel_id"), _DISPATCH_CHANNEL_ID) or _DISPATCH_CHANNEL_ID
    dispatch_message_id = _to_int(data.get("dispatch_message_id"))
    dispatch_channel = guild.get_channel(dispatch_channel_id) if guild is not None and dispatch_channel_id else None

    ticket_text = ticket_channel.mention if isinstance(ticket_channel, discord.TextChannel) else f"票口 ID：{channel_id}"
    if isinstance(dispatch_channel, discord.TextChannel) and dispatch_message_id is not None:
        dispatch_text = f"https://discord.com/channels/{_GUILD_ID}/{dispatch_channel.id}/{dispatch_message_id}"
    elif dispatch_message_id is not None:
        dispatch_text = f"派單訊息 ID：{dispatch_message_id}"
    else:
        dispatch_text = "未紀錄"

    amount = _to_int(data.get("amount"), 0) or 0
    quantity = _to_int(data.get("quantity"), 1) or 1
    item = data.get("item") or "未紀錄"
    category = data.get("category")
    category_label = ORDER_CATEGORY_LABELS.get(category, data.get("category_label") or category or "未紀錄")

    embed.description = f"目前共有 **{total_count}** 筆存單。請先選擇存單，再按下方按鈕操作。"
    embed.add_field(name="顧客", value=f"<@{customer_id}>" if customer_id else "未紀錄", inline=True)
    embed.add_field(name="票口", value=ticket_text, inline=True)
    embed.add_field(name="狀態", value=str(data.get("status") or "stored"), inline=True)
    embed.add_field(name="訂單", value=f"{category_label}｜{item} x{quantity}", inline=False)
    embed.add_field(name="金額", value=_format_amount(amount) if amount else "未紀錄", inline=True)
    embed.add_field(name="付款方式", value=str(data.get("payment_method") or "未紀錄"), inline=True)
    embed.add_field(name="存單時間", value=str(data.get("stored_at") or "未紀錄"), inline=False)
    embed.add_field(name="存單原因", value=str(data.get("stored_reason") or data.get("store_reason") or "未填寫"), inline=False)
    embed.add_field(name="預計恢復", value=str(data.get("stored_expected_time") or data.get("resume_at") or "未填寫"), inline=True)
    embed.add_field(name="存單備註", value=str(data.get("stored_note") or data.get("note") or "無")[:1024], inline=False)
    embed.add_field(name="派單訊息", value=dispatch_text, inline=False)
    return embed

