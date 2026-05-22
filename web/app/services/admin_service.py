import json
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from shared.models import (
    AdminAuditLog,
    OrderAssignment,
    SyncEventType,
    WebOrder,
    WorkerPayoutOverride,
)
from web.app.services.order_service import create_sync_event, recalculate_order_payouts


def get_admin_display_name(user: dict) -> str:
    return str(
        user.get("global_name")
        or user.get("username")
        or user.get("id")
        or "未知管理員"
    )


def write_admin_audit_log(
    db: Session,
    *,
    admin_user: dict,
    action: str,
    target_type: str,
    target_id: str | None = None,
    before: dict | None = None,
    after: dict | None = None,
) -> None:
    db.add(
        AdminAuditLog(
            admin_discord_id=str(admin_user["id"]),
            action=action,
            target_type=target_type,
            target_id=target_id,
            before_json=json.dumps(before, ensure_ascii=False) if before is not None else None,
            after_json=json.dumps(after, ensure_ascii=False) if after is not None else None,
        )
    )


def set_customer_service_for_order(
    db: Session,
    *,
    order_id: int,
    customer_service_discord_id: str,
    customer_service_display_name: str,
    admin_user: dict,
    reason: str | None = None,
) -> None:
    order = db.get(WebOrder, order_id)

    if order is None:
        raise ValueError("找不到這張訂單。")

    customer_service_discord_id = str(customer_service_discord_id).strip()
    customer_service_display_name = str(customer_service_display_name or customer_service_discord_id).strip()

    if not customer_service_discord_id:
        raise ValueError("請輸入客服 Discord ID。")

    before = {
        "order_id": order.id,
        "customer_service_discord_id": order.customer_service_discord_id,
        "customer_service_display_name": order.customer_service_display_name,
    }

    order.customer_service_discord_id = customer_service_discord_id
    order.customer_service_display_name = customer_service_display_name

    db.flush()

    recalculate_order_payouts(db, order_id)

    create_sync_event(
        db,
        event_type=SyncEventType.ORDER_UPDATED,
        order_id=order_id,
        payload={
            "reason": "customer_service_updated",
            "customer_service_discord_id": customer_service_discord_id,
            "customer_service_display_name": customer_service_display_name,
            "admin_discord_id": str(admin_user["id"]),
            "admin_display_name": get_admin_display_name(admin_user),
        },
    )

    write_admin_audit_log(
        db,
        admin_user=admin_user,
        action="set_customer_service_for_order",
        target_type="web_order",
        target_id=str(order_id),
        before=before,
        after={
            "order_id": order.id,
            "customer_service_discord_id": customer_service_discord_id,
            "customer_service_display_name": customer_service_display_name,
            "reason": reason or "",
        },
    )

    db.commit()


def toggle_named_bonus_for_assignment(
    db: Session,
    *,
    assignment_id: int,
    enabled: bool,
    admin_user: dict,
) -> None:
    assignment = db.get(OrderAssignment, assignment_id)

    if assignment is None:
        raise ValueError("找不到這筆接單紀錄。")

    before = {
        "assignment_id": assignment.id,
        "order_id": assignment.order_id,
        "worker_discord_id": assignment.worker_discord_id,
        "has_named_bonus": assignment.has_named_bonus,
    }

    assignment.has_named_bonus = bool(enabled)
    db.flush()

    recalculate_order_payouts(db, assignment.order_id)

    create_sync_event(
        db,
        event_type=SyncEventType.ORDER_UPDATED,
        order_id=assignment.order_id,
        payload={
            "reason": "named_bonus_updated",
            "assignment_id": assignment.id,
            "worker_discord_id": assignment.worker_discord_id,
            "has_named_bonus": bool(enabled),
        },
    )

    write_admin_audit_log(
        db,
        admin_user=admin_user,
        action="toggle_named_bonus",
        target_type="order_assignment",
        target_id=str(assignment.id),
        before=before,
        after={
            **before,
            "has_named_bonus": bool(enabled),
        },
    )

    db.commit()


def remove_worker_from_order(
    db: Session,
    *,
    assignment_id: int,
    admin_user: dict,
    reason: str | None = None,
) -> None:
    assignment = db.get(OrderAssignment, assignment_id)

    if assignment is None:
        raise ValueError("找不到這筆接單紀錄。")

    before = {
        "assignment_id": assignment.id,
        "order_id": assignment.order_id,
        "worker_discord_id": assignment.worker_discord_id,
        "worker_display_name": assignment.worker_display_name,
        "is_active": assignment.is_active,
        "has_named_bonus": assignment.has_named_bonus,
    }

    assignment.is_active = False
    assignment.has_named_bonus = False
    assignment.removed_at = datetime.utcnow()

    db.flush()

    recalculate_order_payouts(db, assignment.order_id)

    create_sync_event(
        db,
        event_type=SyncEventType.ORDER_UNCLAIMED,
        order_id=assignment.order_id,
        payload={
            "reason": "admin_removed_worker",
            "worker_discord_id": assignment.worker_discord_id,
            "worker_display_name": assignment.worker_display_name,
            "admin_discord_id": str(admin_user["id"]),
            "admin_display_name": get_admin_display_name(admin_user),
        },
    )

    write_admin_audit_log(
        db,
        admin_user=admin_user,
        action="remove_worker_from_order",
        target_type="order_assignment",
        target_id=str(assignment.id),
        before=before,
        after={
            **before,
            "is_active": False,
            "has_named_bonus": False,
            "reason": reason or "",
        },
    )

    db.commit()


def add_worker_to_order(
    db: Session,
    *,
    order_id: int,
    worker_discord_id: str,
    worker_display_name: str,
    admin_user: dict,
    reason: str | None = None,
) -> None:
    order = db.get(WebOrder, order_id)

    if order is None:
        raise ValueError("找不到這張訂單。")

    worker_discord_id = str(worker_discord_id).strip()
    worker_display_name = str(worker_display_name or worker_discord_id).strip()

    if not worker_discord_id:
        raise ValueError("請輸入打手 Discord ID。")

    existing_active = db.scalar(
        select(OrderAssignment)
        .where(OrderAssignment.order_id == order_id)
        .where(OrderAssignment.worker_discord_id == worker_discord_id)
        .where(OrderAssignment.is_active.is_(True))
        .limit(1)
    )

    if existing_active is not None:
        raise ValueError("這位打手已經在這張單裡。")

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
            "reason": "admin_added_worker",
            "worker_discord_id": worker_discord_id,
            "worker_display_name": worker_display_name,
            "admin_discord_id": str(admin_user["id"]),
            "admin_display_name": get_admin_display_name(admin_user),
        },
    )

    write_admin_audit_log(
        db,
        admin_user=admin_user,
        action="add_worker_to_order",
        target_type="web_order",
        target_id=str(order_id),
        after={
            "order_id": order_id,
            "worker_discord_id": worker_discord_id,
            "worker_display_name": worker_display_name,
            "reason": reason or "",
        },
    )

    db.commit()


def set_manual_worker_payout(
    db: Session,
    *,
    order_id: int,
    worker_discord_id: str,
    worker_display_name: str | None,
    manual_final_payout: int,
    reason: str | None,
    admin_user: dict,
) -> None:
    order = db.get(WebOrder, order_id)

    if order is None:
        raise ValueError("找不到這張訂單。")

    if manual_final_payout < 0:
        raise ValueError("手動分潤金額不能小於 0。")

    override = db.scalar(
        select(WorkerPayoutOverride)
        .where(WorkerPayoutOverride.order_id == order_id)
        .where(WorkerPayoutOverride.worker_discord_id == str(worker_discord_id))
        .limit(1)
    )

    before = None

    if override is None:
        override = WorkerPayoutOverride(
            order_id=order_id,
            worker_discord_id=str(worker_discord_id),
            worker_display_name=worker_display_name,
            manual_final_payout=int(manual_final_payout),
            reason=reason,
            created_by_discord_id=str(admin_user["id"]),
            created_by_display_name=get_admin_display_name(admin_user),
        )
        db.add(override)
    else:
        before = {
            "manual_final_payout": override.manual_final_payout,
            "reason": override.reason,
        }
        override.manual_final_payout = int(manual_final_payout)
        override.reason = reason
        override.worker_display_name = worker_display_name
        override.created_by_discord_id = str(admin_user["id"])
        override.created_by_display_name = get_admin_display_name(admin_user)

    db.flush()

    recalculate_order_payouts(db, order_id)

    create_sync_event(
        db,
        event_type=SyncEventType.ORDER_UPDATED,
        order_id=order_id,
        payload={
            "reason": "manual_worker_payout_updated",
            "worker_discord_id": str(worker_discord_id),
            "manual_final_payout": int(manual_final_payout),
        },
    )

    write_admin_audit_log(
        db,
        admin_user=admin_user,
        action="set_manual_worker_payout",
        target_type="worker_payout_override",
        target_id=f"{order_id}:{worker_discord_id}",
        before=before,
        after={
            "order_id": order_id,
            "worker_discord_id": str(worker_discord_id),
            "manual_final_payout": int(manual_final_payout),
            "reason": reason or "",
        },
    )

    db.commit()