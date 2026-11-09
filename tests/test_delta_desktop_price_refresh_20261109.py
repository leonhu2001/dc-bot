from __future__ import annotations

import pytest

from core.vip_levels import get_vip_discount_pay_rate
from services.order_rules import calculate_price, get_rule
from services.orders import get_order_item_details_for_group
from services.quick_order_v2_price_lists import DELTA_DESKTOP_PRICE_LISTS
from services.self_service_point_benefit_policy import check_order_point_benefit_allowed


@pytest.mark.parametrize("key, count, amount", [
    ("basic_entertain_single", 1, 350),
    ("basic_entertain_single", 2, 650),
    ("basic_entertain_female_single", 1, 350),
    ("basic_entertain_male_single", 2, 650),
    ("basic_tech_secret_single", 1, 450),
    ("basic_tech_secret_single", 2, 850),
    ("basic_tech_topsecret_single", 1, 500),
    ("basic_tech_topsecret_single", 2, 950),
    ("basic_one_companion_one_guard_secret", 1, 800),
    ("basic_one_companion_one_guard_topsecret", 1, 900),
])
def test_desktop_pricing_shared_by_discord_and_web(key, count, amount):
    rule = get_rule(key)
    assert rule.category == "delta_desktop_basic"
    result = calculate_price(rule, quantity=1, player_count=count)
    assert result.total_amount == amount


@pytest.mark.parametrize("key, old_mobile_price, players", [
    ("basic_mobile_entertain_single", 320, 1),
    ("basic_mobile_entertain_single", 600, 2),
    ("basic_mobile_tech_secret_single", 380, 1),
    ("basic_mobile_tech_secret_single", 760, 2),
    ("basic_mobile_tech_topsecret_single", 420, 1),
    ("basic_mobile_tech_topsecret_single", 840, 2),
])
def test_mobile_prices_not_affected(key, old_mobile_price, players):
    assert calculate_price(
        get_rule(key), quantity=1, player_count=players
    ).total_amount == old_mobile_price


@pytest.mark.parametrize("key, price, text", [
    ("basic_trial_500", 500, "850W"),
    ("basic_trial_1000", 1000, "1888W"),
    ("basic_bet_1000", 1200, "800W"),
    ("basic_bet_1500", 1500, "1000W"),
    ("basic_bet_2500", 2400, "1200W"),
    ("basic_oil_fuel", 3000, "2000W"),
    ("basic_oil_satellite", 2000, "1688W"),
    ("basic_oil_all", 4500, "3688W"),
])
def test_fixed_desktop_price_notes_and_order_quoting(key, price, text):
    rule = get_rule(key)
    assert calculate_price(rule, quantity=1).total_amount == price
    assert text in rule.note


def test_new_trial_policy_no_vip_or_points_and_correct_names():
    details = get_order_item_details_for_group("delta_desktop_basic", "體驗單")
    assert [(item["label"], item["rule_key"]) for item in details] == [
        ("普通｜850w", "basic_trial_500"),
        ("尊爵｜1888w", "basic_trial_1000"),
    ]
    for item in details:
        rule = get_rule(item["rule_key"])
        assert rule.vip_discount_allowed is False
        assert rule.point_benefits_allowed is False
        eligible, reason = check_order_point_benefit_allowed(
            rule, {"key": "discount_20"}, {},
        )
        assert eligible is False
        assert "體驗單" in reason


def test_service_copies_match_guarantees_and_no_old_rates():
    text_by_key = {
        key: str(plan["text"])
        for key, plan in DELTA_DESKTOP_PRICE_LISTS.items()
    }
    assert "1 小時內 7 殺" in text_by_key["one_guard"]
    assert "1 小時內 7 殺" in text_by_key["technical"]
    assert "777W 保底" in text_by_key["technical"]
    assert "850W 保底" in text_by_key["technical"]
    assert "普通體驗單不卡底" in text_by_key["trial"]
    assert "打手選圖（絕密）" in text_by_key["bet"]
    assert "GTI 衛星通信天線" in text_by_key["oil"]
    assert "3688W" in text_by_key["oil"]
