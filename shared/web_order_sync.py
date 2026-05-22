from __future__ import annotations

from sqlalchemy import select

from shared.db import SessionLocal
from shared.models import WebOrder


def _to_text_id(value) -> str | None:
    if value is None:
        return None

    text = str(value).strip()
    return text or None


def _to_int(value, default: int = 0) -> int:
    try:
        if value is None or value == "":
            return default
        return int(value)
    except (TypeError, ValueError):
        return default


def upsert_web_order_from_dispatch(
    *,
    ticket_channel_id,
    dispatch_channel_id,
    dispatch_message_id,
    customer_discord_id,
    customer_display_name: str | None,
    category: str,
    item: str,
    quantity,
    amount,
    payment_method: str | None,
    status: str = "active",
    customer_service_discord_id=None,
    customer_service_display_name: str | None = None,
    bot_order_no: str | None = None,
    note: str | None = None,
) -> WebOrder:
    """Create/update the dashboard order record from a Discord bot dispatch.

    This function is intentionally small and synchronous so bot.py can call it
    after sending a dispatch message without needing web routes.
    """
    ticket_channel_id_text = _to_text_id(ticket_channel_id)
    dispatch_message_id_text = _to_text_id(dispatch_message_id)

    if ticket_channel_id_text is None:
        raise ValueError("ticket_channel_id is required")

    db = SessionLocal()

    try:
        order = None

        if ticket_channel_id_text:
            order = db.scalar(
                select(WebOrder)
                .where(WebOrder.ticket_channel_id == ticket_channel_id_text)
                .limit(1)
            )

        if order is None and dispatch_message_id_text:
            order = db.scalar(
                select(WebOrder)
                .where(WebOrder.dispatch_message_id == dispatch_message_id_text)
                .limit(1)
            )

        if order is None:
            order = WebOrder(
                ticket_channel_id=ticket_channel_id_text,
                category=str(category or "未紀錄"),
                item=str(item or "未紀錄"),
            )
            db.add(order)

        order.bot_order_no = bot_order_no
        order.ticket_channel_id = ticket_channel_id_text
        order.dispatch_channel_id = _to_text_id(dispatch_channel_id)
        order.dispatch_message_id = dispatch_message_id_text

        order.customer_discord_id = _to_text_id(customer_discord_id)
        order.customer_display_name = customer_display_name

        order.category = str(category or "未紀錄")
        order.item = str(item or "未紀錄")
        order.quantity = _to_int(quantity, 1) or 1
        order.amount = _to_int(amount, 0)
        order.payment_method = payment_method or "未紀錄"
        order.status = str(status or "active")

        order.customer_service_discord_id = _to_text_id(customer_service_discord_id)
        order.customer_service_display_name = customer_service_display_name

        if note:
            order.note = note

        db.commit()
        db.refresh(order)

        return order
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
