from services.order_discounts import (
    allocate_store_absorbed_fixed_discount,
)
from shared.payout import calculate_order_payout


def test_fixed_discount_is_fully_absorbed_by_store():
    result = allocate_store_absorbed_fixed_discount(
        after_percent_amount=1000,
        fixed_discount_amount=100,
    )

    assert result.payout_base_amount == 1000
    assert result.customer_pay_amount == 900
    assert result.store_absorbed_amount == 100


def test_fixed_discount_does_not_reverse_percent_discount_on_payout_base():
    result = allocate_store_absorbed_fixed_discount(
        after_percent_amount=900,
        fixed_discount_amount=100,
    )

    assert result.payout_base_amount == 900
    assert result.customer_pay_amount == 800
    assert result.store_absorbed_amount == 100


def test_fixed_and_point_discounts_are_store_absorbed_with_specify_fee():
    result = allocate_store_absorbed_fixed_discount(
        after_percent_amount=1000,
        fixed_discount_amount=100,
        additional_store_discount_amount=50,
        extra_customer_charge_amount=100,
    )

    assert result.payout_base_amount == 1100
    assert result.customer_pay_amount == 950
    assert result.store_absorbed_amount == 150


def test_fixed_discount_is_capped_at_discountable_amount():
    result = allocate_store_absorbed_fixed_discount(
        after_percent_amount=80,
        fixed_discount_amount=100,
    )

    assert result.after_fixed_amount == 0
    assert result.payout_base_amount == 80
    assert result.customer_pay_amount == 0
    assert result.store_absorbed_amount == 80


def test_fixed_discount_keeps_actual_worker_payout_unchanged():
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
    assert allocation.store_absorbed_amount == 100
    assert payout.worker_payouts[0].final_payout == 800
    assert payout.customer_service_payout == 50
