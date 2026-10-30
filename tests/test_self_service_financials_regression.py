from types import SimpleNamespace

import pytest

from services import self_service_financials as financials
from services.order_rules import OrderRule, PriceResult
import services.self_service_loyalty_discount as loyalty_discount


def _to_int(value, default=None):
    try:
        if value is None or str(value).strip() == "":
            return default
        return int(value)
    except (TypeError, ValueError):
        return default


def _allocate(
    *,
    after_percent_amount,
    fixed_discount_amount,
    additional_store_discount_amount=0,
    extra_customer_charge_amount=0,
):
    after_percent_amount = int(after_percent_amount or 0)
    fixed_discount_amount = int(fixed_discount_amount or 0)
    additional_store_discount_amount = int(additional_store_discount_amount or 0)
    extra_customer_charge_amount = int(extra_customer_charge_amount or 0)
    return SimpleNamespace(
        payout_base_amount=after_percent_amount + extra_customer_charge_amount,
        customer_pay_amount=max(
            0,
            after_percent_amount
            - fixed_discount_amount
            - additional_store_discount_amount
            + extra_customer_charge_amount,
        ),
        store_absorbed_amount=fixed_discount_amount + additional_store_discount_amount,
    )


def _rule(*, player_count_enabled=False, max_player_count=1):
    return OrderRule(
        category="custom",
        key="finance_regression",
        label="財務回歸測試",
        pricing_type="hourly",
        price=600,
        unit_label="H",
        allowed_roles=("male_companion",),
        required_staff_count=("player_count" if player_count_enabled else 1),
        player_count_enabled=player_count_enabled,
        min_player_count=1,
        max_player_count=max_player_count,
        allow_specify=True,
        specify_fee_default=100,
        specify_fee_by_role={"male_companion": 100},
        point_benefits_allowed=True,
    )


def _price(*, base=600, specify=100):
    return PriceResult(
        base_amount=base,
        specify_fee=specify,
        staff_adjustment_amount=0,
        total_amount=base + specify,
        service_quantity=1,
        required_staff_count=1,
        free_specify_fee=False,
        details=(),
    )


@pytest.fixture(autouse=True)
def _stable_finance_dependencies(monkeypatch):
    monkeypatch.setattr(financials, "_to_int", _to_int)
    monkeypatch.setattr(financials, "allocate_store_absorbed_fixed_discount", _allocate)
    monkeypatch.setattr(
        financials,
        "_resolve_self_service_discount_rate",
        lambda rule, data: (100.0, "", "none", "普通魔丸"),
    )
    monkeypatch.setattr(
        financials,
        "resolve_vip_monthly_cash_discount",
        lambda data, **kwargs: (None, 0),
    )
    monkeypatch.setattr(
        financials,
        "build_vip_monthly_discount_result",
        lambda selected, amount: {},
    )
    monkeypatch.setattr(
        financials,
        "build_vip_monthly_discount_note",
        lambda selected, amount, **kwargs: "",
    )
    monkeypatch.setattr(
        loyalty_discount,
        "resolve_self_service_loyalty_discount",
        lambda **kwargs: {
            "service_value": 0,
            "discount_amount": 0,
            "coupon_id": None,
            "coupon_title": "",
            "coupon": None,
            "service_note": "",
        },
    )


def test_normal_specify_fee_is_collected_and_enters_payout(monkeypatch):
    monkeypatch.setattr(financials, "get_selected_order_point_benefit", lambda data, rule: None)
    monkeypatch.setattr(financials, "calculate_one_seat_service_bonus_value", lambda **kwargs: 0)

    result = financials.calculate_self_service_financials(_rule(), _price(), {"quantity": 1})

    assert result["customer_pay_amount"] == 700
    assert result["payout_base_amount"] == 700
    assert result["store_absorbed_amount"] == 0
    assert result["effective_specify_fee"] == 100


def test_point_waived_specify_fee_is_not_payout_or_store_value(monkeypatch):
    monkeypatch.setattr(
        financials,
        "get_selected_order_point_benefit",
        lambda data, rule: {
            "key": "free_specify",
            "name": "免指定費",
            "cost": 100,
            "kind": "free_specify_fee",
        },
    )
    monkeypatch.setattr(financials, "calculate_one_seat_service_bonus_value", lambda **kwargs: 0)

    result = financials.calculate_self_service_financials(_rule(), _price(), {"quantity": 1})

    assert result["point_waived_specify_fee"] == 100
    assert result["effective_specify_fee"] == 0
    assert result["customer_pay_amount"] == 600
    assert result["payout_base_amount"] == 600
    assert result["store_absorbed_amount"] == 0


def test_point_cash_discount_is_store_absorbed_without_cutting_payout(monkeypatch):
    monkeypatch.setattr(
        financials,
        "get_selected_order_point_benefit",
        lambda data, rule: {
            "key": "cash_200",
            "name": "200T 折價",
            "cost": 200,
            "kind": "cash_discount",
            "amount": 200,
        },
    )
    monkeypatch.setattr(financials, "calculate_one_seat_service_bonus_value", lambda **kwargs: 0)

    result = financials.calculate_self_service_financials(
        _rule(),
        _price(specify=0),
        {"quantity": 1},
    )

    assert result["point_discount_coupon_amount"] == 200
    assert result["customer_pay_amount"] == 400
    assert result["payout_base_amount"] == 600
    assert result["store_absorbed_amount"] == 200


def test_multi_seat_point_service_reward_is_funded_once_per_selected_seat(monkeypatch):
    monkeypatch.setattr(
        financials,
        "get_selected_order_point_benefit",
        lambda data, rule: {
            "key": "extra_hour",
            "name": "加贈 1H",
            "cost": 300,
            "kind": "extra_hours",
            "hours": 1,
            "seat_count": 4,
        },
    )
    monkeypatch.setattr(financials, "calculate_one_seat_service_bonus_value", lambda **kwargs: 100)
    monkeypatch.setattr(
        financials,
        "resolve_rule_staff_count",
        lambda rule, player_count: int(player_count or 1),
    )

    result = financials.calculate_self_service_financials(
        _rule(player_count_enabled=True, max_player_count=4),
        _price(base=900, specify=0),
        {"quantity": 1, "player_count": 3},
    )

    assert result["point_service_value"] == 300
    assert result["customer_pay_amount"] == 900
    assert result["payout_base_amount"] == 1200
    assert result["store_absorbed_amount"] == 300
