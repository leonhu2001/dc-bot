import json
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from shared.models import (
    OrderAssignment,
    OrderStatus,
    SyncEvent,
    SyncEventStatus,
    SyncEventType,
    WebOrder,
)


def get_display_name(user: dict) -> str:
    return str(
        user.get("global_name")
        or user.get("username")
        or user.get("id")
        or "未知使用者"
    )


def create_demo_orders_if_empty(db: Session) -> None:
    existing_order = db.scalar(select(WebOrder).limit(1))

    if existing_order is not None:
        return

    demo_orders = [
        WebOrder(
            bot_order_no="DEMO-001",
            customer_display_name="測試老闆 A",
            category="Valorant",
            item="陪打",
            quantity=2,
            amount=1000,
            payment_method="街口",
            status=OrderStatus.ACTIVE.value,
            customer_service_display_name="測試客服",
            note="這是測試派單，之後會改成由 Discord bot 寫入。",
        ),
        WebOrder(
            bot_order_no="DEMO-002",
            customer_display_name="測試老闆 B",
            category="基礎單",
            item="技術陪",
            quantity=1,
            amount=800,
            payment_method="轉帳",
            status=OrderStatus.ACTIVE.value,
            customer_service_display_name="測試客服",
            note="測試用 active 訂單。",
        ),
        WebOrder(
            bot_order_no="DEMO-003",
            customer_display_name="測試老闆 C",
            category="趣味單",
            item="瘋狗嘶咬",
            quantity=1,
            amount=1200,
            payment_method="街口",
            status=OrderStatus.ACTIVE.value,
            customer_service_display_name="測試客服",
            note="測試用派單卡片。",
        ),
    ]

    db.add_all(demo_orders)
    db.commit()


def list_active_orders(db: Session) -> list[WebOrder]:
    statement = (
        select(WebOrder)
        .where(WebOrder.status == OrderStatus.ACTIVE.value)
        .options(selectinload(WebOrder.assignments))
        .order_by(WebOrder.created_at.desc())
    )

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


def get_active_assignments_for_order(order: WebOrder) -> list[OrderAssignment]:
    return [
        assignment
        for assignment in order.assignments
        if assignment.is_active
    ]


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
    db.refresh(order)

    return order


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
    db.refresh(order)

    return order