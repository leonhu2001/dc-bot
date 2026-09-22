from __future__ import annotations

import sqlite3
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any

TAIPEI_TZ = timezone(timedelta(hours=8))

PAYMENT_REVIEW_PENDING = "pending_review"
PAYMENT_REVIEW_APPROVED = "approved_pending_apply"
PAYMENT_REVIEW_APPLIED = "applied"
PAYMENT_REVIEW_REJECTED = "rejected"
PAYMENT_REVIEW_APPLY_ERROR = "apply_error"

SOURCE_LABELS = {
    "order": "點單",
    "worker_tip": "🍗 雞腿",
}


def _db_path(db_file: str | Path | None = None) -> Path:
    if db_file is not None:
        return Path(db_file)
    return Path(__file__).resolve().parents[1] / "web_dashboard.db"


def _now_iso() -> str:
    return datetime.now(TAIPEI_TZ).isoformat(timespec="seconds")


def ensure_payment_review_tables(db_file: str | Path | None = None) -> None:
    path = _db_path(db_file)
    with sqlite3.connect(path, timeout=15) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS payment_reviews (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                review_no TEXT UNIQUE,
                source_type TEXT NOT NULL,
                source_id TEXT NOT NULL,
                ticket_channel_id TEXT,
                customer_discord_id TEXT NOT NULL,
                customer_display_name TEXT,
                target_discord_id TEXT,
                target_display_name TEXT,
                amount INTEGER NOT NULL,
                payment_method TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending_review',
                discord_notification_message_id TEXT,
                approved_at TEXT,
                approved_by_discord_id TEXT,
                approved_by_display_name TEXT,
                rejected_at TEXT,
                rejected_by_discord_id TEXT,
                rejected_by_display_name TEXT,
                rejected_reason TEXT,
                applied_at TEXT,
                apply_error TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_payment_reviews_status
            ON payment_reviews(status, id ASC)
            """
        )
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_payment_reviews_source
            ON payment_reviews(source_type, source_id, id DESC)
            """
        )
        conn.commit()


def _review_no(row_id: int, now: datetime | None = None) -> str:
    now = now or datetime.now(TAIPEI_TZ)
    return f"PAY-{now.strftime('%Y%m%d')}-{int(row_id):04d}"


def create_payment_review(
    *,
    source_type: str,
    source_id: str | int,
    ticket_channel_id: str | int | None,
    customer_discord_id: str | int,
    customer_display_name: str | None,
    amount: int,
    payment_method: str,
    target_discord_id: str | int | None = None,
    target_display_name: str | None = None,
    db_file: str | Path | None = None,
) -> dict[str, Any]:
    ensure_payment_review_tables(db_file)

    source_type = str(source_type or "").strip()
    if source_type not in SOURCE_LABELS:
        raise ValueError("不支援的付款審核類型。")

    source_id_text = str(source_id or "").strip()
    if not source_id_text:
        raise ValueError("付款審核缺少來源編號。")

    amount = int(amount or 0)
    if amount <= 0:
        raise ValueError("付款審核金額必須大於 0。")

    payment_method = str(payment_method or "").strip()
    if payment_method not in {"街口", "轉帳"}:
        raise ValueError("只有街口或轉帳需要付款審核。")

    path = _db_path(db_file)
    now = datetime.now(TAIPEI_TZ)
    now_text = now.isoformat(timespec="seconds")

    with sqlite3.connect(path, timeout=15) as conn:
        conn.row_factory = sqlite3.Row
        conn.execute("BEGIN IMMEDIATE")

        existing = conn.execute(
            """
            SELECT *
            FROM payment_reviews
            WHERE source_type = ?
              AND source_id = ?
              AND status IN ('pending_review', 'approved_pending_apply')
            ORDER BY id DESC
            LIMIT 1
            """,
            (source_type, source_id_text),
        ).fetchone()

        if existing is not None:
            conn.commit()
            return dict(existing)

        cur = conn.execute(
            """
            INSERT INTO payment_reviews (
                source_type,
                source_id,
                ticket_channel_id,
                customer_discord_id,
                customer_display_name,
                target_discord_id,
                target_display_name,
                amount,
                payment_method,
                status,
                created_at,
                updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending_review', ?, ?)
            """,
            (
                source_type,
                source_id_text,
                str(ticket_channel_id) if ticket_channel_id is not None else None,
                str(customer_discord_id),
                str(customer_display_name or "").strip() or None,
                str(target_discord_id) if target_discord_id is not None else None,
                str(target_display_name or "").strip() or None,
                amount,
                payment_method,
                now_text,
                now_text,
            ),
        )
        row_id = int(cur.lastrowid)
        review_no = _review_no(row_id, now)
        conn.execute(
            "UPDATE payment_reviews SET review_no = ? WHERE id = ?",
            (review_no, row_id),
        )
        conn.commit()

        row = conn.execute(
            "SELECT * FROM payment_reviews WHERE id = ?",
            (row_id,),
        ).fetchone()
        return dict(row)


def set_payment_review_notification(
    review_id: int,
    message_id: str | int,
    *,
    db_file: str | Path | None = None,
) -> None:
    ensure_payment_review_tables(db_file)
    with sqlite3.connect(_db_path(db_file), timeout=15) as conn:
        conn.execute(
            """
            UPDATE payment_reviews
            SET discord_notification_message_id = ?,
                updated_at = ?
            WHERE id = ?
            """,
            (str(message_id), _now_iso(), int(review_id)),
        )
        conn.commit()


def list_payment_reviews(
    *,
    status: str | None = None,
    limit: int = 300,
    db_file: str | Path | None = None,
) -> list[dict[str, Any]]:
    ensure_payment_review_tables(db_file)
    safe_limit = max(1, min(int(limit or 300), 1000))

    with sqlite3.connect(_db_path(db_file), timeout=15) as conn:
        conn.row_factory = sqlite3.Row
        if status:
            rows = conn.execute(
                """
                SELECT *
                FROM payment_reviews
                WHERE status = ?
                ORDER BY id DESC
                LIMIT ?
                """,
                (str(status), safe_limit),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM payment_reviews ORDER BY id DESC LIMIT ?",
                (safe_limit,),
            ).fetchall()
        return [dict(row) for row in rows]


def get_payment_review(
    review_id: int,
    *,
    db_file: str | Path | None = None,
) -> dict[str, Any] | None:
    ensure_payment_review_tables(db_file)
    with sqlite3.connect(_db_path(db_file), timeout=15) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT * FROM payment_reviews WHERE id = ?",
            (int(review_id),),
        ).fetchone()
        return dict(row) if row else None


def approve_payment_review(
    review_id: int,
    *,
    operator_discord_id: str | int,
    operator_display_name: str | None,
    db_file: str | Path | None = None,
) -> dict[str, Any]:
    ensure_payment_review_tables(db_file)
    now = _now_iso()

    with sqlite3.connect(_db_path(db_file), timeout=15) as conn:
        conn.row_factory = sqlite3.Row
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute(
            "SELECT * FROM payment_reviews WHERE id = ?",
            (int(review_id),),
        ).fetchone()

        if row is None:
            raise ValueError("找不到這筆付款審核。")
        if str(row["status"]) != PAYMENT_REVIEW_PENDING:
            raise ValueError("只有待審核付款可以核准。")

        conn.execute(
            """
            UPDATE payment_reviews
            SET status = ?,
                approved_at = ?,
                approved_by_discord_id = ?,
                approved_by_display_name = ?,
                apply_error = NULL,
                updated_at = ?
            WHERE id = ?
            """,
            (
                PAYMENT_REVIEW_APPROVED,
                now,
                str(operator_discord_id),
                str(operator_display_name or "").strip() or None,
                now,
                int(review_id),
            ),
        )
        conn.commit()
        result = conn.execute(
            "SELECT * FROM payment_reviews WHERE id = ?",
            (int(review_id),),
        ).fetchone()
        return dict(result)


def reject_payment_review(
    review_id: int,
    *,
    operator_discord_id: str | int,
    operator_display_name: str | None,
    reason: str | None,
    db_file: str | Path | None = None,
) -> dict[str, Any]:
    ensure_payment_review_tables(db_file)
    now = _now_iso()

    with sqlite3.connect(_db_path(db_file), timeout=15) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT * FROM payment_reviews WHERE id = ?",
            (int(review_id),),
        ).fetchone()

        if row is None:
            raise ValueError("找不到這筆付款審核。")
        if str(row["status"]) not in {
            PAYMENT_REVIEW_PENDING,
            PAYMENT_REVIEW_APPLY_ERROR,
        }:
            raise ValueError("這筆付款審核目前不能駁回。")

        conn.execute(
            """
            UPDATE payment_reviews
            SET status = ?,
                rejected_at = ?,
                rejected_by_discord_id = ?,
                rejected_by_display_name = ?,
                rejected_reason = ?,
                updated_at = ?
            WHERE id = ?
            """,
            (
                PAYMENT_REVIEW_REJECTED,
                now,
                str(operator_discord_id),
                str(operator_display_name or "").strip() or None,
                str(reason or "").strip() or "客服駁回",
                now,
                int(review_id),
            ),
        )
        conn.commit()
        result = conn.execute(
            "SELECT * FROM payment_reviews WHERE id = ?",
            (int(review_id),),
        ).fetchone()
        return dict(result)


def list_payment_reviews_for_runtime(
    *,
    statuses: tuple[str, ...] = (
        PAYMENT_REVIEW_APPROVED,
        PAYMENT_REVIEW_REJECTED,
    ),
    limit: int = 30,
    db_file: str | Path | None = None,
) -> list[dict[str, Any]]:
    ensure_payment_review_tables(db_file)
    placeholders = ",".join("?" for _ in statuses)

    with sqlite3.connect(_db_path(db_file), timeout=15) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            f"""
            SELECT *
            FROM payment_reviews
            WHERE status IN ({placeholders})
              AND applied_at IS NULL
            ORDER BY id ASC
            LIMIT ?
            """,
            [*statuses, max(1, min(int(limit or 30), 100))],
        ).fetchall()
        return [dict(row) for row in rows]


def mark_payment_review_applied(
    review_id: int,
    *,
    db_file: str | Path | None = None,
) -> None:
    ensure_payment_review_tables(db_file)
    now = _now_iso()
    with sqlite3.connect(_db_path(db_file), timeout=15) as conn:
        conn.execute(
            """
            UPDATE payment_reviews
            SET status = ?,
                applied_at = ?,
                apply_error = NULL,
                updated_at = ?
            WHERE id = ?
            """,
            (PAYMENT_REVIEW_APPLIED, now, now, int(review_id)),
        )
        conn.commit()


def mark_payment_review_rejection_applied(
    review_id: int,
    *,
    db_file: str | Path | None = None,
) -> None:
    ensure_payment_review_tables(db_file)
    now = _now_iso()
    with sqlite3.connect(_db_path(db_file), timeout=15) as conn:
        conn.execute(
            """
            UPDATE payment_reviews
            SET applied_at = ?,
                apply_error = NULL,
                updated_at = ?
            WHERE id = ?
            """,
            (now, now, int(review_id)),
        )
        conn.commit()


def retry_payment_review_apply(
    review_id: int,
    *,
    db_file: str | Path | None = None,
) -> dict[str, Any]:
    ensure_payment_review_tables(db_file)
    now = _now_iso()

    with sqlite3.connect(_db_path(db_file), timeout=15) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT * FROM payment_reviews WHERE id = ?",
            (int(review_id),),
        ).fetchone()

        if row is None:
            raise ValueError("找不到這筆付款審核。")
        if str(row["status"]) != PAYMENT_REVIEW_APPLY_ERROR:
            raise ValueError("只有套用失敗的付款可以重新套用。")

        conn.execute(
            """
            UPDATE payment_reviews
            SET status = ?,
                apply_error = NULL,
                updated_at = ?
            WHERE id = ?
            """,
            (
                PAYMENT_REVIEW_APPROVED,
                now,
                int(review_id),
            ),
        )
        conn.commit()

        result = conn.execute(
            "SELECT * FROM payment_reviews WHERE id = ?",
            (int(review_id),),
        ).fetchone()
        return dict(result)


def mark_payment_review_apply_error(
    review_id: int,
    error: str,
    *,
    db_file: str | Path | None = None,
) -> None:
    ensure_payment_review_tables(db_file)
    with sqlite3.connect(_db_path(db_file), timeout=15) as conn:
        conn.execute(
            """
            UPDATE payment_reviews
            SET status = ?,
                apply_error = ?,
                updated_at = ?
            WHERE id = ?
            """,
            (
                PAYMENT_REVIEW_APPLY_ERROR,
                str(error or "")[:1500],
                _now_iso(),
                int(review_id),
            ),
        )
        conn.commit()


def source_label(value: str | None) -> str:
    text = str(value or "").strip()
    return SOURCE_LABELS.get(text, text or "未知")
