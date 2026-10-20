from __future__ import annotations

from typing import Any

from sqlalchemy import text

from services import vip_timer


def _ensure_table(db) -> None:
    db.execute(text("""
        CREATE TABLE IF NOT EXISTS vip_timer_pause_requests (
            order_id INTEGER PRIMARY KEY,
            requester_discord_id TEXT NOT NULL,
            requester_side TEXT NOT NULL,
            requested_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
    """))


def _actor_side(session: dict, actor_id: Any, staff_ids: list[str] | None) -> str | None:
    actor = str(actor_id or "").strip()
    if not actor:
        return None
    if actor == str(session.get("customer_discord_id") or "").strip():
        return "customer"
    if actor in {str(value or "").strip() for value in (staff_ids or []) if str(value or "").strip()}:
        return "staff"
    return None


def get_pause_request(order_id: int) -> dict | None:
    db = vip_timer.SessionLocal()
    try:
        vip_timer.ensure_vip_timer_tables(db)
        _ensure_table(db)
        session = vip_timer.get_session(int(order_id), db)
        if not session or str(session.get("status") or "") != "running":
            return None
        row = db.execute(
            text("SELECT * FROM vip_timer_pause_requests WHERE order_id=:order_id LIMIT 1"),
            {"order_id": int(order_id)},
        ).mappings().first()
        return dict(row) if row else None
    finally:
        db.close()


def clear_pause_request(order_id: int) -> None:
    db = vip_timer.SessionLocal()
    try:
        _ensure_table(db)
        db.execute(
            text("DELETE FROM vip_timer_pause_requests WHERE order_id=:order_id"),
            {"order_id": int(order_id)},
        )
        db.commit()
    finally:
        db.close()


def request_or_confirm_pause(
    order_id: int,
    actor_id: Any,
    staff_ids: list[str] | None,
) -> dict[str, Any]:
    """Require customer/staff cross-confirmation before pausing a running timer.

    The staff side is collective: when multiple accepted staff exist, any one of
    them may request or confirm for the staff side. A second click from the same
    side does not confirm the pause; it simply reports that the opposite side is
    still required.
    """
    db = vip_timer.SessionLocal()
    try:
        vip_timer.ensure_vip_timer_tables(db)
        _ensure_table(db)
        session = vip_timer.get_session(int(order_id), db)
        if not session or str(session.get("status") or "") != "running":
            db.execute(
                text("DELETE FROM vip_timer_pause_requests WHERE order_id=:order_id"),
                {"order_id": int(order_id)},
            )
            db.commit()
            raise ValueError("目前不是計時中狀態。")

        actor = str(actor_id or "").strip()
        side = _actor_side(session, actor, staff_ids)
        if side is None:
            raise ValueError("暫停必須由老闆或本單已接單的打手操作。")

        row = db.execute(
            text("SELECT * FROM vip_timer_pause_requests WHERE order_id=:order_id LIMIT 1"),
            {"order_id": int(order_id)},
        ).mappings().first()

        if row is None:
            now = vip_timer.utc_iso()
            db.execute(text("""
                INSERT INTO vip_timer_pause_requests(
                    order_id, requester_discord_id, requester_side, requested_at, updated_at
                ) VALUES (:order_id, :actor, :side, :now, :now)
            """), {
                "order_id": int(order_id),
                "actor": actor,
                "side": side,
                "now": now,
            })
            vip_timer._event(db, int(order_id), "pause_requested", actor, {"side": side})
            db.commit()
            return {
                "state": "requested",
                "requester_side": side,
                "requester_discord_id": actor,
            }

        request = dict(row)
        requester_side = str(request.get("requester_side") or "")
        if requester_side == side:
            return {
                "state": "waiting",
                "requester_side": requester_side,
                "requester_discord_id": str(request.get("requester_discord_id") or ""),
            }

        db.execute(
            text("DELETE FROM vip_timer_pause_requests WHERE order_id=:order_id"),
            {"order_id": int(order_id)},
        )
        vip_timer._event(
            db,
            int(order_id),
            "pause_confirmed",
            actor,
            {
                "confirming_side": side,
                "requester_side": requester_side,
                "requester_discord_id": str(request.get("requester_discord_id") or ""),
            },
        )
        db.commit()
    finally:
        db.close()

    vip_timer.pause_timer(int(order_id), actor_id)
    return {
        "state": "paused",
        "requester_side": requester_side,
        "confirmed_by_side": side,
    }


__all__ = [
    "clear_pause_request",
    "get_pause_request",
    "request_or_confirm_pause",
]
