from __future__ import annotations

from typing import Any


VIP_MONTHLY_FUNDING_SOURCE = "vip_monthly_cash"
VIP_MONTHLY_FUNDING_MODE = "store"


def apply_vip_monthly_store_funding(result: dict[str, Any]) -> dict[str, Any]:
    """Convert only the VIP monthly cash voucher from shared to store-funded.

    The existing finance engine already subtracts the VIP monthly cash amount
    from the customer's payment.  Under the old shared-discount allocator it
    also subtracted that same amount from the payroll basis.  Restore only that
    monthly-voucher amount to the payout basis and record the same amount as a
    store subsidy.  Ordinary fixed discounts and point-cash discounts keep their
    existing funding policy.
    """
    result = dict(result or {})
    amount = max(0, int(result.get("vip_monthly_cash_amount") or 0))
    if amount <= 0:
        return result

    result["payout_base_amount"] = max(
        0,
        int(result.get("payout_base_amount") or 0) + amount,
    )
    result["store_absorbed_amount"] = max(
        0,
        int(result.get("store_absorbed_amount") or 0) + amount,
    )
    result["vip_monthly_funding"] = VIP_MONTHLY_FUNDING_MODE
    return result


# The calculator now imports apply_vip_monthly_store_funding directly.
# Historical code may still import this module, but startup no longer rebinds
# self_service_financials.calculate_self_service_financials.

__all__ = [
    "VIP_MONTHLY_FUNDING_SOURCE",
    "VIP_MONTHLY_FUNDING_MODE",
    "apply_vip_monthly_store_funding",
]
