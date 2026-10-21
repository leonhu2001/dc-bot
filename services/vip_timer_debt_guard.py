from __future__ import annotations

from functools import wraps

from sqlalchemy import text


_WEB_INSTALLED = False
_DISCORD_INSTALLED = False


def has_pending_vip_timer_payment(customer_id: str) -> bool:
    from services import vip_timer as timer

    customer = str(customer_id or "").strip()
    if not customer:
        return False
    db = timer.SessionLocal()
    try:
        timer.ensure_vip_timer_tables(db)
        timer.reconcile_customer_sessions(db, customer)
        row = db.execute(text("""
            SELECT 1
            FROM vip_timer_sessions
            WHERE customer_discord_id=:customer_id
              AND status='pending_payment'
            LIMIT 1
        """), {"customer_id": customer}).first()
        db.commit()
        return row is not None
    finally:
        db.close()


def assert_customer_can_create_order(customer_id: str) -> None:
    if has_pending_vip_timer_payment(str(customer_id)):
        raise ValueError(
            "你目前有一張 VIP 自由計時單尚未付款。"
            "請先完成該筆結算，付款完成後才能建立任何新訂單。"
        )


def install_web_pending_timer_debt_guard() -> None:
    global _WEB_INSTALLED
    if _WEB_INSTALLED:
        return

    from web.app.services import public_order_create as create_module

    original_create = create_module.create_public_order

    @wraps(original_create)
    def guarded_create(db, *, customer_id: str, customer_display_name: str, payload: dict, request_key: str):
        assert_customer_can_create_order(str(customer_id))
        return original_create(
            db,
            customer_id=customer_id,
            customer_display_name=customer_display_name,
            payload=payload,
            request_key=request_key,
        )

    create_module.create_public_order = guarded_create
    _WEB_INSTALLED = True


def install_discord_pending_timer_debt_guard() -> None:
    global _DISCORD_INSTALLED
    if _DISCORD_INSTALLED:
        return

    from services import self_service_ui_runtime as ui

    original_create = ui.create_waiting_acceptance_order_from_self_service

    @wraps(original_create)
    async def guarded_create(interaction, *, customer_id: int, channel_id: int):
        assert_customer_can_create_order(str(customer_id))
        return await original_create(
            interaction,
            customer_id=customer_id,
            channel_id=channel_id,
        )

    ui.create_waiting_acceptance_order_from_self_service = guarded_create
    _DISCORD_INSTALLED = True


__all__ = [
    "assert_customer_can_create_order",
    "has_pending_vip_timer_payment",
    "install_discord_pending_timer_debt_guard",
    "install_web_pending_timer_debt_guard",
]
