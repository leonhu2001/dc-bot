from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from services.order_rules import (
    AW_COLLISION_ORDER_RULE_KEYS,
    AW_COLLISION_RECEIVER_ROLE_ID,
    COIN_WASH_ORDER_RULE_KEYS,
    HALFCOIN_RECEIVER_ROLE_ID,
)
from web.app.services.dispatch_assignment_eligibility import (
    cached_staff_role_ids,
    eligible_dispatch_assignees,
    is_eligible_dispatch_assignee,
)
from web.app.services.dispatch_claim_access import evaluate_dispatch_claim_access
from web.app.services.dispatch_support import assign_companion_from_dispatch
from web.app.services.role_catalog import (
    RECEIVER_ROLE_IDS,
    ROLE_LABEL_BY_ID,
    can_login_dashboard,
)
from web.app.services.staff_service import classify_roles


WASH_ID = "1565369317929918554"
AW_ID = "1571080769407942787"
SPECIAL_ID = WASH_ID
OLD_ID = "1565369029005287595"
COMPANION_ID = "1500751059239440575"
PROTECTOR_ID = "1500234130871550004"
SPECIAL_PRODUCTS = [
    "staff_internal_ammo_dump_500m",
    "staff_internal_car_500m",
    "staff_internal_aw_collision",
    "farm_coin_wash_car",
    "farm_coin_wash_ammo_dump",
    "farm_halfcoin_120m",
    "farm_halfcoin_360m",
    "farm_aw_collision_1_100",
    "farm_aw_collision_101_500",
    "farm_aw_collision_501_plus",
]


def member(role_ids, *, active=True, is_worker=False, is_companion=False, uid="123"):
    return SimpleNamespace(
        discord_id=uid,
        display_name=f"member {uid}",
        global_name=None,
        username=None,
        roles_json=json.dumps(role_ids),
        is_active=active,
        is_worker=is_worker,
        is_companion=is_companion,
    )


@pytest.mark.parametrize("rule_key", SPECIAL_PRODUCTS)
def test_dispatch_picker_only_contains_members_with_matching_special_role(rule_key):
    order = SimpleNamespace(order_rule_key=rule_key, dispatch_acceptance_meta=None)
    needed_role_id = AW_ID if rule_key in AW_COLLISION_ORDER_RULE_KEYS else WASH_ID
    members = [
        member([COMPANION_ID], is_companion=True, is_worker=True, uid="companion"),
        member([PROTECTOR_ID], is_worker=True, uid="protector"),
        member([OLD_ID], is_worker=True, uid="retired"),
        member([WASH_ID], uid="wash-only"),
        member([AW_ID], uid="aw-only"),
        member([AW_ID, WASH_ID], uid="both"),
        member([needed_role_id], active=False, uid="inactive"),
        member([], is_companion=True, uid="stale-flag"),
    ]
    result = eligible_dispatch_assignees(order, members)
    assert [x.discord_id for x in result] == (
        ["aw-only", "both"] if rule_key in AW_COLLISION_ORDER_RULE_KEYS
        else ["wash-only", "both"]
    )


def test_old_dispatch_snapshot_cannot_bypass_updated_special_role_rule():
    order = SimpleNamespace(
        order_rule_key="staff_internal_ammo_dump_500m",
        dispatch_acceptance_meta={
            "order_rule_key": "staff_internal_ammo_dump_500m",
            "allowed_role_ids_json": json.dumps([COMPANION_ID, PROTECTOR_ID]),
            "required_game_role_ids_json": "[]",
        },
    )
    assert not is_eligible_dispatch_assignee(order, member([COMPANION_ID], is_companion=True))
    assert is_eligible_dispatch_assignee(order, member([SPECIAL_ID]))
    assert cached_staff_role_ids(member(["not-a-role"])) == {"not-a-role"}
    assert cached_staff_role_ids(member([])) == set()


@pytest.mark.parametrize("role_id,label", [(WASH_ID, "洗幣"), (AW_ID, "AW")])
def test_special_roles_are_recognized_by_web_staff_sync_and_login(role_id, label):
    assert HALFCOIN_RECEIVER_ROLE_ID == WASH_ID
    assert AW_COLLISION_RECEIVER_ROLE_ID == AW_ID
    assert role_id in RECEIVER_ROLE_IDS
    assert ROLE_LABEL_BY_ID[role_id] == label
    assert can_login_dashboard([role_id])
    is_cs, is_worker, is_companion = classify_roles([role_id])
    assert is_cs is False
    assert is_worker is True
    assert is_companion is False


def test_legacy_web_claim_access_uses_current_special_role_not_old_snapshot():
    old_time = (datetime.now(timezone.utc) - timedelta(minutes=3)).isoformat()
    meta = {
        "order_rule_key": "farm_aw_collision_1_100",
        "required_staff_count": 1,
        "min_protector_count": 0,
        "allowed_role_ids_json": json.dumps([OLD_ID]),
        "required_game_role_ids_json": "[]",
        "specified_staff_ids_json": "[]",
        "status": "waiting_acceptance",
        "created_at": old_time,
    }
    permitted = evaluate_dispatch_claim_access(
        meta=meta,
        active_rows=[],
        order_status="waiting_acceptance",
        user_id="special",
        user_role_ids=[AW_ID],
    )
    denied = evaluate_dispatch_claim_access(
        meta=meta,
        active_rows=[],
        order_status="waiting_acceptance",
        user_id="wrong",
        user_role_ids=[WASH_ID],
    )
    assert permitted["allowed"] is True
    assert denied["allowed"] is False


def test_active_support_assign_rejects_forged_non_special_worker(monkeypatch):
    from web.app.services import dispatch_support as support

    order = SimpleNamespace(
        id=91, status="active", order_rule_key="staff_internal_car_500m"
    )
    class FakeDB:
        def get(self, model, key):
            assert key == 91
            return order
    db = FakeDB()
    selected = {"current": member([COMPANION_ID], is_companion=True)}
    calls = []
    monkeypatch.setattr(
        support,
        "get_staff_member_by_id",
        lambda db, discord_id: selected["current"],
    )
    monkeypatch.setattr(
        support, "add_worker_to_order",
        lambda *args, **kwargs: calls.append(kwargs),
    )

    with pytest.raises(ValueError, match="Discord 接單身分組"):
        assign_companion_from_dispatch(
            db,
            order_id=91,
            companion_discord_id="123",
            support_user={"is_customer_service": True},
        )
    assert not calls

    selected["current"] = member([SPECIAL_ID], uid="123")
    message = assign_companion_from_dispatch(
        db,
        order_id=91,
        companion_discord_id="123",
        support_user={"is_customer_service": True},
    )
    assert "已指派" in message
    assert len(calls) == 1


def test_regular_dispatch_assignment_uses_ordinary_game_roles_and_no_special_backdoor():
    order = SimpleNamespace(
        order_rule_key="basic_entertain_single",
        dispatch_acceptance_meta={
            "order_rule_key": "basic_entertain_single",
            "allowed_role_ids_json": json.dumps([COMPANION_ID]),
            "required_game_role_ids_json": json.dumps(["1555453406041088131"]),
        },
    )
    assert is_eligible_dispatch_assignee(
        order, member([COMPANION_ID, "1555453406041088131"])
    )
    assert not is_eligible_dispatch_assignee(order, member([COMPANION_ID]))
    assert not is_eligible_dispatch_assignee(order, member([SPECIAL_ID]))


def test_aw_snapshot_cannot_trick_web_picker_into_selecting_coin_wash_member():
    order = SimpleNamespace(
        order_rule_key="staff_internal_aw_collision",
        dispatch_acceptance_meta={
            "order_rule_key": "staff_internal_aw_collision",
            "allowed_role_ids_json": json.dumps([WASH_ID]),
            "required_game_role_ids_json": "[]",
        },
    )
    assert not is_eligible_dispatch_assignee(order, member([WASH_ID]))
    assert is_eligible_dispatch_assignee(order, member([AW_ID]))
    assert is_eligible_dispatch_assignee(order, member([AW_ID, WASH_ID]))
