from __future__ import annotations

import sqlite3
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any

from services.topups import ensure_topup_tables

TAIPEI_TZ = timezone(timedelta(hours=8))


def _now_iso() -> str:
    return datetime.now(TAIPEI_TZ).isoformat(timespec="seconds")


def _db_path() -> Path:
    return Path(__file__).resolve().parents[1] / "bot.db"


def ensure_topup_notification_columns() -> None:
    ensure_topup_tables()
    path = _db_path()

    with sqlite3.connect(path, timeout=15) as conn:
        columns = {
            str(row[1])
            for row in conn.execute("PRAGMA table_info(topup_orders)").fetchall()
        }

        if "review_notified_at" not in columns:
            conn.execute(
                "ALTER TABLE topup_orders ADD COLUMN review_notified_at TEXT"
            )

        if "review_notification_message_id" not in columns:
            conn.execute(
                "ALTER TABLE topup_orders ADD COLUMN review_notification_message_id TEXT"
            )

        conn.commit()


def list_unnotified_pending_reviews(limit: int = 20) -> list[dict[str, Any]]:
    ensure_topup_notification_columns()
    path = _db_path()
    safe_limit = max(1, min(int(limit or 20), 100))

    with sqlite3.connect(path, timeout=15) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            """
            SELECT *
            FROM topup_orders
            WHERE status = 'pending_review'
              AND review_notified_at IS NULL
            ORDER BY id ASC
            LIMIT ?
            """,
            (safe_limit,),
        ).fetchall()
        return [dict(row) for row in rows]


def mark_review_notified(topup_id: int, message_id: str | int) -> None:
    ensure_topup_notification_columns()
    path = _db_path()

    with sqlite3.connect(path, timeout=15) as conn:
        conn.execute(
            """
            UPDATE topup_orders
            SET review_notified_at = ?,
                review_notification_message_id = ?
            WHERE id = ?
            """,
            (_now_iso(), str(message_id), int(topup_id)),
        )
        conn.commit()
