from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

from core.time_utils import get_taipei_now_iso


def _db_path(db_file: str | Path | None = None) -> Path:
    if db_file is not None:
        return Path(db_file)
    return Path(__file__).resolve().parents[1] / "bot.db"


def ensure_wallet_tables(db_file: str | Path | None = None) -> None:
    path = _db_path(db_file)
    with sqlite3.connect(path, timeout=15) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS customer_wallets (
                customer_discord_id TEXT PRIMARY KEY,
                balance INTEGER NOT NULL DEFAULT 0,
                updated_at TEXT
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS wallet_transactions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                customer_discord_id TEXT NOT NULL,
                amount INTEGER NOT NULL,
                balance_before INTEGER NOT NULL,
                balance_after INTEGER NOT NULL,
                type TEXT NOT NULL,
                order_channel_id TEXT,
                order_no TEXT,
                operator_discord_id TEXT,
                operator_display_name TEXT,
                note TEXT,
                created_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_wallet_tx_reference ON wallet_transactions(customer_discord_id, order_no, type)"
        )
        conn.commit()


def get_wallet_balance(customer_id: str | int, db_file: str | Path | None = None) -> int:
    ensure_wallet_tables(db_file)
    path = _db_path(db_file)
    with sqlite3.connect(path, timeout=15) as conn:
        row = conn.execute(
            "SELECT balance FROM customer_wallets WHERE customer_discord_id=?",
            (str(customer_id),),
        ).fetchone()
        return int(row[0] or 0) if row else 0


def find_wallet_transaction(
    *,
    customer_id: str | int,
    order_no: str,
    tx_type: str,
    db_file: str | Path | None = None,
) -> dict[str, Any] | None:
    ensure_wallet_tables(db_file)
    path = _db_path(db_file)
    with sqlite3.connect(path, timeout=15) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            """
            SELECT * FROM wallet_transactions
            WHERE customer_discord_id=? AND order_no=? AND type=?
            ORDER BY id DESC LIMIT 1
            """,
            (str(customer_id), str(order_no), str(tx_type)),
        ).fetchone()
        return dict(row) if row else None


def adjust_wallet_balance(
    *,
    customer_id: str | int,
    amount: int,
    tx_type: str,
    operator_discord_id: str | int | None = None,
    operator_display_name: str | None = None,
    order_channel_id: str | int | None = None,
    order_no: str | None = None,
    note: str | None = None,
    allow_negative: bool = False,
    db_file: str | Path | None = None,
) -> dict[str, Any]:
    ensure_wallet_tables(db_file)
    path = _db_path(db_file)
    amount = int(amount or 0)
    if amount == 0:
        raise ValueError("異動金額不能為 0。")

    with sqlite3.connect(path, timeout=15) as conn:
        conn.row_factory = sqlite3.Row
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute(
            "SELECT balance FROM customer_wallets WHERE customer_discord_id=?",
            (str(customer_id),),
        ).fetchone()
        before = int(row["balance"] or 0) if row else 0
        after = before + amount
        if after < 0 and not allow_negative:
            raise ValueError(f"錢包餘額不足，目前餘額 {before:,}T。")

        now_text = get_taipei_now_iso()
        conn.execute(
            """
            INSERT INTO customer_wallets(customer_discord_id,balance,updated_at)
            VALUES(?,?,?)
            ON CONFLICT(customer_discord_id)
            DO UPDATE SET balance=excluded.balance, updated_at=excluded.updated_at
            """,
            (str(customer_id), after, now_text),
        )
        cur = conn.execute(
            """
            INSERT INTO wallet_transactions(
                customer_discord_id, amount, balance_before, balance_after, type,
                order_channel_id, order_no, operator_discord_id,
                operator_display_name, note, created_at
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                str(customer_id), amount, before, after, str(tx_type),
                str(order_channel_id) if order_channel_id is not None else None,
                str(order_no) if order_no else None,
                str(operator_discord_id) if operator_discord_id else None,
                str(operator_display_name or "").strip() or None,
                str(note or "").strip() or None,
                now_text,
            ),
        )
        tx_id = int(cur.lastrowid)
        conn.commit()
        return {
            "id": tx_id,
            "customer_discord_id": str(customer_id),
            "amount": amount,
            "balance_before": before,
            "balance_after": after,
            "type": str(tx_type),
            "note": note,
            "created_at": now_text,
        }
