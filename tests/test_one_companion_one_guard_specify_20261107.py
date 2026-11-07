from __future__ import annotations

from types import SimpleNamespace

import pytest

from services import order_rule_store
from services.order_rule_store import ensure_order_rule_store, publish_rule_override
from services.order_rules import (
    ALL_ROLE_IDS,
    ONE_COMPANION_ONE_GUARD_RULE_KEYS,
    ORDER_RULES,
    calculate_price,
    get_base_rule,
    get_rule,
    invalidate_rule_override_cache,
    one_guard_specifiable_companion_role,
    rule_to_override_payload,
)
from services.orders import get_order_item_details_for_group
from services.self_service_selection_runtime import get_specified_staff_entries_for_rule
from web.app.services.checkout_preview import _choose_role_key


@pytest.mark.parametrize(
    "rule_key,base_price",
    [
        ("basic_one_companion_one_guard_secret", 720),
        ("basic_one_companion_one_guard_topsecret", 770),
    ],
)
def test_one_guard_both_difficulties_can_designate_exactly_one_companion(rule_key, base_price):
    rule = get_rule(rule_key)
    assert rule.allow_specify is True
    assert rule.max_specified_count == 1
    assert rule.required_staff_count == 2
    assert rule.min_protector_count == 1
    for companion in ("male_companion", "female_companion"):
        one_hour = calculate_price(rule, quantity=1, specified_roles=[companion])
        assert one_hour.base_amount == base_price
        assert one_hour.specify_fee == 100
        assert one_hour.total_amount == base_price + 100
        two_hours = calculate_price(rule, quantity=2, specified_roles=[companion])
        assert two_hours.base_amount == base_price * 2
        assert two_hours.free_specify_fee
        assert two_hours.specify_fee == 0
        assert two_hours.total_amount == base_price * 2

    for protector in ("top_protector", "male_protector", "female_protector"):
        with pytest.raises(ValueError, match="不可指定護衛"):
            calculate_price(rule, quantity=1, specified_roles=[protector])
    with pytest.raises(ValueError, match="只能指定 1 位陪玩"):
        calculate_price(rule, quantity=1, specified_roles=["male_companion", "female_companion"])


@pytest.mark.parametrize("rule_key", sorted(ONE_COMPANION_ONE_GUARD_RULE_KEYS))
def test_one_guard_specify_member_must_be_companion_only_with_desktop_role(rule_key):
    rule = get_rule(rule_key)
    male = ALL_ROLE_IDS["male_companion"]
    female = ALL_ROLE_IDS["female_companion"]
    guard = ALL_ROLE_IDS["male_protector"]
    desktop = ALL_ROLE_IDS["delta_desktop"]
    mobile = ALL_ROLE_IDS["delta_mobile"]

    assert one_guard_specifiable_companion_role(rule, {male, desktop}) == "male_companion"
    assert one_guard_specifiable_companion_role(rule, {female, desktop}) == "female_companion"
    for role_ids in ({male}, {male, mobile}, {guard, desktop}, {male, guard, desktop}):
        assert one_guard_specifiable_companion_role(rule, role_ids) is None
    assert _choose_role_key(rule, {male, desktop}) == "male_companion"
    assert _choose_role_key(rule, {female, desktop}) == "female_companion"
    for role_ids in ({male, mobile}, {guard, desktop}, {male, guard, desktop}):
        assert _choose_role_key(rule, role_ids) is None


def test_one_guard_discord_picker_filters_guard_and_non_desktop_staff():
    rule = get_rule("basic_one_companion_one_guard_secret")
    ids = ALL_ROLE_IDS

    def member(number, label, roles):
        return SimpleNamespace(
            id=number, display_name=label, name=label, bot=False,
            roles=[SimpleNamespace(id=int(ids[key])) for key in roles],
        )

    guild = SimpleNamespace(members=[
        member(1, "可指定男陪", ["male_companion", "delta_desktop"]),
        member(2, "可指定女陪", ["female_companion", "delta_desktop"]),
        member(3, "不可指定護衛", ["male_protector", "delta_desktop"]),
        member(4, "缺端遊", ["female_companion"]),
        member(5, "雙身分護優先", ["male_companion", "male_protector", "delta_desktop"]),
        member(6, "只有手遊", ["male_companion", "delta_mobile"]),
    ])
    entries = get_specified_staff_entries_for_rule(guild, rule)
    assert {entry["id"] for entry in entries} == {"1", "2"}
    assert {entry["description"] for entry in entries} == {"魔丸♞男陪", "魔丸♟女陪"}


def test_old_manager_override_does_not_turn_designation_off(tmp_path, monkeypatch):
    database = tmp_path / "web_dashboard.db"
    ensure_order_rule_store(database)
    monkeypatch.setattr(order_rule_store, "default_db_path", lambda: database)
    key = "basic_one_companion_one_guard_secret"
    base = get_base_rule(key)
    payload = rule_to_override_payload(base)
    payload["allow_specify"] = False
    payload["max_specified_count"] = 2
    payload["specify_fee_default"] = 0
    payload["specify_fee_by_role"] = {}

    publish_rule_override(
        rule_key=key,
        payload=payload,
        actor_discord_id="1",
        actor_display_name="legacy test",
        expected_active_version=0,
        db_file=database,
    )
    invalidate_rule_override_cache()
    try:
        effective = ORDER_RULES[key]
        assert effective.allow_specify is True
        assert effective.max_specified_count == 1
        assert calculate_price(
            effective, quantity=1, specified_roles=["male_companion"]
        ).specify_fee == 100
    finally:
        invalidate_rule_override_cache()


def test_one_guard_catalog_remains_desktop_only():
    details = get_order_item_details_for_group("delta_desktop_basic", "一陪一護")
    assert {item["rule_key"] for item in details} == ONE_COMPANION_ONE_GUARD_RULE_KEYS
    assert get_order_item_details_for_group("delta_mobile_basic", "一陪一護") == []
