from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class FixedDiscountAllocation:
    """Resolved financial amounts for a store-absorbed fixed discount."""

    after_fixed_amount: int
    payout_base_amount: int
    customer_pay_amount: int
    store_absorbed_amount: int


def allocate_store_absorbed_fixed_discount(
    *,
    after_percent_amount: int,
    fixed_discount_amount: int = 0,
    additional_store_discount_amount: int = 0,
    extra_customer_charge_amount: int = 0,
) -> FixedDiscountAllocation:
    """Allocate fixed discounts without reducing the payout base.

    Percentage discounts are expected to have already been applied to
    after_percent_amount. A fixed discount entered by customer service is
    fully absorbed by the store, so it lowers what the customer pays but does
    not lower worker/customer-service payout calculations.

    additional_store_discount_amount is for other store-funded discounts such
    as point cash coupons. extra_customer_charge_amount covers charges such as
    effective specify fees that are added after the service amount.
    """

    after_percent = max(0, int(after_percent_amount or 0))
    fixed_discount = max(
        0,
        min(after_percent, int(fixed_discount_amount or 0)),
    )

    after_fixed = max(0, after_percent - fixed_discount)

    additional_store_discount = max(
        0,
        min(after_fixed, int(additional_store_discount_amount or 0)),
    )
    extra_charge = max(0, int(extra_customer_charge_amount or 0))

    return FixedDiscountAllocation(
        after_fixed_amount=after_fixed,
        payout_base_amount=after_percent + extra_charge,
        customer_pay_amount=(
            after_fixed
            - additional_store_discount
            + extra_charge
        ),
        store_absorbed_amount=(
            fixed_discount
            + additional_store_discount
        ),
    )
