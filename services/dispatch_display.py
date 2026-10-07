from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Any, Mapping

from services.order_rules import ORDER_RULES
from shared.order_acceptance import PUBLIC_ACCEPTANCE_LOCK_SECONDS, WAITING_ACCEPTANCE


def _json_dict(value: Any) -> dict:
    if isinstance(value, dict):
        return dict(value)
    if value is None:
        return {}
    try:
        parsed = json.loads(str(value))
    except Exception:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def normalize_service_unit(value: Any) -> str:
    text = str(value or "單").strip() or "單"
    if text.upper() == "H" or text in {"時", "小時"}:
        return "小時"
    if text in {"局", "場", "單"}:
        return text
    return text


def resolve_service_unit(
    *,
    rule_key: str | None = None,
    rule_snapshot: Any = None,
    fallback: str = "單",
) -> str:
    snapshot = _json_dict(rule_snapshot)
    snapshot_unit = snapshot.get("unit_label")
    if snapshot_unit:
        return normalize_service_unit(snapshot_unit)

    key = str(rule_key or "").strip()
    if key:
        rule = ORDER_RULES.get(key)
        if rule is not None:
            return normalize_service_unit(getattr(rule, "unit_label", fallback))

    return normalize_service_unit(fallback)


def _number(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return float(default)


def _format_number(value: float) -> str:
    if abs(value - round(value)) < 1e-9:
        return str(int(round(value)))
    return f"{value:.2f}".rstrip("0").rstrip(".")


def format_service_quantity(value: Any, unit: str) -> str:
    amount = max(0.0, _number(value, 0.0))
    normalized_unit = normalize_service_unit(unit)

    if normalized_unit == "小時":
        whole_hours = int(amount)
        minutes = int(round((amount - whole_hours) * 60))
        if minutes >= 60:
            whole_hours += minutes // 60
            minutes %= 60
        if whole_hours and minutes:
            return f"{whole_hours} 小時 {minutes} 分鐘"
        if whole_hours:
            return f"{whole_hours} 小時"
        if minutes:
            return f"{minutes} 分鐘"
        return "0 小時"

    return f"{_format_number(amount)} {normalized_unit}"


def build_service_display(
    *,
    quantity: Any,
    rule_key: str | None = None,
    rule_snapshot: Any = None,
    price_snapshot: Any = None,
    price_data: Mapping[str, Any] | None = None,
) -> dict:
    snapshot = _json_dict(price_snapshot)
    if price_data:
        snapshot.update({key: value for key, value in price_data.items() if value is not None})

    unit = resolve_service_unit(
        rule_key=(
            rule_key
            or snapshot.get("order_rule_key")
        ),
        rule_snapshot=rule_snapshot,
        fallback="單",
    )

    purchased = max(0.0, _number(quantity, 0.0))
    service_quantity = max(
        purchased,
        _number(snapshot.get("service_quantity"), purchased),
    )
    automatic_bonus = max(
        0.0,
        _number(snapshot.get("service_bonus_quantity"), service_quantity - purchased),
    )

    point_extra = 0.0
    if unit == "小時":
        point_extra = max(0.0, _number(snapshot.get("point_extra_hours"), 0.0))
    elif unit == "局":
        point_extra = max(0.0, _number(snapshot.get("point_extra_games"), 0.0))

    total = max(purchased, service_quantity) + point_extra

    bonus_lines: list[str] = []
    promotion_text = str(snapshot.get("service_promotion_text") or "").strip()
    if promotion_text:
        bonus_lines.append(promotion_text)
    elif automatic_bonus > 0:
        bonus_lines.append(f"活動加贈 +{format_service_quantity(automatic_bonus, unit)}")

    point_name = str(snapshot.get("point_benefit_name") or "").strip()
    point_bonus_text = str(snapshot.get("service_bonus_text") or "").strip()
    if point_name:
        point_line = f"點數福利：{point_name}"
        if point_bonus_text:
            point_line += f"｜{point_bonus_text}"
        bonus_lines.append(point_line)
    elif point_bonus_text:
        bonus_lines.append(f"點數福利：{point_bonus_text}")

    return {
        "unit": unit,
        "purchased_quantity": purchased,
        "automatic_bonus_quantity": automatic_bonus,
        "point_extra_quantity": point_extra,
        "total_quantity": total,
        "purchased_text": format_service_quantity(purchased, unit),
        "total_text": format_service_quantity(total, unit),
        "bonus_text": "\n".join(dict.fromkeys(line for line in bonus_lines if line)),
        "has_bonus": total > purchased or bool(bonus_lines),
    }


def acceptance_lock_display(created_at_value: Any, status_value: Any) -> dict:
    status = str(status_value or "").strip()
    if status != WAITING_ACCEPTANCE:
        return {
            "locked": False,
            "opens_at": None,
            "remaining_seconds": 0,
        }

    created_text = str(created_at_value or "").strip()
    if not created_text:
        return {
            "locked": False,
            "opens_at": None,
            "remaining_seconds": 0,
        }

    try:
        created = datetime.fromisoformat(created_text.replace("Z", "+00:00"))
    except ValueError:
        return {
            "locked": False,
            "opens_at": None,
            "remaining_seconds": 0,
        }

    if created.tzinfo is None:
        created = created.replace(tzinfo=timezone.utc)
    else:
        created = created.astimezone(timezone.utc)

    opens_at = created + timedelta(seconds=PUBLIC_ACCEPTANCE_LOCK_SECONDS)
    remaining_float = (opens_at - datetime.now(timezone.utc)).total_seconds()
    locked = remaining_float > 0

    return {
        "locked": locked,
        "opens_at": opens_at.isoformat().replace("+00:00", "Z"),
        "remaining_seconds": (
            max(0, int(remaining_float + 0.999))
            if locked
            else 0
        ),
    }


def dispatch_status_display(
    *,
    status: Any,
    locked: bool = False,
    current_staff_count: int = 0,
    required_staff_count: int = 0,
) -> tuple[str, str]:
    normalized = str(status or "").strip()
    current = max(0, int(current_staff_count or 0))
    required = max(0, int(required_staff_count or 0))
    missing = max(0, required - current)

    if normalized == WAITING_ACCEPTANCE:
        if locked:
            return "🔒 接單保護期", "派單建立後 1 分鐘統一開放接單。"
        if current > 0 and required > 0:
            return f"🟢 接單中｜{current}/{required} 人", f"目前尚缺 {missing} 人。"
        if missing > 0:
            return "🟢 開放接單", f"目前尚缺 {missing} 人。"
        return "🟢 開放接單", "可接單。"

    if normalized == "accepted_pending_pay":
        return "🟡 接單完成｜等待付款", "接單名額已滿，等待顧客付款成立。"
    if normalized == "active":
        return "🟢 服務進行中", "訂單已付款成立。"
    if normalized == "stored":
        return "📦 已存單", "此訂單目前暫停並已存單。"
    if normalized == "closed":
        return "✅ 已結單", "訂單已完成。"
    if normalized == "cancelled":
        return "⚫ 已取消", "訂單已取消。"

    return normalized or "未知狀態", ""
