from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import inspect, text

from shared.db import engine


def _now_text() -> str:
    return datetime.now(timezone.utc).isoformat()


def ensure_order_credential_tables() -> None:
    """Create metadata-only tables for temporary credential delivery.

    Security rule: account names, passwords, recovery codes, login notes, and any
    other credential contents must never be written to these tables.
    """
    with engine.begin() as conn:
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS order_credential_deliveries (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                order_id INTEGER NOT NULL,
                submitted_by_discord_id TEXT,
                recipient_discord_id TEXT NOT NULL,
                recipient_type TEXT NOT NULL,
                recipient_display_name TEXT,
                dm_channel_id TEXT,
                dm_message_id TEXT,
                delivered_at TEXT NOT NULL,
                revoked_at TEXT,
                revoke_status TEXT,
                revoke_reason TEXT
            )
        """))
        conn.execute(text("""
            CREATE INDEX IF NOT EXISTS idx_order_credential_delivery_active
            ON order_credential_deliveries(order_id, revoked_at)
        """))
        conn.execute(text("""
            CREATE INDEX IF NOT EXISTS idx_order_credential_delivery_recipient
            ON order_credential_deliveries(recipient_discord_id)
        """))


    columns = {
        str(column.get("name"))
        for column in inspect(engine).get_columns(
            "order_credential_deliveries"
        )
    }

    if "submitted_by_discord_id" not in columns:
        with engine.begin() as conn:
            conn.execute(
                text(
                    """
                    ALTER TABLE order_credential_deliveries
                    ADD COLUMN submitted_by_discord_id TEXT
                    """
                )
            )


def get_order_id_by_ticket_channel(ticket_channel_id: int | str | None) -> int | None:
    if ticket_channel_id is None:
        return None

    ticket_channel_id_text = str(ticket_channel_id).strip()
    if not ticket_channel_id_text:
        return None

    with engine.begin() as conn:
        row = conn.execute(text("""
            SELECT id
            FROM web_orders
            WHERE ticket_channel_id = :ticket_channel_id
            ORDER BY id DESC
            LIMIT 1
        """), {"ticket_channel_id": ticket_channel_id_text}).mappings().first()

    return int(row["id"]) if row else None


def get_order_context(order_id: int) -> dict[str, Any] | None:
    with engine.begin() as conn:
        row = conn.execute(text("""
            SELECT
                id,
                bot_order_no,
                ticket_channel_id,
                dispatch_message_id,
                customer_discord_id,
                customer_display_name,
                category,
                item,
                order_rule_key,
                status
            FROM web_orders
            WHERE id = :order_id
            LIMIT 1
        """), {"order_id": int(order_id)}).mappings().first()

    return dict(row) if row else None


def get_active_worker_ids(order_id: int) -> list[str]:
    with engine.begin() as conn:
        rows = conn.execute(text("""
            SELECT worker_discord_id
            FROM order_assignments
            WHERE order_id = :order_id
              AND is_active = 1
            ORDER BY assigned_at ASC, id ASC
        """), {"order_id": int(order_id)}).mappings().all()

    result: list[str] = []
    for row in rows:
        worker_id = str(row.get("worker_discord_id") or "").strip()
        if worker_id and worker_id not in result:
            result.append(worker_id)
    return result


def record_delivery(
    *,
    order_id: int,
    submitted_by_discord_id: int | str | None,
    recipient_discord_id: int | str,
    recipient_type: str,
    recipient_display_name: str | None,
    dm_channel_id: int | str | None,
    dm_message_id: int | str | None,
) -> int:
    ensure_order_credential_tables()

    with engine.begin() as conn:
        result = conn.execute(text("""
            INSERT INTO order_credential_deliveries (
                order_id,
                submitted_by_discord_id,
                recipient_discord_id,
                recipient_type,
                recipient_display_name,
                dm_channel_id,
                dm_message_id,
                delivered_at
            )
            VALUES (
                :order_id,
                :submitted_by_discord_id,
                :recipient_discord_id,
                :recipient_type,
                :recipient_display_name,
                :dm_channel_id,
                :dm_message_id,
                :delivered_at
            )
        """), {
            "order_id": int(order_id),
            "submitted_by_discord_id": (
                str(submitted_by_discord_id)
                if submitted_by_discord_id is not None
                else None
            ),
            "recipient_discord_id": str(recipient_discord_id),
            "recipient_type": str(recipient_type),
            "recipient_display_name": recipient_display_name,
            "dm_channel_id": str(dm_channel_id) if dm_channel_id is not None else None,
            "dm_message_id": str(dm_message_id) if dm_message_id is not None else None,
            "delivered_at": _now_text(),
        })
        delivery_id = result.lastrowid

    return int(delivery_id)


def list_active_deliveries(order_id: int) -> list[dict[str, Any]]:
    ensure_order_credential_tables()

    with engine.begin() as conn:
        rows = conn.execute(text("""
            SELECT
                id,
                order_id,
                submitted_by_discord_id,
                recipient_discord_id,
                recipient_type,
                recipient_display_name,
                dm_channel_id,
                dm_message_id,
                delivered_at,
                revoked_at,
                revoke_status,
                revoke_reason
            FROM order_credential_deliveries
            WHERE order_id = :order_id
              AND revoked_at IS NULL
            ORDER BY id ASC
        """), {"order_id": int(order_id)}).mappings().all()

    return [dict(row) for row in rows]


def mark_delivery_revoked(
    delivery_id: int,
    *,
    status: str,
    reason: str | None = None,
) -> None:
    ensure_order_credential_tables()

    with engine.begin() as conn:
        conn.execute(text("""
            UPDATE order_credential_deliveries
            SET revoked_at = :revoked_at,
                revoke_status = :revoke_status,
                revoke_reason = :revoke_reason
            WHERE id = :delivery_id
        """), {
            "revoked_at": _now_text(),
            "revoke_status": str(status),
            "revoke_reason": reason,
            "delivery_id": int(delivery_id),
        })


def list_delivery_history(order_id: int) -> list[dict[str, Any]]:
    ensure_order_credential_tables()

    with engine.begin() as conn:
        rows = conn.execute(text("""
            SELECT
                id,
                order_id,
                submitted_by_discord_id,
                recipient_discord_id,
                recipient_type,
                recipient_display_name,
                dm_channel_id,
                dm_message_id,
                delivered_at,
                revoked_at,
                revoke_status,
                revoke_reason
            FROM order_credential_deliveries
            WHERE order_id = :order_id
            ORDER BY id ASC
        """), {"order_id": int(order_id)}).mappings().all()

    return [dict(row) for row in rows]


__all__ = [
    "ensure_order_credential_tables",
    "get_active_worker_ids",
    "get_order_context",
    "get_order_id_by_ticket_channel",
    "list_active_deliveries",
    "list_delivery_history",
    "mark_delivery_revoked",
    "record_delivery",
]
