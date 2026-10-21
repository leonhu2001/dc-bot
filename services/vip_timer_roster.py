from __future__ import annotations

import json
from typing import Any

from sqlalchemy import text

from services.order_rules import (
    ORDER_RULES,
    get_allowed_role_ids,
    get_required_game_role_ids,
    role_ids_match_requirements,
)
from services.vip_timer import (
    SessionLocal,
    _accrue_segment,
    _current_segment,
    _event,
    get_session,
    rule_snapshot,
    strip_vip_timer_rule_key,
    utc_iso,
    utc_now,
)
from shared.order_acceptance import PROTECTOR_ROLE_IDS, get_acceptance_state
from shared.order_state import (
    ACCEPTED_PENDING_PAY,
    WAITING_ACCEPTANCE,
    transition_order_state_in_connection,
)


PREPAY_STATES = {WAITING_ACCEPTANCE, ACCEPTED_PENDING_PAY}
_HEADCOUNT_LABELS = {1: "單陪", 2: "雙陪", 3: "三陪", 4: "四陪"}


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


def _detail_staff_count(detail: dict) -> int:
    rule = ORDER_RULES.get(str(detail.get("rule_key") or "").strip())
    if rule is None:
        return 0
    required = getattr(rule, "required_staff_count", 1)
    if required == "player_count":
        try:
            selected = int(detail.get("player_count") or 0)
        except (TypeError, ValueError):
            selected = 0
        if selected > 0:
            return selected
        return max(1, int(getattr(rule, "min_player_count", 1) or 1))
    try:
        return max(1, int(required or 1))
    except (TypeError, ValueError):
        return 0


def _current_gameplay_group(rule_key: str, current_count: int) -> tuple[str, dict] | None:
    """Find the checkout gameplay family that owns the live rule/headcount."""
    from services import vip_timer_select_flow as flow
    from services import vip_timer_selector_order_v3 as selector
    from services.vip_timer_policy_v5 import _GAME_ORDER

    flow.refresh_vip_timer_self_service_catalog()
    fallback: tuple[str, dict] | None = None
    for game_label in _GAME_ORDER:
        groups = selector._spec_groups(flow._details_for_game(str(game_label)))
        for group in groups:
            for detail in group.get("details") or ():
                if str(detail.get("rule_key") or "").strip() != str(rule_key):
                    continue
                if fallback is None:
                    fallback = (str(game_label), dict(group))
                if _detail_staff_count(detail) == int(current_count):
                    return str(game_label), dict(group)
    return fallback


def _target_variant(rule_key: str, current_count: int, target_count: int) -> dict | None:
    """Resolve another headcount inside the same game/gameplay family.

    Many catalog products use separate fixed rules for 單陪/雙陪/... rather
    than one player_count rule. Roster adjustment therefore resolves the target
    fourth-layer variant instead of assuming the current rule itself is elastic.
    """
    owner = _current_gameplay_group(str(rule_key), int(current_count))
    if owner is None:
        return None
    game_label, group = owner
    rows = [
        dict(detail)
        for detail in (group.get("details") or ())
        if _detail_staff_count(detail) == int(target_count)
    ]
    if not rows:
        return None
    rows.sort(
        key=lambda detail: (
            str(detail.get("vip_timer_service_type") or ""),
            str(detail.get("value") or ""),
        )
    )
    detail = rows[0]
    target_key = str(detail.get("rule_key") or "").strip()
    target_rule = ORDER_RULES.get(target_key)
    if target_rule is None:
        return None
    return {
        "game_label": game_label,
        "gameplay_label": str(group.get("label") or ""),
        "service_type": str(detail.get("vip_timer_service_type") or _HEADCOUNT_LABELS.get(int(target_count), "")),
        "rule_key": target_key,
        "rule": target_rule,
        "detail": detail,
    }


def _supported_counts(rule_key: str, current_count: int) -> list[int]:
    owner = _current_gameplay_group(str(rule_key), int(current_count))
    if owner is None:
        return [int(current_count)]
    _, group = owner
    counts = sorted(
        {
            _detail_staff_count(detail)
            for detail in (group.get("details") or ())
            if _detail_staff_count(detail) > 0
        }
    )
    return counts or [int(current_count)]


def roster_capabilities(order_id: int) -> dict[str, Any]:
    from services.vip_timer_catalog_guard import is_public_timer_rule

    session, rule_key, rule = _current_rule(int(order_id))
    staff_ids = _active_staff_ids(int(order_id))
    count = len(staff_ids)
    counts = _supported_counts(rule_key, count) if count else []
    return {
        "order_id": int(order_id),
        "status": str(session.get("status") or ""),
        "rule_key": rule_key,
        "rule_label": str(getattr(rule, "label", rule_key) or rule_key),
        "staff_ids": staff_ids,
        "count": count,
        "minimum": min(counts) if counts else count,
        "maximum": max(counts) if counts else count,
        "supported_counts": counts,
        "can_add": bool(count and (count + 1) in counts),
        "can_reduce": bool(count > 1 and (count - 1) in counts),
        "can_replace": bool(staff_ids and is_public_timer_rule(rule_key)),
    }


def _validate_remaining_claims(rule, claims, target_count: int) -> None:
    allowed_role_ids = get_allowed_role_ids(rule)
    required_game_role_ids = get_required_game_role_ids(rule)
    protector_count = 0

    for claim in claims:
        role_ids = {str(value) for value in (claim.staff_role_ids or ()) if str(value).strip()}
        if not role_ids_match_requirements(
            role_ids,
            allowed_role_ids,
            required_game_role_ids,
        ):
            display_name = str(claim.staff_display_name or claim.staff_discord_id)
            raise ValueError(
                f"{display_name} 不符合調整後規格的接單資格，請先切換其他玩法或聯繫客服。"
            )
        if role_ids & PROTECTOR_ROLE_IDS:
            protector_count += 1

    minimum_protectors = int(getattr(rule, "min_protector_count", 0) or 0)
    remaining_slots = max(0, int(target_count) - len(claims))
    if protector_count + remaining_slots < minimum_protectors:
        raise ValueError("調整後無法滿足這個玩法的護級人數需求。")


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


def _set_pending_rule(db, order_id: int, target_rule_key: str) -> dict:
    snap = rule_snapshot(str(target_rule_key))
    db.execute(
        text(
            """
            UPDATE vip_timer_sessions
            SET current_rule_key=:rule_key,
                current_rule_label=:rule_label,
                current_category_label=:category_label,
                current_hourly_rate=0,
                updated_at=:now
            WHERE order_id=:order_id
            """
        ),
        {
            "rule_key": str(snap.get("rule_key") or target_rule_key),
            "rule_label": str(snap.get("rule_label") or target_rule_key),
            "category_label": str(snap.get("category_label") or ""),
            "now": utc_iso(),
            "order_id": int(order_id),
        },
    )
    return snap


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

    Add/reduce resolves the adjacent fourth-layer headcount inside the same
    game/gameplay family, so fixed 單陪/雙陪/三陪/四陪 rules work just like
    player_count rules. Every change freezes the current billing segment at the
    operation timestamp. Waiting for a new/replacement worker is never billable.
    """
    from services.vip_timer_catalog_guard import is_public_timer_rule

    action = str(action or "").strip().lower()
    if action not in {"add", "reduce", "replace"}:
        raise ValueError("未知的陪玩調整方式。")

    session, rule_key, rule = _current_rule(int(order_id))
    timer_status = str(session.get("status") or "")
    if timer_status not in {"running", "paused"}:
        raise ValueError("只有計時中或暫停中的 VIP 自由計時單可以調整陪玩。")

    state_before = get_acceptance_state(int(order_id))
    current_staff = [str(claim.staff_discord_id) for claim in state_before.claims]
    if not current_staff:
        raise ValueError("目前沒有已接單陪玩，無法調整名單。")

    outgoing = str(outgoing_staff_id or "").strip()
    if action in {"reduce", "replace"} and outgoing not in current_staff:
        raise ValueError("要調整的陪玩目前不在這張單上。")

    current_count = len(current_staff)
    target_count = (
        current_count + 1
        if action == "add"
        else current_count - 1
        if action == "reduce"
        else current_count
    )
    if target_count <= 0:
        raise ValueError("VIP 自由計時至少需要 1 位陪玩。")

    target_rule_key = rule_key
    target_rule = rule
    target_variant = None
    if action in {"add", "reduce"}:
        target_variant = _target_variant(rule_key, current_count, target_count)
        if target_variant is None:
            label = _HEADCOUNT_LABELS.get(target_count, f"{target_count}陪")
            raise ValueError(f"目前玩法沒有「{label}」規格，不能直接調整成 {target_count} 位。")
        target_rule_key = str(target_variant["rule_key"])
        target_rule = target_variant["rule"]
    elif not is_public_timer_rule(rule_key):
        raise ValueError("目前玩法已停止開放，不能建立新的換人計費區段，請聯繫客服處理。")

    remaining_claims = [
        claim
        for claim in state_before.claims
        if action not in {"reduce", "replace"}
        or str(claim.staff_discord_id) != outgoing
    ]
    _validate_remaining_claims(target_rule, remaining_claims, target_count)

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

        target_snap = _set_pending_rule(db, int(order_id), target_rule_key)
        _sync_acceptance_rule_meta(
            db,
            order_id=int(order_id),
            rule_key=target_rule_key,
            rule=target_rule,
            target_count=target_count,
        )

        remaining_count = len(remaining_claims)
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
                "before_rule_key": rule_key,
                "target_rule_key": target_rule_key,
                "target_rule_label": target_snap.get("rule_label"),
                "target_staff_count": target_count,
                "timer_was_running": timer_status == "running",
                "gameplay_label": (target_variant or {}).get("gameplay_label"),
                "service_type": (target_variant or {}).get("service_type"),
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
        "target_rule_key": target_rule_key,
        "target_rule_label": str(getattr(target_rule, "label", target_rule_key) or target_rule_key),
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
