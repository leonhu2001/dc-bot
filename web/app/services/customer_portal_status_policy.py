from __future__ import annotations

from typing import Any


PAID_ACTIVE_STATUS_LABEL = "已付款｜進行中"


def install_customer_portal_status_policy() -> None:
    """Keep paid/active member-order copy internally consistent.

    The canonical order state is already switched to ``active`` after payment is
    applied.  This presentation policy makes that state explicit to customers and
    prevents an empty legacy payment-method field from falling back to ``待付款``.
    """
    from web.app.services import customer_portal

    customer_portal.ORDER_STATUS_LABELS["active"] = PAID_ACTIVE_STATUS_LABEL

    original = customer_portal._order_to_public
    if getattr(original, "_paid_active_status_policy", False):
        return

    def wrapped_order_to_public(
        row,
        *,
        payment: dict[str, Any] | None,
        support: dict[str, Any] | None,
        assignments: list[dict[str, Any]],
        guild_id: str | int | None,
    ) -> dict[str, Any]:
        result = original(
            row,
            payment=payment,
            support=support,
            assignments=assignments,
            guild_id=guild_id,
        )

        if str(result.get("status") or "").strip().lower() != "active":
            return result

        result["status_label"] = PAID_ACTIVE_STATUS_LABEL

        payment_method = str(result.get("payment_method") or "").strip()
        if payment_method in {"", "待付款"}:
            review_method = str((payment or {}).get("payment_method") or "").strip()
            result["payment_method"] = review_method or "已付款"

        return result

    wrapped_order_to_public._paid_active_status_policy = True
    customer_portal._order_to_public = wrapped_order_to_public


__all__ = ["PAID_ACTIVE_STATUS_LABEL", "install_customer_portal_status_policy"]
