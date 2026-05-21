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
