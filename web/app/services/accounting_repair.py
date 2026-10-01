from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from shared.db import SessionLocal
from shared.models import (
    AdminAuditLog,
    CustomerServicePayout,
    OrderAssignment,
    PayoutStatus,
    SyncEvent,
    SyncEventStatus,
    SyncEventType,
    WebOrder,
    WorkerPayout,
)
from web.app.services.order_service import recalculate_order_payouts


RECALCULATE_UNPAID_PAYOUTS = "recalculate_unpaid_payouts"
VOID_CANCELLED_PAYOUTS = "void_cancelled_payouts"
QUEUE_WALLET_ORDER_RECONCILIATION = "queue_wallet_order_reconciliation"

ALLOWED_REPAIR_ACTIONS = {
    RECALCULATE_UNPAID_PAYOUTS,
    VOID_CANCELLED_PAYOUTS,
    QUEUE_WALLET_ORDER_RECONCILIATION,
}


def _normalize(value: Any) -> str:
    return str(value or "").strip()


def _bot_db_path() -> Path:
    return Path(__file__).resolve().parents[3] / "bot.db"


def _actor_payload(actor: dict | None) -> dict[str, str]:
    actor_id, actor_name = _actor_values(actor)
    return {
        "admin_discord_id": actor_id,
        "admin_display_name": actor_name,
    }


def _load_wallet_order_state(
    order: WebOrder,
) -> dict[str, int]:
    customer_id = _normalize(order.customer_discord_id)
    ticket_channel_id = _normalize(order.ticket_channel_id)

    if not customer_id:
        raise ValueError("這張訂單缺少顧客 Discord ID，不能自動對帳。")

    if not ticket_channel_id:
        raise ValueError("這張訂單缺少 ticket_channel_id，不能自動對帳。")

    path = _bot_db_path()
    if not path.exists():
        raise ValueError("找不到 bot.db，無法讀取錢包流水。")

    with sqlite3.connect(path, timeout=15) as conn:
        conn.row_factory = sqlite3.Row

        table_row = conn.execute(
            """
            SELECT 1
            FROM sqlite_master
            WHERE type='table' AND name='wallet_transactions'
            """
        ).fetchone()
        if table_row is None:
            raise ValueError("wallet_transactions 不存在，無法執行錢包對帳。")

        row = conn.execute(
            """
            SELECT
                COALESCE(SUM(
                    CASE
                        WHEN type IN ('payment', 'payment_adjustment')
                        THEN amount
                        ELSE 0
                    END
                ), 0) AS wallet_net,
                COALESCE(SUM(
                    CASE WHEN type = 'payment' THEN 1 ELSE 0 END
                ), 0) AS payment_count
            FROM wallet_transactions
            WHERE customer_discord_id = ?
              AND order_channel_id = ?
            """,
            (
                customer_id,
                ticket_channel_id,
            ),
        ).fetchone()

        wallet_row = conn.execute(
            """
            SELECT balance
            FROM customer_wallets
            WHERE customer_discord_id = ?
            LIMIT 1
            """,
            (customer_id,),
        ).fetchone()

    return {
        "wallet_net": int(row["wallet_net"] or 0) if row else 0,
        "payment_count": int(row["payment_count"] or 0) if row else 0,
        "wallet_balance": int(wallet_row["balance"] or 0) if wallet_row else 0,
    }


def _find_pending_wallet_reconciliation(
    db: Session,
    order_id: int,
) -> SyncEvent | None:
    events = list(
        db.scalars(
            select(SyncEvent)
            .where(SyncEvent.order_id == int(order_id))
            .where(
                SyncEvent.status.in_(
                    [
                        SyncEventStatus.PENDING.value,
                        SyncEventStatus.PROCESSING.value,
                    ]
                )
            )
            .order_by(SyncEvent.id.desc())
        ).all()
    )

    for event in events:
        try:
            payload = json.loads(event.payload_json or "{}")
        except Exception:
            payload = {}

        if str(payload.get("sync_kind") or "") == "wallet_reconciliation":
            return event

    return None


def _queue_wallet_order_reconciliation(
    db: Session,
    *,
    order: WebOrder,
    actor: dict | None,
) -> dict[str, Any]:
    if _normalize(order.payment_method) != "我的錢包":
        raise ValueError("只有付款方式為「我的錢包」的訂單可以執行這個修復。")

    expected_pay_amount = int(
        order.customer_pay_amount
        if order.customer_pay_amount is not None
        else order.amount
        or 0
    )
    expected_net = -max(0, expected_pay_amount)

    state = _load_wallet_order_state(order)
    actual_net = int(state["wallet_net"])
    payment_count = int(state["payment_count"])
    wallet_balance = int(state["wallet_balance"])

    if payment_count <= 0:
        raise ValueError(
            "找不到原始 payment 流水；這不是單純金額差額，需人工確認。"
        )

    if actual_net == expected_net:
        raise ValueError("這張訂單的錢包淨扣款目前已經一致，不需要修復。")

    if actual_net > 0:
        raise ValueError(
            "目前錢包淨額為正數，無法安全推導歷史付款基準，需人工確認。"
        )

    pending = _find_pending_wallet_reconciliation(
        db,
        int(order.id),
    )
    if pending is not None:
        raise ValueError(
            f"這張訂單已有待處理的錢包對帳事件 #{pending.id}，請等待 Bot 處理。"
        )

    delta = int(expected_net - actual_net)
    if delta < 0 and wallet_balance < abs(delta):
        raise ValueError(
            f"顧客目前錢包餘額 {wallet_balance}T，不足以補扣 {abs(delta)}T。"
        )

    old_effective_pay_amount = abs(actual_net)
    actor_payload = _actor_payload(actor)

    event = SyncEvent(
        event_type=SyncEventType.ORDER_UPDATED.value,
        status=SyncEventStatus.PENDING.value,
        order_id=int(order.id),
        payload_json=json.dumps(
            {
                "order_id": int(order.id),
                "source": "accounting_reconciliation",
                "sync_kind": "wallet_reconciliation",
                "old_amount": old_effective_pay_amount,
                "new_amount": expected_pay_amount,
                "old_customer_pay_amount": old_effective_pay_amount,
                "new_customer_pay_amount": expected_pay_amount,
                "old_payment_method": "我的錢包",
                "new_payment_method": "我的錢包",
                "old_customer_discord_id": _normalize(order.customer_discord_id),
                "new_customer_discord_id": _normalize(order.customer_discord_id),
                **actor_payload,
            },
            ensure_ascii=False,
        ),
    )
    db.add(event)
    db.flush()

    actor_id, actor_name = _actor_values(actor)
    db.add(
        AdminAuditLog(
            admin_discord_id=actor_id,
            action="accounting_queue_wallet_reconciliation",
            target_type="order",
            target_id=str(int(order.id)),
            before_json=json.dumps(
                {
                    "operator": actor_name,
                    "wallet_net": actual_net,
                    "expected_wallet_net": expected_net,
                    "wallet_balance": wallet_balance,
                },
                ensure_ascii=False,
            ),
            after_json=json.dumps(
                {
                    "operator": actor_name,
                    "queued_event_id": int(event.id),
                    "delta": delta,
                    "target_wallet_net": expected_net,
                },
                ensure_ascii=False,
            ),
            created_at=datetime.utcnow(),
        )
    )

    if delta < 0:
        action_text = f"補扣 {abs(delta)}T"
    else:
        action_text = f"退款 {delta}T"

    return {
        "order_id": int(order.id),
        "action": QUEUE_WALLET_ORDER_RECONCILIATION,
        "message": (
            f"已排入{action_text}事件 #{event.id}。"
            "Bot 會先再次驗證修改前淨扣款，再以冪等流水執行。"
        ),
        "event_id": int(event.id),
        "delta": delta,
        "before": {
            "wallet_net": actual_net,
            "expected_wallet_net": expected_net,
            "wallet_balance": wallet_balance,
        },
        "after": {
            "queued_event_id": int(event.id),
            "target_wallet_net": expected_net,
        },
    }


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

    if normalized_action == QUEUE_WALLET_ORDER_RECONCILIATION:
        return _queue_wallet_order_reconciliation(
            db,
            order=order,
            actor=actor,
        )

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
