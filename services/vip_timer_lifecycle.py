from __future__ import annotations

from typing import Callable

from sqlalchemy import text

from shared.db import SessionLocal


_INSTALLED = False
_ORIGINAL_RECONCILE = None


def _order_status(order_id: int, db=None) -> str:
    owns = db is None
    if owns:
        db = SessionLocal()
    try:
        row = db.execute(
            text(
                """
                SELECT status
                FROM web_orders
                WHERE id = :order_id
                LIMIT 1
                """
            ),
            {"order_id": int(order_id)},
        ).first()
        return str(row[0] if row else "").strip().lower()
    except Exception:
        return ""
    finally:
        if owns:
            db.close()


def _terminal_timer_status(order_status: str) -> str | None:
    status = str(order_status or "").strip().lower()
    if status in {"cancelled", "canceled"}:
        return "cancelled"
    if status in {"active", "closed"}:
        return "paid"
    return None


def _sync_terminal_session(order_id: int, order_status: str, db=None) -> str | None:
    from services.vip_timer import ensure_vip_timer_tables, utc_iso

    next_status = _terminal_timer_status(order_status)
    if next_status is None:
        return None

    owns = db is None
    if owns:
        db = SessionLocal()
    try:
        ensure_vip_timer_tables(db)
        db.execute(
            text(
                """
                UPDATE vip_timer_sessions
                SET status = :status,
                    updated_at = :updated_at
                WHERE order_id = :order_id
                  AND status IN (
                      'waiting_staff',
                      'ready',
                      'running',
                      'paused',
                      'pending_payment'
                  )
                """
            ),
            {
                "status": next_status,
                "updated_at": utc_iso(),
                "order_id": int(order_id),
            },
        )
        if owns:
            db.commit()
    finally:
        if owns:
            db.close()

    return next_status


def _assert_order_open(order_id: int) -> None:
    order_status = _order_status(int(order_id))
    next_status = _sync_terminal_session(int(order_id), order_status)
    if next_status == "cancelled":
        raise ValueError("這張 VIP 自由計時單已取消，不能再操作計時。")
    if next_status == "paid":
        raise ValueError("這張 VIP 自由計時單已完成付款，不能再操作計時。")


def _guard(operation: Callable):
    def wrapped(order_id: int, *args, **kwargs):
        _assert_order_open(int(order_id))
        return operation(order_id, *args, **kwargs)

    wrapped.__name__ = getattr(operation, "__name__", "vip_timer_guarded_operation")
    wrapped.__doc__ = getattr(operation, "__doc__", None)
    return wrapped


def install_vip_timer_lifecycle_guard() -> None:
    """Keep timer-session lifecycle aligned with the authoritative web order.

    A cancelled timer must not keep blocking the customer's next timer order, and
    a cancelled/paid order must never keep accepting start/pause/switch/end
    actions from an old persistent Discord component after a restart.
    """
    global _INSTALLED, _ORIGINAL_RECONCILE
    if _INSTALLED:
        return

    from services import vip_timer as timer

    _ORIGINAL_RECONCILE = timer.reconcile_customer_sessions

    def reconcile_customer_sessions(db, customer_id: str) -> None:
        _ORIGINAL_RECONCILE(db, customer_id)
        try:
            rows = db.execute(
                text(
                    """
                    SELECT
                        s.order_id,
                        o.status AS order_status
                    FROM vip_timer_sessions s
                    JOIN web_orders o
                      ON o.id = s.order_id
                    WHERE s.customer_discord_id = :customer_id
                      AND s.status IN (
                          'waiting_staff',
                          'ready',
                          'running',
                          'paused',
                          'pending_payment'
                      )
                    """
                ),
                {"customer_id": str(customer_id)},
            ).mappings().all()
        except Exception:
            return

        for row in rows:
            _sync_terminal_session(
                int(row["order_id"]),
                str(row.get("order_status") or ""),
                db=db,
            )

    timer.reconcile_customer_sessions = reconcile_customer_sessions
    timer.start_timer = _guard(timer.start_timer)
    timer.pause_timer = _guard(timer.pause_timer)
    timer.resume_timer = _guard(timer.resume_timer)
    timer.switch_rule = _guard(timer.switch_rule)
    timer.end_timer = _guard(timer.end_timer)

    _INSTALLED = True


__all__ = ["install_vip_timer_lifecycle_guard"]
