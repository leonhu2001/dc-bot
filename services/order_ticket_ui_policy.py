from __future__ import annotations

import discord


_INSTALLED = False


def _is_paid_active_order(data: dict) -> bool:
    """Only treat a canonical, completed active payment as an established order."""
    status = str(data.get("status") or "").strip().lower()
    if status != "active":
        return False

    if data.get("payment_processing") or data.get("payment_finalizing"):
        return False

    return any(
        data.get(key)
        for key in (
            "payment_submitted_at",
            "payment_zero_amount_completed_at",
            "payment_review_applied_at",
            "payment_review_finalized_id",
            "receipt_id",
            "receipt_message_id",
            "wallet_transaction_id",
        )
    )


def install_payment_finalize_rename_policy(order_runtime) -> None:
    """Compatibility hook; payment runtime now renames natively after settlement."""
    return None


def install_order_ticket_ui_policy() -> None:
    """Compatibility hook; paid-vs-unpaid prefix is resolved in naming policy."""
    global _INSTALLED
    _INSTALLED = True


__all__ = [
    "install_order_ticket_ui_policy",
    "install_payment_finalize_rename_policy",
]
