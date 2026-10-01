from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from statistics import median
from typing import Any

TAIPEI_TZ = timezone(timedelta(hours=8))
ACTIVE_SUPPORT_CALL_STATUSES = ("open", "claimed")


def _db_path(db_file: str | Path | None = None) -> Path:
    if db_file is not None:
        return Path(db_file)
    return Path(__file__).resolve().parents[1] / "web_dashboard.db"


def _now() -> datetime:
    return datetime.now(TAIPEI_TZ)


def _now_iso() -> str:
    return _now().isoformat(timespec="seconds")


def _parse_datetime(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None

    if text.endswith("Z"):
        text = text[:-1] + "+00:00"

    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None

    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=TAIPEI_TZ)

    return parsed.astimezone(TAIPEI_TZ)


def ensure_support_call_tables(db_file: str | Path | None = None) -> None:
    path = _db_path(db_file)

    with sqlite3.connect(path, timeout=15) as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS support_calls (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ticket_channel_id TEXT NOT NULL,
                customer_discord_id TEXT NOT NULL,
                customer_display_name TEXT,
                notification_message_id TEXT,
                status TEXT NOT NULL DEFAULT 'open',
                called_at TEXT NOT NULL,
                claimed_at TEXT,
                claimed_by_discord_id TEXT,
                claimed_by_display_name TEXT,
                resolved_at TEXT,
                resolved_by_discord_id TEXT,
                resolved_by_display_name TEXT,
                reminder_stage INTEGER NOT NULL DEFAULT 0,
                last_reminded_at TEXT,
                cancel_reason TEXT,
                updated_at TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_support_calls_ticket
                ON support_calls(ticket_channel_id, id DESC);

            CREATE INDEX IF NOT EXISTS idx_support_calls_status
                ON support_calls(status, called_at ASC);

            CREATE INDEX IF NOT EXISTS idx_support_calls_notification
                ON support_calls(notification_message_id);
            """
        )
        conn.commit()


def create_or_get_active_support_call(
    *,
    ticket_channel_id: str | int,
    customer_discord_id: str | int,
    customer_display_name: str | None,
    db_file: str | Path | None = None,
) -> tuple[dict[str, Any], bool]:
    ensure_support_call_tables(db_file)
    path = _db_path(db_file)
    now = _now_iso()

    with sqlite3.connect(path, timeout=15) as conn:
        conn.row_factory = sqlite3.Row
        conn.execute("BEGIN IMMEDIATE")

        existing = conn.execute(
            """
            SELECT *
            FROM support_calls
            WHERE ticket_channel_id = ?
              AND status IN ('open', 'claimed')
            ORDER BY id DESC
            LIMIT 1
            """,
            (str(ticket_channel_id),),
        ).fetchone()

        if existing is not None:
            conn.commit()
            return dict(existing), False

        cur = conn.execute(
            """
            INSERT INTO support_calls (
                ticket_channel_id,
                customer_discord_id,
                customer_display_name,
                status,
                called_at,
                updated_at
            )
            VALUES (?, ?, ?, 'open', ?, ?)
            """,
            (
                str(ticket_channel_id),
                str(customer_discord_id),
                str(customer_display_name or "").strip() or None,
                now,
                now,
            ),
        )
        call_id = int(cur.lastrowid)
        conn.commit()

        row = conn.execute(
            "SELECT * FROM support_calls WHERE id = ?",
            (call_id,),
        ).fetchone()
        return dict(row), True


def set_support_call_notification(
    call_id: int,
    notification_message_id: str | int,
    *,
    db_file: str | Path | None = None,
) -> None:
    ensure_support_call_tables(db_file)
    with sqlite3.connect(_db_path(db_file), timeout=15) as conn:
        conn.execute(
            """
            UPDATE support_calls
            SET notification_message_id = ?,
                updated_at = ?
            WHERE id = ?
            """,
            (str(notification_message_id), _now_iso(), int(call_id)),
        )
        conn.commit()


def cancel_support_call(
    call_id: int,
    reason: str,
    *,
    db_file: str | Path | None = None,
) -> None:
    ensure_support_call_tables(db_file)
    with sqlite3.connect(_db_path(db_file), timeout=15) as conn:
        conn.execute(
            """
            UPDATE support_calls
            SET status = 'cancelled',
                cancel_reason = ?,
                updated_at = ?
            WHERE id = ?
              AND status IN ('open', 'claimed')
            """,
            (str(reason or "")[:500], _now_iso(), int(call_id)),
        )
        conn.commit()


def get_support_call(
    call_id: int,
    *,
    db_file: str | Path | None = None,
) -> dict[str, Any] | None:
    ensure_support_call_tables(db_file)
    with sqlite3.connect(_db_path(db_file), timeout=15) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT * FROM support_calls WHERE id = ?",
            (int(call_id),),
        ).fetchone()
        return dict(row) if row else None


def get_support_call_by_notification(
    notification_message_id: str | int,
    *,
    db_file: str | Path | None = None,
) -> dict[str, Any] | None:
    ensure_support_call_tables(db_file)
    with sqlite3.connect(_db_path(db_file), timeout=15) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            """
            SELECT *
            FROM support_calls
            WHERE notification_message_id = ?
            ORDER BY id DESC
            LIMIT 1
            """,
            (str(notification_message_id),),
        ).fetchone()
        return dict(row) if row else None


def claim_support_call(
    call_id: int,
    *,
    staff_discord_id: str | int,
    staff_display_name: str | None,
    db_file: str | Path | None = None,
) -> tuple[dict[str, Any], bool]:
    ensure_support_call_tables(db_file)
    path = _db_path(db_file)
    now = _now_iso()

    with sqlite3.connect(path, timeout=15) as conn:
        conn.row_factory = sqlite3.Row
        conn.execute("BEGIN IMMEDIATE")

        row = conn.execute(
            "SELECT * FROM support_calls WHERE id = ?",
            (int(call_id),),
        ).fetchone()
        if row is None:
            conn.rollback()
            raise ValueError("找不到這筆客服呼叫。")

        current = dict(row)
        if str(current.get("status") or "") != "open":
            conn.commit()
            return current, False

        cur = conn.execute(
            """
            UPDATE support_calls
            SET status = 'claimed',
                claimed_at = ?,
                claimed_by_discord_id = ?,
                claimed_by_display_name = ?,
                updated_at = ?
            WHERE id = ?
              AND status = 'open'
            """,
            (
                now,
                str(staff_discord_id),
                str(staff_display_name or "").strip() or None,
                now,
                int(call_id),
            ),
        )
        changed = int(cur.rowcount or 0) == 1
        conn.commit()

        latest = conn.execute(
            "SELECT * FROM support_calls WHERE id = ?",
            (int(call_id),),
        ).fetchone()
        return dict(latest), changed


def resolve_support_call(
    call_id: int,
    *,
    staff_discord_id: str | int,
    staff_display_name: str | None,
    db_file: str | Path | None = None,
) -> tuple[dict[str, Any], bool]:
    ensure_support_call_tables(db_file)
    path = _db_path(db_file)
    now = _now_iso()

    with sqlite3.connect(path, timeout=15) as conn:
        conn.row_factory = sqlite3.Row
        conn.execute("BEGIN IMMEDIATE")

        row = conn.execute(
            "SELECT * FROM support_calls WHERE id = ?",
            (int(call_id),),
        ).fetchone()
        if row is None:
            conn.rollback()
            raise ValueError("找不到這筆客服呼叫。")

        current = dict(row)
        if str(current.get("status") or "") != "claimed":
            conn.commit()
            return current, False

        cur = conn.execute(
            """
            UPDATE support_calls
            SET status = 'resolved',
                resolved_at = ?,
                resolved_by_discord_id = ?,
                resolved_by_display_name = ?,
                updated_at = ?
            WHERE id = ?
              AND status = 'claimed'
            """,
            (
                now,
                str(staff_discord_id),
                str(staff_display_name or "").strip() or None,
                now,
                int(call_id),
            ),
        )
        changed = int(cur.rowcount or 0) == 1
        conn.commit()

        latest = conn.execute(
            "SELECT * FROM support_calls WHERE id = ?",
            (int(call_id),),
        ).fetchone()
        return dict(latest), changed


def list_active_support_calls(
    *,
    db_file: str | Path | None = None,
    limit: int = 200,
) -> list[dict[str, Any]]:
    ensure_support_call_tables(db_file)
    safe_limit = max(1, min(int(limit or 200), 1000))

    with sqlite3.connect(_db_path(db_file), timeout=15) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            """
            SELECT *
            FROM support_calls
            WHERE status IN ('open', 'claimed')
            ORDER BY called_at ASC, id ASC
            LIMIT ?
            """,
            (safe_limit,),
        ).fetchall()
        return [dict(row) for row in rows]


def mark_support_call_reminder(
    call_id: int,
    stage: int,
    *,
    db_file: str | Path | None = None,
) -> bool:
    ensure_support_call_tables(db_file)
    stage = max(0, int(stage))
    now = _now_iso()

    with sqlite3.connect(_db_path(db_file), timeout=15) as conn:
        cur = conn.execute(
            """
            UPDATE support_calls
            SET reminder_stage = ?,
                last_reminded_at = ?,
                updated_at = ?
            WHERE id = ?
              AND status = 'open'
              AND reminder_stage < ?
            """,
            (stage, now, now, int(call_id), stage),
        )
        conn.commit()
        return int(cur.rowcount or 0) == 1


def _response_seconds(row: dict[str, Any]) -> int | None:
    called = _parse_datetime(row.get("called_at"))
    claimed = _parse_datetime(row.get("claimed_at"))
    if called is None or claimed is None:
        return None
    return max(0, int((claimed - called).total_seconds()))


def _duration_text(seconds: int | None) -> str:
    if seconds is None:
        return "-"
    seconds = max(0, int(seconds))
    minutes, secs = divmod(seconds, 60)
    if minutes < 60:
        return f"{minutes} 分 {secs} 秒"
    hours, minutes = divmod(minutes, 60)
    return f"{hours} 小時 {minutes} 分"


def build_support_call_snapshot(
    *,
    db_file: str | Path | None = None,
    days: int = 30,
    limit: int = 300,
) -> dict[str, Any]:
    ensure_support_call_tables(db_file)
    safe_days = max(1, min(int(days or 30), 365))
    safe_limit = max(20, min(int(limit or 300), 1000))
    cutoff = _now() - timedelta(days=safe_days)

    with sqlite3.connect(_db_path(db_file), timeout=15) as conn:
        conn.row_factory = sqlite3.Row
        rows = [
            dict(row)
            for row in conn.execute(
                """
                SELECT *
                FROM support_calls
                ORDER BY id DESC
                LIMIT ?
                """,
                (safe_limit,),
            ).fetchall()
        ]

    active = [
        row
        for row in rows
        if str(row.get("status") or "") in ACTIVE_SUPPORT_CALL_STATUSES
    ]

    recent = []
    for row in rows:
        called = _parse_datetime(row.get("called_at"))
        if called is not None and called >= cutoff:
            recent.append(row)

    responses = [
        value
        for value in (_response_seconds(row) for row in recent)
        if value is not None
    ]

    within_5 = sum(1 for value in responses if value <= 300)
    average_seconds = (
        int(round(sum(responses) / len(responses)))
        if responses
        else None
    )
    median_seconds = (
        int(round(median(responses)))
        if responses
        else None
    )

    now = _now()
    for row in rows:
        called = _parse_datetime(row.get("called_at"))
        age_seconds = (
            max(0, int((now - called).total_seconds()))
            if called is not None
            else None
        )
        row["age_seconds"] = age_seconds
        row["age_text"] = _duration_text(age_seconds)
        response = _response_seconds(row)
        row["response_seconds"] = response
        row["response_text"] = _duration_text(response)

    return {
        "days": safe_days,
        "checked_at": now.strftime("%Y/%m/%d %H:%M:%S"),
        "active_count": len(active),
        "open_count": sum(
            1 for row in active if str(row.get("status") or "") == "open"
        ),
        "claimed_count": sum(
            1 for row in active if str(row.get("status") or "") == "claimed"
        ),
        "recent_count": len(recent),
        "response_count": len(responses),
        "within_5_count": within_5,
        "within_5_rate": (
            round(within_5 * 100 / len(responses), 1)
            if responses
            else None
        ),
        "average_response_seconds": average_seconds,
        "average_response_text": _duration_text(average_seconds),
        "median_response_seconds": median_seconds,
        "median_response_text": _duration_text(median_seconds),
        "rows": rows,
    }
