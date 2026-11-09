from __future__ import annotations

import pytest

from services.order_rules import calculate_price, get_rule
from services.one_companion_one_guard_payout import (
    allocate_integer_gross_shares, payout_bases_for_rule,
)
from services.quick_order_v2_price_lists import DELTA_DESKTOP_PRICE_LISTS
from services.self_service_point_benefit_policy import check_order_point_benefit_allowed
from web.app.services.order_groups import get_grouped_order_catalog


@pytest.mark.parametrize("key,base,seat_prices", [
    ("basic_entertain_single", 350, {1: 350, 2: 650}),
    ("basic_entertain_female_single", 350, {1: 350, 2: 650}),
    ("basic_entertain_male_single", 350, {1: 350, 2: 650}),
    ("basic_tech_secret_single", 450, {1: 450, 2: 850}),
    ("basic_tech_topsecret_single", 500, {1: 500, 2: 950}),
])
def test_desktop_hourly_rules_charge_new_owner_prices(key, base, seat_prices):
    rule = get_rule(key)
    assert rule.category == "delta_desktop_basic"
    assert rule.price == base
    assert rule.player_count_prices == seat_prices
    for seats, unit_price in seat_prices.items():
        assert calculate_price(rule, player_count=seats, quantity=2).total_amount == unit_price * 2


@pytest.mark.parametrize("key,price,description", [
    ("basic_trial_500", 500, "850W"),
    ("basic_trial_1000", 1000, "1888W"),
    ("basic_bet_1000", 1300, "800W"),
    ("basic_bet_1500", 1800, "1000W"),
    ("basic_bet_2500", 2400, "1200W"),
    ("basic_oil_fuel", 3000, "2000W"),
    ("basic_oil_satellite", 2000, "1500W"),
    ("basic_oil_all", 4500, "3500W"),
])
def test_desktop_fixed_products_match_price_and_guarantee(key, price, description):
    rule = get_rule(key)
    assert rule.category == "delta_desktop_basic"
    assert calculate_price(rule).total_amount == price
    assert description in rule.note
    if key.startswith("basic_trial_"):
        assert not rule.vip_discount_allowed
        assert not rule.point_benefits_allowed
        assert not rule.loyalty_benefits_enabled


def test_desktop_one_guard_weights_follow_new_entertainment_and_tech_single_prices():
    for key, weights in (
        ("basic_one_companion_one_guard_secret", (450, 350)),
        ("basic_one_companion_one_guard_topsecret", (500, 350)),
    ):
        rule = get_rule(key)
        assert rule.price == sum(weights)
        assert payout_bases_for_rule(key) == weights
        allocation = allocate_integer_gross_shares(
            key, [("protector", "booster"), ("companion", "companion")], rule.price
        )
        assert allocation == {"protector": weights[0], "companion": weights[1]}
        assert calculate_price(rule, quantity=2, specified_roles=[
            "female_protector", "male_companion",
        ]).specify_fee == 0
        assert calculate_price(rule, quantity=1, specified_roles=[
            "female_protector", "male_companion",
        ]).specify_fee == 200


def test_desktop_and_mobile_catalogs_are_not_confused():
    desktop = {
        item["key"]: item
        for item in get_grouped_order_catalog("delta_desktop_basic")
    }
    mobile = {
        item["key"]: item
        for item in get_grouped_order_catalog("delta_mobile_basic")
    }
    assert desktop["entertain"]["starting_price"] == 350
    assert desktop["tech_play"]["starting_price"] == 450
    assert desktop["trial"]["starting_price"] == 500
    assert mobile["entertain_mobile"]["starting_price"] == 320
    assert mobile["tech_play_mobile"]["starting_price"] == 380
    assert get_rule("basic_mobile_entertain_single").player_count_prices == {1: 320, 2: 600}
    assert get_rule("basic_mobile_tech_topsecret_single").player_count_prices == {1: 420, 2: 840}


def test_desktop_public_copy_guarantees_and_no_discounts():
    p = DELTA_DESKTOP_PRICE_LISTS
    assert "不卡底" in p["trial"]["text"]
    assert "850W" in p["trial"]["text"] and "1888W" in p["trial"]["text"]
    assert "1 小時內 7 殺" in p["one_guard"]["text"]
    assert "1 小時內 7 殺" in p["technical"]["text"]
    assert "777W 保底" in p["technical"]["text"]
    assert "850W 保底" in p["technical"]["text"]
    for key in ("basic_trial_500", "basic_trial_1000"):
        rule = get_rule(key)
        allowed, reason = check_order_point_benefit_allowed(
            rule, {"key": "discount_20"}, {"quantity": 1}
        )
        assert not allowed
        assert "折扣" in reason
