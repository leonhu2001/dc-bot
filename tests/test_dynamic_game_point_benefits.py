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
from web.app.services.point_benefit_policy_bridge import install_shared_point_benefit_policy


def _benefit(key: str) -> dict:
    item = get_point_benefit_item(key)
    assert item is not None
    return item


def _configure_redemption_lookup(monkeypatch) -> None:
    monkeypatch.setattr(redemption, "get_order_point_item", get_point_benefit_item, raising=False)

    def _test_to_int(value, default=0):
        try:
            return int(value)
        except (TypeError, ValueError):
            return default

    # Production injects this adapter through configure_order_point_redemption().
    # These focused unit tests call the private pre-payment resolver directly, so
    # mirror that one required runtime dependency instead of weakening production
    # fail-fast configuration.
    monkeypatch.setattr(redemption, "_to_int", _test_to_int, raising=False)


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


def test_black_tide_uses_formal_one_seat_price_instead_of_nonlinear_checkout_total() -> None:
    rule = ORDER_RULES["basic_black_tide_entertain"]
    benefit = _benefit("entertain_double_service_large")

    assert uses_dynamic_service_point_cost(rule, benefit)
    # 黑潮雙陪本體是非線性總價 600，但點數服務福利要用單陪正式價 320
    # 計算：320 / 2 * 0.9 = 144 -> 單席進位 150，再乘 2 席 = 300。
    assert calculate_service_bonus_point_cost(
        rule=rule,
        benefit=benefit,
        player_count=2,
    ) == 300
    assert int(benefit["cost"]) == 280


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
    _configure_redemption_lookup(monkeypatch)

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
    _configure_redemption_lookup(monkeypatch)

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


def test_discord_point_free_specify_fee_is_not_common_payout_or_store_subsidy() -> None:
    rule = ORDER_RULES["valorant_ascendant_ng"]
    price = calculate_price(
        rule,
        quantity=1,
        player_count=1,
        specified_roles=["valorant_ascendant"],
    )
    assert price.specify_fee == 100

    result = financials.calculate_self_service_financials(
        rule,
        price,
        {
            "quantity": 1,
            "player_count": 1,
            "specified_staff_ids": ["123"],
            "selected_point_benefit_key": "free_specify_fee",
        },
    )

    assert result["point_waived_specify_fee"] == 100
    assert result["effective_specify_fee"] == 0
    # Promotions/other shared discounts may already reduce the service amount. The
    # invariant here is that the uncollected specify fee adds nothing to payout.
    assert result["payout_base_amount"] == result["customer_pay_amount"]
    assert result["store_absorbed_amount"] == 0


def test_discord_automatic_free_specify_fee_has_no_phantom_amount() -> None:
    rule = ORDER_RULES["valorant_ascendant_ng"]
    price = calculate_price(
        rule,
        quantity=2,
        player_count=1,
        specified_roles=["valorant_ascendant"],
    )
    assert price.free_specify_fee is True
    assert price.specify_fee == 0

    result = financials.calculate_self_service_financials(
        rule,
        price,
        {
            "quantity": 2,
            "player_count": 1,
            "specified_staff_ids": ["123"],
        },
    )

    assert result["effective_specify_fee"] == 0
    assert result["payout_base_amount"] == result["customer_pay_amount"]
    assert result["store_absorbed_amount"] == 0


def test_web_specify_fee_accounting_matches_discord_and_shared_cash_policy() -> None:
    install_shared_point_benefit_policy()
    from web.app.services import checkout_preview as checkout

    collected = checkout.calculate_checkout_financials(
        service_amount=330,
        vip_pay_rate=100,
        specify_fee=100,
        point_item=None,
        wallet_balance=0,
        use_wallet=False,
    )
    assert collected["customer_pay_amount"] == 430
    assert collected["payout_base_amount"] == 430
    assert collected["store_absorbed_amount"] == 0

    waived = checkout.calculate_checkout_financials(
        service_amount=330,
        vip_pay_rate=100,
        specify_fee=100,
        point_item=_benefit("free_specify_fee"),
        wallet_balance=0,
        use_wallet=False,
    )
    assert waived["customer_pay_amount"] == 330
    assert waived["payout_base_amount"] == 330
    assert waived["point_store_absorbed_amount"] == 0
    assert waived["store_absorbed_amount"] == 0

    cash = checkout.calculate_checkout_financials(
        service_amount=330,
        vip_pay_rate=100,
        specify_fee=0,
        point_item=_benefit("discount_50"),
        wallet_balance=0,
        use_wallet=False,
    )
    assert cash["customer_pay_amount"] == 280
    assert cash["payout_base_amount"] == 280
    assert cash["point_store_absorbed_amount"] == 0
    assert cash["store_absorbed_amount"] == 0
