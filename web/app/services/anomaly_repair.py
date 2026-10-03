from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import select

from services.payment_reviews import (
    get_payment_review,
    retry_payment_review_apply,
)
from shared.db import SessionLocal
from shared.models import SyncEvent, SyncEventStatus
from web.app.services.accounting_repair import (
    ALLOWED_REPAIR_ACTIONS,
    apply_accounting_repair,
)
from web.app.services.audit_trail import (
    audit_snapshot,
    write_sqlite_audit_log,
)


RETRY_PAYMENT_APPLY = "retry_payment_review_apply"
RETRY_SYNC_EVENT = "retry_sync_event"

SAFE_ANOMALY_REPAIR_ACTIONS = {
    RETRY_PAYMENT_APPLY,
    RETRY_SYNC_EVENT,
    *ALLOWED_REPAIR_ACTIONS,
}


def _actor_id(actor: dict | None) -> str:
    return str((actor or {}).get("id") or "")


def _retry_sync_event(
    event_id: int,
    *,
    actor: dict | None,
) -> dict[str, Any]:
    with SessionLocal() as db:
        event = db.scalar(
            select(SyncEvent).where(SyncEvent.id == int(event_id))
        )
        if event is None:
            raise ValueError("找不到這筆同步事件。")

        if str(event.status or "") == SyncEventStatus.DONE.value:
            raise ValueError("這筆同步事件已完成，不需要重新排隊。")

        before = {
            "id": int(event.id),
            "event_type": str(event.event_type or ""),
            "status": str(event.status or ""),
            "order_id": event.order_id,
            "error_message": str(event.error_message or ""),
            "retry_count": int(event.retry_count or 0),
            "processed_at": (
                event.processed_at.isoformat()
                if event.processed_at is not None
                else None
            ),
        }

        event.status = SyncEventStatus.PENDING.value
        event.error_message = None
        event.processed_at = None
        db.commit()

        after = {
            **before,
            "status": SyncEventStatus.PENDING.value,
            "error_message": "",
            "processed_at": None,
        }

    write_sqlite_audit_log(
        admin_discord_id=_actor_id(actor),
        action="retry_sync_event",
        target_type="sync_event",
        target_id=str(int(event_id)),
        before=before,
        after=after,
    )

    return {
        "action": RETRY_SYNC_EVENT,
        "message": f"同步事件 SYNC-{int(event_id)} 已重新排入待處理佇列。",
        "target_id": int(event_id),
    }


def _retry_payment(
    review_id: int,
    *,
    actor: dict | None,
) -> dict[str, Any]:
    before = get_payment_review(int(review_id))
    if before is None:
        raise ValueError("找不到這筆付款審核。")

    after = retry_payment_review_apply(int(review_id))

    write_sqlite_audit_log(
        admin_discord_id=_actor_id(actor),
        action="retry_payment_review_apply",
        target_type="payment_review",
        target_id=str(int(review_id)),
        before=audit_snapshot(before),
        after=audit_snapshot(after),
        metadata={"source": "anomaly_repair_center"},
    )

    return {
        "action": RETRY_PAYMENT_APPLY,
        "message": (
            f"{after.get('review_no') or f'PAY-{int(review_id)}'} "
            "已重新排入付款套用流程。"
        ),
        "target_id": int(review_id),
    }


def apply_anomaly_repair(
    *,
    action: str,
    target_id: int | None = None,
    order_id: int | None = None,
    actor: dict | None = None,
) -> dict[str, Any]:
    action = str(action or "").strip()
    if action not in SAFE_ANOMALY_REPAIR_ACTIONS:
        raise ValueError("這個異常沒有開放自動修復。")

    if action == RETRY_PAYMENT_APPLY:
        if target_id is None:
            raise ValueError("缺少付款審核 ID。")
        return _retry_payment(int(target_id), actor=actor)

    if action == RETRY_SYNC_EVENT:
        if target_id is None:
            raise ValueError("缺少同步事件 ID。")
        return _retry_sync_event(int(target_id), actor=actor)

    if action in ALLOWED_REPAIR_ACTIONS:
        if order_id is None:
            raise ValueError("缺少訂單 ID，不能執行帳務修復。")
        return apply_accounting_repair(
            order_id=int(order_id),
            action=action,
            actor=actor,
        )

    raise ValueError("不支援的修復動作。")
