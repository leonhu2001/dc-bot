from __future__ import annotations

import sqlite3
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any

TAIPEI_TZ = timezone(timedelta(hours=8))

PENDING_REVIEW = "pending_review"
APPROVED_PENDING_APPLY = "approved_pending_apply"
REJECTED_PENDING_APPLY = "rejected_pending_apply"
PROCESSING = "processing"
COMPLETED = "completed"
REJECTED = "rejected"
FAILED = "failed"


def _now_iso() -> str:
    return datetime.now(TAIPEI_TZ).isoformat(timespec="seconds")


def _db_path(db_file: str | Path | None = None) -> Path:
    if db_file is not None:
        return Path(db_file)
    return Path(__file__).resolve().parents[1] / "web_dashboard.db"


def ensure_payment_review_tables(db_file: str | Path | None = None) -> None:
    path = _db_path(db_file)
    with sqlite3.connect(path, timeout=15) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS payment_reviews (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                review_no TEXT UNIQUE,
                review_type TEXT NOT NULL,
                reference_id INTEGER NOT NULL,
                order_id INTEGER,
                ticket_channel_id TEXT,
                customer_discord_id TEXT NOT NULL,
                customer_display_name TEXT,
                amount INTEGER NOT NULL,
                payment_method TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending_review',
                submitted_at TEXT,
                approved_at TEXT,
                approved_by_discord_id TEXT,
                approved_by_display_name TEXT,
                rejected_at TEXT,
                rejected_by_discord_id TEXT,
                rejected_by_display_name TEXT,
                rejected_reason TEXT,
                applied_at TEXT,
                retry_count INTEGER NOT NULL DEFAULT 0,
                last_error TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS idx_payment_reviews_source
            ON payment_reviews(review_type, reference_id)
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
            CREATE INDEX IF NOT EXISTS idx_payment_reviews_ticket
            ON payment_reviews(ticket_channel_id, id DESC)
            """
        )
        conn.commit()


def _make_review_no(review_type: str, row_id: int, now: datetime | None = None) -> str:
    now = now or datetime.now(TAIPEI_TZ)
    prefix = "ORDERPAY" if str(review_type) == "order" else "TIPPAY"
    return f"{prefix}-{now.strftime('%Y%m%d')}-{int(row_id):04d}"


def create_or_resubmit_payment_review(
    *,
    review_type: str,
    reference_id: int,
    order_id: int | None,
    ticket_channel_id: str | int | None,
    customer_discord_id: str | int,
    customer_display_name: str | None,
    amount: int,
    payment_method: str,
    db_file: str | Path | None = None,
) -> dict[str, Any]:
    ensure_payment_review_tables(db_file)

    review_type = str(review_type or "").strip().lower()
    if review_type not in {"order", "tip"}:
        raise ValueError("不支援的付款審核類型。")

    reference_id = int(reference_id)
    amount = int(amount or 0)
    if reference_id <= 0:
        raise ValueError("付款審核來源資料異常。")
    if amount <= 0:
        raise ValueError("付款金額必須大於 0。")

    method = str(payment_method or "").strip()
    if method not in {"街口", "轉帳"}:
        raise ValueError("只有街口或轉帳需要網站審核。")

    path = _db_path(db_file)
    now = datetime.now(TAIPEI_TZ)
    now_text = now.isoformat(timespec="seconds")

    with sqlite3.connect(path, timeout=15) as conn:
        conn.row_factory = sqlite3.Row
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute(
            """
            SELECT *
            FROM payment_reviews
            WHERE review_type = ? AND reference_id = ?
            LIMIT 1
            """,
            (review_type, reference_id),
        ).fetchone()

        if row is None:
            cur = conn.execute(
                """
                INSERT INTO payment_reviews (
                    review_type,
                    reference_id,
                    order_id,
                    ticket_channel_id,
                    customer_discord_id,
                    customer_display_name,
                    amount,
                    payment_method,
                    status,
                    submitted_at,
                    created_at,
                    updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'pending_review', ?, ?, ?)
                """,
                (
                    review_type,
                    reference_id,
                    int(order_id) if order_id is not None else None,
                    str(ticket_channel_id) if ticket_channel_id is not None else None,
                    str(customer_discord_id),
                    str(customer_display_name or "").strip() or None,
                    amount,
                    method,
                    now_text,
                    now_text,
                    now_text,
                ),
            )
            row_id = int(cur.lastrowid)
            review_no = _make_review_no(review_type, row_id, now)
            conn.execute(
                "UPDATE payment_reviews SET review_no = ? WHERE id = ?",
                (review_no, row_id),
            )
        else:
            status = str(row["status"] or "")
            if status in {PENDING_REVIEW, APPROVED_PENDING_APPLY, PROCESSING}:
                raise ValueError("這筆付款已經在審核中，請勿重複送出。")
            if status == COMPLETED:
                raise ValueError("這筆付款已完成審核。")

            row_id = int(row["id"])
            conn.execute(
                """
                UPDATE payment_reviews
                SET order_id = ?,
                    ticket_channel_id = ?,
                    customer_discord_id = ?,
                    customer_display_name = ?,
                    amount = ?,
                    payment_method = ?,
                    status = 'pending_review',
                    submitted_at = ?,
                    approved_at = NULL,
                    approved_by_discord_id = NULL,
                    approved_by_display_name = NULL,
                    rejected_at = NULL,
                    rejected_by_discord_id = NULL,
                    rejected_by_display_name = NULL,
                    rejected_reason = NULL,
                    applied_at = NULL,
                    retry_count = 0,
                    last_error = NULL,
                    updated_at = ?
                WHERE id = ?
                """,
                (
                    int(order_id) if order_id is not None else None,
                    str(ticket_channel_id) if ticket_channel_id is not None else None,
                    str(customer_discord_id),
                    str(customer_display_name or "").strip() or None,
                    amount,
                    method,
                    now_text,
                    now_text,
                    row_id,
                ),
            )

        conn.commit()
        result = conn.execute(
            "SELECT * FROM payment_reviews WHERE id = ?",
            (row_id,),
        ).fetchone()
        return dict(result)


def list_payment_reviews(
    *,
    status: str | None = None,
    limit: int = 300,
    db_file: str | Path | None = None,
) -> list[dict[str, Any]]:
    ensure_payment_review_tables(db_file)
    path = _db_path(db_file)
    safe_limit = max(1, min(int(limit or 300), 500))
    with sqlite3.connect(path, timeout=15) as conn:
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
    db_file: str | Path | None = None,
) -> dict[str, Any] | None:
    ensure_payment_review_tables(db_file)
    path = _db_path(db_file)
    with sqlite3.connect(path, timeout=15) as conn:
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
    path = _db_path(db_file)
    now = _now_iso()
    with sqlite3.connect(path, timeout=15) as conn:
        conn.row_factory = sqlite3.Row
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute(
            "SELECT * FROM payment_reviews WHERE id = ?",
            (int(review_id),),
        ).fetchone()
        if row is None:
            raise ValueError("找不到這筆付款審核。")
        if str(row["status"] or "") != PENDING_REVIEW:
            raise ValueError("只有等待審核的付款可以核准。")

        conn.execute(
            """
            UPDATE payment_reviews
            SET status = 'approved_pending_apply',
                approved_at = ?,
                approved_by_discord_id = ?,
                approved_by_display_name = ?,
                rejected_at = NULL,
                rejected_by_discord_id = NULL,
                rejected_by_display_name = NULL,
                rejected_reason = NULL,
                last_error = NULL,
                updated_at = ?
            WHERE id = ?
            """,
            (
                now,
                str(operator_discord_id),
                str(operator_display_name or "").strip() or None,
                now,
                int(review_id),
            ),
        )
        conn.commit()
        return dict(
            conn.execute(
                "SELECT * FROM payment_reviews WHERE id = ?",
                (int(review_id),),
            ).fetchone()
        )


def reject_payment_review(
    review_id: int,
    *,
    operator_discord_id: str | int,
    operator_display_name: str | None,
    reason: str | None,
    db_file: str | Path | None = None,
) -> dict[str, Any]:
    ensure_payment_review_tables(db_file)
    path = _db_path(db_file)
    now = _now_iso()
    with sqlite3.connect(path, timeout=15) as conn:
        conn.row_factory = sqlite3.Row
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute(
            "SELECT * FROM payment_reviews WHERE id = ?",
            (int(review_id),),
        ).fetchone()
        if row is None:
            raise ValueError("找不到這筆付款審核。")
        if str(row["status"] or "") != PENDING_REVIEW:
            raise ValueError("只有等待審核的付款可以駁回。")

        conn.execute(
            """
            UPDATE payment_reviews
            SET status = 'rejected_pending_apply',
                rejected_at = ?,
                rejected_by_discord_id = ?,
                rejected_by_display_name = ?,
                rejected_reason = ?,
                approved_at = NULL,
                approved_by_discord_id = NULL,
                approved_by_display_name = NULL,
                last_error = NULL,
                updated_at = ?
            WHERE id = ?
            """,
            (
                now,
                str(operator_discord_id),
                str(operator_display_name or "").strip() or None,
                str(reason or "").strip() or "客服駁回",
                now,
                int(review_id),
            ),
        )
        conn.commit()
        return dict(
            conn.execute(
                "SELECT * FROM payment_reviews WHERE id = ?",
                (int(review_id),),
            ).fetchone()
        )


def list_pending_payment_review_actions(
    *,
    limit: int = 20,
    db_file: str | Path | None = None,
) -> list[dict[str, Any]]:
    ensure_payment_review_tables(db_file)
    path = _db_path(db_file)
    safe_limit = max(1, min(int(limit or 20), 100))
    with sqlite3.connect(path, timeout=15) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            """
            SELECT *
            FROM payment_reviews
            WHERE status IN ('approved_pending_apply', 'rejected_pending_apply', 'processing')
            ORDER BY updated_at ASC, id ASC
            LIMIT ?
            """,
            (safe_limit,),
        ).fetchall()
        return [dict(row) for row in rows]


def mark_payment_review_processing(
    review_id: int,
    *,
    expected_status: str,
    db_file: str | Path | None = None,
) -> bool:
    ensure_payment_review_tables(db_file)
    path = _db_path(db_file)
    now = _now_iso()
    with sqlite3.connect(path, timeout=15) as conn:
        cur = conn.execute(
            """
            UPDATE payment_reviews
            SET status = 'processing',
                updated_at = ?
            WHERE id = ?
              AND status = ?
            """,
            (now, int(review_id), str(expected_status)),
        )
        conn.commit()
        return int(cur.rowcount or 0) == 1


def mark_payment_review_completed(
    review_id: int,
    db_file: str | Path | None = None,
) -> None:
    ensure_payment_review_tables(db_file)
    path = _db_path(db_file)
    now = _now_iso()
    with sqlite3.connect(path, timeout=15) as conn:
        conn.execute(
            """
            UPDATE payment_reviews
            SET status = 'completed',
                applied_at = ?,
                last_error = NULL,
                updated_at = ?
            WHERE id = ?
            """,
            (now, now, int(review_id)),
        )
        conn.commit()


def mark_payment_review_rejected_applied(
    review_id: int,
    db_file: str | Path | None = None,
) -> None:
    ensure_payment_review_tables(db_file)
    path = _db_path(db_file)
    now = _now_iso()
    with sqlite3.connect(path, timeout=15) as conn:
        conn.execute(
            """
            UPDATE payment_reviews
            SET status = 'rejected',
                applied_at = ?,
                last_error = NULL,
                updated_at = ?
            WHERE id = ?
            """,
            (now, now, int(review_id)),
        )
        conn.commit()


def mark_payment_review_apply_failed(
    review_id: int,
    *,
    original_pending_status: str,
    error_message: str,
    db_file: str | Path | None = None,
) -> None:
    ensure_payment_review_tables(db_file)
    path = _db_path(db_file)
    now = _now_iso()
    with sqlite3.connect(path, timeout=15) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT retry_count FROM payment_reviews WHERE id = ?",
            (int(review_id),),
        ).fetchone()
        retry_count = int(row["retry_count"] or 0) + 1 if row else 1
        next_status = FAILED if retry_count >= 5 else str(original_pending_status)
        conn.execute(
            """
            UPDATE payment_reviews
            SET status = ?,
                retry_count = ?,
                last_error = ?,
                updated_at = ?
            WHERE id = ?
            """,
            (
                next_status,
                retry_count,
                str(error_message or "")[:3000],
                now,
                int(review_id),
            ),
        )
        conn.commit()


def payment_review_status_label(value: str | None) -> str:
    return {
        PENDING_REVIEW: "待審核",
        APPROVED_PENDING_APPLY: "核准處理中",
        REJECTED_PENDING_APPLY: "駁回處理中",
        PROCESSING: "處理中",
        COMPLETED: "已完成",
        REJECTED: "已駁回",
        FAILED: "處理失敗",
    }.get(str(value or ""), str(value or "未知"))
