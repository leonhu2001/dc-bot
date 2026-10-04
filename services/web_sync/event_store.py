from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any


DEFAULT_STALE_PROCESSING_MINUTES = 10


def _db_path(db_file: str | Path | None = None) -> Path:
    if db_file is not None:
        return Path(db_file)
    return Path(__file__).resolve().parents[2] / "web_dashboard.db"


def claim_pending_events(
    *,
    limit: int = 10,
    stale_processing_minutes: int = DEFAULT_STALE_PROCESSING_MINUTES,
    db_file: str | Path | None = None,
) -> list[dict[str, Any]]:
    """Atomically claim generic Web -> Discord sync events.

    Claim/unclaim events belong to the acceptance-sync worker, so this store
    deliberately excludes them. A BEGIN IMMEDIATE transaction serializes the
    select-and-mark operation so two Bot workers cannot process the same row.
    """

    path = _db_path(db_file)
    safe_limit = max(1, min(int(limit or 10), 100))
    stale_minutes = max(1, int(stale_processing_minutes or 10))

    with sqlite3.connect(path, timeout=15) as conn:
        conn.row_factory = sqlite3.Row
        conn.execute("BEGIN IMMEDIATE")

        # Recover rows abandoned by a Bot process that died after claiming
        # them. processed_at is the timestamp of the current processing attempt.
        conn.execute(
            """
            UPDATE sync_events
            SET status = 'pending'
            WHERE status = 'processing'
              AND processed_at IS NOT NULL
              AND processed_at <= datetime('now', ?)
            """,
            (f"-{stale_minutes} minutes",),
        )

        rows = conn.execute(
            """
            SELECT
                e.id AS event_id,
                e.order_id,
                e.event_type,
                e.retry_count,
                e.payload_json,
                w.id AS web_order_id,
                w.ticket_channel_id,
                w.dispatch_channel_id,
                w.dispatch_message_id,
                w.category,
                w.item,
                w.quantity,
                w.amount,
                w.customer_discord_id,
                w.customer_display_name
            FROM sync_events e
            JOIN web_orders w ON w.id = e.order_id
            WHERE e.status = 'pending'
              AND e.event_type NOT IN ('order_claimed', 'order_unclaimed')
            ORDER BY e.id ASC
            LIMIT ?
            """,
            (safe_limit,),
        ).fetchall()

        event_ids = [int(row["event_id"]) for row in rows]
        if event_ids:
            placeholders = ",".join("?" for _ in event_ids)
            cursor = conn.execute(
                f"""
                UPDATE sync_events
                SET status = 'processing',
                    processed_at = datetime('now')
                WHERE status = 'pending'
                  AND id IN ({placeholders})
                """,
                event_ids,
            )
            if cursor.rowcount != len(event_ids):
                conn.rollback()
                return []

        conn.commit()
        return [dict(row) for row in rows]


def get_assignments(
    order_id: int,
    *,
    db_file: str | Path | None = None,
) -> list[dict[str, Any]]:
    with sqlite3.connect(_db_path(db_file), timeout=15) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            """
            SELECT
                worker_discord_id,
                worker_display_name,
                role_type,
                is_active
            FROM order_assignments
            WHERE order_id = ?
              AND is_active = 1
            ORDER BY id ASC
            """,
            (int(order_id),),
        ).fetchall()
        return [dict(row) for row in rows]


def mark_event_done(
    event_id: int,
    *,
    db_file: str | Path | None = None,
) -> None:
    with sqlite3.connect(_db_path(db_file), timeout=15) as conn:
        conn.execute(
            """
            UPDATE sync_events
            SET status = 'done',
                error_message = NULL,
                processed_at = datetime('now')
            WHERE id = ?
            """,
            (int(event_id),),
        )
        conn.commit()


def mark_event_failed(
    event_id: int,
    error_message: str,
    retry_count: int,
    *,
    db_file: str | Path | None = None,
    max_retries: int = 3,
) -> None:
    next_retry = int(retry_count or 0) + 1
    retry_limit = max(1, int(max_retries or 3))
    next_status = "failed" if next_retry >= retry_limit else "pending"

    with sqlite3.connect(_db_path(db_file), timeout=15) as conn:
        conn.execute(
            """
            UPDATE sync_events
            SET status = ?,
                error_message = ?,
                retry_count = ?,
                processed_at = CASE
                    WHEN ? = 'failed' THEN datetime('now')
                    ELSE processed_at
                END
            WHERE id = ?
            """,
            (
                next_status,
                str(error_message or "")[:1000],
                next_retry,
                next_status,
                int(event_id),
            ),
        )
        conn.commit()


def _table_exists(conn: sqlite3.Connection, table_name: str) -> bool:
    row = conn.execute(
        """
        SELECT 1
        FROM sqlite_master
        WHERE type = 'table'
          AND name = ?
        LIMIT 1
        """,
        (str(table_name),),
    ).fetchone()
    return row is not None


def load_order_created_bundle(
    order_id: int,
    *,
    db_file: str | Path | None = None,
) -> dict[str, dict[str, Any]]:
    with sqlite3.connect(_db_path(db_file), timeout=15) as conn:
        conn.row_factory = sqlite3.Row

        order_row = conn.execute(
            """
            SELECT *
            FROM web_orders
            WHERE id = ?
            LIMIT 1
            """,
            (int(order_id),),
        ).fetchone()

        if order_row is None:
            raise RuntimeError(f"找不到網站訂單 WEB-{order_id}")

        acceptance_row = None
        if _table_exists(conn, "order_acceptance_meta"):
            acceptance_row = conn.execute(
                """
                SELECT *
                FROM order_acceptance_meta
                WHERE order_id = ?
                LIMIT 1
                """,
                (int(order_id),),
            ).fetchone()

        submission_row = None
        if _table_exists(conn, "web_order_submission_meta"):
            submission_row = conn.execute(
                """
                SELECT *
                FROM web_order_submission_meta
                WHERE order_id = ?
                LIMIT 1
                """,
                (int(order_id),),
            ).fetchone()

        return {
            "order": dict(order_row),
            "acceptance": dict(acceptance_row) if acceptance_row is not None else {},
            "submission": dict(submission_row) if submission_row is not None else {},
        }


def update_order_created_links(
    order_id: int,
    *,
    ticket_channel_id: Any = None,
    dispatch_channel_id: Any = None,
    dispatch_message_id: Any = None,
    db_file: str | Path | None = None,
) -> None:
    updates: list[str] = []
    values: list[Any] = []

    if ticket_channel_id is not None:
        updates.append("ticket_channel_id = ?")
        values.append(str(ticket_channel_id))

    if dispatch_channel_id is not None:
        updates.append("dispatch_channel_id = ?")
        values.append(str(dispatch_channel_id))

    if dispatch_message_id is not None:
        updates.append("dispatch_message_id = ?")
        values.append(str(dispatch_message_id))

    if not updates:
        return

    values.append(int(order_id))

    with sqlite3.connect(_db_path(db_file), timeout=15) as conn:
        conn.execute(
            "UPDATE web_orders SET "
            + ", ".join(updates)
            + " WHERE id = ?",
            tuple(values),
        )
        conn.commit()


def mark_order_created_processing(
    event_id: int,
    *,
    db_file: str | Path | None = None,
) -> None:
    with sqlite3.connect(_db_path(db_file), timeout=15) as conn:
        conn.execute(
            """
            UPDATE sync_events
            SET status = 'processing',
                error_message = NULL
            WHERE id = ?
              AND event_type = 'order_created'
              AND status IN (
                  'pending',
                  'failed',
                  'processing'
              )
            """,
            (int(event_id),),
        )
        conn.commit()


def fetch_order_created_retry_events(
    *,
    limit: int = 10,
    db_file: str | Path | None = None,
) -> list[dict[str, Any]]:
    safe_limit = max(1, min(int(limit or 10), 100))

    with sqlite3.connect(_db_path(db_file), timeout=15) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            """
            SELECT
                e.id AS event_id,
                e.order_id,
                e.event_type,
                e.retry_count,
                w.id AS web_order_id,
                w.ticket_channel_id,
                w.dispatch_channel_id,
                w.dispatch_message_id,
                w.category,
                w.item,
                w.quantity,
                w.amount,
                w.customer_discord_id,
                w.customer_display_name
            FROM sync_events e
            JOIN web_orders w
              ON w.id = e.order_id
            WHERE e.event_type = 'order_created'
              AND e.status IN (
                  'failed',
                  'processing'
              )
              AND COALESCE(
                  e.retry_count,
                  0
              ) < 20
            ORDER BY e.id ASC
            LIMIT ?
            """,
            (safe_limit,),
        ).fetchall()

        return [dict(row) for row in rows]
