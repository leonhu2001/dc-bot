import json
from datetime import datetime

from sqlalchemy import delete, select, text
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
from shared.order_acceptance import (
    ACCEPTED_PENDING_PAY,
    WAITING_ACCEPTANCE,
    claim_acceptance_order,
    has_acceptance_meta,
    unclaim_acceptance_order,
)


def get_display_name(user: dict) -> str:
    return str(
        user.get("global_name")
        or user.get("username")
        or user.get("id")
        or "未知使用者"
    )


VISIBLE_DISPATCH_STATUSES = [
    OrderStatus.ACTIVE.value,
    WAITING_ACCEPTANCE,
    ACCEPTED_PENDING_PAY,
]

PREPAY_DISPATCH_STATUSES = {
    WAITING_ACCEPTANCE,
    ACCEPTED_PENDING_PAY,
}


PENDING_PAYMENT_METHODS = {
    "",
    "待付款",
    "未紀錄",
    "未记录",
    "pending",
    "unpaid",
}


def _normalize_text(value) -> str:
    return str(value or "").strip()


def _is_pending_payment_method(value) -> bool:
    return _normalize_text(value).lower() in PENDING_PAYMENT_METHODS


def get_acceptance_meta_status_for_order(db: Session, order_id: int) -> str | None:
    row = db.execute(
        text("""
            SELECT status
            FROM order_acceptance_meta
            WHERE order_id = :order_id
            LIMIT 1
        """),
        {"order_id": int(order_id)},
    ).mappings().first()

    if row is None:
        return None

    return _normalize_text(row.get("status")) or None


def ensure_not_unpaid_prepay_order_for_legacy_assignment(
    db: Session,
    order: WebOrder,
    *,
    action_label: str,
) -> None:
    """防止付款前接單流程誤走舊 active assignment / payout 流程。"""
    meta_status = get_acceptance_meta_status_for_order(db, int(order.id))

    if meta_status is None:
        return

    order_status = _normalize_text(order.status)
    payment_method = _normalize_text(getattr(order, "payment_method", None))

    if (
        order_status in PREPAY_DISPATCH_STATUSES
        or meta_status in PREPAY_DISPATCH_STATUSES
        or _is_pending_payment_method(payment_method)
    ):
        raise ValueError(
            f"這張訂單是付款前接單流程，尚未付款成立，不能用舊流程{action_label}。"
            "請先補付款 panel，等顧客付款送出後再操作。"
        )


def _user_role_ids(user: dict) -> list[str]:
    role_ids: list[str] = []

    for key in ("role_ids", "roles", "discord_role_ids"):
        value = user.get(key)
        if isinstance(value, list):
            role_ids.extend(str(item) for item in value if str(item).strip())
        elif isinstance(value, str):
            text_value = value.strip()
            if not text_value:
                continue
            try:
                parsed = json.loads(text_value)
            except Exception:
                parsed = None
            if isinstance(parsed, list):
                role_ids.extend(str(item) for item in parsed if str(item).strip())
            else:
                role_ids.extend(part.strip() for part in text_value.split(",") if part.strip())

    roles_json = user.get("roles_json")
    if isinstance(roles_json, str) and roles_json.strip():
        try:
            parsed = json.loads(roles_json)
        except Exception:
            parsed = None
        if isinstance(parsed, list):
            role_ids.extend(str(item) for item in parsed if str(item).strip())

    return list(dict.fromkeys(role_ids))


def _prepay_claimed_order_ids(db: Session, worker_discord_id: str) -> set[int]:
    rows = db.execute(
        text("""
            SELECT c.order_id
            FROM order_acceptance_claims c
            JOIN web_orders o ON o.id = c.order_id
            WHERE c.staff_discord_id = :worker_discord_id
              AND c.is_active = 1
              AND o.status IN ('waiting_acceptance', 'accepted_pending_pay')
        """),
        {"worker_discord_id": str(worker_discord_id)},
    ).fetchall()

    return {int(row[0]) for row in rows}

PROTECTOR_ROLE_IDS_FOR_PREPAY_DISPLAY = {
    "1500234130871550004",
    "1500234170943934544",
    "1500751039060643990",
}


def _load_json_list_for_prepay_claims(value) -> list[str]:
    if value is None:
        return []

    try:
        parsed = json.loads(str(value))
    except Exception:
        return []

    if not isinstance(parsed, list):
        return []

    return [str(item) for item in parsed if str(item).strip()]


def attach_acceptance_claims_to_orders(db: Session, orders: list[WebOrder]) -> None:
    for order in orders:
        setattr(order, "prepay_claims", [])
        setattr(order, "prepay_claim_count", 0)
        setattr(order, "prepay_required_count", 0)
        setattr(order, "prepay_protector_count", 0)
        setattr(order, "prepay_min_protector_count", 0)

        meta = db.execute(
            text("""
                SELECT
                    required_staff_count,
                    min_protector_count
                FROM order_acceptance_meta
                WHERE order_id = :order_id
                LIMIT 1
            """),
            {"order_id": int(order.id)},
        ).mappings().first()

        if meta is None:
            continue

        rows = db.execute(
            text("""
                SELECT
                    staff_discord_id,
                    staff_display_name,
                    staff_role_ids_json
                FROM order_acceptance_claims
                WHERE order_id = :order_id
                  AND is_active = 1
                ORDER BY claimed_at ASC, id ASC
            """),
            {"order_id": int(order.id)},
        ).mappings().all()

        claims = []
        protector_count = 0

        for row in rows:
            role_ids = set(_load_json_list_for_prepay_claims(row["staff_role_ids_json"]))

            if role_ids & PROTECTOR_ROLE_IDS_FOR_PREPAY_DISPLAY:
                protector_count += 1

            claims.append({
                "worker_discord_id": str(row["staff_discord_id"]),
                "worker_display_name": row["staff_display_name"] or str(row["staff_discord_id"]),
                "has_named_bonus": False,
            })

        setattr(order, "prepay_claims", claims)
        setattr(order, "prepay_claim_count", len(claims))
        setattr(order, "prepay_required_count", int(meta["required_staff_count"] or 0))
        setattr(order, "prepay_protector_count", protector_count)
        setattr(order, "prepay_min_protector_count", int(meta["min_protector_count"] or 0))

def create_demo_orders_if_empty(db: Session) -> None:
    # 正式環境不再自動建立 DEMO 測試訂單。
    return


def list_active_orders(db: Session) -> list[WebOrder]:
    statement = (
        select(WebOrder)
        .where(WebOrder.status.in_(VISIBLE_DISPATCH_STATUSES))
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
    return len(get_worker_active_order_ids(db, worker_discord_id))


def get_worker_active_order_ids(db: Session, worker_discord_id: str) -> set[int]:
    active_ids = {
        assignment.order_id
        for assignment in get_worker_active_assignments(db, worker_discord_id)
    }

    active_ids.update(_prepay_claimed_order_ids(db, str(worker_discord_id)))

    return active_ids

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

    ensure_not_unpaid_prepay_order_for_legacy_assignment(
        db,
        order,
        action_label="計算分潤",
    )

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
        total_amount=int(
            getattr(order, "payout_base_amount", None)
            or order.amount
            or 0
        ),
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

    if str(order.status) in PREPAY_DISPATCH_STATUSES:
        staff_role_ids = _user_role_ids(user)

        if not staff_role_ids:
            raise ValueError("網站登入資料缺少 Discord 身分組，請重新登入後再接單。")

        state = claim_acceptance_order(
            order_id=order_id,
            staff_discord_id=worker_discord_id,
            staff_display_name=worker_display_name,
            staff_role_ids=staff_role_ids,
            source="web",
        )

        create_sync_event(
            db,
            event_type=SyncEventType.ORDER_CLAIMED,
            order_id=order_id,
            payload={
                "order_id": order_id,
                "worker_discord_id": worker_discord_id,
                "worker_display_name": worker_display_name,
                "source": "web",
                "prepay_acceptance": True,
                "accepted_count": state.accepted_count,
                "required_staff_count": state.required_staff_count,
                "status": state.status,
            },
        )

        db.commit()
        db.expire_all()

        refreshed_order = db.scalar(
            select(WebOrder)
            .where(WebOrder.id == order_id)
            .options(selectinload(WebOrder.assignments))
            .options(selectinload(WebOrder.payouts))
        )

        if refreshed_order is None:
            raise ValueError("接單成功，但重新讀取訂單失敗。")

        return refreshed_order

    if get_acceptance_meta_status_for_order(db, order_id) is not None:
        raise ValueError("這張訂單已離開付款前接單階段，網站不能再新增接單。")

    raise ValueError("這張訂單不是付款前接單狀態，不能在網站接單。")

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

    if str(order.status) in PREPAY_DISPATCH_STATUSES:
        state = unclaim_acceptance_order(
            order_id=order_id,
            staff_discord_id=worker_discord_id,
            source="web",
        )

        create_sync_event(
            db,
            event_type=SyncEventType.ORDER_UNCLAIMED,
            order_id=order_id,
            payload={
                "order_id": order_id,
                "worker_discord_id": worker_discord_id,
                "worker_display_name": worker_display_name,
                "source": "web",
                "prepay_acceptance": True,
                "accepted_count": state.accepted_count,
                "required_staff_count": state.required_staff_count,
                "status": state.status,
            },
        )

        db.commit()
        db.expire_all()

        refreshed_order = db.scalar(
            select(WebOrder)
            .where(WebOrder.id == order_id)
            .options(selectinload(WebOrder.assignments))
            .options(selectinload(WebOrder.payouts))
        )

        if refreshed_order is None:
            raise ValueError("取消接單成功，但重新讀取訂單失敗。")

        return refreshed_order

    if get_acceptance_meta_status_for_order(db, order_id) is not None:
        raise ValueError("這張訂單已離開付款前接單階段，網站不能取消接單。")

    raise ValueError("這張訂單不是付款前接單狀態，不能在網站取消接單。")
