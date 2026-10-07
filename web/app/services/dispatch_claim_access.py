from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from services.order_rules import ORDER_RULES, role_ids_match_requirements
from shared.order_acceptance import (
    ACCEPTED_PENDING_PAY,
    EXACT_ONE_PROTECTOR_RULE_KEYS,
    PROTECTOR_ROLE_IDS,
    PUBLIC_ACCEPTANCE_LOCK_SECONDS,
    WAITING_ACCEPTANCE,
)
from shared.models import OrderStatus


def _json_list(value) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    try:
        parsed = json.loads(str(value))
    except Exception:
        return []
    if not isinstance(parsed, list):
        return []
    return [str(item).strip() for item in parsed if str(item).strip()]


def _json_dict(value) -> dict:
    if isinstance(value, dict):
        return dict(value)
    if value is None:
        return {}
    try:
        parsed = json.loads(str(value))
    except Exception:
        return {}
    return dict(parsed) if isinstance(parsed, dict) else {}


def dispatch_user_role_ids(user: dict | None) -> list[str]:
    user = user or {}
    role_ids: list[str] = []

    for key in ("role_ids", "roles", "discord_role_ids"):
        value = user.get(key)
        if isinstance(value, list):
            role_ids.extend(str(item) for item in value if str(item).strip())
        elif isinstance(value, str):
            text_value = value.strip()
            if not text_value:
                continue
            try:
                parsed = json.loads(text_value)
            except Exception:
                parsed = None
            if isinstance(parsed, list):
                role_ids.extend(str(item) for item in parsed if str(item).strip())
            else:
                role_ids.extend(
                    part.strip()
                    for part in text_value.split(",")
                    if part.strip()
                )

    roles_json = user.get("roles_json")
    if isinstance(roles_json, str) and roles_json.strip():
        try:
            parsed = json.loads(roles_json)
        except Exception:
            parsed = None
        if isinstance(parsed, list):
            role_ids.extend(str(item) for item in parsed if str(item).strip())

    return list(dict.fromkeys(role_ids))


def _parse_utc(value) -> datetime | None:
    if isinstance(value, datetime):
        parsed = value
    else:
        text_value = str(value or "").strip()
        if not text_value:
            return None
        try:
            parsed = datetime.fromisoformat(text_value.replace("Z", "+00:00"))
        except ValueError:
            return None

    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def public_lock_window(created_at, *, now: datetime | None = None) -> dict:
    created = _parse_utc(created_at)
    if created is None:
        return {
            "active": False,
            "unlock_at_epoch_ms": None,
        }

    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    else:
        current = current.astimezone(timezone.utc)

    elapsed = (current - created).total_seconds()
    unlock_at = created + timedelta(seconds=PUBLIC_ACCEPTANCE_LOCK_SECONDS)

    return {
        "active": 0 <= elapsed < PUBLIC_ACCEPTANCE_LOCK_SECONDS,
        "unlock_at_epoch_ms": int(unlock_at.timestamp() * 1000),
    }


def load_dispatch_claim_snapshot(db: Session, order_id: int) -> dict | None:
    meta = db.execute(
        text(
            """
            SELECT
                order_rule_key,
                required_staff_count,
                min_protector_count,
                allowed_role_ids_json,
                required_game_role_ids_json,
                specified_staff_ids_json,
                status,
                created_at
            FROM order_acceptance_meta
            WHERE order_id = :order_id
            LIMIT 1
            """
        ),
        {"order_id": int(order_id)},
    ).mappings().first()

    if meta is None:
        return None

    claims = db.execute(
        text(
            """
            SELECT
                staff_discord_id,
                staff_role_ids_json
            FROM order_acceptance_claims
            WHERE order_id = :order_id
              AND is_active = 1
            ORDER BY claimed_at ASC, id ASC
            """
        ),
        {"order_id": int(order_id)},
    ).mappings().all()

    return {
        "meta": dict(meta),
        "active_rows": [dict(row) for row in claims],
    }


def evaluate_dispatch_claim_access(
    *,
    meta: dict[str, Any],
    active_rows: list[dict[str, Any]],
    order_status: str | None,
    user_id: str | None,
    user_role_ids: list[str] | tuple[str, ...] | set[str],
    now: datetime | None = None,
) -> dict:
    user_id = str(user_id or "").strip()
    role_ids = {str(role_id) for role_id in (user_role_ids or []) if str(role_id).strip()}
    status = str(order_status or meta.get("status") or "").strip()
    specified_staff_ids = _json_list(meta.get("specified_staff_ids_json"))
    specified_set = set(specified_staff_ids)
    is_specified = bool(user_id and user_id in specified_set)
    lock = public_lock_window(meta.get("created_at"), now=now)

    result = {
        "allowed": False,
        "reason": "此狀態不開放網站接單。",
        "is_specified": is_specified,
        "lock_active": bool(lock["active"]),
        "unlock_at_epoch_ms": lock["unlock_at_epoch_ms"],
    }

    if status != WAITING_ACCEPTANCE:
        if status == ACCEPTED_PENDING_PAY:
            result["reason"] = "接單名額已滿，等待付款成立。"
        elif status == OrderStatus.ACTIVE.value:
            result["reason"] = "已付款成立，網站接單已鎖定。"
        return result

    if not user_id:
        result["reason"] = "無法確認你的 Discord 身分。"
        return result

    if not role_ids:
        result["reason"] = "網站登入資料缺少 Discord 身分組，請重新登入後再接單。"
        return result

    if lock["active"] and not is_specified:
        result["reason"] = "🔒 目前為 1 分鐘接單保護期；指定人員可立即接單，其他人請稍後。"
        return result

    allowed_role_ids = set(_json_list(meta.get("allowed_role_ids_json")))
    required_game_role_ids = set(_json_list(meta.get("required_game_role_ids_json")))

    if not role_ids_match_requirements(
        role_ids,
        allowed_role_ids,
        required_game_role_ids,
    ):
        result["reason"] = "你的遊戲身分組或職位／階級不符合這張單的可接條件。"
        return result

    if any(
        str(row.get("staff_discord_id") or "") == user_id
        for row in active_rows
    ):
        result["reason"] = "你已經接了這張單。"
        return result

    required_staff_count = max(1, int(meta.get("required_staff_count") or 1))
    if len(active_rows) >= required_staff_count:
        result["reason"] = "這張單已經滿人，無法接單。"
        return result

    if specified_staff_ids and not is_specified:
        unrestricted_slots = max(0, required_staff_count - len(specified_set))
        non_specified_active_count = sum(
            1
            for row in active_rows
            if str(row.get("staff_discord_id") or "") not in specified_set
        )
        if non_specified_active_count >= unrestricted_slots:
            result["reason"] = "這張單已指定其他人員，剩餘名額不可由你接單。"
            return result

    order_rule_key = str(meta.get("order_rule_key") or "")
    min_protector_count = max(0, int(meta.get("min_protector_count") or 0))
    candidate_is_protector = bool(role_ids & PROTECTOR_ROLE_IDS)
    current_protector_count = 0

    for row in active_rows:
        claim_roles = set(_json_list(row.get("staff_role_ids_json")))
        if claim_roles & PROTECTOR_ROLE_IDS:
            current_protector_count += 1

    next_protector_count = current_protector_count + (1 if candidate_is_protector else 0)
    remaining_slots_after_claim = required_staff_count - (len(active_rows) + 1)

    if (
        order_rule_key in EXACT_ONE_PROTECTOR_RULE_KEYS
        and next_protector_count > 1
    ):
        result["reason"] = "這張單固定 1 護 + 1 陪；已有護級接單，下一位不能再由護級接。"
        return result

    if next_protector_count + remaining_slots_after_claim < min_protector_count:
        result["reason"] = (
            "這張單固定 1 護 + 1 陪；剩餘名額必須由護級接單。"
            if order_rule_key in EXACT_ONE_PROTECTOR_RULE_KEYS
            else "這張單至少需要護級接單，剩餘名額不能再由陪級接。"
        )
        return result

    result["allowed"] = True
    result["reason"] = "現在可以接單。"
    return result


def evaluate_dispatch_claim_access_for_user(
    snapshot: dict | None,
    *,
    order_status: str | None,
    user: dict | None,
    now: datetime | None = None,
) -> dict:
    if snapshot is None:
        return {
            "allowed": False,
            "reason": "這張訂單沒有付款前接單資料。",
            "is_specified": False,
            "lock_active": False,
            "unlock_at_epoch_ms": None,
        }

    return evaluate_dispatch_claim_access(
        meta=dict(snapshot.get("meta") or {}),
        active_rows=list(snapshot.get("active_rows") or []),
        order_status=order_status,
        user_id=str((user or {}).get("id") or ""),
        user_role_ids=dispatch_user_role_ids(user),
        now=now,
    )


def _format_number(value: float) -> str:
    if float(value).is_integer():
        return str(int(value))
    return f"{value:g}"


def _quantity_unit_for_order(order) -> str:
    rule_key = str(getattr(order, "order_rule_key", None) or "").strip()
    rule = ORDER_RULES.get(rule_key)
    unit = str(getattr(rule, "unit_label", None) or "單").strip() if rule else "單"
    if unit.upper() == "H":
        return "小時"
    return unit or "單"


def build_dispatch_service_context(order) -> dict:
    quantity = max(1, int(getattr(order, "quantity", 1) or 1))
    unit = _quantity_unit_for_order(order)
    raw_snapshot = _json_dict(getattr(order, "price_snapshot_json", None))
    preview = raw_snapshot.get("preview") if isinstance(raw_snapshot.get("preview"), dict) else {}
    finance = preview.get("finance") if isinstance(preview.get("finance"), dict) else {}
    point = preview.get("point") if isinstance(preview.get("point"), dict) else {}

    point_name = str(
        raw_snapshot.get("point_benefit_name")
        or point.get("name")
        or ""
    ).strip()
    point_cost = int(
        raw_snapshot.get("point_benefit_cost")
        or point.get("cost")
        or 0
    )
    point_key = str(
        raw_snapshot.get("point_benefit_key")
        or point.get("key")
        or ""
    ).strip()
    bonus_text = str(
        raw_snapshot.get("service_bonus_text")
        or finance.get("point_service_note")
        or ""
    ).strip()
    promotion_text = str(raw_snapshot.get("service_promotion_text") or "").strip()

    extra_hours = float(raw_snapshot.get("point_extra_hours") or 0)
    extra_games = int(raw_snapshot.get("point_extra_games") or 0)

    if point_key and extra_hours <= 0 and extra_games <= 0:
        try:
            from web.app.services.checkout_preview import POINT_ITEM_MAP

            point_item = POINT_ITEM_MAP.get(point_key) or {}
            kind = str(point_item.get("kind") or "")
            if kind == "extra_hours":
                extra_hours = float(point_item.get("hours") or 0)
            elif kind in {"extra_game", "extra_games"}:
                extra_games = int(point_item.get("games") or 0)
        except Exception:
            pass

    service_text = f"{quantity} {unit}"
    actual_service_text = service_text

    if unit == "小時" and extra_hours > 0:
        actual_service_text = f"{_format_number(quantity + extra_hours)} 小時"
    elif unit in {"局", "場"} and extra_games > 0:
        actual_service_text = f"{quantity + extra_games} {unit}"

    point_benefit_text = ""
    if point_name:
        prefix = f"{point_cost} 點｜" if point_cost > 0 else ""
        point_benefit_text = f"{prefix}{point_name}"
        if bonus_text and bonus_text not in point_benefit_text:
            point_benefit_text += f"｜{bonus_text}"
    elif bonus_text:
        point_benefit_text = bonus_text

    return {
        "quantity_unit": unit,
        "service_text": service_text,
        "actual_service_text": actual_service_text,
        "service_bonus_text": bonus_text,
        "point_benefit_text": point_benefit_text,
        "promotion_text": promotion_text,
    }


def decorate_dispatch_order(
    db: Session,
    order,
    *,
    user: dict | None,
) -> None:
    snapshot = load_dispatch_claim_snapshot(db, int(order.id))
    access = evaluate_dispatch_claim_access_for_user(
        snapshot,
        order_status=str(getattr(order, "status", None) or ""),
        user=user,
    )
    service = build_dispatch_service_context(order)

    setattr(order, "dispatch_user_can_claim_now", bool(access["allowed"]))
    setattr(order, "dispatch_user_claim_reason", str(access["reason"]))
    setattr(order, "dispatch_user_is_specified", bool(access["is_specified"]))
    setattr(order, "dispatch_public_lock_active", bool(access["lock_active"]))
    setattr(order, "dispatch_unlock_at_epoch_ms", access["unlock_at_epoch_ms"])

    setattr(order, "dispatch_quantity_unit", service["quantity_unit"])
    setattr(order, "dispatch_service_text", service["service_text"])
    setattr(order, "dispatch_actual_service_text", service["actual_service_text"])
    setattr(order, "dispatch_service_bonus_text", service["service_bonus_text"])
    setattr(order, "dispatch_point_benefit_text", service["point_benefit_text"])
    setattr(order, "dispatch_promotion_text", service["promotion_text"])

    status = str(getattr(order, "status", None) or "").strip()
    current_count = int(getattr(order, "dispatch_current_staff_count", 0) or 0)

    if status == WAITING_ACCEPTANCE:
        if access["lock_active"]:
            if access["is_specified"] and access["allowed"]:
                status_label = "指定可立即接單"
            else:
                status_label = "接單保護期"
        elif current_count > 0:
            status_label = "接單中"
        else:
            status_label = "開放接單"
    elif status == ACCEPTED_PENDING_PAY:
        status_label = "接單完成｜等待付款"
    elif status == OrderStatus.ACTIVE.value:
        status_label = "服務進行中"
    else:
        status_label = status or "未知狀態"

    setattr(order, "dispatch_status_label", status_label)

    if status == WAITING_ACCEPTANCE and not access["allowed"]:
        setattr(order, "dispatch_locked_message", str(access["reason"]))
