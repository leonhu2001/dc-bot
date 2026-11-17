"""Owner-approved Black Tide 5-seat source/Discord/Web parity regressions.

Never revive old four-seat prices or mutate legacy order/payout snapshots.
"""
from __future__ import annotations

import pytest

from services.order_rules import (
    BLACK_TIDE_APPROVAL_REVISION_MARKER,
    ORDER_RULES,
    calculate_price,
    get_base_rule,
    get_rule,
    rule_to_override_payload,
)
from services.orders import get_order_item_details_for_group
from services.loyalty_benefits import (
    HOURLY_BONUS,
    HOURLY_THRESHOLD,
    loyalty_policy_for_rule,
)
from services.quick_order_v2_price_lists import DELTA_DESKTOP_PRICE_LISTS
from web.app.services.order_groups import get_grouped_order_catalog


@pytest.mark.parametrize("rule_key,amounts", [
    ("basic_black_tide_entertain", (350, 650, 975, 1300, 1625)),
    ("basic_black_tide_tech", (450, 850, 1275, 1700, 2125)),
])
def test_black_tide_each_hourly_seat_price_and_max_five(rule_key, amounts):
    rule = get_rule(rule_key)
    assert rule.category == "delta_desktop_basic"
    assert rule.pricing_type == "hourly"
    assert rule.min_player_count == 1
    assert rule.max_player_count == 5
    assert rule.max_specified_count == 5
    assert rule.required_staff_count == "player_count"
    for seats, amount in enumerate(amounts, start=1):
        quote = calculate_price(rule, quantity=1, player_count=seats)
        assert quote.base_amount == amount
        assert quote.required_staff_count == seats
        assert calculate_price(
            rule, quantity=2, player_count=seats
        ).base_amount == amount * 2
    with pytest.raises(ValueError, match="最多只能點"):
        calculate_price(rule, quantity=1, player_count=6)


@pytest.mark.parametrize("rule_key,role", [
    ("basic_black_tide_entertain", "female_companion"),
    ("basic_black_tide_tech", "top_protector"),
])
def test_designation_fee_100_each_and_two_hour_waiver_unchanged(rule_key, role):
    rule = get_rule(rule_key)
    assert rule.specify_free_basis == "quantity"
    assert rule.specify_free_min_units == 2
    one = calculate_price(rule, quantity=1, player_count=1, specified_roles=[role])
    assert one.specify_fee == 100
    two = calculate_price(rule, quantity=2, player_count=1, specified_roles=[role])
    assert two.specify_fee == 0
    assert two.free_specify_fee


@pytest.mark.parametrize("key", [
    "basic_black_tide_entertain", "basic_black_tide_tech",
])
def test_both_black_tide_services_earn_one_hour_voucher_after_ten_hours(key):
    policy = loyalty_policy_for_rule(key)
    assert policy is not None
    assert policy["pricing_type"] == "hourly"
    assert policy["threshold_units"] == HOURLY_THRESHOLD == 10
    assert policy["benefit_kind"] == "extra_hours"
    assert policy["benefit_units"] == HOURLY_BONUS == 1


def test_discord_black_tide_panel_and_web_catalog_show_same_terms():
    copy = DELTA_DESKTOP_PRICE_LISTS["black_tide"]["text"]
    for fragment in (
        "350T / H", "每人 325T / H", "450T / H", "每人 425T / H",
        "2～5 人", "10H", "1H 折價券", "每人 +100T", "2H 以上免指定費",
    ):
        assert fragment in copy, fragment
    for old in ("320T / H", "300T / H", "400T / H", "380T / H", "30 分鐘券"):
        assert old not in copy, old

    web = next(
        item for item in get_grouped_order_catalog("delta_desktop_basic")
        if item["key"] == "black_tide"
    )
    assert [v["rule_key"] for v in web["variants"]] == [
        "basic_black_tide_entertain", "basic_black_tide_tech",
    ]
    description = web["description"]
    for fragment in (
        "單陪 350T/H", "多陪每人 325T/H", "單陪 450T/H",
        "多陪每人 425T/H", "2～5 人", "10H", "1H 折價券",
        "指定每位 +100T", "2H 以上免指定費",
    ):
        assert fragment in description, fragment
    dc = get_order_item_details_for_group("delta_desktop_basic", "黑潮爆破")
    assert [v["rule_key"] for v in dc] == [v["rule_key"] for v in web["variants"]]


@pytest.mark.parametrize("key", ["basic_black_tide_entertain", "basic_black_tide_tech"])
def test_old_manager_approved_four_seat_prices_cannot_override_owner_update(monkeypatch, key):
    base = get_base_rule(key)
    stale = rule_to_override_payload(base)
    stale.update({
        "price": 320 if key.endswith("entertain") else 400,
        "player_count_prices": {"1": 320, "2": 600, "3": 900, "4": 1200},
        "max_player_count": 4,
        "max_specified_count": 4,
        "loyalty_benefits_enabled": False,
        "__owner_confirmed_after_canonical": True,
        "__owner_confirmed_delta_desktop_image_final_20261116": True,
    })
    monkeypatch.setattr(ORDER_RULES, "_refresh_external", lambda: None)
    monkeypatch.setattr(ORDER_RULES, "_override_cache", {key: {"payload": stale}})
    restored = ORDER_RULES[key]
    assert restored.player_count_prices == base.player_count_prices
    assert restored.max_player_count == 5
    assert restored.max_specified_count == 5
    assert restored.loyalty_benefits_enabled


def test_new_explicit_web_manager_publish_can_still_change_black_tide(monkeypatch):
    key = "basic_black_tide_entertain"
    published = rule_to_override_payload(get_base_rule(key))
    published["player_count_prices"] = {"1": 355, "2": 660, "3": 990, "4": 1320, "5": 1650}
    published["price"] = 355
    published["__owner_confirmed_after_canonical"] = True
    published[BLACK_TIDE_APPROVAL_REVISION_MARKER] = True
    monkeypatch.setattr(ORDER_RULES, "_refresh_external", lambda: None)
    monkeypatch.setattr(ORDER_RULES, "_override_cache", {key: {"payload": published}})
    assert calculate_price(ORDER_RULES[key], player_count=5).base_amount == 1650


def test_non_black_tide_delta_entertainment_nov18_price_and_fun_unchanged():
    assert calculate_price(get_rule("basic_entertain_single"), player_count=1).base_amount == 350
    assert calculate_price(get_rule("basic_entertain_single"), player_count=2).base_amount == 680
    assert get_rule("fun_lovebirds").category == "delta_desktop_fun"
