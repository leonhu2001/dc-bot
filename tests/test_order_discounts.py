import pytest

from services.order_discounts import (
    FUNDING_SHARED,
    FUNDING_STORE,
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

    # A new/unknown benefit must not silently reduce worker payout.
    assert get_discount_funding_policy("future_new_benefit") == FUNDING_STORE


def test_fixed_discount_is_shared_by_customer_and_payout_base():
    result = allocate_store_absorbed_fixed_discount(
        after_percent_amount=1000,
        fixed_discount_amount=100,
    )

    assert result.payout_base_amount == 900
    assert result.customer_pay_amount == 900
    assert result.store_absorbed_amount == 0


def test_fixed_discount_stays_after_percent_discount():
    result = allocate_store_absorbed_fixed_discount(
        after_percent_amount=900,
        fixed_discount_amount=100,
    )

    assert result.payout_base_amount == 800
    assert result.customer_pay_amount == 800
    assert result.store_absorbed_amount == 0


def test_fixed_and_point_cash_discounts_share_payout_base_with_specify_fee():
    result = allocate_store_absorbed_fixed_discount(
        after_percent_amount=1000,
        fixed_discount_amount=100,
        additional_store_discount_amount=50,
        extra_customer_charge_amount=100,
    )

    # 1000 - 100 - 50 + 100 specify fee.
    assert result.payout_base_amount == 950
    assert result.customer_pay_amount == 950
    assert result.store_absorbed_amount == 0


def test_fixed_discount_is_capped_at_discountable_amount():
    result = allocate_store_absorbed_fixed_discount(
        after_percent_amount=80,
        fixed_discount_amount=100,
    )

    assert result.after_fixed_amount == 0
    assert result.payout_base_amount == 0
    assert result.customer_pay_amount == 0
    assert result.store_absorbed_amount == 0


def test_shared_fixed_discount_reduces_worker_and_cs_basis_together():
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
    # 900 x (1 - 80%) x 25% = 45T; persisted effective gross rate remains 5%.
    assert payout.customer_service_payout == pytest.approx(45)
    assert payout.customer_service_rate == pytest.approx(0.05)


def test_named_worker_reduces_customer_service_share_with_margin_pool():
    payout = calculate_order_payout(
        total_amount=1000,
        worker_discord_ids=["worker_a"],
        named_bonus_worker_ids=["worker_a"],
    )

    assert payout.worker_payouts[0].final_payout == pytest.approx(850)
    # Margin pool is 150; CS receives 25% = 37.5T.
    assert payout.customer_service_payout == pytest.approx(37.5)
    assert payout.customer_service_rate == pytest.approx(0.0375)


def test_legacy_customer_service_gross_rate_is_available_for_old_orders():
    payout = calculate_order_payout(
        total_amount=1000,
        worker_discord_ids=["worker_a"],
        named_bonus_worker_ids=["worker_a"],
        legacy_customer_service_gross_rate=0.05,
    )

    assert payout.worker_payouts[0].final_payout == pytest.approx(850)
    assert payout.customer_service_payout == pytest.approx(50)
    assert payout.customer_service_rate == pytest.approx(0.05)
