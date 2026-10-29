from __future__ import annotations

from types import SimpleNamespace

import pytest

from services import order_point_redemption as redemption
from services import self_service_financials as financials
from services.order_rules import ORDER_RULES, calculate_price
from services.point_benefit_catalog import (
    adapt_point_benefit_for_rule,
    calculate_service_bonus_point_cost,
    calculate_service_bonus_value,
    get_point_benefit_item,
    uses_dynamic_service_point_cost,
)
from services.quick_order_v2_price_lists import _valorant_price_list
from services.self_service_point_benefit_policy import check_order_point_benefit_allowed


def _benefit(key: str) -> dict:
    item = get_point_benefit_item(key)
    assert item is not None
    return item


def test_lol_grandmaster_ng_dynamic_points_round_per_seat_before_multiplying() -> None:
    rule = ORDER_RULES["lol_grandmaster_ng"]
    small = _benefit("tech_triple_service_small")
    large = _benefit("tech_triple_service_large")

    assert calculate_service_bonus_point_cost(rule=rule, benefit=small, player_count=3) == 270
    assert calculate_service_bonus_point_cost(rule=rule, benefit=large, player_count=3) == 510

    single_small = _benefit("tech_single_service_small")
    single_large = _benefit("tech_single_service_large")
    assert calculate_service_bonus_point_cost(rule=rule, benefit=single_small, player_count=1) == 90
    assert calculate_service_bonus_point_cost(rule=rule, benefit=single_large, player_count=1) == 170

    # Important: 360 / 2 * 0.9 = 162 -> 170 per person, THEN x3 = 510.
    # Rounding only after multiplying all seats would incorrectly produce 490.
    assert calculate_service_bonus_point_cost(rule=rule, benefit=large, player_count=3) != 490


def test_lol_elite_ranked_dynamic_points_match_confirmed_examples() -> None:
    rule = ORDER_RULES["lol_elite_ranked"]

    assert calculate_service_bonus_point_cost(
        rule=rule,
        benefit=_benefit("tech_single_service_small"),
        player_count=1,
    ) == 200
    assert calculate_service_bonus_point_cost(
        rule=rule,
        benefit=_benefit("tech_single_service_large"),
        player_count=1,
    ) == 360
    assert calculate_service_bonus_point_cost(
        rule=rule,
        benefit=_benefit("tech_double_service_small"),
        player_count=2,
    ) == 400
    assert calculate_service_bonus_point_cost(
        rule=rule,
        benefit=_benefit("tech_double_service_large"),
        player_count=2,
    ) == 720


def test_dynamic_catalog_is_enabled_for_lol_valorant_and_apex() -> None:
    examples = (
        ("lol_grandmaster_ng", "tech_single_service_large"),
        ("valorant_ascendant_ng", "tech_single_service_large"),
        ("apex_diamond_ng", "tech_single_service_large"),
    )

    for rule_key, benefit_key in examples:
        rule = ORDER_RULES[rule_key]
        benefit = _benefit(benefit_key)
        assert uses_dynamic_service_point_cost(rule, benefit)
        adapted = adapt_point_benefit_for_rule(rule, benefit)
        assert int(adapted["cost"]) == calculate_service_bonus_point_cost(
            rule=rule,
            benefit=benefit,
            player_count=1,
        )


def test_non_dynamic_catalog_keeps_existing_fixed_point_cost() -> None:
    rule = ORDER_RULES["basic_black_tide_tech"]
    benefit = _benefit("tech_double_service_large")

    assert not uses_dynamic_service_point_cost(rule, benefit)
    assert calculate_service_bonus_point_cost(
        rule=rule,
        benefit=benefit,
        player_count=2,
    ) == int(benefit["cost"])


def test_service_bonus_salary_value_covers_all_actual_companions_without_point_discount() -> None:
    rule = ORDER_RULES["lol_grandmaster_ng"]

    assert calculate_service_bonus_value(
        rule=rule,
        service_original=1080,
        quantity=1,
        player_count=3,
        extra_hours=0.5,
    ) == 540
    assert calculate_service_bonus_value(
        rule=rule,
        service_original=1080,
        quantity=1,
        player_count=3,
        extra_hours=1.0,
    ) == 1080


def test_discord_financial_runtime_funds_three_seats_once_not_twice() -> None:
    rule = ORDER_RULES["lol_grandmaster_ng"]
    price = calculate_price(rule, quantity=1, player_count=3)
    result = financials.calculate_self_service_financials(
        rule,
        price,
        {
            "quantity": 1,
            "player_count": 3,
            "selected_point_benefit_key": "tech_triple_service_large",
        },
    )

    # Purchased service is 360 x 3 = 1080. +1H adds the same 1080 salary value
    # across the three workers. It must not stay at one-seat 360 or double-multiply
    # to 3240 through stacked runtime wrappers.
    assert result["point_service_value"] == 1080
    assert result["store_absorbed_amount"] == 1080
    assert "3 位陪玩同步加贈" in result["service_bonus_text"]


def test_game_service_point_policy_is_no_longer_blocked() -> None:
    rule = ORDER_RULES["lol_grandmaster_ng"]
    benefit = _benefit("tech_triple_service_large")

    allowed, reason = check_order_point_benefit_allowed(
        rule,
        benefit,
        {"quantity": 1, "player_count": 3, "specified_staff_ids": []},
    )

    assert allowed, reason


def test_discord_payment_recomputes_dynamic_cost_and_ignores_stored_snapshot(monkeypatch) -> None:
    monkeypatch.setattr(redemption, "get_order_point_item", get_point_benefit_item, raising=False)

    data = {
        "order_rule_key": "lol_grandmaster_ng",
        "player_count": 3,
        "quantity": 1,
        "selected_point_benefit_key": "tech_triple_service_large",
        "point_benefit_cost": 1,
    }

    info = redemption._get_pending_order_point_benefit_info(data)

    assert info is not None
    assert info["cost"] == 510
    assert data["point_benefit_cost"] == 510

    data["point_benefit_cost"] = 99999
    info = redemption._get_pending_order_point_benefit_info(data)
    assert info is not None
    assert info["cost"] == 510


def test_discord_payment_rejects_dynamic_service_reward_for_wrong_seat_count(monkeypatch) -> None:
    monkeypatch.setattr(redemption, "get_order_point_item", get_point_benefit_item, raising=False)

    data = {
        "order_rule_key": "lol_grandmaster_ng",
        "player_count": 3,
        "quantity": 1,
        "selected_point_benefit_key": "tech_double_service_large",
        "point_benefit_cost": 1,
    }

    with pytest.raises(ValueError, match="陪玩人數"):
        redemption._get_pending_order_point_benefit_info(data)


def test_valorant_two_units_are_free_specify_fee_in_rule_and_copy() -> None:
    rule = ORDER_RULES["valorant_ascendant_ranked"]
    result = calculate_price(
        rule,
        quantity=2,
        player_count=1,
        specified_roles=["valorant_ascendant"],
    )

    assert result.free_specify_fee is True
    assert result.specify_fee == 0

    text = _valorant_price_list(SimpleNamespace(guild=None))
    assert "2H 或 2局以上免指定費" in text
    assert "500T" not in text
