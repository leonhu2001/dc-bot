from __future__ import annotations

import sqlite3

import pytest

from services.smart_dispatch import (
    create_smart_dispatch_plan, get_smart_dispatch_plan,
    list_pending_smart_dispatch_plans,
)
from views.smart_dispatch import (
    _reconcile_legacy_receiver_candidates,
    _is_dedicated_receiver_dispatch,
    get_eligible_dispatch_candidate_ids,
)
from types import SimpleNamespace


WASH = "1565369317929918554"
AW = "1571080769407942787"


@pytest.mark.parametrize(
    ("rule_key", "stale_id", "expected_id"),
    [
        ("staff_internal_car_500m", AW, WASH),
        ("staff_internal_ammo_dump_500m", AW, WASH),
        ("farm_coin_wash_car", AW, WASH),
        ("farm_coin_wash_ammo_dump", AW, WASH),
        ("staff_internal_aw_collision", WASH, AW),
        ("farm_aw_collision_1_100", WASH, AW),
        ("farm_aw_collision_101_500", WASH, AW),
        ("farm_aw_collision_501_plus", WASH, AW),
    ],
)
def test_existing_smart_dispatch_plans_reconcile_to_live_receiver(
    tmp_path, rule_key, stale_id, expected_id
):
    db_file = tmp_path / "smart-dispatch.sqlite3"
    with sqlite3.connect(db_file) as db:
        db.execute(
            "CREATE TABLE web_orders (id INTEGER PRIMARY KEY, order_rule_key TEXT)"
        )
        db.execute(
            "INSERT INTO web_orders VALUES (1, ?)", (rule_key,)
        )
        db.commit()

    create_smart_dispatch_plan(
        order_id=1, dispatch_channel_id=5, dispatch_message_id=6,
        required_staff_count=1,
        allowed_role_ids=[stale_id], required_game_role_ids=[],
        specified_staff_ids=[],
        ranked_candidate_ids=["old-member"],
        notified_candidate_ids=["old-member"],
        db_file=db_file,
    )
    for plan in (
        get_smart_dispatch_plan(1, db_file=db_file),
        list_pending_smart_dispatch_plans(db_file=db_file)[0],
    ):
        assert plan["allowed_role_ids"] == [expected_id]
        assert plan["required_game_role_ids"] == []
        assert plan["receiver_roles_reconciled"] is True
        assert _is_dedicated_receiver_dispatch(plan["allowed_role_ids"])

        _reconcile_legacy_receiver_candidates(plan, {"correct-member"})
        assert plan["ranked_candidate_ids"] == ["correct-member"]
        assert plan["notified_candidate_ids"] == []


def test_new_plans_and_regular_orders_remain_unchanged(tmp_path):
    db_file = tmp_path / "smart-dispatch.sqlite3"
    with sqlite3.connect(db_file) as db:
        db.execute(
            "CREATE TABLE web_orders (id INTEGER PRIMARY KEY, order_rule_key TEXT)"
        )
        db.execute("INSERT INTO web_orders VALUES (1, 'staff_internal_aw_collision')")
        db.execute("INSERT INTO web_orders VALUES (2, 'basic_entertain_single')")
        db.commit()

    for order_id, role_id in ((1, AW), (2, "1500751059239440575")):
        create_smart_dispatch_plan(
            order_id=order_id, dispatch_channel_id=5, dispatch_message_id=6,
            required_staff_count=1,
            allowed_role_ids=[role_id], required_game_role_ids=[],
            specified_staff_ids=[],
            ranked_candidate_ids=["worker-a"], notified_candidate_ids=["worker-a"],
            db_file=db_file,
        )
        plan = get_smart_dispatch_plan(order_id, db_file=db_file)
        assert plan["receiver_roles_reconciled"] is False
        _reconcile_legacy_receiver_candidates(plan, {"worker-b"})
        assert plan["ranked_candidate_ids"] == ["worker-a"]
        assert plan["notified_candidate_ids"] == ["worker-a"]


def test_real_discord_member_selection_never_treats_aw_only_as_washer():
    guild = SimpleNamespace(members=[
        SimpleNamespace(id=100, bot=False, roles=[SimpleNamespace(id=int(WASH))]),
        SimpleNamespace(id=200, bot=False, roles=[SimpleNamespace(id=int(AW))]),
        SimpleNamespace(id=300, bot=False, roles=[
            SimpleNamespace(id=int(WASH)), SimpleNamespace(id=int(AW)),
        ]),
    ])
    assert get_eligible_dispatch_candidate_ids(
        guild, allowed_role_ids=[WASH]
    ) == ["100", "300"]
    assert get_eligible_dispatch_candidate_ids(
        guild, allowed_role_ids=[AW]
    ) == ["200", "300"]
