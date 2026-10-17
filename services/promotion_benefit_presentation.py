from __future__ import annotations

from typing import Any

from services.promotion_benefits import (
    ACTIVE,
    EFFECT_FIXED_CASH,
    EFFECT_FREE_GAMES,
    EFFECT_FREE_HOURS,
    EFFECT_FREE_ORDER,
    EFFECT_PERCENT,
    EFFECT_WAIVE_SPECIFY,
    list_issued_benefits,
)


def _number_text(value: Any) -> str:
    try:
        number = float(value or 0)
    except (TypeError, ValueError):
        number = 0.0
    return f"{number:g}"


def benefit_effect_text(rules: dict | None) -> str:
    data = rules or {}
    kind = str(data.get("effect_kind") or "")
    value = _number_text(data.get("effect_value"))
    if kind == EFFECT_FIXED_CASH:
        return f"{value}T 抵用"
    if kind == EFFECT_PERCENT:
        return f"{value}% 折扣"
    if kind == EFFECT_FREE_HOURS:
        return f"免費 {value} 小時"
    if kind == EFFECT_FREE_GAMES:
        return f"免費 {value} 局"
    if kind == EFFECT_WAIVE_SPECIFY:
        return "免指定費"
    if kind == EFFECT_FREE_ORDER:
        return "整單免單"
    return "福利券"


def _expiry_text(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return "不限"
    return text.replace("T", " ")[:16]


def present_issued_benefit(row: dict) -> dict:
    rules = dict(row.get("rules") or {})
    remaining_uses = max(0, int(row.get("remaining_uses") or 0))
    status = str(row.get("status") or "").strip().lower()
    return {
        "id": int(row.get("id") or 0),
        "title": str(row.get("title") or rules.get("name") or "優惠福利"),
        "status": status,
        "is_available": status == ACTIVE and remaining_uses > 0,
        "effect_text": benefit_effect_text(rules),
        "remaining_uses": remaining_uses,
        "expires_at": row.get("expires_at"),
        "expires_at_text": _expiry_text(row.get("expires_at")),
    }


def list_customer_promotion_benefits(
    customer_discord_id: str | int,
    *,
    active_only: bool = True,
    limit: int = 100,
    web_db=None,
) -> list[dict]:
    rows = list_issued_benefits(
        customer_discord_id=customer_discord_id,
        limit=limit,
        web_db=web_db,
    )
    items = [present_issued_benefit(row) for row in rows]
    if active_only:
        items = [item for item in items if item["is_available"]]
    return items


def build_benefit_grant_dm(item: dict) -> str:
    return (
        "🎁 **你收到新的福利**\n"
        f"福利：**{item.get('title') or '優惠福利'}**\n"
        f"內容：{item.get('effect_text') or '福利券'}\n"
        f"可使用次數：{int(item.get('remaining_uses') or 0)} 次\n"
        f"有效期限：{item.get('expires_at_text') or '不限'}\n\n"
        "可到 Discord「我的福利」或網站會員中心查看與使用。"
    )
