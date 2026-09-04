from __future__ import annotations

from typing import Callable, Any

import discord

from services.order_rules import (
    CATEGORY_LABELS as RULE_CATEGORY_LABELS,
    ORDER_RULES,
    get_rules_by_category,
)


def _to_int(value, default: int | None = None) -> int | None:
    try:
        if value is None or value == "":
            return default
        return int(value)
    except (TypeError, ValueError):
        return default


ORDER_CATEGORY_LABELS = dict(RULE_CATEGORY_LABELS)

# 新自助下單固定商品表。
# UI 不再靠 rule.label 內的分隔符猜「主品項 / 規格」，所有顯示與選項都在這裡明確定義。
SELF_SERVICE_ORDER_CATALOG: dict[str, list[dict]] = {
    "basic": [
        {
            "label": "絕巴四幻神賭單",
            "details": [
                {"label": "縱橫", "value": "zongheng", "rule_key": "basic_exbar_gamble_zongheng", "quantity_unit": "單", "min_quantity": 1, "max_quantity": 1},
                {"label": "萬金淚冠", "value": "leiguan", "rule_key": "basic_exbar_gamble_leiguan", "quantity_unit": "單", "min_quantity": 1, "max_quantity": 1},
                {"label": "測距儀", "value": "rangefinder", "rule_key": "basic_exbar_gamble_rangefinder", "quantity_unit": "單", "min_quantity": 1, "max_quantity": 1},
                {"label": "天圓地方", "value": "tianyuan", "rule_key": "basic_exbar_gamble_tianyuan", "quantity_unit": "單", "min_quantity": 1, "max_quantity": 1},
            ],
        },
        {
            "label": "絕巴技術陪",
            "details": [
                {"label": "絕巴技術陪", "value": "exbar_tech", "rule_key": "basic_exbar_tech", "quantity_unit": "小時", "min_quantity": 1, "max_quantity": 24},
            ],
        },
        {
            "label": "技術陪",
            "details": [
                {"label": "機密單陪", "value": "secret_single", "rule_key": "basic_tech_secret_single", "quantity_unit": "小時", "min_quantity": 1, "max_quantity": 24},
                {"label": "機密雙陪", "value": "secret_double", "rule_key": "basic_tech_secret_double", "quantity_unit": "小時", "min_quantity": 1, "max_quantity": 24},
                {"label": "絕密單陪", "value": "topsecret_single", "rule_key": "basic_tech_topsecret_single", "quantity_unit": "小時", "min_quantity": 1, "max_quantity": 24},
                {"label": "絕密雙陪", "value": "topsecret_double", "rule_key": "basic_tech_topsecret_double", "quantity_unit": "小時", "min_quantity": 1, "max_quantity": 24},
            ],
        },
        {
            "label": "娛樂陪",
            "details": [
                {"label": "單陪", "value": "single", "rule_key": "basic_entertain_single", "quantity_unit": "小時", "min_quantity": 1, "max_quantity": 24},
                {"label": "雙陪", "value": "double", "rule_key": "basic_entertain_double", "quantity_unit": "小時", "min_quantity": 1, "max_quantity": 24},
            ],
        },
        {
            "label": "甜蜜陪",
            "details": [
                {"label": "單陪", "value": "single", "rule_key": "basic_sweet_single", "quantity_unit": "小時", "min_quantity": 1, "max_quantity": 24},
            ],
        },
        {
            "label": "體驗單",
            "details": [
                {"label": "777w", "value": "777w", "rule_key": "basic_trial_500", "quantity_unit": "單", "min_quantity": 1, "max_quantity": 1},
                {"label": "1688w", "value": "1688w", "rule_key": "basic_trial_1000", "quantity_unit": "單", "min_quantity": 1, "max_quantity": 1},
            ],
        },
        {
            "label": "教學單",
            "details": [
                {"label": "導師1名", "value": "teacher_1", "rule_key": "basic_teaching_one", "quantity_unit": "小時", "min_quantity": 3, "max_quantity": 24},
                {"label": "導師2名", "value": "teacher_2", "rule_key": "basic_teaching_two", "quantity_unit": "小時", "min_quantity": 3, "max_quantity": 24},
            ],
        },
        {
            "label": "賭約單",
            "details": [
                {"label": "800w", "value": "800w", "rule_key": "basic_bet_1000", "quantity_unit": "單", "min_quantity": 1, "max_quantity": 1},
                {"label": "1000w", "value": "1000w", "rule_key": "basic_bet_1500", "quantity_unit": "單", "min_quantity": 1, "max_quantity": 1},
                {"label": "1200w", "value": "1200w", "rule_key": "basic_bet_2500", "quantity_unit": "單", "min_quantity": 1, "max_quantity": 1},
            ],
        },
        {
            "label": "油鍋單",
            "details": [
                {"label": "火箭燃油", "value": "fuel", "rule_key": "basic_oil_fuel", "quantity_unit": "單", "min_quantity": 1, "max_quantity": 1},
                {"label": "GTI衛星通訊天線", "value": "satellite", "rule_key": "basic_oil_satellite", "quantity_unit": "單", "min_quantity": 1, "max_quantity": 1},
                {"label": "全包", "value": "all", "rule_key": "basic_oil_all", "quantity_unit": "單", "min_quantity": 1, "max_quantity": 1},
            ],
        },
    ],
    "fun": [
        {"label": "比翼雙飛", "details": [{"label": "比翼雙飛", "value": "lovebirds", "rule_key": "fun_lovebirds", "quantity_unit": "單", "min_quantity": 1, "max_quantity": 1}]},
        {"label": "已讀亂回", "details": [{"label": "已讀亂回", "value": "read_no_reply", "rule_key": "fun_read_no_reply", "quantity_unit": "單", "min_quantity": 1, "max_quantity": 1}]},
        {"label": "豪到你了嗎", "details": [{"label": "豪到你了嗎", "value": "rich_enough", "rule_key": "fun_rich_enough", "quantity_unit": "單", "min_quantity": 1, "max_quantity": 1}]},
        {"label": "想吃自己打", "details": [{"label": "想吃自己打", "value": "eat_yourself", "rule_key": "fun_eat_yourself", "quantity_unit": "單", "min_quantity": 1, "max_quantity": 1}]},
        {
            "label": "魔丸娛樂嘎拉給木",
            "details": [
                {
                    "label": "基礎",
                    "value": "basic",
                    "rule_key": "fun_mawan_galagame_basic",
                    "quantity_unit": "單",
                    "min_quantity": 1,
                    "max_quantity": 1,
                },
                {
                    "label": "標準",
                    "value": "standard",
                    "rule_key": "fun_mawan_galagame_standard",
                    "quantity_unit": "單",
                    "min_quantity": 1,
                    "max_quantity": 1,
                },
                {
                    "label": "困難",
                    "value": "hard",
                    "rule_key": "fun_mawan_galagame_hard",
                    "quantity_unit": "單",
                    "min_quantity": 1,
                    "max_quantity": 1,
                },
                {
                    "label": "地獄",
                    "value": "hell",
                    "rule_key": "fun_mawan_galagame_hell",
                    "quantity_unit": "單",
                    "min_quantity": 1,
                    "max_quantity": 1,
                },
            ],
        },
    ],
    "farm": [
        {"label": "賽季3x3", "details": [{"label": "賽季3x3", "value": "season_3x3", "rule_key": "farm_season_3x3_normal", "quantity_unit": "單", "min_quantity": 1, "max_quantity": 1}]},
        {"label": "部門任務", "details": [{"label": "部門任務", "value": "department", "rule_key": "farm_department_task", "quantity_unit": "單", "min_quantity": 1, "max_quantity": 1}]},
        {
            "label": "哈夫幣代洗",
            "details": [
                {"label": "120M", "value": "120m", "rule_key": "farm_halfcoin_120m", "quantity_unit": "單", "min_quantity": 1, "max_quantity": 1},
                {"label": "360M", "value": "360m", "rule_key": "farm_halfcoin_360m", "quantity_unit": "單", "min_quantity": 1, "max_quantity": 1},
            ],
        },
    ],
    "steam": [
        {
            "label": "娛樂陪",
            "details": [
                {"label": f"陪玩{count}名", "value": f"players_{count}", "rule_key": "steam_play", "player_count": count, "quantity_unit": "小時", "min_quantity": 1, "max_quantity": 24}
                for count in range(1, 5)
            ],
        },
    ],
    "valorant": [
        {
            "label": "娛樂陪",
            "details": [
                {"label": f"陪玩{count}名", "value": f"players_{count}", "rule_key": "valorant_entertain", "player_count": count, "quantity_unit": "小時", "min_quantity": 1, "max_quantity": 24}
                for count in range(1, 5)
            ],
        },
    ],
    "custom": [
        {
            "label": "自訂",
            "details": [
                {"label": f"陪玩{count}名", "value": f"players_{count}", "rule_key": "custom_custom_order", "player_count": count, "quantity_unit": "小時", "min_quantity": 1, "max_quantity": 24}
                for count in range(1, 5)
            ],
        },
    ],
}


# 所有 rule label 仍保留，讓舊訂單 / 舊紀錄可繼續被辨識。
ORDER_ITEMS_BY_CATEGORY = {
    category: [rule.label for rule in get_rules_by_category(category)]
    for category in ORDER_CATEGORY_LABELS
}

ORDER_RULE_KEY_BY_LABEL = {
    rule.label: rule.key
    for rule in ORDER_RULES.values()
}

# 舊版顯示名稱別名，確保未結舊單即使沒有 order_rule_key 仍可被找回。
ORDER_RULE_KEY_BY_LABEL.update({
    "絕巴四幻神賭單｜賭縱橫": "basic_exbar_gamble_zongheng",
    "絕巴四幻神賭單｜賭淚冠": "basic_exbar_gamble_leiguan",
    "絕巴四幻神賭單｜賭測距儀": "basic_exbar_gamble_rangefinder",
    "絕巴四幻神賭單｜賭天圓地方": "basic_exbar_gamble_tianyuan",
    "技術陪｜機密單護": "basic_tech_secret_single",
    "技術陪｜機密雙護": "basic_tech_secret_double",
    "技術陪｜絕密單護": "basic_tech_topsecret_single",
    "技術陪｜絕密雙護": "basic_tech_topsecret_double",
    "甜蜜單｜單陪": "basic_sweet_single",
    "教學單｜導師一名": "basic_teaching_one",
    "教學單｜導師兩名": "basic_teaching_two",
    "賭約單 1000": "basic_bet_1000",
    "賭約單 1500": "basic_bet_1500",
    "賭約單 2500": "basic_bet_2500",
    "賭約單 800w": "basic_bet_1000",
    "賭約單 1000w": "basic_bet_1500",
    "賭約單 1200w": "basic_bet_2500",
    "體驗單 500": "basic_trial_500",
    "體驗單 1000": "basic_trial_1000",
    "體驗單 777w": "basic_trial_500",
    "體驗單 1688w": "basic_trial_1000",
    "賽季3x3｜普通": "farm_season_3x3_normal",
    "代解部門任務": "farm_department_task",
    "Steam 陪玩": "steam_play",
    "Valorant 陪玩｜娛樂陪": "valorant_entertain",
    "自訂單": "custom_custom_order",
})

ORDER_ITEM_TO_CATEGORY = {
    label: ORDER_RULES[rule_key].category
    for label, rule_key in ORDER_RULE_KEY_BY_LABEL.items()
    if rule_key in ORDER_RULES
}

ORDER_ITEM_GROUPS_BY_CATEGORY = {
    category: [group["label"] for group in groups]
    for category, groups in SELF_SERVICE_ORDER_CATALOG.items()
}


def get_order_item_group_label(item_label: str | None) -> str | None:
    if item_label is None:
        return None

    key = ORDER_RULE_KEY_BY_LABEL.get(str(item_label))
    if key is None:
        return str(item_label)

    for category, groups in SELF_SERVICE_ORDER_CATALOG.items():
        for group in groups:
            for detail in group.get("details", []):
                if detail.get("rule_key") == key:
                    return str(group["label"])

    return str(item_label)


def get_order_item_details_for_group(category: str | None, group_label: str | None) -> list[dict]:
    if category is None or group_label is None:
        return []

    for group in SELF_SERVICE_ORDER_CATALOG.get(str(category), []):
        if str(group.get("label")) != str(group_label):
            continue

        result: list[dict] = []
        for detail in group.get("details", []):
            item = dict(detail)
            rule = ORDER_RULES.get(str(item.get("rule_key") or ""))
            item["item"] = str(getattr(rule, "label", "") or item.get("label") or "")
            result.append(item)
        return result

    return []


def get_order_item_detail_for_selection(
    category: str | None,
    group_label: str | None,
    detail_value: str | None,
) -> dict | None:
    if detail_value is None:
        return None

    for detail in get_order_item_details_for_group(category, group_label):
        if str(detail.get("value")) == str(detail_value):
            return detail
    return None


def get_order_item_detail_label(item_label: str | None) -> str | None:
    if item_label is None:
        return None

    rule_key = ORDER_RULE_KEY_BY_LABEL.get(str(item_label))
    if rule_key is None:
        return str(item_label)

    for groups in SELF_SERVICE_ORDER_CATALOG.values():
        for group in groups:
            for detail in group.get("details", []):
                if detail.get("rule_key") == rule_key:
                    return str(detail.get("label") or item_label)

    return str(item_label)


def get_self_service_quantity_meta(
    category: str | None,
    group_label: str | None,
    detail_value: str | None,
) -> dict | None:
    detail = get_order_item_detail_for_selection(category, group_label, detail_value)
    if detail is None:
        return None

    return {
        "unit": str(detail.get("quantity_unit") or "單"),
        "min": max(1, int(detail.get("min_quantity") or 1)),
        "max": max(1, int(detail.get("max_quantity") or 1)),
    }


SPECIAL_COMPANION_ITEMS = {
    rule.label
    for rule in ORDER_RULES.values()
    if rule.allow_specify
}

QUANTITY_SELECT_ITEMS = {
    detail["item"]
    for category, groups in SELF_SERVICE_ORDER_CATALOG.items()
    for group in groups
    for detail in get_order_item_details_for_group(category, group["label"])
    if int(detail.get("max_quantity") or 1) > 1
}

QUANTITY_OPTIONS = list(range(1, 25))

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
    staff_note: str | None = None,
) -> discord.Embed:
    payment_text = str(payment_method or "未紀錄").strip() or "未紀錄"

    if payment_text in {"待付款", "未付款", "等待付款"}:
        status_text = "等待接單｜付款前"
        color = discord.Color.gold()
    elif payment_text in {"未紀錄", "待客服確認"}:
        status_text = "狀態未紀錄"
        color = discord.Color.blue()
    else:
        status_text = "已付款｜服務進行中"
        color = discord.Color.green()

    ticket_text = getattr(source_channel, "mention", None) or "未紀錄"

    embed = discord.Embed(
        title="魔丸娛樂｜接單面板",
        description="所有派單、接單、存單、恢復與結單狀態皆以此面板為準。",
        color=color,
    )

    embed.add_field(name="狀態", value=status_text, inline=False)
    embed.add_field(name="顧客", value=str(customer_mention or "未紀錄"), inline=True)
    embed.add_field(name="票口", value=str(ticket_text), inline=True)
    embed.add_field(name="訂單", value=f"{category_label}｜{item}", inline=False)
    embed.add_field(name="數量", value=f"{quantity} 單", inline=True)
    embed.add_field(name="付款方式", value=payment_text, inline=True)

    if companion_preference is not None:
        embed.add_field(name="指定", value=str(companion_preference), inline=True)

    if staff_note is None:
        source_channel_id = getattr(source_channel, "id", None)

        try:
            source_data = _ORDER_SELECTIONS.get(int(source_channel_id), {}) if source_channel_id is not None else {}
        except (TypeError, ValueError):
            source_data = {}

        if isinstance(source_data, dict):
            staff_note = source_data.get("staff_note") or source_data.get("customer_service_note") or source_data.get("staff_order_note")

    staff_note_text = str(staff_note or "").strip()
    if staff_note_text:
        embed.add_field(name="客服備註", value=staff_note_text[:1024], inline=False)

    normalized_receiver_text = str(receiver_text or "").strip()

    for prefix in ("打手：", "打手:", "陪玩：", "陪玩:"):
        if normalized_receiver_text.startswith(prefix):
            normalized_receiver_text = normalized_receiver_text[len(prefix):].strip()
            break

    if not normalized_receiver_text:
        normalized_receiver_text = "尚未接單"

    embed.add_field(name="目前接單", value=normalized_receiver_text[:1024], inline=False)

    embed.set_footer(text="魔丸娛樂｜接單系統")
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

