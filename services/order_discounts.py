from __future__ import annotations

from dataclasses import dataclass


FUNDING_SHARED = "shared"
FUNDING_STORE = "store"

# 單一規則來源：價格型百分比折扣降低分潤基準；會員資產／固定補償由店家吸收。
DISCOUNT_FUNDING_POLICY: dict[str, str] = {
    "vip_percent": FUNDING_SHARED,
    "manual_percent": FUNDING_SHARED,
    "promotion_percent": FUNDING_SHARED,
    "manual_fixed": FUNDING_STORE,
    "customer_compensation": FUNDING_STORE,
    "point_cash": FUNDING_STORE,
    "point_specify": FUNDING_STORE,
    "point_service": FUNDING_STORE,
    "loyalty_coupon": FUNDING_STORE,
    "vip_monthly_cash": FUNDING_STORE,
    "vip_monthly_service": FUNDING_STORE,
}


def get_discount_funding_policy(source: str | None) -> str:
    """Return the canonical funding side for a discount/benefit source.

    Unknown sources deliberately default to store-funded so a newly introduced
    benefit cannot silently reduce worker payout before its policy is reviewed.
    """
    key = str(source or "").strip()
    return DISCOUNT_FUNDING_POLICY.get(key, FUNDING_STORE)


def is_store_funded_discount(source: str | None) -> bool:
    return get_discount_funding_policy(source) == FUNDING_STORE


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
    """Allocate store-funded fixed/member-asset benefits without cutting payout.

    Percentage/VIP discounts are applied before this function and therefore
    lower both customer payment and the payout base. Fixed discounts, points,
    monthly VIP cash benefits, loyalty benefits and service compensation are
    store-funded and must not further reduce worker payout.
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
