from __future__ import annotations

from dataclasses import dataclass


FUNDING_SHARED = "shared"
FUNDING_STORE = "store"

# 單一規則來源：正常銷售優惠由顧客 / 打手 / 客服 / 店家共同承擔；
# 店家責任補償與「送服務」福利仍由店家吸收。
DISCOUNT_FUNDING_POLICY: dict[str, str] = {
    "vip_percent": FUNDING_SHARED,
    "manual_percent": FUNDING_SHARED,
    "promotion_percent": FUNDING_SHARED,
    "manual_fixed": FUNDING_SHARED,
    "point_cash": FUNDING_SHARED,
    "vip_monthly_cash": FUNDING_SHARED,

    "customer_compensation": FUNDING_STORE,
    "point_specify": FUNDING_STORE,
    "point_service": FUNDING_STORE,
    "loyalty_coupon": FUNDING_STORE,
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
    after_fixed_amount: int
    payout_base_amount: int
    customer_pay_amount: int
    store_absorbed_amount: int
    shared_discount_amount: int = 0


def allocate_fixed_discounts(
    *,
    after_percent_amount: int,
    shared_discount_amount: int = 0,
    store_discount_amount: int = 0,
    extra_customer_charge_amount: int = 0,
) -> FixedDiscountAllocation:
    """Allocate shared and store-funded fixed discounts in one canonical step.

    Shared cash discounts reduce both customer payment and the payout base.
    Store-funded discounts reduce customer payment only. Extra customer charges
    (for example an effective specify fee) increase both payment and payout base.
    """
    after_percent = max(0, int(after_percent_amount or 0))
    shared_discount = max(
        0,
        min(after_percent, int(shared_discount_amount or 0)),
    )
    after_shared = max(0, after_percent - shared_discount)

    store_discount = max(
        0,
        min(after_shared, int(store_discount_amount or 0)),
    )
    extra_charge = max(0, int(extra_customer_charge_amount or 0))

    return FixedDiscountAllocation(
        after_fixed_amount=after_shared,
        payout_base_amount=after_shared + extra_charge,
        customer_pay_amount=max(0, after_shared - store_discount + extra_charge),
        store_absorbed_amount=store_discount,
        shared_discount_amount=shared_discount,
    )


def allocate_store_absorbed_fixed_discount(
    *,
    after_percent_amount: int,
    fixed_discount_amount: int = 0,
    additional_store_discount_amount: int = 0,
    extra_customer_charge_amount: int = 0,
) -> FixedDiscountAllocation:
    """Compatibility entry point for the current checkout callers.

    Before the 2026-10-17 policy this function made every fixed cash discount
    store-funded.  Current checkout callers pass normal manual fixed discounts,
    point cash coupons and VIP monthly cash coupons here; those are now shared
    discounts.  The old function name is retained only to avoid a broad runtime
    wiring change.  True store-funded responsibility compensation must call
    ``allocate_fixed_discounts(..., store_discount_amount=...)`` explicitly.
    """
    shared_total = max(0, int(fixed_discount_amount or 0)) + max(
        0,
        int(additional_store_discount_amount or 0),
    )
    return allocate_fixed_discounts(
        after_percent_amount=after_percent_amount,
        shared_discount_amount=shared_total,
        store_discount_amount=0,
        extra_customer_charge_amount=extra_customer_charge_amount,
    )
