from __future__ import annotations

from datetime import timedelta
from typing import Any

from sqlalchemy import text


REQUEST_TTL_SECONDS = 180


def _timer_module():
    from services import vip_timer as timer

    return timer


def ensure_pause_request_table(db=None) -> None:
    timer = _timer_module()
    owns = db is None
    if owns:
        db = timer.SessionLocal()
    try:
        db.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS vip_timer_pause_requests (
                    order_id INTEGER PRIMARY KEY,
                    requester_discord_id TEXT NOT NULL,
                    requester_side TEXT NOT NULL,
                    requested_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
        )
        if owns:
            db.commit()
    finally:
        if owns:
            db.close()


def _actor_side(session: dict, actor_id: Any, staff_ids: list[str] | None = None) -> str:
    actor = str(actor_id or "").strip()
    if not actor:
        return "support"
    if actor == str(session.get("customer_discord_id") or "").strip():
        return "customer"
    staff = {str(value).strip() for value in (staff_ids or []) if str(value).strip()}
    if actor in staff:
        return "staff"
    return "support"


def _read_request(db, order_id: int) -> dict | None:
    timer = _timer_module()
    row = db.execute(
        text(
            """
            SELECT order_id, requester_discord_id, requester_side, requested_at, updated_at
            FROM vip_timer_pause_requests
            WHERE order_id = :order_id
            LIMIT 1
            """
        ),
        {"order_id": int(order_id)},
    ).mappings().first()
    if row is None:
        return None

    result = dict(row)
    requested_at = timer.parse_dt(result.get("requested_at"))
    if requested_at is not None and timer.utc_now() - requested_at >= timedelta(seconds=REQUEST_TTL_SECONDS):
        db.execute(
            text("DELETE FROM vip_timer_pause_requests WHERE order_id=:order_id"),
            {"order_id": int(order_id)},
        )
        timer._event(
            db,
            int(order_id),
            "pause_request_expired",
            result.get("requester_discord_id"),
            {"requester_side": result.get("requester_side")},
        )
        return None
    return result


def get_pause_request(order_id: int) -> dict | None:
    timer = _timer_module()
    db = timer.SessionLocal()
    try:
        ensure_pause_request_table(db)
        result = _read_request(db, int(order_id))
        db.commit()
        return result
    finally:
        db.close()


def clear_pause_request(order_id: int, *, actor_id: Any = None, reason: str = "cleared") -> None:
    timer = _timer_module()
    db = timer.SessionLocal()
    try:
        ensure_pause_request_table(db)
        existing = _read_request(db, int(order_id))
        if existing is None:
            db.commit()
            return
        db.execute(
            text("DELETE FROM vip_timer_pause_requests WHERE order_id=:order_id"),
            {"order_id": int(order_id)},
        )
        timer._event(
            db,
            int(order_id),
            "pause_request_cleared",
            actor_id,
            {
                "reason": str(reason or "cleared"),
                "requester_side": existing.get("requester_side"),
            },
        )
        db.commit()
    finally:
        db.close()


def request_or_confirm_pause(
    order_id: int,
    actor_id: Any,
    staff_ids: list[str] | None = None,
) -> dict:
    """Request a pause, or confirm the opposite side's pending request.

    Customer and accepted staff form the two confirmation sides. When multiple
    staff are assigned, any one accepted staff member can represent the staff
    side. Support/admin operators keep an emergency override and pause directly.
    The timer keeps running until the second side confirms.
    """

    timer = _timer_module()
    session = timer.get_session(int(order_id))
    if not session or str(session.get("status") or "") != "running":
        clear_pause_request(int(order_id), actor_id=actor_id, reason="not_running")
        raise ValueError("目前不是計時中狀態。")

    side = _actor_side(session, actor_id, staff_ids)
    if side == "support":
        clear_pause_request(int(order_id), actor_id=actor_id, reason="support_override")
        paused = timer.pause_timer(int(order_id), actor_id)
        return {
            "state": "paused",
            "confirmed": True,
            "forced": True,
            "session": paused,
        }

    db = timer.SessionLocal()
    try:
        ensure_pause_request_table(db)
        existing = _read_request(db, int(order_id))
        now_text = timer.utc_iso()

        if existing is None:
            db.execute(
                text(
                    """
                    INSERT INTO vip_timer_pause_requests(
                        order_id, requester_discord_id, requester_side, requested_at, updated_at
                    ) VALUES (
                        :order_id, :requester, :side, :requested_at, :updated_at
                    )
                    ON CONFLICT(order_id) DO UPDATE SET
                        requester_discord_id=excluded.requester_discord_id,
                        requester_side=excluded.requester_side,
                        requested_at=excluded.requested_at,
                        updated_at=excluded.updated_at
                    """
                ),
                {
                    "order_id": int(order_id),
                    "requester": str(actor_id or ""),
                    "side": side,
                    "requested_at": now_text,
                    "updated_at": now_text,
                },
            )
            timer._event(
                db,
                int(order_id),
                "pause_requested",
                actor_id,
                {"requester_side": side},
            )
            db.commit()
            return {
                "state": "pending",
                "confirmed": False,
                "requester_side": side,
                "requester_discord_id": str(actor_id or ""),
                "waiting_for": "staff" if side == "customer" else "customer",
            }

        requester_side = str(existing.get("requester_side") or "")
        if requester_side == side:
            db.commit()
            return {
                "state": "pending",
                "confirmed": False,
                "requester_side": requester_side,
                "requester_discord_id": str(existing.get("requester_discord_id") or ""),
                "waiting_for": "staff" if requester_side == "customer" else "customer",
                "already_requested": True,
            }

        db.execute(
            text("DELETE FROM vip_timer_pause_requests WHERE order_id=:order_id"),
            {"order_id": int(order_id)},
        )
        timer._event(
            db,
            int(order_id),
            "pause_confirmed",
            actor_id,
            {
                "requester_discord_id": str(existing.get("requester_discord_id") or ""),
                "requester_side": requester_side,
                "confirmer_side": side,
            },
        )
        db.commit()
    finally:
        db.close()

    paused = timer.pause_timer(int(order_id), actor_id)
    return {
        "state": "paused",
        "confirmed": True,
        "forced": False,
        "requester_side": requester_side,
        "session": paused,
    }


__all__ = [
    "REQUEST_TTL_SECONDS",
    "clear_pause_request",
    "ensure_pause_request_table",
    "get_pause_request",
    "request_or_confirm_pause",
]
