from __future__ import annotations


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
}

QUANTITY_SELECT_ITEMS = {
    "娛樂陪",
    "技術陪",
}

QUANTITY_OPTIONS = list(range(1, 9))


_ORDER_SELECTIONS: dict[int, dict] = {}
_PARSE_RECEIPT_AMOUNT = None


def configure_order_helpers(order_selections: dict[int, dict], parse_receipt_amount_func=None) -> None:
    global _ORDER_SELECTIONS, _PARSE_RECEIPT_AMOUNT
    _ORDER_SELECTIONS = order_selections
    _PARSE_RECEIPT_AMOUNT = parse_receipt_amount_func


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

