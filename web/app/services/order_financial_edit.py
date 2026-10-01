from __future__ import annotations


def preserve_order_financial_gaps(
    *,
    previous_amount: int,
    previous_customer_pay_amount: int | None,
    previous_payout_base_amount: int | None,
    new_amount: int,
) -> dict[str, int | None]:
    """Preserve existing absolute financial gaps during generic admin edits.

    Generic order editing should not silently erase an already-recorded
    customer discount or payout-base adjustment. Dedicated finance tools can
    still change those values explicitly.
    """
    previous_amount = max(0, int(previous_amount or 0))
    new_amount = max(0, int(new_amount or 0))

    if previous_customer_pay_amount is None:
        new_customer_pay_amount = None
    else:
        customer_gap = max(
            0,
            previous_amount - int(previous_customer_pay_amount),
        )
        new_customer_pay_amount = max(
            0,
            new_amount - customer_gap,
        )

    if previous_payout_base_amount is None:
        new_payout_base_amount = new_amount
    else:
        payout_gap = max(
            0,
            previous_amount - int(previous_payout_base_amount),
        )
        new_payout_base_amount = max(
            0,
            new_amount - payout_gap,
        )

    return {
        "customer_pay_amount": new_customer_pay_amount,
        "payout_base_amount": new_payout_base_amount,
    }
