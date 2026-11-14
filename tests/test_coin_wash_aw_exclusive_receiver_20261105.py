from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import create_engine, text

from services.order_rules import (
    AW_COLLISION_RECEIVER_ROLE_ID,
    COIN_WASH_AW_ORDER_RULE_KEYS,
    COIN_WASH_AW_RECEIVER_ROLE_ID,
    COIN_WASH_ORDER_RULE_KEYS,
    AW_COLLISION_ORDER_RULE_KEYS,
    HALFCOIN_RECEIVER_ROLE_ID,
    ORDER_RULES,
    SOURCE_AUTHORITY_QUALIFICATION_RULE_KEYS,
    get_allowed_role_ids,
    get_base_rule,
    role_ids_match_requirements,
    rule_role_labels,
)
from shared import order_acceptance
from shared.order_state import WAITING_ACCEPTANCE


EXPECTED_RULE_KEYS = {
    "farm_halfcoin_120m",
    "farm_halfcoin_360m",
    "farm_coin_wash_car",
    "farm_coin_wash_ammo_dump",
    "farm_aw_collision_1_100",
    "farm_aw_collision_101_500",
    "farm_aw_collision_501_plus",
    "staff_internal_ammo_dump_500m",
    "staff_internal_car_500m",
    "staff_internal_aw_collision",
}


def test_separate_special_receiver_roles_for_coin_wash_and_aw():
    assert COIN_WASH_AW_RECEIVER_ROLE_ID == "1565369317929918554"  # legacy alias: wash only
    assert HALFCOIN_RECEIVER_ROLE_ID == "1565369317929918554"
    assert AW_COLLISION_RECEIVER_ROLE_ID == "1571080769407942787"
    assert AW_COLLISION_RECEIVER_ROLE_ID != HALFCOIN_RECEIVER_ROLE_ID
    assert COIN_WASH_ORDER_RULE_KEYS.isdisjoint(AW_COLLISION_ORDER_RULE_KEYS)
    assert COIN_WASH_AW_ORDER_RULE_KEYS == EXPECTED_RULE_KEYS
    assert COIN_WASH_AW_ORDER_RULE_KEYS <= SOURCE_AUTHORITY_QUALIFICATION_RULE_KEYS


@pytest.mark.parametrize("rule_key", sorted(EXPECTED_RULE_KEYS))
def test_each_product_only_allows_its_own_role_and_never_the_other(rule_key):
    rule = ORDER_RULES[rule_key]
    is_aw = rule_key in AW_COLLISION_ORDER_RULE_KEYS
    required = AW_COLLISION_RECEIVER_ROLE_ID if is_aw else HALFCOIN_RECEIVER_ROLE_ID
    other = HALFCOIN_RECEIVER_ROLE_ID if is_aw else AW_COLLISION_RECEIVER_ROLE_ID
    assert get_allowed_role_ids(rule) == [required]
    assert rule_role_labels(rule) == ("AW" if is_aw else "洗幣")
    assert rule.required_game_roles == ()
    assert rule.required_roles == ()
    assert role_ids_match_requirements([required], get_allowed_role_ids(rule))
    for other_roles in (
        [other],
        ["1500234130871550004"],  # protector
        ["1500751059239440575"],  # companion
        ["1565369029005287595"],  # obsolete AW receiver role
        [],
    ):
        assert not role_ids_match_requirements(other_roles, get_allowed_role_ids(rule))


@pytest.mark.parametrize(
    "rule_key",
    ["farm_coin_wash_car", "farm_aw_collision_1_100", "staff_internal_car_500m"],
)
def test_admin_override_cannot_broaden_shared_receiver_qualification(monkeypatch, rule_key):
    monkeypatch.setattr(ORDER_RULES, "_refresh_external", lambda: None)
    monkeypatch.setattr(
        ORDER_RULES,
        "_override_cache",
        {
            rule_key: {
                "payload": {
                    "allowed_roles": ["top_protector", "male_companion"],
                    "required_game_roles": ["delta_desktop"],
                }
            }
        },
    )
    rule = ORDER_RULES[rule_key]
    assert rule.allowed_roles == get_base_rule(rule_key).allowed_roles
    assert rule.required_game_roles == ()
    required = (AW_COLLISION_RECEIVER_ROLE_ID if rule_key in AW_COLLISION_ORDER_RULE_KEYS
                else HALFCOIN_RECEIVER_ROLE_ID)
    assert get_allowed_role_ids(rule) == [required]


@pytest.mark.parametrize(
    ("rule_key", "stale_snapshot_role"),
    [
        ("staff_internal_ammo_dump_500m", AW_COLLISION_RECEIVER_ROLE_ID),
        ("staff_internal_car_500m", AW_COLLISION_RECEIVER_ROLE_ID),
        ("staff_internal_aw_collision", HALFCOIN_RECEIVER_ROLE_ID),
        ("farm_aw_collision_1_100", HALFCOIN_RECEIVER_ROLE_ID),
        ("farm_aw_collision_101_500", HALFCOIN_RECEIVER_ROLE_ID),
        ("farm_aw_collision_501_plus", HALFCOIN_RECEIVER_ROLE_ID),
    ],
)
def test_existing_dispatched_orders_reject_stale_role_even_with_old_snapshot(
    monkeypatch, rule_key, stale_snapshot_role,
):
    engine = create_engine("sqlite:///:memory:")
    monkeypatch.setattr(order_acceptance, "engine", engine)
    with engine.begin() as conn:
        conn.execute(text("""
            CREATE TABLE web_orders (
                id INTEGER PRIMARY KEY,
                status TEXT NOT NULL,
                dispatch_message_id TEXT,
                updated_at TEXT
            )
        """))
        conn.execute(
            text("""
                INSERT INTO web_orders(id, status, dispatch_message_id, updated_at)
                VALUES (1, :status, '1000', CURRENT_TIMESTAMP)
            """),
            {"status": WAITING_ACCEPTANCE},
        )

    order_acceptance.create_or_update_acceptance_meta(
        order_id=1,
        order_rule_key=rule_key,
        required_staff_count=1,
        allowed_role_ids=[stale_snapshot_role],
        status=WAITING_ACCEPTANCE,
    )
    past = (
        datetime.now(UTC).replace(tzinfo=None)
        - timedelta(seconds=order_acceptance.PUBLIC_ACCEPTANCE_LOCK_SECONDS + 5)
    ).isoformat(timespec="seconds")
    with engine.begin() as conn:
        conn.execute(
            text("UPDATE order_acceptance_meta SET created_at=:past WHERE order_id=1"),
            {"past": past},
        )

    with pytest.raises(ValueError, match="不符合"):
        order_acceptance.claim_acceptance_order(
            order_id=1,
            staff_discord_id="other_worker",
            staff_display_name="wrong receiver",
            staff_role_ids=[stale_snapshot_role],
            source="discord",
        )

    state = order_acceptance.claim_acceptance_order(
        order_id=1,
        staff_discord_id="correct_worker",
        staff_display_name="authorized receiver",
        staff_role_ids=[
            AW_COLLISION_RECEIVER_ROLE_ID if rule_key in AW_COLLISION_ORDER_RULE_KEYS
            else HALFCOIN_RECEIVER_ROLE_ID
        ],
        source="discord",
    )
    assert state.accepted_count == 1
    assert state.claims[0].staff_discord_id == "correct_worker"


def test_ordinary_orders_keep_existing_receiver_requirements():
    allowed, required = order_acceptance._effective_claim_role_requirements(
        "delta_desktop_basic_some_rule",
        {"1500234130871550004"},
        {"12345"},
    )
    assert allowed == {"1500234130871550004"}
    assert required == {"12345"}
