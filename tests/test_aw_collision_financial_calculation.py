from types import SimpleNamespace

from services import self_service_financials as financials
from services.aw_collision_catalog import AW_RULE_KEYS
from services.order_rules import ORDER_RULES, calculate_price


class _Allocation:
    def __init__(self, amount: int):
        self.payout_base_amount = int(amount)
        self.store_absorbed_amount = 0
        self.customer_pay_amount = int(amount)


def _configure_minimal_financial_runtime():
    financials._to_int = lambda value, default=None: default if value in (None, "") else int(value)
    financials.allocate_store_absorbed_fixed_discount = lambda *, after_percent_amount, **kwargs: _Allocation(after_percent_amount)
    financials.get_self_service_quantity_unit = lambda *args, **kwargs: "發"
    financials._is_specify_preference = lambda value: False
    financials._role_key_for_member = lambda *args, **kwargs: None
    financials.get_customer_reward_data = lambda customer_id: {}
    financials.get_effective_member_level = lambda data: {"name": "鑽石魔丸"}
    financials.get_vip_discount_pay_rate = lambda *args, **kwargs: 90


def test_aw_ignores_vip_and_discount_state_and_uses_internal_price():
    _configure_minimal_financial_runtime()
    rule = ORDER_RULES[AW_RULE_KEYS[1]]
    automatic = calculate_price(rule, quantity=200)

    data = {
        "customer_id": 123,
        "quantity": 200,
        "manual_staff_amount": 777,
        "manual_staff_price_reason": "內部價格",
        "manual_discount_percent": 50,
        "manual_discount_percent_override": True,
        "cash_coupon_amount": 100,
        "fixed_discount_amount": 100,
        "selected_point_benefit_key": "discount_20",
    }

    result = financials.calculate_self_service_financials(rule, automatic, data)

    assert result["service_original_amount"] == 777
    assert result["customer_pay_amount"] == 777
    assert result["payout_base_amount"] == 777
    assert result["discount_rate_percent"] == 100
    assert result["manual_discount_amount"] == 0
    assert result["cash_coupon_amount"] == 0
    assert result["point_discount_coupon_amount"] == 0
    assert result["store_absorbed_amount"] == 0


def test_aw_without_internal_price_keeps_automatic_tier_price():
    _configure_minimal_financial_runtime()
    rule = ORDER_RULES[AW_RULE_KEYS[1]]
    automatic = calculate_price(rule, quantity=200)
    result = financials.calculate_self_service_financials(
        rule,
        automatic,
        {"customer_id": 123, "quantity": 200},
    )

    assert automatic.base_amount == 900
    assert result["customer_pay_amount"] == 900
    assert result["payout_base_amount"] == 900
