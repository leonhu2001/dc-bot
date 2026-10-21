from __future__ import annotations

from typing import Any

from sqlalchemy import text


_DISCORD_INSTALLED = False
_WEB_INSTALLED = False


def get_pending_vip_timer_order_id(customer_id: Any) -> int | None:
    """Return the customer's authoritative unpaid VIP timer order, if any."""
    from services import vip_timer as timer

    customer = str(customer_id or "").strip()
    if not customer:
        return None

    db = timer.SessionLocal()
    try:
        timer.ensure_vip_timer_tables(db)
        # Keep the same reconciliation semantics as the timer storefront: if the
        # linked order has already advanced to a paid/active terminal state, do
        # not keep a stale timer row blocking the customer.
        timer.reconcile_customer_sessions(db, customer)
        row = db.execute(
            text(
                """
                SELECT order_id
                FROM vip_timer_sessions
                WHERE customer_discord_id=:customer_id
                  AND status='pending_payment'
                ORDER BY order_id DESC
                LIMIT 1
                """
            ),
            {"customer_id": customer},
        ).first()
        db.commit()
        return int(row[0]) if row is not None else None
    finally:
        db.close()


def assert_customer_can_create_new_order(customer_id: Any) -> None:
    order_id = get_pending_vip_timer_order_id(customer_id)
    if order_id is None:
        return
    raise ValueError(
        f"你有一張 VIP 自由計時單尚未完成付款（WEB-{order_id}）。"
        "請先完成付款後再建立新訂單；待付款期間一般訂單與新的 VIP 自由計時單都會暫停建立。"
    )


def install_discord_pending_order_guard() -> None:
    """Guard both Discord self-service dispatch references after timer wrapping."""
    global _DISCORD_INSTALLED
    if _DISCORD_INSTALLED:
        return

    from services import self_service_dispatch_runtime as dispatch
    from services import self_service_runtime as runtime

    # VIP timer self-service replaces this creator with its timer-aware wrapper.
    # Install this guard after that integration so the pending-payment check is
    # the outermost boundary for both normal and VIP self-service orders.
    original = runtime.create_self_service_waiting_acceptance_order
    if getattr(original, "_vip_timer_pending_order_guard", False):
        dispatch.create_waiting_acceptance_order = original
        _DISCORD_INSTALLED = True
        return

    async def guarded_create_waiting_acceptance_order(
        interaction,
        *,
        customer_id: int,
        channel_id: int,
        deps,
    ):
        assert_customer_can_create_new_order(customer_id)
        return await original(
            interaction,
            customer_id=customer_id,
            channel_id=channel_id,
            deps=deps,
        )

    guarded_create_waiting_acceptance_order._vip_timer_pending_order_guard = True
    guarded_create_waiting_acceptance_order._vip_timer_pending_order_original = original
    runtime.create_self_service_waiting_acceptance_order = guarded_create_waiting_acceptance_order
    dispatch.create_waiting_acceptance_order = guarded_create_waiting_acceptance_order
    _DISCORD_INSTALLED = True


def install_web_pending_order_guard() -> None:
    """Guard the website's canonical public-order creation service."""
    global _WEB_INSTALLED
    if _WEB_INSTALLED:
        return

    from web.app.services import public_order_create as public_order_module

    original = public_order_module.create_public_order
    if getattr(original, "_vip_timer_pending_order_guard", False):
        _WEB_INSTALLED = True
        return

    def guarded_create_public_order(
        db,
        *,
        customer_id: str,
        customer_display_name: str,
        payload: dict,
        request_key: str,
    ):
        assert_customer_can_create_new_order(customer_id)
        return original(
            db,
            customer_id=customer_id,
            customer_display_name=customer_display_name,
            payload=payload,
            request_key=request_key,
        )

    guarded_create_public_order._vip_timer_pending_order_guard = True
    guarded_create_public_order._vip_timer_pending_order_original = original
    public_order_module.create_public_order = guarded_create_public_order
    _WEB_INSTALLED = True


__all__ = [
    "assert_customer_can_create_new_order",
    "get_pending_vip_timer_order_id",
    "install_discord_pending_order_guard",
    "install_web_pending_order_guard",
]
