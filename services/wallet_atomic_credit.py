from __future__ import annotations

import sqlite3
from typing import Any

from core.time_utils import get_taipei_now_iso


_ALLOWED_SCHEMAS = frozenset({"main", "walletdb"})


def credit_principal_in_connection(
    conn: sqlite3.Connection,
    *,
    customer_id: str | int,
    amount: int,
    tx_type: str,
    order_no: str,
    operator_discord_id: str | int | None = None,
    operator_display_name: str | None = None,
    note: str = "",
    schema: str = "main",
) -> dict[str, Any]:
    """Credit wallet principal inside a caller-owned SQLite transaction.

    Used when another SQLite ledger and bot.db must commit or roll back together.
    The caller must attach bot.db under ``walletdb`` before using that schema.
    """
    schema_name = str(schema or "main").strip()
    if schema_name not in _ALLOWED_SCHEMAS:
        raise ValueError("不支援的錢包資料庫 schema。")
    prefix = f"{schema_name}."

    customer_text = str(customer_id or "").strip()
    tx_type_text = str(tx_type or "").strip()
    order_no_text = str(order_no or "").strip()
    if not customer_text:
        raise ValueError("無法確認錢包使用者。")
    try:
        amount_int = int(amount)
    except (TypeError, ValueError) as exc:
        raise ValueError("錢包入帳金額格式錯誤。") from exc
    if amount_int <= 0:
        raise ValueError("錢包入帳金額必須大於 0T。")
    if not tx_type_text or not order_no_text:
        raise ValueError("錢包交易類型或識別碼不完整。")

    existing = conn.execute(
        f"""
        SELECT id, amount
        FROM {prefix}wallet_transactions
        WHERE customer_discord_id = ?
          AND order_no = ?
          AND type = ?
        LIMIT 1
        """,
        (customer_text, order_no_text, tx_type_text),
    ).fetchone()
    if existing is not None:
        existing_amount = int(
            existing["amount"] if isinstance(existing, sqlite3.Row) else existing[1]
        )
        if existing_amount != amount_int:
            raise ValueError("同一錢包交易識別碼已存在不同金額，已停止重複入帳。")
        return {
            "transaction_id": int(
                existing["id"] if isinstance(existing, sqlite3.Row) else existing[0]
            ),
            "amount": existing_amount,
            "created": False,
        }

    row = conn.execute(
        f"""
        SELECT balance, principal_balance, bonus_balance, refund_offset_balance
        FROM {prefix}customer_wallets
        WHERE customer_discord_id = ?
        """,
        (customer_text,),
    ).fetchone()

    if row is None:
        before = 0
        principal_before = 0
        bonus_before = 0
        refund_offset_before = 0
    elif isinstance(row, sqlite3.Row):
        before = int(row["balance"] or 0)
        principal_before = int(row["principal_balance"] or 0)
        bonus_before = int(row["bonus_balance"] or 0)
        refund_offset_before = int(row["refund_offset_balance"] or 0)
    else:
        before = int(row[0] or 0)
        principal_before = int(row[1] or 0)
        bonus_before = int(row[2] or 0)
        refund_offset_before = int(row[3] or 0)

    after = before + amount_int
    principal_after = principal_before + amount_int
    now_iso = get_taipei_now_iso()

    if row is None:
        conn.execute(
            f"""
            INSERT INTO {prefix}customer_wallets (
                customer_discord_id, balance, principal_balance,
                bonus_balance, refund_offset_balance, updated_at
            ) VALUES (?, ?, ?, 0, 0, ?)
            """,
            (customer_text, after, principal_after, now_iso),
        )
    else:
        conn.execute(
            f"""
            UPDATE {prefix}customer_wallets
            SET balance = ?, principal_balance = ?, bonus_balance = ?,
                refund_offset_balance = ?, updated_at = ?
            WHERE customer_discord_id = ?
            """,
            (
                after,
                principal_after,
                bonus_before,
                refund_offset_before,
                now_iso,
                customer_text,
            ),
        )

    cur = conn.execute(
        f"""
        INSERT INTO {prefix}wallet_transactions (
            customer_discord_id, amount, balance_before, balance_after, type,
            order_channel_id, order_no, operator_discord_id,
            operator_display_name, note, created_at
        ) VALUES (?, ?, ?, ?, ?, NULL, ?, ?, ?, ?, ?)
        """,
        (
            customer_text,
            amount_int,
            before,
            after,
            tx_type_text,
            order_no_text,
            str(operator_discord_id or "").strip() or None,
            str(operator_display_name or "").strip() or None,
            str(note or "")[:500],
            now_iso,
        ),
    )
    return {
        "transaction_id": int(cur.lastrowid),
        "amount": amount_int,
        "balance_before": before,
        "balance_after": after,
        "created": True,
    }
