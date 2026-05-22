from __future__ import annotations

import json
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from shared.db import SessionLocal
from shared.models import OrderAssignment, SyncEvent, SyncEventStatus, WebOrder


SYNC_EVENT_TYPES_FOR_DISCORD = {
    "order_claimed",
    "order_unclaimed",
    "order_updated",
    "order_closed",
    "order_cancelled",
}


def _to_int(value, default: int = 0) -> int:
    try:
        if value is None or value == "":
            return default
        return int(value)
    except (TypeError, ValueError):
        return default


def fetch_pending_web_sync_events(limit: int = 20) -> list[dict]:
    db = SessionLocal()

    try:
        statement = (
            select(SyncEvent)
            .where(SyncEvent.status == SyncEventStatus.PENDING.value)
            .where(SyncEvent.event_type.in_(SYNC_EVENT_TYPES_FOR_DISCORD))
            .order_by(SyncEvent.created_at.asc())
            .limit(max(1, min(int(limit or 20), 100)))
        )

        events = []

        for event in db.scalars(statement).all():
            events.append(
                {
                    "id": event.id,
                    "event_type": event.event_type,
                    "order_id": event.order_id,
                    "payload": json.loads(event.payload_json or "{}"),
                }
            )

        return events
    finally:
        db.close()


def mark_web_sync_event_processing(event_id: int) -> None:
    db = SessionLocal()

    try:
        event = db.get(SyncEvent, int(event_id))
        if event is None:
            return

        event.status = SyncEventStatus.PROCESSING.value
        db.commit()
    finally:
        db.close()


def mark_web_sync_event_done(event_id: int) -> None:
    db = SessionLocal()

    try:
        event = db.get(SyncEvent, int(event_id))
        if event is None:
            return

        event.status = SyncEventStatus.DONE.value
        event.error_message = None
        event.processed_at = datetime.utcnow()
        db.commit()
    finally:
        db.close()


def mark_web_sync_event_failed(event_id: int, error_message: str) -> None:
    db = SessionLocal()

    try:
        event = db.get(SyncEvent, int(event_id))
        if event is None:
            return

        event.retry_count = int(event.retry_count or 0) + 1
        event.error_message = str(error_message)[:3000]
        event.processed_at = datetime.utcnow()

        if event.retry_count >= 5:
            event.status = SyncEventStatus.FAILED.value
        else:
            event.status = SyncEventStatus.PENDING.value

        db.commit()
    finally:
        db.close()


def get_web_order_sync_payload(order_id: int) -> dict:
    db = SessionLocal()

    try:
        order = db.scalar(
            select(WebOrder)
            .where(WebOrder.id == int(order_id))
            .options(selectinload(WebOrder.assignments))
            .limit(1)
        )

        if order is None:
            raise ValueError(f"web order not found: {order_id}")

        active_assignments: list[OrderAssignment] = [
            assignment
            for assignment in order.assignments
            if assignment.is_active
        ]

        companion_ids = []
        booster_ids = []

        for assignment in active_assignments:
            worker_id = _to_int(assignment.worker_discord_id, 0)
            if not worker_id:
                continue

            role_type = str(assignment.role_type or "booster").lower()
            if role_type == "companion":
                companion_ids.append(worker_id)
            else:
                booster_ids.append(worker_id)

        return {
            "id": order.id,
            "bot_order_no": order.bot_order_no,
            "ticket_channel_id": order.ticket_channel_id,
            "dispatch_channel_id": order.dispatch_channel_id,
            "dispatch_message_id": order.dispatch_message_id,
            "customer_discord_id": order.customer_discord_id,
            "customer_display_name": order.customer_display_name,
            "category": order.category,
            "item": order.item,
            "quantity": order.quantity,
            "amount": order.amount,
            "payment_method": order.payment_method,
            "status": order.status,
            "customer_service_discord_id": order.customer_service_discord_id,
            "customer_service_display_name": order.customer_service_display_name,
            "note": order.note,
            "companion_preference": None,
            "companion_ids": companion_ids,
            "booster_ids": booster_ids,
            "locked": str(order.status or "active").lower() in {"stored", "closed", "cancelled", "canceled"},
        }
    finally:
        db.close()
