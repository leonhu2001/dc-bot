from __future__ import annotations

from dataclasses import dataclass


FUNDING_SHARED = "shared"
FUNDING_STORE = "store"

# 單一規則來源：正常銷售優惠共同分攤；責任型補償與免費服務由店家吸收。
# 未知來源仍預設 store，避免未審核的新福利默默降低打手／客服薪資。
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
    """Return the canonical funding side for a discount/benefit source."""
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


def allocate_store_absorbed_fixed_discount(
    *,
    after_percent_amount: int,
    fixed_discount_amount: int = 0,
    additional_store_discount_amount: int = 0,
    extra_customer_charge_amount: int = 0,
) -> FixedDiscountAllocation:
    """Compatibility allocator for ordinary fixed cash discounts.

    Historical callers use this function for manual fixed discounts and for the
    point/VIP monthly *cash* discounts. From the 2026-10-17 policy these are
    normal sales discounts: they reduce customer payment *and* the payout base,
    so worker / customer-service / store share them proportionally.

    Store-responsibility compensation and service gifts must use
    ``allocate_store_funded_discount`` instead. Keeping that path explicit is
    intentional: a newly added benefit must never silently cut worker pay.
    """
    after_percent = max(0, int(after_percent_amount or 0))
    fixed_discount = max(
        0,
        min(after_percent, int(fixed_discount_amount or 0)),
    )
    after_fixed = max(0, after_percent - fixed_discount)

    # Parameter name is retained for source compatibility. Existing callers put
    # point-cash / VIP monthly cash here; those are now shared fixed discounts.
    additional_shared_discount = max(
        0,
        min(after_fixed, int(additional_store_discount_amount or 0)),
    )
    after_all_shared = max(0, after_fixed - additional_shared_discount)
    extra_charge = max(0, int(extra_customer_charge_amount or 0))

    return FixedDiscountAllocation(
        after_fixed_amount=after_fixed,
        payout_base_amount=after_all_shared + extra_charge,
        customer_pay_amount=after_all_shared + extra_charge,
        store_absorbed_amount=0,
    )


def allocate_store_funded_discount(
    *,
    payout_base_amount: int,
    customer_pay_amount: int,
    discount_amount: int,
) -> FixedDiscountAllocation:
    """Apply a store-funded subsidy without reducing payroll basis."""
    payout_base = max(0, int(payout_base_amount or 0))
    payable = max(0, int(customer_pay_amount or 0))
    discount = max(0, min(payable, int(discount_amount or 0)))
    return FixedDiscountAllocation(
        after_fixed_amount=max(0, payable - discount),
        payout_base_amount=payout_base,
        customer_pay_amount=max(0, payable - discount),
        store_absorbed_amount=discount,
    )
