from __future__ import annotations

import sqlite3
from collections.abc import Callable
from datetime import datetime
from pathlib import Path


_DB_PATH_PROVIDER: Callable[[], str | Path] | None = None


def configure_worker_tip_store(*, db_path_provider: Callable[[], str | Path]) -> None:
    global _DB_PATH_PROVIDER
    _DB_PATH_PROVIDER = db_path_provider


def _db_path() -> Path:
    if _DB_PATH_PROVIDER is not None:
        return Path(_DB_PATH_PROVIDER())
    return Path(__file__).resolve().parents[1] / "web_dashboard.db"


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(_db_path(), timeout=15)
    conn.row_factory = sqlite3.Row
    return conn


def _now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def ensure_worker_tip_tables() -> None:
    conn = _connect()
    try:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS worker_tips (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                order_id INTEGER,
                ticket_channel_id TEXT NOT NULL,
                dispatch_message_id TEXT,
                receipt_id TEXT,
                customer_discord_id TEXT NOT NULL,
                customer_display_name TEXT,
                worker_discord_id TEXT NOT NULL,
                worker_display_name TEXT,
                amount INTEGER NOT NULL,
                payment_method TEXT NOT NULL,
                payment_status TEXT NOT NULL DEFAULT 'pending',
                payout_status TEXT NOT NULL DEFAULT 'unpaid',
                wallet_transaction_id INTEGER,
                confirmation_message_id TEXT,
                confirmed_by_discord_id TEXT,
                confirmed_by_display_name TEXT,
                paid_at TEXT,
                payout_paid_at TEXT,
                cancelled_at TEXT,
                note TEXT,
                source TEXT NOT NULL DEFAULT 'discord',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_worker_tips_order
                ON worker_tips(order_id);
            CREATE INDEX IF NOT EXISTS idx_worker_tips_ticket
                ON worker_tips(ticket_channel_id);
            CREATE INDEX IF NOT EXISTS idx_worker_tips_worker
                ON worker_tips(worker_discord_id);
            CREATE INDEX IF NOT EXISTS idx_worker_tips_payment
                ON worker_tips(payment_status, payout_status);
            """
        )
        conn.commit()
    finally:
        conn.close()


def get_worker_tip(tip_id: int) -> sqlite3.Row | None:
    ensure_worker_tip_tables()
    conn = _connect()
    try:
        return conn.execute(
            "SELECT * FROM worker_tips WHERE id = ? LIMIT 1",
            (int(tip_id),),
        ).fetchone()
    finally:
        conn.close()


def create_worker_tip(
    *,
    order: sqlite3.Row | None,
    ticket_channel_id: int | str,
    customer_id: int,
    customer_display_name: str,
    target: dict,
    amount: int,
    payment_method: str,
    payment_status: str = "pending",
) -> int:
    ensure_worker_tip_tables()

    amount = int(amount)
    if amount <= 0:
        raise ValueError("雞腿金額必須大於 0。")

    now = _now_iso()
    order_id = int(order["id"]) if order is not None else None
    dispatch_message_id = (
        str(order["dispatch_message_id"])
        if order is not None and order["dispatch_message_id"] is not None
        else None
    )
    receipt_id = (
        str(order["bot_order_no"])
        if order is not None and order["bot_order_no"] is not None
        else None
    )

    conn = _connect()
    try:
        cur = conn.execute(
            """
            INSERT INTO worker_tips (
                order_id,
                ticket_channel_id,
                dispatch_message_id,
                receipt_id,
                customer_discord_id,
                customer_display_name,
                worker_discord_id,
                worker_display_name,
                amount,
                payment_method,
                payment_status,
                payout_status,
                source,
                created_at,
                updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'unpaid', 'discord', ?, ?)
            """,
            (
                order_id,
                str(ticket_channel_id),
                dispatch_message_id,
                receipt_id,
                str(customer_id),
                str(customer_display_name or customer_id),
                str(target.get("staff_id") or ""),
                str(target.get("display_name") or target.get("staff_id") or ""),
                amount,
                str(payment_method),
                str(payment_status),
                now,
                now,
            ),
        )
        tip_id = int(cur.lastrowid)
        conn.commit()
        return tip_id
    finally:
        conn.close()


def set_worker_tip_confirmation_message(tip_id: int, message_id: int | str) -> None:
    ensure_worker_tip_tables()
    conn = _connect()
    try:
        conn.execute(
            """
            UPDATE worker_tips
            SET confirmation_message_id = ?,
                updated_at = ?
            WHERE id = ?
            """,
            (str(message_id), _now_iso(), int(tip_id)),
        )
        conn.commit()
    finally:
        conn.close()


def mark_worker_tip_paid(
    tip_id: int,
    *,
    confirmed_by=None,
    wallet_transaction_id: int | None = None,
) -> sqlite3.Row | None:
    ensure_worker_tip_tables()
    now = _now_iso()
    confirmer_id = str(getattr(confirmed_by, "id", "") or "") or None
    confirmer_name = (
        getattr(confirmed_by, "display_name", None)
        or getattr(confirmed_by, "name", None)
        or confirmer_id
    )

    conn = _connect()
    try:
        row = conn.execute(
            "SELECT * FROM worker_tips WHERE id = ? LIMIT 1",
            (int(tip_id),),
        ).fetchone()

        if row is None:
            return None

        if str(row["payment_status"] or "") == "paid":
            return row

        if str(row["payment_status"] or "") == "cancelled":
            raise ValueError("這筆雞腿已取消，不能再確認付款。")

        conn.execute(
            """
            UPDATE worker_tips
            SET payment_status = 'paid',
                payout_status = CASE
                    WHEN payout_status = 'paid' THEN 'paid'
                    ELSE 'unpaid'
                END,
                wallet_transaction_id = COALESCE(?, wallet_transaction_id),
                confirmed_by_discord_id = COALESCE(?, confirmed_by_discord_id),
                confirmed_by_display_name = COALESCE(?, confirmed_by_display_name),
                paid_at = COALESCE(paid_at, ?),
                updated_at = ?
            WHERE id = ?
            """,
            (
                wallet_transaction_id,
                confirmer_id,
                confirmer_name,
                now,
                now,
                int(tip_id),
            ),
        )
        conn.commit()
        return conn.execute(
            "SELECT * FROM worker_tips WHERE id = ? LIMIT 1",
            (int(tip_id),),
        ).fetchone()
    finally:
        conn.close()


def mark_worker_tip_cancelled(tip_id: int, *, cancelled_by=None) -> sqlite3.Row | None:
    ensure_worker_tip_tables()
    now = _now_iso()
    actor_name = (
        getattr(cancelled_by, "display_name", None)
        or getattr(cancelled_by, "name", None)
        or str(getattr(cancelled_by, "id", "") or "")
    )

    conn = _connect()
    try:
        row = conn.execute(
            "SELECT * FROM worker_tips WHERE id = ? LIMIT 1",
            (int(tip_id),),
        ).fetchone()

        if row is None:
            return None

        if str(row["payment_status"] or "") == "paid":
            raise ValueError("這筆雞腿已確認付款，不能直接取消。")

        conn.execute(
            """
            UPDATE worker_tips
            SET payment_status = 'cancelled',
                cancelled_at = ?,
                note = CASE
                    WHEN COALESCE(note, '') = '' THEN ?
                    ELSE note || '｜' || ?
                END,
                updated_at = ?
            WHERE id = ?
            """,
            (
                now,
                f"由 {actor_name or '使用者'} 取消",
                f"由 {actor_name or '使用者'} 取消",
                now,
                int(tip_id),
            ),
        )
        conn.commit()
        return conn.execute(
            "SELECT * FROM worker_tips WHERE id = ? LIMIT 1",
            (int(tip_id),),
        ).fetchone()
    finally:
        conn.close()


def has_pending_worker_tips(ticket_channel_id: int | str) -> bool:
    ensure_worker_tip_tables()
    conn = _connect()
    try:
        row = conn.execute(
            """
            SELECT id
            FROM worker_tips
            WHERE ticket_channel_id = ?
              AND payment_status IN ('pending', 'pending_review')
            LIMIT 1
            """,
            (str(ticket_channel_id),),
        ).fetchone()
        return row is not None
    finally:
        conn.close()


def get_pending_worker_tip_confirmations() -> list[dict]:
    ensure_worker_tip_tables()
    conn = _connect()
    try:
        rows = conn.execute(
            """
            SELECT id, customer_discord_id, confirmation_message_id
            FROM worker_tips
            WHERE payment_status = 'pending'
              AND confirmation_message_id IS NOT NULL
              AND TRIM(confirmation_message_id) <> ''
            ORDER BY id ASC
            """
        ).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()
