from __future__ import annotations

import hashlib
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


def get_staff_id_for_profile_thread(
    thread_id: int | str,
    *,
    db_file: str | Path | None = None,
) -> str | None:
    """Resolve exactly one profile from a Discord thread id without a full-profile scan."""
    thread_id_text = str(thread_id or "").strip()
    if not thread_id_text:
        return None
    with _connect(db_file) as conn:
        if not _table_exists(conn, "staff_profiles"):
            return None
        row = conn.execute(
            """
            SELECT staff_discord_id
            FROM staff_profiles
            WHERE forum_thread_id = ?
            LIMIT 1
            """,
            (thread_id_text,),
        ).fetchone()
    if row is None:
        return None
    value = str(row["staff_discord_id"] or "").strip()
    return value or None


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


def _insert_refresh_event(
    conn: sqlite3.Connection,
    staff_id: object,
    reason: str,
) -> bool:
    staff_id_text = str(staff_id or "").strip()
    if not staff_id_text:
        return False

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
        (staff_id_text, str(reason or "data_changed")[:100]),
    )
    return int(cur.rowcount or 0) > 0


def _create_profile_triggers(conn: sqlite3.Connection) -> None:
    columns = _table_columns(conn, "staff_profiles")
    if not columns or "staff_discord_id" not in columns:
        return

    watched = [
        name
        for name in (
            "display_name",
            "profile_type",
            "role_title",
            "main_games",
            "service_tags",
            "bio",
            "card_image_url",
            "forum_thread_id",
            "forum_channel_id",
            "panel_message_id",
            "is_public",
        )
        if name in columns
    ]
    if not watched:
        return

    conn.execute(
        f"""
        CREATE TRIGGER IF NOT EXISTS trg_staff_profile_refresh_profile_update
        AFTER UPDATE OF {', '.join(watched)}
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
    columns = _table_columns(conn, "staff_favorites")
    if "staff_discord_id" not in columns:
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
    if "staff_discord_id" not in columns:
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

    watched = [
        name
        for name in (
            "staff_discord_id",
            "rating",
            "is_public",
            "is_hidden",
            "comment",
            "service_category",
            "service_item",
            "created_at",
        )
        if name in columns
    ]
    if not watched:
        return

    conn.execute(
        f"""
        CREATE TRIGGER IF NOT EXISTS trg_staff_profile_refresh_review_update
        AFTER UPDATE OF {', '.join(watched)}
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


def _assignment_active_sql(columns: set[str], alias: str) -> str:
    if "is_active" in columns:
        return f"COALESCE({alias}.is_active, 1) = 1"
    return "1 = 1"


def _create_order_triggers(conn: sqlite3.Connection) -> None:
    order_columns = _table_columns(conn, "web_orders")
    assignment_columns = _table_columns(conn, "order_assignments")
    if not {"id", "status"}.issubset(order_columns):
        return
    if not {"order_id", "worker_discord_id"}.issubset(assignment_columns):
        return

    active_oa = _assignment_active_sql(assignment_columns, "oa")
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
              AND {active_oa}
              AND COALESCE(oa.worker_discord_id, '') != '';
        END
        """
    )

    new_active = (
        "COALESCE(NEW.is_active, 1) = 1"
        if "is_active" in assignment_columns
        else "1 = 1"
    )
    old_active = (
        "COALESCE(OLD.is_active, 1) = 1"
        if "is_active" in assignment_columns
        else "1 = 1"
    )

    conn.execute(
        f"""
        CREATE TRIGGER IF NOT EXISTS trg_staff_profile_refresh_assignment_insert
        AFTER INSERT ON order_assignments
        WHEN {new_active}
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
        WHEN {old_active}
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

    watched = ["worker_discord_id"]
    if "is_active" in assignment_columns:
        watched.append("is_active")

    conn.execute(
        f"""
        CREATE TRIGGER IF NOT EXISTS trg_staff_profile_refresh_assignment_update
        AFTER UPDATE OF {', '.join(watched)}
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
    """Install durable DB-level refresh rules and the snapshot safety net."""
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
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS staff_profile_refresh_state (
                staff_discord_id TEXT PRIMARY KEY,
                fingerprint TEXT NOT NULL,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )

        _create_profile_triggers(conn)
        _create_favorite_triggers(conn)
        _create_review_triggers(conn)
        _create_order_triggers(conn)
        conn.commit()


def _profile_rows(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    columns = _table_columns(conn, "staff_profiles")
    if "staff_discord_id" not in columns:
        return []

    select_parts = ["staff_discord_id"]
    for name in (
        "updated_at",
        "is_public",
        "panel_message_id",
        "forum_thread_id",
        "forum_channel_id",
    ):
        if name in columns:
            select_parts.append(name)

    return [
        dict(row)
        for row in conn.execute(
            f"SELECT {', '.join(select_parts)} FROM staff_profiles"
        ).fetchall()
    ]


def _favorite_counts(conn: sqlite3.Connection) -> dict[str, int]:
    columns = _table_columns(conn, "staff_favorites")
    if "staff_discord_id" not in columns:
        return {}
    return {
        str(row["staff_discord_id"]): int(row["c"] or 0)
        for row in conn.execute(
            """
            SELECT staff_discord_id, COUNT(*) AS c
            FROM staff_favorites
            GROUP BY staff_discord_id
            """
        ).fetchall()
    }


def _review_stats(conn: sqlite3.Connection) -> dict[str, tuple[Any, ...]]:
    columns = _table_columns(conn, "order_reviews")
    if "staff_discord_id" not in columns:
        return {}

    conditions = []
    if "is_public" in columns:
        conditions.append("COALESCE(is_public, 1) = 1")
    if "is_hidden" in columns:
        conditions.append("COALESCE(is_hidden, 0) = 0")
    where_sql = "WHERE " + " AND ".join(conditions) if conditions else ""

    rating_sql = "AVG(rating)" if "rating" in columns else "NULL"
    latest_sql = "MAX(created_at)" if "created_at" in columns else "NULL"
    recent_sql = (
        "SUM(CASE WHEN datetime(NULLIF(created_at, '')) >= datetime('now', '-30 days') "
        "THEN 1 ELSE 0 END)"
        if "created_at" in columns
        else "0"
    )

    rows = conn.execute(
        f"""
        SELECT
            staff_discord_id,
            COUNT(*) AS review_count,
            {rating_sql} AS average_rating,
            {latest_sql} AS latest_review_at,
            {recent_sql} AS recent_review_count
        FROM order_reviews
        {where_sql}
        GROUP BY staff_discord_id
        """
    ).fetchall()

    return {
        str(row["staff_discord_id"]): (
            int(row["review_count"] or 0),
            round(float(row["average_rating"] or 0.0), 4),
            str(row["latest_review_at"] or ""),
            int(row["recent_review_count"] or 0),
        )
        for row in rows
    }


def _order_stats(conn: sqlite3.Connection) -> dict[str, tuple[int, int]]:
    order_columns = _table_columns(conn, "web_orders")
    assignment_columns = _table_columns(conn, "order_assignments")
    if not {"id", "status"}.issubset(order_columns):
        return {}
    if not {"order_id", "worker_discord_id"}.issubset(assignment_columns):
        return {}

    active_sql = _assignment_active_sql(assignment_columns, "oa")
    date_candidates = [
        name
        for name in ("closed_at", "updated_at", "created_at")
        if name in order_columns
    ]
    if date_candidates:
        date_expr = "COALESCE(" + ", ".join(
            f"NULLIF(wo.{name}, '')" for name in date_candidates
        ) + ")"
        recent_sql = (
            f"COUNT(DISTINCT CASE WHEN datetime({date_expr}) >= datetime('now', '-30 days') "
            "THEN wo.id END)"
        )
    else:
        recent_sql = "0"

    rows = conn.execute(
        f"""
        SELECT
            oa.worker_discord_id AS staff_discord_id,
            COUNT(DISTINCT wo.id) AS completed_count,
            {recent_sql} AS recent_completed_count
        FROM order_assignments oa
        JOIN web_orders wo ON wo.id = oa.order_id
        WHERE wo.status = 'closed'
          AND {active_sql}
          AND COALESCE(oa.worker_discord_id, '') != ''
        GROUP BY oa.worker_discord_id
        """
    ).fetchall()

    return {
        str(row["staff_discord_id"]): (
            int(row["completed_count"] or 0),
            int(row["recent_completed_count"] or 0),
        )
        for row in rows
    }


def _profile_snapshots(conn: sqlite3.Connection) -> dict[str, tuple[str, bool]]:
    favorites = _favorite_counts(conn)
    reviews = _review_stats(conn)
    orders = _order_stats(conn)
    snapshots: dict[str, tuple[str, bool]] = {}

    for profile in _profile_rows(conn):
        staff_id = str(profile.get("staff_discord_id") or "").strip()
        if not staff_id:
            continue

        panel_message_id = str(profile.get("panel_message_id") or "").strip()
        channel_id = str(
            profile.get("forum_thread_id")
            or profile.get("forum_channel_id")
            or ""
        ).strip()
        has_panel = bool(panel_message_id and channel_id)

        values = (
            staff_id,
            str(profile.get("updated_at") or ""),
            int(profile.get("is_public") or 0),
            panel_message_id,
            channel_id,
            favorites.get(staff_id, 0),
            reviews.get(staff_id, (0, 0.0, "", 0)),
            orders.get(staff_id, (0, 0)),
        )
        fingerprint = hashlib.sha256(repr(values).encode("utf-8")).hexdigest()
        snapshots[staff_id] = (fingerprint, has_panel)

    return snapshots


def _reconcile_snapshot_events(conn: sqlite3.Connection) -> int:
    """Detect missed trigger events by comparing panel-visible DB state."""
    snapshots = _profile_snapshots(conn)
    existing = {
        str(row["staff_discord_id"]): str(row["fingerprint"])
        for row in conn.execute(
            "SELECT staff_discord_id, fingerprint FROM staff_profile_refresh_state"
        ).fetchall()
    }

    enqueued = 0
    for staff_id, (fingerprint, has_panel) in snapshots.items():
        previous = existing.get(staff_id)
        if previous is None:
            conn.execute(
                """
                INSERT INTO staff_profile_refresh_state (
                    staff_discord_id,
                    fingerprint,
                    updated_at
                )
                VALUES (?, ?, CURRENT_TIMESTAMP)
                """,
                (staff_id, fingerprint),
            )
            if has_panel and _insert_refresh_event(conn, staff_id, "snapshot_bootstrap"):
                enqueued += 1
            continue

        if previous == fingerprint:
            continue

        conn.execute(
            """
            UPDATE staff_profile_refresh_state
            SET fingerprint = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE staff_discord_id = ?
            """,
            (fingerprint, staff_id),
        )
        if has_panel and _insert_refresh_event(conn, staff_id, "snapshot_changed"):
            enqueued += 1

    if snapshots:
        placeholders = ",".join("?" for _ in snapshots)
        conn.execute(
            f"""
            DELETE FROM staff_profile_refresh_state
            WHERE staff_discord_id NOT IN ({placeholders})
            """,
            tuple(snapshots.keys()),
        )
    else:
        conn.execute("DELETE FROM staff_profile_refresh_state")

    return enqueued


def enqueue_staff_profile_refresh(
    staff_id: int | str,
    *,
    reason: str = "manual",
    db_file: str | Path | None = None,
) -> bool:
    ensure_staff_profile_refresh_sync(db_file=db_file)
    with _connect(db_file) as conn:
        inserted = _insert_refresh_event(conn, staff_id, reason)
        conn.commit()
        return inserted


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
            UPDATE staff_profile_refresh_events AS current
            SET status = 'done',
                error_message = 'superseded by newer pending refresh event',
                processed_at = CURRENT_TIMESTAMP
            WHERE current.status = 'processing'
              AND current.processed_at IS NOT NULL
              AND current.processed_at <= datetime('now', ?)
              AND EXISTS (
                  SELECT 1
                  FROM staff_profile_refresh_events newer
                  WHERE newer.staff_discord_id = current.staff_discord_id
                    AND newer.status = 'pending'
                    AND newer.id != current.id
              )
            """,
            (f"-{stale_minutes} minutes",),
        )
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

        _reconcile_snapshot_events(conn)

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
    requested_status = "failed" if next_retry >= retry_limit else "pending"

    with _connect(db_file) as conn:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute(
            """
            SELECT staff_discord_id
            FROM staff_profile_refresh_events
            WHERE id = ?
            LIMIT 1
            """,
            (int(event_id),),
        ).fetchone()
        if row is None:
            conn.rollback()
            return

        next_status = requested_status
        final_error = str(error_message or "")[:1000]
        if requested_status == "pending":
            newer_pending = conn.execute(
                """
                SELECT 1
                FROM staff_profile_refresh_events
                WHERE staff_discord_id = ?
                  AND status = 'pending'
                  AND id != ?
                LIMIT 1
                """,
                (str(row["staff_discord_id"]), int(event_id)),
            ).fetchone()
            if newer_pending is not None:
                next_status = "done"
                final_error = "superseded by newer pending refresh event"

        conn.execute(
            """
            UPDATE staff_profile_refresh_events
            SET status = ?,
                retry_count = ?,
                error_message = ?,
                processed_at = CASE
                    WHEN ? = 'pending' THEN NULL
                    ELSE CURRENT_TIMESTAMP
                END
            WHERE id = ?
            """,
            (
                next_status,
                next_retry,
                final_error,
                next_status,
                int(event_id),
            ),
        )
        conn.commit()
