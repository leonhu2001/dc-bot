from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

from core.time_utils import get_taipei_now_iso
from services.wallet_service import get_wallet_balance_breakdown


PENDING = "pending"
PROCESSING = "processing"
COMPLETED = "completed"
FAILED = "failed"
DEFAULT_STALE_PROCESSING_MINUTES = 10


def _db_path(db_file: str | Path | None = None) -> Path:
    if db_file is not None:
        return Path(db_file)
    return Path(__file__).resolve().parents[1] / "bot.db"


def ensure_wallet_refund_tables(db_file: str | Path | None = None) -> None:
    path = _db_path(db_file)
    with sqlite3.connect(path, timeout=15) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS wallet_refund_requests (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                customer_discord_id TEXT NOT NULL,
                amount INTEGER NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                requested_by_discord_id TEXT,
                requested_by_display_name TEXT,
                note TEXT,
                wallet_transaction_id INTEGER,
                wallet_debit_amount INTEGER NOT NULL DEFAULT 0,
                bonus_offset_applied INTEGER NOT NULL DEFAULT 0,
                bonus_reversal_transaction_id INTEGER,
                bonus_revoked_amount INTEGER NOT NULL DEFAULT 0,
                vip_total_before INTEGER,
                vip_total_after INTEGER,
                vip_level_before TEXT,
                vip_level_after TEXT,
                created_at TEXT NOT NULL,
                processing_at TEXT,
                completed_at TEXT,
                failed_at TEXT,
                error_message TEXT,
                updated_at TEXT NOT NULL
            )
            """
        )
        columns = {
            str(row[1])
            for row in conn.execute("PRAGMA table_info(wallet_refund_requests)").fetchall()
        }
        if "wallet_debit_amount" not in columns:
            conn.execute(
                "ALTER TABLE wallet_refund_requests "
                "ADD COLUMN wallet_debit_amount INTEGER NOT NULL DEFAULT 0"
            )
        if "bonus_offset_applied" not in columns:
            conn.execute(
                "ALTER TABLE wallet_refund_requests "
                "ADD COLUMN bonus_offset_applied INTEGER NOT NULL DEFAULT 0"
            )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_wallet_refunds_status "
            "ON wallet_refund_requests(status, id ASC)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_wallet_refunds_customer "
            "ON wallet_refund_requests(customer_discord_id, id DESC)"
        )
        conn.commit()


def create_wallet_refund_request(
    *,
    customer_discord_id: str | int,
    amount: int,
    requested_by_discord_id: str | int | None,
    requested_by_display_name: str | None,
    note: str | None = None,
    db_file: str | Path | None = None,
) -> dict[str, Any]:
    ensure_wallet_refund_tables(db_file)
    amount = int(amount or 0)
    if amount <= 0:
        raise ValueError("退款金額必須大於 0。")

    breakdown = get_wallet_balance_breakdown(customer_discord_id, db_file)
    refundable = int(breakdown.get("refundable_balance") or 0)
    if amount > refundable:
        raise ValueError(
            f"目前最多可實退 {refundable:,}T；已使用但尚未由本金消費沖抵的贈額，會先從退款額度扣除。"
        )

    path = _db_path(db_file)
    now_text = get_taipei_now_iso()
    with sqlite3.connect(path, timeout=15) as conn:
        conn.row_factory = sqlite3.Row
        conn.execute("BEGIN IMMEDIATE")
        existing = conn.execute(
            """
            SELECT id
            FROM wallet_refund_requests
            WHERE customer_discord_id=?
              AND status IN ('pending', 'processing')
            LIMIT 1
            """,
            (str(customer_discord_id),),
        ).fetchone()
        if existing is not None:
            raise ValueError("此會員已有退款正在處理，請完成後再建立下一筆。")

        cur = conn.execute(
            """
            INSERT INTO wallet_refund_requests (
                customer_discord_id, amount, status,
                requested_by_discord_id, requested_by_display_name,
                note, created_at, updated_at
            ) VALUES (?, ?, 'pending', ?, ?, ?, ?, ?)
            """,
            (
                str(customer_discord_id),
                amount,
                str(requested_by_discord_id) if requested_by_discord_id else None,
                str(requested_by_display_name or "").strip() or None,
                str(note or "").strip() or None,
                now_text,
                now_text,
            ),
        )
        request_id = int(cur.lastrowid)
        conn.commit()
        row = conn.execute(
            "SELECT * FROM wallet_refund_requests WHERE id=?",
            (request_id,),
        ).fetchone()
        return dict(row)


def list_pending_wallet_refunds(
    *,
    limit: int = 20,
    stale_processing_minutes: int = DEFAULT_STALE_PROCESSING_MINUTES,
    db_file: str | Path | None = None,
) -> list[dict[str, Any]]:
    """Return queued refunds after reclaiming abandoned processing leases."""
    ensure_wallet_refund_tables(db_file)
    path = _db_path(db_file)
    safe_limit = max(1, min(int(limit or 20), 100))
    stale_minutes = max(1, int(stale_processing_minutes or DEFAULT_STALE_PROCESSING_MINUTES))
    now_text = get_taipei_now_iso()

    with sqlite3.connect(path, timeout=15) as conn:
        conn.row_factory = sqlite3.Row
        conn.execute("BEGIN IMMEDIATE")
        conn.execute(
            """
            UPDATE wallet_refund_requests
            SET status='pending',
                processing_at=NULL,
                error_message='退款處理程序中斷，系統已自動重新排隊',
                updated_at=?
            WHERE status='processing'
              AND (
                  processing_at IS NULL
                  OR datetime(processing_at) <= datetime('now', ?)
              )
            """,
            (now_text, f"-{stale_minutes} minutes"),
        )
        rows = conn.execute(
            """
            SELECT * FROM wallet_refund_requests
            WHERE status='pending'
            ORDER BY id ASC
            LIMIT ?
            """,
            (safe_limit,),
        ).fetchall()
        conn.commit()
        return [dict(row) for row in rows]


def list_customer_wallet_refunds(
    customer_discord_id: str | int,
    *,
    limit: int = 20,
    db_file: str | Path | None = None,
) -> list[dict[str, Any]]:
    ensure_wallet_refund_tables(db_file)
    path = _db_path(db_file)
    safe_limit = max(1, min(int(limit or 20), 100))
    with sqlite3.connect(path, timeout=15) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            """
            SELECT * FROM wallet_refund_requests
            WHERE customer_discord_id=?
            ORDER BY id DESC
            LIMIT ?
            """,
            (str(customer_discord_id), safe_limit),
        ).fetchall()
        return [dict(row) for row in rows]


def mark_wallet_refund_processing(
    refund_id: int,
    db_file: str | Path | None = None,
) -> bool:
    ensure_wallet_refund_tables(db_file)
    path = _db_path(db_file)
    now_text = get_taipei_now_iso()
    with sqlite3.connect(path, timeout=15) as conn:
        cur = conn.execute(
            """
            UPDATE wallet_refund_requests
            SET status='processing', processing_at=?, updated_at=?, error_message=NULL
            WHERE id=? AND status='pending'
            """,
            (now_text, now_text, int(refund_id)),
        )
        conn.commit()
        return int(cur.rowcount or 0) == 1


def mark_wallet_refund_completed(
    refund_id: int,
    *,
    wallet_transaction_id: int,
    wallet_debit_amount: int,
    bonus_offset_applied: int,
    bonus_reversal_transaction_id: int | None,
    bonus_revoked_amount: int,
    vip_total_before: int,
    vip_total_after: int,
    vip_level_before: str,
    vip_level_after: str,
    db_file: str | Path | None = None,
) -> None:
    ensure_wallet_refund_tables(db_file)
    path = _db_path(db_file)
    now_text = get_taipei_now_iso()
    with sqlite3.connect(path, timeout=15) as conn:
        conn.execute(
            """
            UPDATE wallet_refund_requests
            SET status='completed',
                wallet_transaction_id=?,
                wallet_debit_amount=?,
                bonus_offset_applied=?,
                bonus_reversal_transaction_id=?,
                bonus_revoked_amount=?,
                vip_total_before=?,
                vip_total_after=?,
                vip_level_before=?,
                vip_level_after=?,
                completed_at=?, updated_at=?, error_message=NULL
            WHERE id=?
            """,
            (
                int(wallet_transaction_id),
                max(0, int(wallet_debit_amount or 0)),
                max(0, int(bonus_offset_applied or 0)),
                int(bonus_reversal_transaction_id)
                if bonus_reversal_transaction_id is not None
                else None,
                max(0, int(bonus_revoked_amount or 0)),
                max(0, int(vip_total_before or 0)),
                max(0, int(vip_total_after or 0)),
                str(vip_level_before or "普通魔丸"),
                str(vip_level_after or "普通魔丸"),
                now_text,
                now_text,
                int(refund_id),
            ),
        )
        conn.commit()


def mark_wallet_refund_failed(
    refund_id: int,
    error: object,
    db_file: str | Path | None = None,
) -> None:
    """Terminal failure: the refund did not debit the wallet and needs review."""
    ensure_wallet_refund_tables(db_file)
    path = _db_path(db_file)
    now_text = get_taipei_now_iso()
    with sqlite3.connect(path, timeout=15) as conn:
        conn.execute(
            """
            UPDATE wallet_refund_requests
            SET status='failed', failed_at=?, error_message=?, updated_at=?
            WHERE id=?
            """,
            (now_text, str(error or "退款處理失敗")[:1000], now_text, int(refund_id)),
        )
        conn.commit()


def reset_wallet_refund_for_retry(
    refund_id: int,
    error: object,
    db_file: str | Path | None = None,
) -> None:
    """Return an in-flight refund to the queue after a recoverable interruption."""
    ensure_wallet_refund_tables(db_file)
    path = _db_path(db_file)
    now_text = get_taipei_now_iso()
    with sqlite3.connect(path, timeout=15) as conn:
        conn.execute(
            """
            UPDATE wallet_refund_requests
            SET status='pending', error_message=?, updated_at=?
            WHERE id=? AND status='processing'
            """,
            (str(error or "退款處理中斷，系統將自動重試")[:1000], now_text, int(refund_id)),
        )
        conn.commit()
