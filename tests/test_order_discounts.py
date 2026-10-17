from services.order_discounts import (
    FUNDING_SHARED,
    FUNDING_STORE,
    allocate_fixed_discounts,
    allocate_store_absorbed_fixed_discount,
    get_discount_funding_policy,
)
from shared.payout import calculate_order_payout


def test_discount_funding_policy_matches_business_rules():
    assert get_discount_funding_policy("vip_percent") == FUNDING_SHARED
    assert get_discount_funding_policy("manual_percent") == FUNDING_SHARED
    assert get_discount_funding_policy("promotion_percent") == FUNDING_SHARED
    assert get_discount_funding_policy("manual_fixed") == FUNDING_SHARED
    assert get_discount_funding_policy("point_cash") == FUNDING_SHARED
    assert get_discount_funding_policy("vip_monthly_cash") == FUNDING_SHARED

    assert get_discount_funding_policy("customer_compensation") == FUNDING_STORE
    assert get_discount_funding_policy("point_specify") == FUNDING_STORE
    assert get_discount_funding_policy("point_service") == FUNDING_STORE
    assert get_discount_funding_policy("loyalty_coupon") == FUNDING_STORE
    assert get_discount_funding_policy("vip_monthly_service") == FUNDING_STORE

    # Unknown/new benefits must never silently reduce worker payout.
    assert get_discount_funding_policy("future_new_benefit") == FUNDING_STORE


def test_normal_fixed_discount_is_shared_and_lowers_payout_base():
    result = allocate_store_absorbed_fixed_discount(
        after_percent_amount=1000,
        fixed_discount_amount=100,
    )

    assert result.payout_base_amount == 900
    assert result.customer_pay_amount == 900
    assert result.store_absorbed_amount == 0
    assert result.shared_discount_amount == 100


def test_fixed_discount_keeps_prior_percent_discount_in_base():
    result = allocate_store_absorbed_fixed_discount(
        after_percent_amount=900,
        fixed_discount_amount=100,
    )

    assert result.payout_base_amount == 800
    assert result.customer_pay_amount == 800
    assert result.store_absorbed_amount == 0


def test_fixed_and_point_cash_discounts_share_with_specify_fee():
    result = allocate_store_absorbed_fixed_discount(
        after_percent_amount=1000,
        fixed_discount_amount=100,
        additional_store_discount_amount=50,
        extra_customer_charge_amount=100,
    )

    assert result.payout_base_amount == 950
    assert result.customer_pay_amount == 950
    assert result.store_absorbed_amount == 0
    assert result.shared_discount_amount == 150


def test_shared_fixed_discount_is_capped_at_discountable_amount():
    result = allocate_store_absorbed_fixed_discount(
        after_percent_amount=80,
        fixed_discount_amount=100,
    )

    assert result.after_fixed_amount == 0
    assert result.payout_base_amount == 0
    assert result.customer_pay_amount == 0
    assert result.store_absorbed_amount == 0
    assert result.shared_discount_amount == 80


def test_responsibility_compensation_can_still_be_store_funded():
    result = allocate_fixed_discounts(
        after_percent_amount=1000,
        store_discount_amount=100,
    )

    assert result.customer_pay_amount == 900
    assert result.payout_base_amount == 1000
    assert result.store_absorbed_amount == 100


def test_shared_discount_reduces_worker_and_cs_base_together():
    allocation = allocate_store_absorbed_fixed_discount(
        after_percent_amount=1000,
        fixed_discount_amount=100,
    )

    payout = calculate_order_payout(
        total_amount=allocation.payout_base_amount,
        worker_discord_ids=["worker_a"],
        named_bonus_worker_ids=[],
    )

    assert allocation.customer_pay_amount == 900
    assert payout.worker_payouts[0].final_payout == 720
    assert payout.customer_service_payout == 45
