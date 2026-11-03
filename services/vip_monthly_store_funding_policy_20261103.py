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


def install_vip_monthly_store_funding_policy_20261103() -> None:
    """Install the owner-approved store-funded VIP monthly cash policy."""
    from services import order_discounts
    from services import self_service_financials

    order_discounts.DISCOUNT_FUNDING_POLICY[
        VIP_MONTHLY_FUNDING_SOURCE
    ] = order_discounts.FUNDING_STORE

    original = self_service_financials.calculate_self_service_financials
    if getattr(original, "_vip_monthly_store_funding_policy_20261103", False):
        return

    def wrapped_calculate_self_service_financials(rule, price_result, data: dict) -> dict:
        result = original(rule, price_result, data)
        return apply_vip_monthly_store_funding(result)

    wrapped_calculate_self_service_financials._vip_monthly_store_funding_policy_20261103 = True
    self_service_financials.calculate_self_service_financials = (
        wrapped_calculate_self_service_financials
    )


__all__ = [
    "VIP_MONTHLY_FUNDING_SOURCE",
    "VIP_MONTHLY_FUNDING_MODE",
    "apply_vip_monthly_store_funding",
    "install_vip_monthly_store_funding_policy_20261103",
]
