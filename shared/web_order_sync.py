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


def update_web_order_status_by_ticket_channel(
    *,
    ticket_channel_id,
    status: str,
    dispatch_message_id=None,
    note: str | None = None,
) -> bool:
    """Update dashboard order status from Discord bot lifecycle actions."""
    ticket_channel_id_text = _to_text_id(ticket_channel_id)

    if ticket_channel_id_text is None:
        raise ValueError("ticket_channel_id is required")

    db = SessionLocal()

    try:
        order = db.scalar(
            select(WebOrder)
            .where(WebOrder.ticket_channel_id == ticket_channel_id_text)
            .limit(1)
        )

        if order is None:
            return False

        order.status = str(status or "active")

        dispatch_message_id_text = _to_text_id(dispatch_message_id)
        if dispatch_message_id_text:
            order.dispatch_message_id = dispatch_message_id_text

        if note:
            order.note = note

        db.commit()
        return True
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()

# --- Discord claim -> Web dashboard sync ---------------------------------
# These helpers are called by bot.py when someone presses the Discord dispatch
# claim / cancel-claim buttons. Website-originated claims already go through
# web/app/services/order_service.py; this mirrors Discord-originated changes
# into the same dashboard tables so /dispatch and payout pages stay consistent.

from datetime import datetime

from sqlalchemy import delete

from shared.models import (
    CustomerServicePayout,
    OrderAssignment,
    PayoutStatus,
    WorkerPayout,
    WorkerPayoutOverride,
)
from shared.payout import calculate_order_payout


def _display_name_from_member(member) -> str:
    return str(
        getattr(member, "display_name", None)
        or getattr(member, "global_name", None)
        or getattr(member, "name", None)
        or getattr(member, "id", None)
        or "未知使用者"
    )


def _recalculate_web_order_payouts(db, order: WebOrder) -> None:
    """Recalculate dashboard payouts from active order_assignments.

    Payout rule:
    - Split total amount by active workers/companions first.
    - Normal worker share = gross_share * 80%.
    - Named bonus worker share = gross_share * 85%.
    """
    assignments = list(
        db.scalars(
            select(OrderAssignment)
            .where(OrderAssignment.order_id == order.id)
            .where(OrderAssignment.is_active.is_(True))
            .order_by(OrderAssignment.assigned_at.asc())
        ).all()
    )

    worker_ids = [str(a.worker_discord_id) for a in assignments]
    named_bonus_worker_ids = [
        str(a.worker_discord_id)
        for a in assignments
        if bool(a.has_named_bonus)
    ]

    payout_result = calculate_order_payout(
        total_amount=int(order.amount or 0),
        worker_discord_ids=worker_ids,
        named_bonus_worker_ids=named_bonus_worker_ids,
    )

    overrides = {
        str(override.worker_discord_id): override
        for override in db.scalars(
            select(WorkerPayoutOverride)
            .where(WorkerPayoutOverride.order_id == order.id)
        ).all()
    }

    assignment_name_map = {
        str(assignment.worker_discord_id): assignment.worker_display_name
        for assignment in assignments
    }

    db.execute(delete(WorkerPayout).where(WorkerPayout.order_id == order.id))
    db.execute(delete(CustomerServicePayout).where(CustomerServicePayout.order_id == order.id))

    for worker_payout in payout_result.worker_payouts:
        override = overrides.get(str(worker_payout.worker_discord_id))
        final_payout = worker_payout.final_payout
        note = None

        if override is not None:
            final_payout = int(override.manual_final_payout or 0)
            note = f"手動指定分潤：{final_payout}T"
            if override.reason:
                note += f"｜原因：{override.reason}"

        db.add(
            WorkerPayout(
                order_id=order.id,
                worker_discord_id=str(worker_payout.worker_discord_id),
                worker_display_name=assignment_name_map.get(str(worker_payout.worker_discord_id)),
                gross_share=worker_payout.gross_share,
                base_rate=worker_payout.base_rate,
                base_payout=worker_payout.base_payout,
                named_bonus_rate=worker_payout.named_bonus_rate,
                named_bonus_amount=worker_payout.named_bonus_amount,
                has_named_bonus=worker_payout.has_named_bonus,
                final_payout=final_payout,
                payout_status=PayoutStatus.UNPAID.value,
                note=note,
            )
        )

    customer_service_discord_id = (
        str(order.customer_service_discord_id)
        if order.customer_service_discord_id
        else "legacy_unassigned_service"
    )
    customer_service_display_name = (
        order.customer_service_display_name
        or "未指定客服"
    )

    db.add(
        CustomerServicePayout(
            order_id=order.id,
            customer_service_discord_id=customer_service_discord_id,
            customer_service_display_name=customer_service_display_name,
            rate=payout_result.customer_service_rate,
            payout_amount=payout_result.customer_service_payout,
            payout_status=PayoutStatus.UNPAID.value,
        )
    )


def sync_web_worker_claim_from_dispatch(
    *,
    dispatch_message_id,
    worker_discord_id,
    worker_display_name: str | None = None,
    role_type: str = "booster",
    claimed: bool = True,
) -> bool:
    """Mirror a Discord dispatch button claim/unclaim into web dashboard DB.

    Returns True when a matching WebOrder was found and updated.
    Returns False when the dashboard does not know this dispatch message yet.
    """
    dispatch_message_id_text = _to_text_id(dispatch_message_id)
    worker_discord_id_text = _to_text_id(worker_discord_id)

    if not dispatch_message_id_text or not worker_discord_id_text:
        return False

    db = SessionLocal()

    try:
        order = db.scalar(
            select(WebOrder)
            .where(WebOrder.dispatch_message_id == dispatch_message_id_text)
            .limit(1)
        )

        if order is None:
            return False

        assignment = db.scalar(
            select(OrderAssignment)
            .where(OrderAssignment.order_id == order.id)
            .where(OrderAssignment.worker_discord_id == worker_discord_id_text)
            .limit(1)
        )

        if claimed:
            if assignment is None:
                assignment = OrderAssignment(
                    order_id=order.id,
                    worker_discord_id=worker_discord_id_text,
                    worker_display_name=worker_display_name or worker_discord_id_text,
                    role_type=str(role_type or "booster"),
                    is_active=True,
                    has_named_bonus=False,
                )
                db.add(assignment)
            else:
                assignment.worker_display_name = worker_display_name or assignment.worker_display_name
                assignment.role_type = str(role_type or assignment.role_type or "booster")
                assignment.is_active = True
                assignment.removed_at = None
        else:
            if assignment is not None:
                assignment.is_active = False
                assignment.removed_at = datetime.utcnow()
                assignment.has_named_bonus = False

        db.flush()
        _recalculate_web_order_payouts(db, order)
        db.commit()
        return True
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()

