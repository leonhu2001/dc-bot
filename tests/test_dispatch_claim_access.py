from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from web.app.services.dispatch_claim_access import (
    build_dispatch_service_context,
    evaluate_dispatch_claim_access,
)


NOW = datetime(2026, 10, 7, 12, 0, 30, tzinfo=timezone.utc)


def _meta(*, specified=(), created_at=None, allowed=("100",), game=("200",)):
    created_at = created_at or (NOW - timedelta(seconds=30)).isoformat()
    return {
        "order_rule_key": "test_rule",
        "required_staff_count": 1,
        "min_protector_count": 0,
        "allowed_role_ids_json": list(allowed),
        "required_game_role_ids_json": list(game),
        "specified_staff_ids_json": list(specified),
        "status": "waiting_acceptance",
        "created_at": created_at,
    }


def test_public_user_is_blocked_during_first_minute():
    result = evaluate_dispatch_claim_access(
        meta=_meta(),
        active_rows=[],
        order_status="waiting_acceptance",
        user_id="A",
        user_role_ids=["100", "200"],
        now=NOW,
    )

    assert result["allowed"] is False
    assert result["lock_active"] is True
    assert "1 分鐘接單保護期" in result["reason"]


def test_specified_user_bypasses_time_lock_but_not_role_requirements():
    allowed = evaluate_dispatch_claim_access(
        meta=_meta(specified=["S"]),
        active_rows=[],
        order_status="waiting_acceptance",
        user_id="S",
        user_role_ids=["100", "200"],
        now=NOW,
    )
    denied = evaluate_dispatch_claim_access(
        meta=_meta(specified=["S"]),
        active_rows=[],
        order_status="waiting_acceptance",
        user_id="S",
        user_role_ids=["100"],
        now=NOW,
    )

    assert allowed["allowed"] is True
    assert allowed["is_specified"] is True
    assert allowed["lock_active"] is True
    assert denied["allowed"] is False
    assert "遊戲身分組" in denied["reason"]


def test_public_user_becomes_claimable_after_60_seconds():
    result = evaluate_dispatch_claim_access(
        meta=_meta(created_at=(NOW - timedelta(seconds=61)).isoformat()),
        active_rows=[],
        order_status="waiting_acceptance",
        user_id="A",
        user_role_ids=["100", "200"],
        now=NOW,
    )

    assert result["lock_active"] is False
    assert result["allowed"] is True


def test_reserved_specified_slot_never_alerts_other_user():
    result = evaluate_dispatch_claim_access(
        meta=_meta(
            specified=["S"],
            created_at=(NOW - timedelta(seconds=61)).isoformat(),
        ),
        active_rows=[],
        order_status="waiting_acceptance",
        user_id="A",
        user_role_ids=["100", "200"],
        now=NOW,
    )

    assert result["allowed"] is False
    assert "指定其他人員" in result["reason"]


def test_dispatch_service_context_keeps_hours_and_point_bonus_visible():
    order = SimpleNamespace(
        quantity=2,
        order_rule_key="basic_entertain_single",
        price_snapshot_json={
            "point_benefit_key": "extra_10",
            "point_benefit_name": "加時 30 分鐘",
            "point_benefit_cost": 15,
            "point_extra_hours": 0.5,
            "service_bonus_text": "服務時間 +30 分鐘",
        },
    )

    result = build_dispatch_service_context(order)

    assert result["service_text"] == "2 小時"
    assert result["actual_service_text"] == "2.5 小時"
    assert "加時 30 分鐘" in result["point_benefit_text"]
