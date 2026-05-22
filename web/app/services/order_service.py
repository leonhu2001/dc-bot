from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from shared.models import OrderAssignment, OrderStatus, WebOrder


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


def get_worker_active_order_count(db: Session, worker_discord_id: str) -> int:
    statement = (
        select(OrderAssignment)
        .join(WebOrder, WebOrder.id == OrderAssignment.order_id)
        .where(OrderAssignment.worker_discord_id == str(worker_discord_id))
        .where(OrderAssignment.is_active.is_(True))
        .where(WebOrder.status == OrderStatus.ACTIVE.value)
    )

    return len(list(db.scalars(statement).all()))