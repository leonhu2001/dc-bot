from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from shared.db import SessionLocal
from shared.models import (
    AdminAuditLog,
    CustomerServicePayout,
    OrderAssignment,
    PayoutStatus,
    WebOrder,
    WorkerPayout,
)
from web.app.services.order_service import recalculate_order_payouts


RECALCULATE_UNPAID_PAYOUTS = "recalculate_unpaid_payouts"
VOID_CANCELLED_PAYOUTS = "void_cancelled_payouts"

ALLOWED_REPAIR_ACTIONS = {
    RECALCULATE_UNPAID_PAYOUTS,
    VOID_CANCELLED_PAYOUTS,
}


def _normalize(value: Any) -> str:
    return str(value or "").strip()


def _serialize_payout_state(db: Session, order_id: int) -> dict[str, Any]:
    worker_rows = list(
        db.scalars(
            select(WorkerPayout)
            .where(WorkerPayout.order_id == int(order_id))
            .order_by(WorkerPayout.id.asc())
        ).all()
    )
    cs_rows = list(
        db.scalars(
            select(CustomerServicePayout)
            .where(CustomerServicePayout.order_id == int(order_id))
            .order_by(CustomerServicePayout.id.asc())
        ).all()
    )

    return {
        "worker_payouts": [
            {
                "id": row.id,
                "worker_discord_id": row.worker_discord_id,
                "final_payout": int(row.final_payout or 0),
                "payout_status": _normalize(row.payout_status),
                "paid_at": (
                    row.paid_at.isoformat()
                    if row.paid_at is not None
                    else None
                ),
            }
            for row in worker_rows
        ],
        "customer_service_payouts": [
            {
                "id": row.id,
                "customer_service_discord_id": row.customer_service_discord_id,
                "payout_amount": int(row.payout_amount or 0),
                "payout_status": _normalize(row.payout_status),
                "paid_at": (
                    row.paid_at.isoformat()
                    if row.paid_at is not None
                    else None
                ),
            }
            for row in cs_rows
        ],
    }


def _all_rows_unpaid_and_clear(rows: list[Any]) -> bool:
    return all(
        _normalize(getattr(row, "payout_status", None)).lower()
        == PayoutStatus.UNPAID.value
        and getattr(row, "paid_at", None) is None
        for row in rows
    )


def _load_payout_rows(
    db: Session,
    order_id: int,
) -> tuple[list[WorkerPayout], list[CustomerServicePayout]]:
    worker_rows = list(
        db.scalars(
            select(WorkerPayout)
            .where(WorkerPayout.order_id == int(order_id))
            .order_by(WorkerPayout.id.asc())
        ).all()
    )
    cs_rows = list(
        db.scalars(
            select(CustomerServicePayout)
            .where(CustomerServicePayout.order_id == int(order_id))
            .order_by(CustomerServicePayout.id.asc())
        ).all()
    )
    return worker_rows, cs_rows


def _validate_recalculate_unpaid_payouts(
    db: Session,
    order: WebOrder,
) -> None:
    status = _normalize(order.status).lower()
    if status not in {"active", "stored", "closed"}:
        raise ValueError(
            "只有 active / stored / closed 訂單可以重算未發放分潤。"
        )

    assignments = list(
        db.scalars(
            select(OrderAssignment)
            .where(OrderAssignment.order_id == int(order.id))
            .where(OrderAssignment.is_active.is_(True))
        ).all()
    )
    if not assignments:
        raise ValueError(
            "這張訂單沒有有效接單人員，不能自動重算分潤。"
        )

    payout_base = int(
        getattr(order, "payout_base_amount", None)
        or getattr(order, "amount", 0)
        or 0
    )
    if payout_base <= 0:
        raise ValueError(
            "這張訂單的分潤計算基礎金額不是正數，需人工確認。"
        )

    cs_id = _normalize(
        getattr(order, "customer_service_discord_id", None)
    )
    if not cs_id or cs_id == "demo_customer_service":
        raise ValueError(
            "這張訂單缺少真實客服 Discord ID，不能自動重算。"
        )

    worker_rows, cs_rows = _load_payout_rows(db, int(order.id))
    if not _all_rows_unpaid_and_clear([*worker_rows, *cs_rows]):
        raise ValueError(
            "這張訂單已有 paid、void、未知狀態或 paid_at 資料，"
            "禁止自動重算分潤。"
        )


def _validate_void_cancelled_payouts(
    db: Session,
    order: WebOrder,
) -> tuple[list[WorkerPayout], list[CustomerServicePayout]]:
    status = _normalize(order.status).lower()
    if status not in {"cancelled", "canceled"}:
        raise ValueError(
            "只有已取消訂單可以把殘留分潤標記為 void。"
        )

    worker_rows, cs_rows = _load_payout_rows(db, int(order.id))
    live_workers = [
        row
        for row in worker_rows
        if _normalize(row.payout_status).lower() != PayoutStatus.VOID.value
    ]
    live_cs = [
        row
        for row in cs_rows
        if _normalize(row.payout_status).lower() != PayoutStatus.VOID.value
    ]
    live_rows = [*live_workers, *live_cs]

    if not live_rows:
        raise ValueError(
            "這張取消訂單已經沒有需要處理的有效分潤。"
        )

    if not _all_rows_unpaid_and_clear(live_rows):
        raise ValueError(
            "取消訂單內含已發放、非 unpaid 或已有 paid_at 的分潤，"
            "不能自動 void，需人工確認。"
        )

    return live_workers, live_cs


def _actor_values(actor: dict | None) -> tuple[str, str]:
    actor = actor or {}
    actor_id = _normalize(
        actor.get("id")
        or actor.get("discord_id")
    )
    actor_name = _normalize(
        actor.get("global_name")
        or actor.get("username")
        or actor.get("name")
        or actor_id
    )
    return actor_id or "unknown", actor_name or "unknown"


def _write_audit_log(
    db: Session,
    *,
    action: str,
    order_id: int,
    actor: dict | None,
    before: dict[str, Any],
    after: dict[str, Any],
) -> None:
    actor_id, actor_name = _actor_values(actor)

    db.add(
        AdminAuditLog(
            admin_discord_id=actor_id,
            action=action,
            target_type="order",
            target_id=str(int(order_id)),
            before_json=json.dumps(
                {
                    "operator": actor_name,
                    "payout_state": before,
                },
                ensure_ascii=False,
            ),
            after_json=json.dumps(
                {
                    "operator": actor_name,
                    "payout_state": after,
                },
                ensure_ascii=False,
            ),
            created_at=datetime.utcnow(),
        )
    )


def apply_accounting_repair_in_session(
    db: Session,
    *,
    order_id: int,
    action: str,
    actor: dict | None = None,
) -> dict[str, Any]:
    normalized_action = _normalize(action)
    if normalized_action not in ALLOWED_REPAIR_ACTIONS:
        raise ValueError("不支援的帳務修復動作。")

    order = db.get(WebOrder, int(order_id))
    if order is None:
        raise ValueError("找不到這張訂單。")

    before = _serialize_payout_state(db, int(order_id))

    if normalized_action == RECALCULATE_UNPAID_PAYOUTS:
        _validate_recalculate_unpaid_payouts(db, order)
        recalculate_order_payouts(db, int(order_id))
        db.flush()
        audit_action = "accounting_recalculate_unpaid_payouts"
        message = "已依目前接單人員、指定加成與 override 重算未發放分潤。"

    elif normalized_action == VOID_CANCELLED_PAYOUTS:
        live_workers, live_cs = _validate_void_cancelled_payouts(
            db,
            order,
        )

        for row in [*live_workers, *live_cs]:
            row.payout_status = PayoutStatus.VOID.value
            row.paid_at = None

        db.flush()
        audit_action = "accounting_void_cancelled_payouts"
        message = "已將取消訂單殘留的未發放分潤標記為 void."

    else:
        raise ValueError("不支援的帳務修復動作。")

    after = _serialize_payout_state(db, int(order_id))

    _write_audit_log(
        db,
        action=audit_action,
        order_id=int(order_id),
        actor=actor,
        before=before,
        after=after,
    )

    return {
        "order_id": int(order_id),
        "action": normalized_action,
        "message": message,
        "before": before,
        "after": after,
    }


def apply_accounting_repair(
    *,
    order_id: int,
    action: str,
    actor: dict | None = None,
) -> dict[str, Any]:
    db = SessionLocal()

    try:
        result = apply_accounting_repair_in_session(
            db,
            order_id=int(order_id),
            action=action,
            actor=actor,
        )
        db.commit()
        return result
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
