from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any


DEFAULT_STALE_PROCESSING_MINUTES = 10
DEFAULT_MAX_RETRIES = 3


def _db_path(db_file: str | Path | None = None) -> Path:
    if db_file is not None:
        return Path(db_file)
    return Path(__file__).resolve().parents[1] / "web_dashboard.db"


def _connect(db_file: str | Path | None = None) -> sqlite3.Connection:
    conn = sqlite3.connect(_db_path(db_file), timeout=15)
    conn.row_factory = sqlite3.Row
    return conn


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


def _table_columns(conn: sqlite3.Connection, table_name: str) -> set[str]:
    if not _table_exists(conn, table_name):
        return set()
    return {
        str(row["name"])
        for row in conn.execute(f"PRAGMA table_info({table_name})").fetchall()
    }


def _create_profile_trigger(conn: sqlite3.Connection) -> None:
    if not _table_exists(conn, "staff_profiles"):
        return

    conn.execute(
        """
        CREATE TRIGGER IF NOT EXISTS trg_staff_profile_refresh_profile_update
        AFTER UPDATE OF
            display_name,
            profile_type,
            role_title,
            main_games,
            service_tags,
            bio,
            card_image_url,
            is_public
        ON staff_profiles
        BEGIN
            INSERT OR IGNORE INTO staff_profile_refresh_events (
                staff_discord_id,
                reason,
                status,
                retry_count,
                created_at
            )
            VALUES (
                NEW.staff_discord_id,
                'profile_updated',
                'pending',
                0,
                CURRENT_TIMESTAMP
            );
        END
        """
    )


def _create_favorite_triggers(conn: sqlite3.Connection) -> None:
    if not _table_exists(conn, "staff_favorites"):
        return

    conn.execute(
        """
        CREATE TRIGGER IF NOT EXISTS trg_staff_profile_refresh_favorite_insert
        AFTER INSERT ON staff_favorites
        BEGIN
            INSERT OR IGNORE INTO staff_profile_refresh_events (
                staff_discord_id,
                reason,
                status,
                retry_count,
                created_at
            )
            VALUES (
                NEW.staff_discord_id,
                'favorite_changed',
                'pending',
                0,
                CURRENT_TIMESTAMP
            );
        END
        """
    )

    conn.execute(
        """
        CREATE TRIGGER IF NOT EXISTS trg_staff_profile_refresh_favorite_delete
        AFTER DELETE ON staff_favorites
        BEGIN
            INSERT OR IGNORE INTO staff_profile_refresh_events (
                staff_discord_id,
                reason,
                status,
                retry_count,
                created_at
            )
            VALUES (
                OLD.staff_discord_id,
                'favorite_changed',
                'pending',
                0,
                CURRENT_TIMESTAMP
            );
        END
        """
    )


def _create_review_triggers(conn: sqlite3.Connection) -> None:
    columns = _table_columns(conn, "order_reviews")
    if not columns or "staff_discord_id" not in columns:
        return

    conn.execute(
        """
        CREATE TRIGGER IF NOT EXISTS trg_staff_profile_refresh_review_insert
        AFTER INSERT ON order_reviews
        BEGIN
            INSERT OR IGNORE INTO staff_profile_refresh_events (
                staff_discord_id,
                reason,
                status,
                retry_count,
                created_at
            )
            VALUES (
                NEW.staff_discord_id,
                'review_changed',
                'pending',
                0,
                CURRENT_TIMESTAMP
            );
        END
        """
    )

    conn.execute(
        """
        CREATE TRIGGER IF NOT EXISTS trg_staff_profile_refresh_review_delete
        AFTER DELETE ON order_reviews
        BEGIN
            INSERT OR IGNORE INTO staff_profile_refresh_events (
                staff_discord_id,
                reason,
                status,
                retry_count,
                created_at
            )
            VALUES (
                OLD.staff_discord_id,
                'review_changed',
                'pending',
                0,
                CURRENT_TIMESTAMP
            );
        END
        """
    )

    update_columns = [
        column
        for column in (
            "staff_discord_id",
            "rating",
            "is_public",
            "is_hidden",
            "comment",
            "service_category",
            "service_item",
            "created_at",
        )
        if column in columns
    ]
    if not update_columns:
        return

    update_of = ", ".join(update_columns)
    conn.execute(
        f"""
        CREATE TRIGGER IF NOT EXISTS trg_staff_profile_refresh_review_update
        AFTER UPDATE OF {update_of}
        ON order_reviews
        BEGIN
            INSERT OR IGNORE INTO staff_profile_refresh_events (
                staff_discord_id,
                reason,
                status,
                retry_count,
                created_at
            )
            VALUES (
                OLD.staff_discord_id,
                'review_changed',
                'pending',
                0,
                CURRENT_TIMESTAMP
            );

            INSERT OR IGNORE INTO staff_profile_refresh_events (
                staff_discord_id,
                reason,
                status,
                retry_count,
                created_at
            )
            VALUES (
                NEW.staff_discord_id,
                'review_changed',
                'pending',
                0,
                CURRENT_TIMESTAMP
            );
        END
        """
    )


def _assignment_active_predicate(columns: set[str], alias: str = "") -> str:
    prefix = f"{alias}." if alias else ""
    if "is_active" in columns:
        return f"COALESCE({prefix}is_active, 1) = 1"
    return "1 = 1"


def _create_order_triggers(conn: sqlite3.Connection) -> None:
    order_columns = _table_columns(conn, "web_orders")
    assignment_columns = _table_columns(conn, "order_assignments")

    required_assignment_columns = {"order_id", "worker_discord_id"}
    if not order_columns or "id" not in order_columns or "status" not in order_columns:
        return
    if not required_assignment_columns.issubset(assignment_columns):
        return

    active_predicate = _assignment_active_predicate(assignment_columns, "oa")

    conn.execute(
        f"""
        CREATE TRIGGER IF NOT EXISTS trg_staff_profile_refresh_order_status
        AFTER UPDATE OF status ON web_orders
        WHEN COALESCE(OLD.status, '') != COALESCE(NEW.status, '')
        BEGIN
            INSERT OR IGNORE INTO staff_profile_refresh_events (
                staff_discord_id,
                reason,
                status,
                retry_count,
                created_at
            )
            SELECT DISTINCT
                oa.worker_discord_id,
                'order_status_changed',
                'pending',
                0,
                CURRENT_TIMESTAMP
            FROM order_assignments oa
            WHERE oa.order_id = NEW.id
              AND {active_predicate}
              AND COALESCE(oa.worker_discord_id, '') != '';
        END
        """
    )

    assignment_active_new = _assignment_active_predicate(assignment_columns, "NEW")
    assignment_active_old = _assignment_active_predicate(assignment_columns, "OLD")

    conn.execute(
        f"""
        CREATE TRIGGER IF NOT EXISTS trg_staff_profile_refresh_assignment_insert
        AFTER INSERT ON order_assignments
        WHEN {assignment_active_new}
          AND COALESCE(NEW.worker_discord_id, '') != ''
        BEGIN
            INSERT OR IGNORE INTO staff_profile_refresh_events (
                staff_discord_id,
                reason,
                status,
                retry_count,
                created_at
            )
            VALUES (
                NEW.worker_discord_id,
                'assignment_changed',
                'pending',
                0,
                CURRENT_TIMESTAMP
            );
        END
        """
    )

    conn.execute(
        f"""
        CREATE TRIGGER IF NOT EXISTS trg_staff_profile_refresh_assignment_delete
        AFTER DELETE ON order_assignments
        WHEN {assignment_active_old}
          AND COALESCE(OLD.worker_discord_id, '') != ''
        BEGIN
            INSERT OR IGNORE INTO staff_profile_refresh_events (
                staff_discord_id,
                reason,
                status,
                retry_count,
                created_at
            )
            VALUES (
                OLD.worker_discord_id,
                'assignment_changed',
                'pending',
                0,
                CURRENT_TIMESTAMP
            );
        END
        """
    )

    update_columns = ["worker_discord_id"]
    if "is_active" in assignment_columns:
        update_columns.append("is_active")

    conn.execute(
        f"""
        CREATE TRIGGER IF NOT EXISTS trg_staff_profile_refresh_assignment_update
        AFTER UPDATE OF {', '.join(update_columns)}
        ON order_assignments
        BEGIN
            INSERT OR IGNORE INTO staff_profile_refresh_events (
                staff_discord_id,
                reason,
                status,
                retry_count,
                created_at
            )
            SELECT
                OLD.worker_discord_id,
                'assignment_changed',
                'pending',
                0,
                CURRENT_TIMESTAMP
            WHERE COALESCE(OLD.worker_discord_id, '') != '';

            INSERT OR IGNORE INTO staff_profile_refresh_events (
                staff_discord_id,
                reason,
                status,
                retry_count,
                created_at
            )
            SELECT
                NEW.worker_discord_id,
                'assignment_changed',
                'pending',
                0,
                CURRENT_TIMESTAMP
            WHERE COALESCE(NEW.worker_discord_id, '') != '';
        END
        """
    )


def ensure_staff_profile_refresh_sync(
    *,
    db_file: str | Path | None = None,
) -> None:
    """Install the durable outbox and DB-level change hooks for profile panels."""
    with _connect(db_file) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS staff_profile_refresh_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                staff_discord_id TEXT NOT NULL,
                reason TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                retry_count INTEGER NOT NULL DEFAULT 0,
                error_message TEXT,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                processed_at TEXT
            )
            """
        )
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_staff_profile_refresh_status
            ON staff_profile_refresh_events(status, id)
            """
        )
        conn.execute(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS idx_staff_profile_refresh_pending_staff
            ON staff_profile_refresh_events(staff_discord_id)
            WHERE status = 'pending'
            """
        )

        _create_profile_trigger(conn)
        _create_favorite_triggers(conn)
        _create_review_triggers(conn)
        _create_order_triggers(conn)
        conn.commit()


def enqueue_staff_profile_refresh(
    staff_id: int | str,
    *,
    reason: str = "manual",
    db_file: str | Path | None = None,
) -> bool:
    ensure_staff_profile_refresh_sync(db_file=db_file)
    staff_id_text = str(staff_id or "").strip()
    if not staff_id_text:
        return False

    with _connect(db_file) as conn:
        cur = conn.execute(
            """
            INSERT OR IGNORE INTO staff_profile_refresh_events (
                staff_discord_id,
                reason,
                status,
                retry_count,
                created_at
            )
            VALUES (?, ?, 'pending', 0, CURRENT_TIMESTAMP)
            """,
            (staff_id_text, str(reason or "manual")[:100]),
        )
        conn.commit()
        return int(cur.rowcount or 0) > 0


def claim_staff_profile_refresh_events(
    *,
    limit: int = 20,
    stale_processing_minutes: int = DEFAULT_STALE_PROCESSING_MINUTES,
    db_file: str | Path | None = None,
) -> list[dict[str, Any]]:
    ensure_staff_profile_refresh_sync(db_file=db_file)
    safe_limit = max(1, min(int(limit or 20), 100))
    stale_minutes = max(1, int(stale_processing_minutes or 10))

    with _connect(db_file) as conn:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute(
            """
            UPDATE staff_profile_refresh_events
            SET status = 'pending',
                processed_at = NULL
            WHERE status = 'processing'
              AND processed_at IS NOT NULL
              AND processed_at <= datetime('now', ?)
            """,
            (f"-{stale_minutes} minutes",),
        )

        rows = conn.execute(
            """
            SELECT
                id AS event_id,
                staff_discord_id,
                reason,
                retry_count
            FROM staff_profile_refresh_events
            WHERE status = 'pending'
            ORDER BY id ASC
            LIMIT ?
            """,
            (safe_limit,),
        ).fetchall()

        event_ids = [int(row["event_id"]) for row in rows]
        if event_ids:
            placeholders = ",".join("?" for _ in event_ids)
            cur = conn.execute(
                f"""
                UPDATE staff_profile_refresh_events
                SET status = 'processing',
                    processed_at = CURRENT_TIMESTAMP
                WHERE status = 'pending'
                  AND id IN ({placeholders})
                """,
                event_ids,
            )
            if int(cur.rowcount or 0) != len(event_ids):
                conn.rollback()
                return []

        conn.commit()
        return [dict(row) for row in rows]


def mark_staff_profile_refresh_done(
    event_id: int,
    *,
    db_file: str | Path | None = None,
) -> None:
    with _connect(db_file) as conn:
        conn.execute(
            """
            UPDATE staff_profile_refresh_events
            SET status = 'done',
                error_message = NULL,
                processed_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (int(event_id),),
        )
        conn.commit()


def mark_staff_profile_refresh_failed(
    event_id: int,
    error_message: str,
    retry_count: int,
    *,
    max_retries: int = DEFAULT_MAX_RETRIES,
    db_file: str | Path | None = None,
) -> None:
    next_retry = int(retry_count or 0) + 1
    retry_limit = max(1, int(max_retries or DEFAULT_MAX_RETRIES))
    next_status = "failed" if next_retry >= retry_limit else "pending"

    with _connect(db_file) as conn:
        conn.execute(
            """
            UPDATE staff_profile_refresh_events
            SET status = ?,
                retry_count = ?,
                error_message = ?,
                processed_at = CASE
                    WHEN ? = 'failed' THEN CURRENT_TIMESTAMP
                    ELSE NULL
                END
            WHERE id = ?
            """,
            (
                next_status,
                next_retry,
                str(error_message or "")[:1000],
                next_status,
                int(event_id),
            ),
        )
        conn.commit()
