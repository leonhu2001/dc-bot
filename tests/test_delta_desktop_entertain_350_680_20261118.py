"""Owner Nov-18 Delta desktop entertainment update is price-only.

All three sellable gender variants use 350T/H single, 680T/H double *total*.
Web, Discord and live checkout use one effective source, with old DB
overrides unable to revive 320/600. Mobile/other games/loyalty unaffected.
"""
from __future__ import annotations

import pytest

from services.order_rules import (
    DELTA_ENTERTAINMENT_APPROVAL_REVISION_MARKER,
    DELTA_ENTERTAINMENT_RULE_KEYS,
    ORDER_RULES,
    calculate_price,
    get_base_rule,
    get_rule,
    rule_to_override_payload,
)
from services.orders import get_order_item_details_for_group
from services.quick_order_v2_price_lists import (
    DELTA_DESKTOP_PRICE_LISTS,
    DELTA_MOBILE_PRICE_LISTS,
)
from web.app.services.order_groups import get_grouped_order_catalog


@pytest.mark.parametrize("key", sorted(DELTA_ENTERTAINMENT_RULE_KEYS))
def test_all_desktop_gender_variants_get_both_owner_prices(key):
    rule = get_rule(key)
    assert rule.category == "delta_desktop_basic"
    assert rule.player_count_prices == {1: 350, 2: 680}
    assert rule.price == 350
    assert rule.price_multiply_player_count is False
    for count, hourly in ((1, 350), (2, 680)):
        for hours in (1, 2, 3):
            result = calculate_price(rule, player_count=count, quantity=hours)
            assert result.base_amount == hourly * hours
            assert result.total_amount == hourly * hours
            assert result.required_staff_count == count


@pytest.mark.parametrize("key", sorted(DELTA_ENTERTAINMENT_RULE_KEYS))
def test_legacy_designation_and_loyalty_terms_remain_identical(key):
    rule = get_rule(key)
    assert rule.loyalty_benefits_enabled is True
    assert rule.specify_fee_default == 100
    assert rule.specify_free_min_units == 2
    assert rule.specify_free_basis == "quantity"
    assert rule.max_specified_count == 2
    assert "不保撤" in rule.note and "無保底" in rule.note
    assert "累積10小時送1小時券" in rule.note

    role = rule.allowed_roles[0]
    one_hour = calculate_price(
        rule, player_count=1, quantity=1, specified_roles=[role],
    )
    assert one_hour.total_amount == 450 and one_hour.specify_fee == 100
    two_hours = calculate_price(
        rule, player_count=1, quantity=2, specified_roles=[role],
    )
    assert two_hours.total_amount == 700 and two_hours.specify_fee == 0
    double_with_two_named = calculate_price(
        rule, player_count=2, quantity=1, specified_roles=[role, role],
    )
    assert double_with_two_named.base_amount == 680
    assert double_with_two_named.specify_fee == 200
    assert double_with_two_named.total_amount == 880


def test_web_catalog_and_discord_selector_both_use_all_three_current_keys():
    variants_dc = get_order_item_details_for_group(
        "delta_desktop_basic", "娛樂陪",
    )
    group_web = next(
        group for group in get_grouped_order_catalog("delta_desktop_basic")
        if group["key"] == "entertain"
    )
    dc_keys = {entry["rule_key"] for entry in variants_dc}
    web_keys = {entry["rule_key"] for entry in group_web["variants"]}
    assert dc_keys == web_keys == DELTA_ENTERTAINMENT_RULE_KEYS
    assert set(entry["price"] for entry in group_web["variants"]) == {350}
    for fragment in ("350T/H", "680T/H", "10小時", "+100T", "2H"):
        assert fragment in group_web["description"].replace(" ", "")
    assert group_web["starting_price"] == 350


def test_discord_price_list_button_has_new_rates_but_same_benefits():
    desktop = DELTA_DESKTOP_PRICE_LISTS["entertainment"]["text"]
    for content in (
        "娛樂單陪", "350T / H",
        "娛樂雙陪", "680T / H",
        "累積 10 小時 → 贈送 1 小時券",
        "每人 +100T", "兩單（2H）以上免指定費", "不保撤、無保底",
    ):
        assert content in desktop
    assert "320T / H" not in desktop
    assert "600T / H" not in desktop
    mobile = DELTA_MOBILE_PRICE_LISTS["entertainment"]["text"]
    assert "320T / H" in mobile and "600T / H" in mobile


def test_mobile_legacy_double_black_tide_and_unrelated_prices_not_changed():
    for key in (
        "basic_mobile_entertain_single",
        "basic_mobile_entertain_female_single",
        "basic_mobile_entertain_male_single",
    ):
        rule = get_rule(key)
        assert rule.player_count_prices == {1: 320, 2: 600}
    for key in (
        "basic_entertain_double",
        "basic_entertain_female_double",
        "basic_entertain_male_double",
    ):
        # Retired historical keys are deliberately not repriced.
        assert get_base_rule(key).price == 600
    assert calculate_price(get_rule("basic_black_tide_entertain"), quantity=1, player_count=1).base_amount == 350
    assert calculate_price(get_rule("basic_black_tide_entertain"), quantity=1, player_count=2).base_amount == 650
    assert get_rule("basic_tech_secret_single").player_count_prices == {1: 450, 2: 850}


@pytest.mark.parametrize("key", sorted(DELTA_ENTERTAINMENT_RULE_KEYS))
def test_previous_approved_manager_price_cannot_rollback_nov18_rates(
    monkeypatch, key,
):
    stale = rule_to_override_payload(get_base_rule(key))
    stale["price"] = 320
    stale["player_count_prices"] = {"1": 320, "2": 600}
    stale["__owner_confirmed_after_canonical"] = True
    stale["__owner_confirmed_delta_desktop_image_final_20261116"] = True
    stale["__owner_confirmed_delta_entertain_320_600_20261116"] = True
    monkeypatch.setattr(ORDER_RULES, "_refresh_external", lambda: None)
    monkeypatch.setattr(
        ORDER_RULES, "_override_cache", {key: {"payload": stale}},
    )
    rule = ORDER_RULES[key]
    assert rule.player_count_prices == {1: 350, 2: 680}
    assert rule.loyalty_benefits_enabled is True
    assert rule.specify_fee_default == 100


def test_future_manager_approval_can_explicitly_update_new_prices(monkeypatch):
    key = "basic_entertain_single"
    payload = rule_to_override_payload(get_base_rule(key))
    payload["price"] = 360
    payload["player_count_prices"] = {"1": 360, "2": 700}
    payload["__owner_confirmed_after_canonical"] = True
    payload[DELTA_ENTERTAINMENT_APPROVAL_REVISION_MARKER] = True
    monkeypatch.setattr(ORDER_RULES, "_refresh_external", lambda: None)
    monkeypatch.setattr(
        ORDER_RULES, "_override_cache", {key: {"payload": payload}},
    )
    assert ORDER_RULES[key].player_count_prices == {1: 360, 2: 700}
