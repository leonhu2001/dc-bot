from __future__ import annotations

import json
from typing import Any

from sqlalchemy import text

from services.order_rules import (
    ORDER_RULES,
    get_allowed_role_ids,
    get_required_game_role_ids,
)
from services.vip_timer import (
    SessionLocal,
    _accrue_segment,
    _current_segment,
    _event,
    get_session,
    strip_vip_timer_rule_key,
    utc_iso,
    utc_now,
)
from shared.order_acceptance import get_acceptance_state
from shared.order_state import (
    ACCEPTED_PENDING_PAY,
    WAITING_ACCEPTANCE,
    transition_order_state_in_connection,
)


PREPAY_STATES = {WAITING_ACCEPTANCE, ACCEPTED_PENDING_PAY}


def _active_staff_ids(order_id: int) -> list[str]:
    state = get_acceptance_state(int(order_id))
    result: list[str] = []
    for claim in state.claims:
        value = str(claim.staff_discord_id or "").strip()
        if value and value not in result:
            result.append(value)
    return result


def _current_rule(order_id: int):
    session = get_session(int(order_id)) or {}
    key = strip_vip_timer_rule_key(str(session.get("current_rule_key") or ""))
    rule = ORDER_RULES.get(key)
    if rule is None:
        raise ValueError("找不到目前玩法規則，暫時不能調整陪玩。")
    return session, key, rule


def _rule_count_bounds(rule) -> tuple[int, int]:
    if getattr(rule, "required_staff_count", 1) != "player_count":
        fixed = max(1, int(getattr(rule, "required_staff_count", 1) or 1))
        return fixed, fixed
    minimum = max(1, int(getattr(rule, "min_player_count", 1) or 1))
    raw_max = getattr(rule, "max_player_count", None)
    maximum = int(raw_max) if raw_max is not None else minimum
    return minimum, max(minimum, maximum)


def roster_capabilities(order_id: int) -> dict[str, Any]:
    session, rule_key, rule = _current_rule(int(order_id))
    staff_ids = _active_staff_ids(int(order_id))
    minimum, maximum = _rule_count_bounds(rule)
    variable = getattr(rule, "required_staff_count", 1) == "player_count"
    return {
        "order_id": int(order_id),
        "status": str(session.get("status") or ""),
        "rule_key": rule_key,
        "rule_label": str(getattr(rule, "label", rule_key) or rule_key),
        "staff_ids": staff_ids,
        "count": len(staff_ids),
        "minimum": minimum,
        "maximum": maximum,
        "can_add": bool(variable and len(staff_ids) < maximum),
        "can_reduce": bool(variable and len(staff_ids) > minimum),
        "can_replace": bool(staff_ids),
    }


def _validate_target(rule, target_count: int) -> None:
    minimum, maximum = _rule_count_bounds(rule)
    if target_count < minimum or target_count > maximum:
        if minimum == maximum:
            raise ValueError(f"這個玩法固定需要 {minimum} 位陪玩，不能直接增減人數。")
        raise ValueError(f"這個玩法只支援 {minimum}～{maximum} 位陪玩。")


def _close_live_segment(db, order_id: int, status: str, now) -> None:
    segment = _current_segment(db, int(order_id))
    if segment is not None:
        if status == "running":
            _accrue_segment(db, segment, now)
        db.execute(
            text("UPDATE vip_timer_segments SET ended_at=:now, updated_at=:now WHERE id=:id"),
            {"now": utc_iso(now), "id": int(segment["id"])},
        )
    db.execute(
        text(
            "UPDATE vip_timer_sessions SET status='paused', paused_at=:now, "
            "current_hourly_rate=0, updated_at=:now WHERE order_id=:order_id"
        ),
        {"now": utc_iso(now), "order_id": int(order_id)},
    )


def _sync_acceptance_rule_meta(db, *, order_id: int, rule_key: str, rule, target_count: int) -> None:
    db.execute(
        text(
            """
            UPDATE order_acceptance_meta
            SET order_rule_key=:rule_key,
                required_staff_count=:required_count,
                min_protector_count=:min_protectors,
                allowed_role_ids_json=:allowed_roles,
                required_game_role_ids_json=:game_roles,
                specified_staff_ids_json='[]',
                point_benefits_allowed=0,
                updated_at=:now
            WHERE order_id=:order_id
            """
        ),
        {
            "rule_key": str(rule_key),
            "required_count": int(target_count),
            "min_protectors": int(getattr(rule, "min_protector_count", 0) or 0),
            "allowed_roles": json.dumps(get_allowed_role_ids(rule), ensure_ascii=False),
            "game_roles": json.dumps(get_required_game_role_ids(rule), ensure_ascii=False),
            "now": utc_iso(),
            "order_id": int(order_id),
        },
    )


def has_open_segment(order_id: int) -> bool:
    db = SessionLocal()
    try:
        return _current_segment(db, int(order_id)) is not None
    finally:
        db.close()


def resume_with_new_roster_segment(
    order_id: int,
    *,
    actor_id: Any,
    pricing_snapshot: dict,
    staff_ids: list[str],
) -> dict[str, Any]:
    """Resume a paused timer after a roster boundary by opening a new segment."""
    db = SessionLocal()
    try:
        session = get_session(int(order_id), db)
        if not session or str(session.get("status") or "") != "paused":
            raise ValueError("目前不是暫停狀態。")
        if _current_segment(db, int(order_id)) is not None:
            raise ValueError("目前已有可繼續的計時區段。")

        state = get_acceptance_state(int(order_id))
        if not state.is_full:
            raise ValueError(
                f"陪玩名單尚未補滿（{state.accepted_count}/{state.required_staff_count}），不能繼續計時。"
            )

        now_text = utc_iso()
        seq = int(
            db.execute(
                text("SELECT COALESCE(MAX(seq),0)+1 FROM vip_timer_segments WHERE order_id=:order_id"),
                {"order_id": int(order_id)},
            ).scalar_one()
        )
        db.execute(
            text(
                """
                INSERT INTO vip_timer_segments(
                    order_id, seq, rule_key, rule_label, category_label, hourly_rate,
                    started_at, active_started_at, ended_at, billable_seconds,
                    actor_discord_id, staff_ids_json, player_count, required_staff_count,
                    created_at, updated_at
                ) VALUES (
                    :order_id, :seq, :rule_key, :rule_label, :category_label, :rate,
                    :now, :now, NULL, 0, :actor, :staff, :player_count,
                    :required_staff_count, :now, :now
                )
                """
            ),
            {
                "order_id": int(order_id),
                "seq": seq,
                "rule_key": str(session.get("current_rule_key") or pricing_snapshot.get("rule_key") or ""),
                "rule_label": str(session.get("current_rule_label") or ""),
                "category_label": str(session.get("current_category_label") or ""),
                "rate": int(pricing_snapshot.get("hourly_rate") or 0),
                "now": now_text,
                "actor": str(actor_id or ""),
                "staff": json.dumps(staff_ids, ensure_ascii=False),
                "player_count": int(pricing_snapshot.get("player_count") or len(staff_ids)),
                "required_staff_count": int(pricing_snapshot.get("required_staff_count") or len(staff_ids)),
            },
        )
        db.execute(
            text(
                """
                UPDATE vip_timer_sessions
                SET status='running', paused_at=NULL,
                    current_hourly_rate=:rate, updated_at=:now
                WHERE order_id=:order_id
                """
            ),
            {
                "rate": int(pricing_snapshot.get("hourly_rate") or 0),
                "now": now_text,
                "order_id": int(order_id),
            },
        )
        _event(
            db,
            int(order_id),
            "resume_after_roster_change",
            actor_id,
            {
                "staff_ids": staff_ids,
                "hourly_rate": int(pricing_snapshot.get("hourly_rate") or 0),
                "player_count": int(pricing_snapshot.get("player_count") or len(staff_ids)),
            },
        )
        db.commit()
        return get_session(int(order_id)) or {}
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def adjust_roster(
    order_id: int,
    *,
    action: str,
    actor_id: Any,
    outgoing_staff_id: str | None = None,
) -> dict[str, Any]:
    """Open a clean roster boundary for add/reduce/replace operations.

    Every change freezes the current billing segment at the operation timestamp.
    The timer stays paused until the resulting roster is complete and Resume is
    pressed, so waiting for a replacement/new worker is never billable time.
    """
    action = str(action or "").strip().lower()
    if action not in {"add", "reduce", "replace"}:
        raise ValueError("未知的陪玩調整方式。")

    session, rule_key, rule = _current_rule(int(order_id))
    timer_status = str(session.get("status") or "")
    if timer_status not in {"running", "paused"}:
        raise ValueError("只有計時中或暫停中的 VIP 自由計時單可以調整陪玩。")

    current_staff = _active_staff_ids(int(order_id))
    if not current_staff:
        raise ValueError("目前沒有已接單陪玩，無法調整名單。")

    outgoing = str(outgoing_staff_id or "").strip()
    if action in {"reduce", "replace"} and outgoing not in current_staff:
        raise ValueError("要調整的陪玩目前不在這張單上。")

    current_count = len(current_staff)
    if action == "add":
        target_count = current_count + 1
    elif action == "reduce":
        target_count = current_count - 1
    else:
        target_count = current_count
    _validate_target(rule, target_count)

    min_protectors = int(getattr(rule, "min_protector_count", 0) or 0)
    if target_count < min_protectors:
        raise ValueError("調整後人數不足以符合這個玩法的護航需求。")

    db = SessionLocal()
    try:
        now = utc_now()
        _close_live_segment(db, int(order_id), timer_status, now)

        if action in {"reduce", "replace"}:
            db.execute(
                text(
                    """
                    UPDATE order_acceptance_claims
                    SET is_active=0,
                        source='vip_timer_roster',
                        unclaimed_at=:now
                    WHERE order_id=:order_id
                      AND staff_discord_id=:staff_id
                      AND is_active=1
                    """
                ),
                {
                    "now": utc_iso(now),
                    "order_id": int(order_id),
                    "staff_id": outgoing,
                },
            )

        _sync_acceptance_rule_meta(
            db,
            order_id=int(order_id),
            rule_key=rule_key,
            rule=rule,
            target_count=target_count,
        )

        remaining_count = current_count - (1 if action in {"reduce", "replace"} else 0)
        target_status = ACCEPTED_PENDING_PAY if remaining_count >= target_count else WAITING_ACCEPTANCE
        transition_order_state_in_connection(
            db.connection(),
            order_id=int(order_id),
            target_status=target_status,
            source="vip_timer_roster",
            reason=f"VIP 自由計時陪玩調整：{action}｜{remaining_count}/{target_count}",
            actor_discord_id=actor_id,
            expected_statuses=PREPAY_STATES,
        )
        _event(
            db,
            int(order_id),
            "roster_change",
            actor_id,
            {
                "action": action,
                "outgoing_staff_id": outgoing or None,
                "before_staff_ids": current_staff,
                "target_staff_count": target_count,
                "timer_was_running": timer_status == "running",
            },
        )
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()

    state = get_acceptance_state(int(order_id))
    return {
        "order_id": int(order_id),
        "action": action,
        "target_staff_count": int(target_count),
        "accepted_count": int(state.accepted_count),
        "is_full": bool(state.is_full),
        "staff_ids": [str(claim.staff_discord_id) for claim in state.claims],
        "timer_status": "paused",
    }


__all__ = [
    "adjust_roster",
    "has_open_segment",
    "resume_with_new_roster_segment",
    "roster_capabilities",
]
