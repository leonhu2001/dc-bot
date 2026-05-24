import json
from datetime import datetime

from sqlalchemy import delete, select
from sqlalchemy.orm import Session, selectinload

from shared.models import (
    CustomerServicePayout,
    OrderAssignment,
    OrderStatus,
    PayoutStatus,
    SyncEvent,
    SyncEventStatus,
    SyncEventType,
    WebOrder,
    WorkerPayout,
    WorkerPayoutOverride,
)
from shared.payout import calculate_order_payout


def get_display_name(user: dict) -> str:
    return str(
        user.get("global_name")
        or user.get("username")
        or user.get("id")
        or "未知使用者"
    )


def create_demo_orders_if_empty(db: Session) -> None:
    # 正式環境不再自動建立 DEMO 測試訂單。
    return


def list_active_orders(db: Session) -> list[WebOrder]:
    statement = (
        select(WebOrder)
        .where(WebOrder.status == OrderStatus.ACTIVE.value)
        .options(selectinload(WebOrder.assignments))
        .options(selectinload(WebOrder.payouts))
        .order_by(WebOrder.created_at.desc())
    )

    return list(db.scalars(statement).all())


def list_admin_orders(db: Session, status_filter: str | None = "active") -> list[WebOrder]:
    statement = (
        select(WebOrder)
        .options(selectinload(WebOrder.assignments))
        .options(selectinload(WebOrder.payouts))
        .order_by(WebOrder.created_at.desc())
    )

    if status_filter and status_filter != "all":
        statement = statement.where(WebOrder.status == str(status_filter))

    return list(db.scalars(statement).all())


def get_worker_active_assignments(db: Session, worker_discord_id: str) -> list[OrderAssignment]:
    statement = (
        select(OrderAssignment)
        .join(WebOrder, WebOrder.id == OrderAssignment.order_id)
        .where(OrderAssignment.worker_discord_id == str(worker_discord_id))
        .where(OrderAssignment.is_active.is_(True))
        .where(WebOrder.status == OrderStatus.ACTIVE.value)
        .order_by(OrderAssignment.assigned_at.desc())
    )

    return list(db.scalars(statement).all())


def get_worker_active_order_count(db: Session, worker_discord_id: str) -> int:
    return len(get_worker_active_assignments(db, worker_discord_id))


def get_worker_active_order_ids(db: Session, worker_discord_id: str) -> set[int]:
    return {
        assignment.order_id
        for assignment in get_worker_active_assignments(db, worker_discord_id)
    }


def create_sync_event(
    db: Session,
    *,
    event_type: SyncEventType,
    order_id: int,
    payload: dict,
) -> None:
    db.add(
        SyncEvent(
            event_type=event_type.value,
            status=SyncEventStatus.PENDING.value,
            order_id=order_id,
            payload_json=json.dumps(payload, ensure_ascii=False),
        )
    )


def get_payout_override(
    db: Session,
    *,
    order_id: int,
    worker_discord_id: str,
) -> WorkerPayoutOverride | None:
    return db.scalar(
        select(WorkerPayoutOverride)
        .where(WorkerPayoutOverride.order_id == order_id)
        .where(WorkerPayoutOverride.worker_discord_id == str(worker_discord_id))
        .limit(1)
    )


def recalculate_order_payouts(db: Session, order_id: int) -> None:
    order = db.get(WebOrder, order_id)

    if order is None:
        raise ValueError("找不到這張訂單，無法計算分潤。")

    assignments = list(
        db.scalars(
            select(OrderAssignment)
            .where(OrderAssignment.order_id == order_id)
            .where(OrderAssignment.is_active.is_(True))
            .order_by(OrderAssignment.assigned_at.asc())
        ).all()
    )

    worker_ids = [
        assignment.worker_discord_id
        for assignment in assignments
    ]

    named_bonus_worker_ids = [
        assignment.worker_discord_id
        for assignment in assignments
        if assignment.has_named_bonus
    ]

    payout_result = calculate_order_payout(
        total_amount=int(order.amount or 0),
        worker_discord_ids=worker_ids,
        named_bonus_worker_ids=named_bonus_worker_ids,
    )

    overrides = {
        override.worker_discord_id: override
        for override in db.scalars(
            select(WorkerPayoutOverride)
            .where(WorkerPayoutOverride.order_id == order_id)
        ).all()
    }

    db.execute(delete(WorkerPayout).where(WorkerPayout.order_id == order_id))
    db.execute(delete(CustomerServicePayout).where(CustomerServicePayout.order_id == order_id))

    assignment_name_map = {
        assignment.worker_discord_id: assignment.worker_display_name
        for assignment in assignments
    }

    for worker_payout in payout_result.worker_payouts:
        override = overrides.get(worker_payout.worker_discord_id)
        final_payout = worker_payout.final_payout
        note = None

        if override is not None:
            final_payout = int(override.manual_final_payout or 0)
            note = f"手動指定分潤：{final_payout}T"
            if override.reason:
                note += f"｜原因：{override.reason}"

        db.add(
            WorkerPayout(
                order_id=order_id,
                worker_discord_id=worker_payout.worker_discord_id,
                worker_display_name=assignment_name_map.get(worker_payout.worker_discord_id),
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
        else "demo_customer_service"
    )
    customer_service_display_name = (
        order.customer_service_display_name
        or "測試客服"
    )

    db.add(
        CustomerServicePayout(
            order_id=order_id,
            customer_service_discord_id=customer_service_discord_id,
            customer_service_display_name=customer_service_display_name,
            rate=payout_result.customer_service_rate,
            payout_amount=payout_result.customer_service_payout,
            payout_status=PayoutStatus.UNPAID.value,
        )
    )


def claim_order_for_worker(
    db: Session,
    *,
    order_id: int,
    user: dict,
) -> WebOrder:
    worker_discord_id = str(user["id"])
    worker_display_name = get_display_name(user)

    order = db.get(WebOrder, order_id)

    if order is None:
        raise ValueError("找不到這張訂單。")

    if order.status != OrderStatus.ACTIVE.value:
        raise ValueError("這張訂單不是 active 狀態，不能接單。")

    existing_same_order = db.scalar(
        select(OrderAssignment)
        .where(OrderAssignment.order_id == order_id)
        .where(OrderAssignment.worker_discord_id == worker_discord_id)
        .where(OrderAssignment.is_active.is_(True))
        .limit(1)
    )

    if existing_same_order is not None:
        raise ValueError("你已經接了這張單。")

    active_order_count = get_worker_active_order_count(db, worker_discord_id)

    if active_order_count > 0:
        raise ValueError("你目前已經有 active 訂單，不能再接新的 active 單。")

    assignment = OrderAssignment(
        order_id=order_id,
        worker_discord_id=worker_discord_id,
        worker_display_name=worker_display_name,
        role_type="booster",
        is_active=True,
        has_named_bonus=False,
    )

    db.add(assignment)
    db.flush()

    recalculate_order_payouts(db, order_id)

    create_sync_event(
        db,
        event_type=SyncEventType.ORDER_CLAIMED,
        order_id=order_id,
        payload={
            "order_id": order_id,
            "worker_discord_id": worker_discord_id,
            "worker_display_name": worker_display_name,
        },
    )

    db.commit()

    refreshed_order = db.scalar(
        select(WebOrder)
        .where(WebOrder.id == order_id)
        .options(selectinload(WebOrder.assignments))
        .options(selectinload(WebOrder.payouts))
    )

    if refreshed_order is None:
        raise ValueError("接單成功，但重新讀取訂單失敗。")

    return refreshed_order


def unclaim_order_for_worker(
    db: Session,
    *,
    order_id: int,
    user: dict,
) -> WebOrder:
    worker_discord_id = str(user["id"])
    worker_display_name = get_display_name(user)

    order = db.get(WebOrder, order_id)

    if order is None:
        raise ValueError("找不到這張訂單。")

    if order.status != OrderStatus.ACTIVE.value:
        raise ValueError("這張訂單不是 active 狀態，不能取消接單。")

    assignment = db.scalar(
        select(OrderAssignment)
        .where(OrderAssignment.order_id == order_id)
        .where(OrderAssignment.worker_discord_id == worker_discord_id)
        .where(OrderAssignment.is_active.is_(True))
        .limit(1)
    )

    if assignment is None:
        raise ValueError("你目前沒有接這張單。")

    assignment.is_active = False
    assignment.removed_at = datetime.utcnow()
    assignment.has_named_bonus = False

    db.flush()

    recalculate_order_payouts(db, order_id)

    create_sync_event(
        db,
        event_type=SyncEventType.ORDER_UNCLAIMED,
        order_id=order_id,
        payload={
            "order_id": order_id,
            "worker_discord_id": worker_discord_id,
            "worker_display_name": worker_display_name,
        },
    )

    db.commit()

    refreshed_order = db.scalar(
        select(WebOrder)
        .where(WebOrder.id == order_id)
        .options(selectinload(WebOrder.assignments))
        .options(selectinload(WebOrder.payouts))
    )

    if refreshed_order is None:
        raise ValueError("取消接單成功，但重新讀取訂單失敗。")

    return refreshed_order