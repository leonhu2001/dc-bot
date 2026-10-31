from services import order_rules
from services.aw_collision_catalog import AW_RULE_KEYS
from services import aw_collision_business_policy
from services import one_companion_one_guard_payout as role_payout
from services import self_service_financials


def test_aw_rules_disable_member_benefits_and_specify():
    for key in AW_RULE_KEYS:
        rule = order_rules.ORDER_RULES[key]
        assert rule.allow_specify is False
        assert rule.vip_discount_allowed is False
        assert rule.point_benefits_allowed is False
        assert rule.loyalty_benefits_enabled is False


def test_aw_payout_is_100_percent_to_worker_with_no_cs_share():
    result = role_payout.calculate_one_companion_one_guard_order_payout(
        rule_key="farm_aw_collision_101_500",
        total_amount=1125,
        worker_roles=[("worker-1", "companion")],
        named_bonus_worker_ids=["worker-1"],
        customer_service_total_amount=1125,
    )

    assert result is not None
    assert result.customer_service_payout == 0
    assert result.customer_service_rate == 0
    assert len(result.worker_payouts) == 1
    worker = result.worker_payouts[0]
    assert worker.base_rate == 1.0
    assert worker.named_bonus_rate == 0
    assert worker.named_bonus_amount == 0
    assert worker.final_payout == 1125
    assert result.total_worker_payout == 1125


def test_aw_financial_policy_is_direct_and_ignores_discount_stacking():
    rule = order_rules.ORDER_RULES["farm_aw_collision_101_500"]
    price = order_rules.calculate_price(rule, quantity=250)
    result = self_service_financials.calculate_self_service_financials(
        rule,
        price,
        {
            "manual_staff_amount": 900,
            "manual_staff_price_reason": "內部價格",
            "manual_discount_percent": 50,
            "cash_coupon_amount": 500,
            "point_discount_coupon_amount": 300,
            "selected_point_benefit_key": "discount_20",
        },
    )

    assert result["customer_pay_amount"] == 900
    assert result["payout_base_amount"] == 900
    assert result["manual_discount_percent"] == 100.0
    assert result["manual_discount_amount"] == 0
    assert result["cash_coupon_amount"] == 0
    assert result["point_discount_coupon_amount"] == 0
    assert result["store_absorbed_amount"] == 0


def test_aw_business_compatibility_installer_does_not_replace_core_functions():
    before_financial = self_service_financials.calculate_self_service_financials
    aw_collision_business_policy.install_aw_collision_business_policy()
    assert self_service_financials.calculate_self_service_financials is before_financial
