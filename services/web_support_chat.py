from __future__ import annotations

import json
import secrets
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

STATUS_AI = "ai"
STATUS_WAITING_HUMAN = "waiting_human"
STATUS_HUMAN = "human"
STATUS_CLOSED = "closed"

SENDER_CUSTOMER = "customer"
SENDER_AI = "ai"
SENDER_STAFF = "staff"
SENDER_SYSTEM = "system"


def _db_path(db_file: str | Path | None = None) -> Path:
    if db_file is not None:
        return Path(db_file)
    return Path(__file__).resolve().parents[1] / "web_dashboard.db"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def ensure_web_support_tables(db_file: str | Path | None = None) -> None:
    path = _db_path(db_file)
    with sqlite3.connect(path, timeout=15) as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS web_support_sessions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                public_token TEXT NOT NULL UNIQUE,
                customer_discord_id TEXT,
                customer_display_name TEXT,
                status TEXT NOT NULL DEFAULT 'ai',
                ai_enabled INTEGER NOT NULL DEFAULT 1,
                handoff_reason TEXT,
                human_requested_at TEXT,
                claimed_at TEXT,
                claimed_by_discord_id TEXT,
                claimed_by_display_name TEXT,
                closed_at TEXT,
                discord_channel_id TEXT,
                discord_thread_id TEXT,
                discord_notification_message_id TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_web_support_sessions_status
                ON web_support_sessions(status, updated_at);

            CREATE INDEX IF NOT EXISTS idx_web_support_sessions_customer
                ON web_support_sessions(customer_discord_id, updated_at);

            CREATE TABLE IF NOT EXISTS web_support_messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id INTEGER NOT NULL,
                sender_type TEXT NOT NULL,
                sender_discord_id TEXT,
                sender_display_name TEXT,
                body TEXT NOT NULL,
                created_at TEXT NOT NULL,
                discord_message_id TEXT,
                metadata_json TEXT,
                FOREIGN KEY(session_id) REFERENCES web_support_sessions(id)
            );

            CREATE INDEX IF NOT EXISTS idx_web_support_messages_session
                ON web_support_messages(session_id, id);
            """
        )
        conn.commit()


def _row(row: sqlite3.Row | None) -> dict[str, Any] | None:
    return dict(row) if row is not None else None


def create_session(
    *,
    customer_discord_id: str | None = None,
    customer_display_name: str | None = None,
    db_file: str | Path | None = None,
) -> dict[str, Any]:
    ensure_web_support_tables(db_file)
    now = _now()
    token = secrets.token_urlsafe(32)

    with sqlite3.connect(_db_path(db_file), timeout=15) as conn:
        conn.row_factory = sqlite3.Row
        cur = conn.execute(
            """
            INSERT INTO web_support_sessions (
                public_token,
                customer_discord_id,
                customer_display_name,
                status,
                ai_enabled,
                created_at,
                updated_at
            )
            VALUES (?, ?, ?, 'ai', 1, ?, ?)
            """,
            (
                token,
                str(customer_discord_id or "").strip() or None,
                str(customer_display_name or "").strip() or None,
                now,
                now,
            ),
        )
        session_id = int(cur.lastrowid)
        conn.commit()
        return _row(
            conn.execute(
                "SELECT * FROM web_support_sessions WHERE id = ?",
                (session_id,),
            ).fetchone()
        ) or {}


def get_session_by_token(
    token: str,
    *,
    db_file: str | Path | None = None,
) -> dict[str, Any] | None:
    ensure_web_support_tables(db_file)
    token = str(token or "").strip()
    if not token:
        return None

    with sqlite3.connect(_db_path(db_file), timeout=15) as conn:
        conn.row_factory = sqlite3.Row
        return _row(
            conn.execute(
                "SELECT * FROM web_support_sessions WHERE public_token = ? LIMIT 1",
                (token,),
            ).fetchone()
        )


def get_session(
    session_id: int,
    *,
    db_file: str | Path | None = None,
) -> dict[str, Any] | None:
    ensure_web_support_tables(db_file)
    with sqlite3.connect(_db_path(db_file), timeout=15) as conn:
        conn.row_factory = sqlite3.Row
        return _row(
            conn.execute(
                "SELECT * FROM web_support_sessions WHERE id = ? LIMIT 1",
                (int(session_id),),
            ).fetchone()
        )


def bind_session_identity(
    session_id: int,
    *,
    customer_discord_id: str | None,
    customer_display_name: str | None,
    db_file: str | Path | None = None,
) -> None:
    ensure_web_support_tables(db_file)
    with sqlite3.connect(_db_path(db_file), timeout=15) as conn:
        conn.execute(
            """
            UPDATE web_support_sessions
            SET customer_discord_id = COALESCE(?, customer_discord_id),
                customer_display_name = COALESCE(?, customer_display_name),
                updated_at = ?
            WHERE id = ?
            """,
            (
                str(customer_discord_id or "").strip() or None,
                str(customer_display_name or "").strip() or None,
                _now(),
                int(session_id),
            ),
        )
        conn.commit()


def add_message(
    session_id: int,
    *,
    sender_type: str,
    body: str,
    sender_discord_id: str | None = None,
    sender_display_name: str | None = None,
    discord_message_id: str | None = None,
    metadata: dict[str, Any] | None = None,
    db_file: str | Path | None = None,
) -> dict[str, Any]:
    ensure_web_support_tables(db_file)
    text = str(body or "").strip()
    if not text:
        raise ValueError("message body is empty")
    if len(text) > 4000:
        text = text[:4000]

    now = _now()

    with sqlite3.connect(_db_path(db_file), timeout=15) as conn:
        conn.row_factory = sqlite3.Row
        cur = conn.execute(
            """
            INSERT INTO web_support_messages (
                session_id,
                sender_type,
                sender_discord_id,
                sender_display_name,
                body,
                created_at,
                discord_message_id,
                metadata_json
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                int(session_id),
                str(sender_type),
                str(sender_discord_id or "").strip() or None,
                str(sender_display_name or "").strip() or None,
                text,
                now,
                str(discord_message_id or "").strip() or None,
                json.dumps(metadata or {}, ensure_ascii=False),
            ),
        )
        message_id = int(cur.lastrowid)
        conn.execute(
            "UPDATE web_support_sessions SET updated_at = ? WHERE id = ?",
            (now, int(session_id)),
        )
        conn.commit()
        return _row(
            conn.execute(
                "SELECT * FROM web_support_messages WHERE id = ?",
                (message_id,),
            ).fetchone()
        ) or {}


def list_messages(
    session_id: int,
    *,
    after_id: int = 0,
    limit: int = 200,
    db_file: str | Path | None = None,
) -> list[dict[str, Any]]:
    ensure_web_support_tables(db_file)
    safe_limit = max(1, min(int(limit or 200), 500))

    with sqlite3.connect(_db_path(db_file), timeout=15) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            """
            SELECT *
            FROM web_support_messages
            WHERE session_id = ?
              AND id > ?
            ORDER BY id ASC
            LIMIT ?
            """,
            (int(session_id), max(0, int(after_id or 0)), safe_limit),
        ).fetchall()
        return [dict(row) for row in rows]


def request_human(
    session_id: int,
    *,
    reason: str,
    db_file: str | Path | None = None,
) -> bool:
    ensure_web_support_tables(db_file)
    now = _now()

    with sqlite3.connect(_db_path(db_file), timeout=15) as conn:
        cur = conn.execute(
            """
            UPDATE web_support_sessions
            SET status = 'waiting_human',
                ai_enabled = 0,
                handoff_reason = ?,
                human_requested_at = COALESCE(human_requested_at, ?),
                updated_at = ?
            WHERE id = ?
              AND status IN ('ai', 'waiting_human')
            """,
            (
                str(reason or "customer_requested")[:500],
                now,
                now,
                int(session_id),
            ),
        )
        conn.commit()
        return cur.rowcount > 0


def claim_session(
    session_id: int,
    *,
    staff_discord_id: str,
    staff_display_name: str,
    db_file: str | Path | None = None,
) -> bool:
    ensure_web_support_tables(db_file)
    now = _now()

    with sqlite3.connect(_db_path(db_file), timeout=15) as conn:
        cur = conn.execute(
            """
            UPDATE web_support_sessions
            SET status = 'human',
                ai_enabled = 0,
                claimed_at = COALESCE(claimed_at, ?),
                claimed_by_discord_id = COALESCE(claimed_by_discord_id, ?),
                claimed_by_display_name = COALESCE(claimed_by_display_name, ?),
                updated_at = ?
            WHERE id = ?
              AND status IN ('waiting_human', 'human')
            """,
            (
                now,
                str(staff_discord_id),
                str(staff_display_name)[:200],
                now,
                int(session_id),
            ),
        )
        conn.commit()
        return cur.rowcount > 0


def close_session(
    session_id: int,
    *,
    db_file: str | Path | None = None,
) -> bool:
    ensure_web_support_tables(db_file)
    now = _now()

    with sqlite3.connect(_db_path(db_file), timeout=15) as conn:
        cur = conn.execute(
            """
            UPDATE web_support_sessions
            SET status = 'closed',
                ai_enabled = 0,
                closed_at = COALESCE(closed_at, ?),
                updated_at = ?
            WHERE id = ?
              AND status != 'closed'
            """,
            (now, now, int(session_id)),
        )
        conn.commit()
        return cur.rowcount > 0


def set_discord_bridge(
    session_id: int,
    *,
    channel_id: str | int,
    thread_id: str | int,
    notification_message_id: str | int,
    db_file: str | Path | None = None,
) -> None:
    ensure_web_support_tables(db_file)

    with sqlite3.connect(_db_path(db_file), timeout=15) as conn:
        conn.execute(
            """
            UPDATE web_support_sessions
            SET discord_channel_id = ?,
                discord_thread_id = ?,
                discord_notification_message_id = ?,
                updated_at = ?
            WHERE id = ?
            """,
            (
                str(channel_id),
                str(thread_id),
                str(notification_message_id),
                _now(),
                int(session_id),
            ),
        )
        conn.commit()


def list_pending_handoffs(
    *,
    limit: int = 100,
    db_file: str | Path | None = None,
) -> list[dict[str, Any]]:
    ensure_web_support_tables(db_file)
    safe_limit = max(1, min(int(limit or 100), 500))

    with sqlite3.connect(_db_path(db_file), timeout=15) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            """
            SELECT *
            FROM web_support_sessions
            WHERE status = 'waiting_human'
              AND (
                    discord_thread_id IS NULL
                    OR discord_thread_id = ''
              )
            ORDER BY human_requested_at ASC, id ASC
            LIMIT ?
            """,
            (safe_limit,),
        ).fetchall()
        return [dict(row) for row in rows]


def get_session_by_thread_id(
    thread_id: str | int,
    *,
    db_file: str | Path | None = None,
) -> dict[str, Any] | None:
    ensure_web_support_tables(db_file)

    with sqlite3.connect(_db_path(db_file), timeout=15) as conn:
        conn.row_factory = sqlite3.Row
        return _row(
            conn.execute(
                """
                SELECT *
                FROM web_support_sessions
                WHERE discord_thread_id = ?
                  AND status IN ('waiting_human', 'human')
                LIMIT 1
                """,
                (str(thread_id),),
            ).fetchone()
        )


def get_session_by_notification_message(
    message_id: str | int,
    *,
    db_file: str | Path | None = None,
) -> dict[str, Any] | None:
    ensure_web_support_tables(db_file)

    with sqlite3.connect(_db_path(db_file), timeout=15) as conn:
        conn.row_factory = sqlite3.Row
        return _row(
            conn.execute(
                """
                SELECT *
                FROM web_support_sessions
                WHERE discord_notification_message_id = ?
                LIMIT 1
                """,
                (str(message_id),),
            ).fetchone()
        )


def recent_customer_text(
    session_id: int,
    *,
    limit: int = 8,
    db_file: str | Path | None = None,
) -> list[dict[str, Any]]:
    ensure_web_support_tables(db_file)

    with sqlite3.connect(_db_path(db_file), timeout=15) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            """
            SELECT sender_type, body, created_at
            FROM web_support_messages
            WHERE session_id = ?
              AND sender_type IN ('customer', 'ai', 'staff')
            ORDER BY id DESC
            LIMIT ?
            """,
            (int(session_id), max(1, min(int(limit or 8), 30))),
        ).fetchall()
        return [dict(row) for row in reversed(rows)]
