from __future__ import annotations

import re
import sqlite3
from pathlib import Path
from typing import Any

from core.time_utils import get_taipei_now_iso


PRINCIPAL_ONLY_DEBIT_TYPES = frozenset({"tip_payment", "refund"})
BONUS_ONLY_DEBIT_TYPES = frozenset({"topup_bonus_reversal", "bonus_reversal"})
BONUS_CREDIT_TYPES = frozenset({"topup_bonus"})


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
                principal_balance INTEGER NOT NULL DEFAULT 0,
                bonus_balance INTEGER NOT NULL DEFAULT 0,
                refund_offset_balance INTEGER NOT NULL DEFAULT 0,
                updated_at TEXT
            )
            """
        )
        wallet_columns = {
            str(row[1])
            for row in conn.execute("PRAGMA table_info(customer_wallets)").fetchall()
        }
        added_principal = "principal_balance" not in wallet_columns
        added_bonus = "bonus_balance" not in wallet_columns
        added_refund_offset = "refund_offset_balance" not in wallet_columns
        if added_principal:
            conn.execute(
                "ALTER TABLE customer_wallets ADD COLUMN principal_balance INTEGER NOT NULL DEFAULT 0"
            )
        if added_bonus:
            conn.execute(
                "ALTER TABLE customer_wallets ADD COLUMN bonus_balance INTEGER NOT NULL DEFAULT 0"
            )
        if added_refund_offset:
            conn.execute(
                "ALTER TABLE customer_wallets ADD COLUMN refund_offset_balance INTEGER NOT NULL DEFAULT 0"
            )

        # 2026-10-14 新制只向後生效。舊錢包無法可靠拆分過往本金與贈額，
        # 因此升級資料結構時把當下既有餘額完整視為舊制本金，不回溯舊交易。
        if added_principal or added_bonus:
            conn.execute(
                """
                UPDATE customer_wallets
                SET principal_balance = balance,
                    bonus_balance = 0
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
            "CREATE INDEX IF NOT EXISTS idx_wallet_tx_reference "
            "ON wallet_transactions(customer_discord_id, order_no, type)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_wallet_tx_payment_channel "
            "ON wallet_transactions(customer_discord_id, order_channel_id, type)"
        )

        conn.execute(
            """
            CREATE TRIGGER IF NOT EXISTS trg_wallet_tx_unique_payment_channel
            BEFORE INSERT ON wallet_transactions
            WHEN NEW.type = 'payment'
              AND NEW.order_channel_id IS NOT NULL
              AND TRIM(NEW.order_channel_id) <> ''
              AND EXISTS (
                  SELECT 1
                  FROM wallet_transactions
                  WHERE customer_discord_id = NEW.customer_discord_id
                    AND order_channel_id = NEW.order_channel_id
                    AND type = 'payment'
              )
            BEGIN
                SELECT RAISE(ABORT, 'duplicate wallet payment channel');
            END
            """
        )

        conn.execute(
            """
            CREATE TRIGGER IF NOT EXISTS trg_wallet_tx_unique_reference
            BEFORE INSERT ON wallet_transactions
            WHEN NEW.order_no IS NOT NULL
              AND TRIM(NEW.order_no) <> ''
              AND EXISTS (
                  SELECT 1
                  FROM wallet_transactions
                  WHERE customer_discord_id = NEW.customer_discord_id
                    AND order_no = NEW.order_no
                    AND type = NEW.type
              )
            BEGIN
                SELECT RAISE(ABORT, 'duplicate wallet transaction reference');
            END
            """
        )

        duplicate = conn.execute(
            """
            SELECT 1
            FROM wallet_transactions
            WHERE order_no IS NOT NULL
              AND TRIM(order_no) <> ''
            GROUP BY customer_discord_id, order_no, type
            HAVING COUNT(*) > 1
            LIMIT 1
            """
        ).fetchone()

        if duplicate is None:
            conn.execute(
                """
                CREATE UNIQUE INDEX IF NOT EXISTS uq_wallet_tx_reference
                ON wallet_transactions(customer_discord_id, order_no, type)
                WHERE order_no IS NOT NULL AND TRIM(order_no) <> ''
                """
            )

        conn.commit()


def _wallet_schema_prefix(schema: str) -> str:
    name = str(schema or "main").strip()
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name):
        raise ValueError("Invalid wallet database schema name.")
    return f"{name}."


def credit_wallet_principal_in_connection(
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
    """Credit principal using the caller's existing SQLite transaction.

    This is the canonical primitive for a workflow that must atomically update
    another SQLite ledger and a wallet attached to the same connection.  It does
    not commit or roll back; transaction ownership stays with the caller.
    """
    customer_text = str(customer_id or "").strip()
    tx_type_text = str(tx_type or "").strip()
    order_no_text = str(order_no or "").strip()
    if not customer_text:
        raise ValueError("customer_id is required")
    try:
        amount_int = int(amount)
    except (TypeError, ValueError) as exc:
        raise ValueError("wallet credit amount must be an integer") from exc
    if amount_int <= 0:
        raise ValueError("wallet credit amount must be greater than zero")
    if not tx_type_text or not order_no_text:
        raise ValueError("wallet transaction type and reference are required")

    prefix = _wallet_schema_prefix(schema)
    existing = conn.execute(
        f"""
        SELECT id, amount, balance_before, balance_after
        FROM {prefix}wallet_transactions
        WHERE customer_discord_id = ?
          AND order_no = ?
          AND type = ?
        LIMIT 1
        """,
        (customer_text, order_no_text, tx_type_text),
    ).fetchone()
    if existing is not None:
        existing_amount = int(existing["amount"] if isinstance(existing, sqlite3.Row) else existing[1])
        if existing_amount != amount_int:
            raise ValueError("wallet transaction reference already exists with a different amount")
        return {
            "transaction_id": int(existing["id"] if isinstance(existing, sqlite3.Row) else existing[0]),
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


def get_wallet_balance(customer_id: str | int, db_file: str | Path | None = None) -> int:
    ensure_wallet_tables(db_file)
    path = _db_path(db_file)
    with sqlite3.connect(path, timeout=15) as conn:
        row = conn.execute(
            "SELECT balance FROM customer_wallets WHERE customer_discord_id=?",
            (str(customer_id),),
        ).fetchone()
        return int(row[0] or 0) if row else 0


def get_wallet_balance_breakdown(
    customer_id: str | int,
    db_file: str | Path | None = None,
) -> dict[str, int]:
    """Return total, cash-backed principal, bonus and currently refundable cash."""
    ensure_wallet_tables(db_file)
    path = _db_path(db_file)
    with sqlite3.connect(path, timeout=15) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            """
            SELECT balance, principal_balance, bonus_balance, refund_offset_balance
            FROM customer_wallets
            WHERE customer_discord_id=?
            """,
            (str(customer_id),),
        ).fetchone()
        if row is None:
            return {
                "balance": 0,
                "principal_balance": 0,
                "bonus_balance": 0,
                "refund_offset_balance": 0,
                "refundable_balance": 0,
            }
        principal = int(row["principal_balance"] or 0)
        refund_offset = max(0, int(row["refund_offset_balance"] or 0))
        refundable = max(0, principal - refund_offset)
        return {
            "balance": int(row["balance"] or 0),
            "principal_balance": principal,
            "bonus_balance": int(row["bonus_balance"] or 0),
            "refund_offset_balance": refund_offset,
            "refundable_balance": refundable,
        }


def get_refundable_wallet_balance(
    customer_id: str | int,
    db_file: str | Path | None = None,
) -> int:
    return int(get_wallet_balance_breakdown(customer_id, db_file)["refundable_balance"])


def get_tip_eligible_wallet_balance(
    customer_id: str | int,
    db_file: str | Path | None = None,
) -> int:
    return int(get_wallet_balance_breakdown(customer_id, db_file)["principal_balance"])


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


def get_wallet_payment_transaction(
    customer_id: str | int,
    order_channel_id: str | int,
    *,
    db_file: str | Path | None = None,
) -> dict[str, Any] | None:
    ensure_wallet_tables(db_file)
    path = _db_path(db_file)
    with sqlite3.connect(path, timeout=15) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            """
            SELECT *
            FROM wallet_transactions
            WHERE customer_discord_id=?
              AND order_channel_id=?
              AND type='payment'
            ORDER BY id ASC
            LIMIT 1
            """,
            (str(customer_id), str(order_channel_id)),
        ).fetchone()
        return dict(row) if row else None


def get_wallet_transactions(
    customer_id: str | int,
    *,
    limit: int = 50,
    db_file: str | Path | None = None,
) -> list[dict[str, Any]]:
    ensure_wallet_tables(db_file)
    path = _db_path(db_file)
    with sqlite3.connect(path, timeout=15) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            """
            SELECT * FROM wallet_transactions
            WHERE customer_discord_id=?
            ORDER BY id DESC
            LIMIT ?
            """,
            (str(customer_id), max(1, min(int(limit), 200))),
        ).fetchall()
        return [dict(row) for row in rows]


def adjust_wallet_balance(
    customer_id: str | int,
    delta: int,
    *,
    tx_type: str,
    order_channel_id: str | int | None = None,
    order_no: str | None = None,
    operator_discord_id: str | int | None = None,
    operator_display_name: str | None = None,
    note: str | None = None,
    db_file: str | Path | None = None,
) -> dict[str, Any]:
    ensure_wallet_tables(db_file)
    customer_id = str(customer_id)
    delta = int(delta)
    order_channel_id = str(order_channel_id) if order_channel_id is not None else None
    order_no = str(order_no) if order_no is not None else None
    path = _db_path(db_file)

    with sqlite3.connect(path, timeout=15) as conn:
        conn.row_factory = sqlite3.Row
        conn.execute("BEGIN IMMEDIATE")
        if order_no:
            existing = conn.execute(
                """
                SELECT * FROM wallet_transactions
                WHERE customer_discord_id=? AND order_no=? AND type=?
                LIMIT 1
                """,
                (customer_id, order_no, tx_type),
            ).fetchone()
            if existing:
                return dict(existing)

        row = conn.execute(
            """
            SELECT balance, principal_balance, bonus_balance, refund_offset_balance
            FROM customer_wallets
            WHERE customer_discord_id=?
            """,
            (customer_id,),
        ).fetchone()
        before = int(row["balance"] or 0) if row else 0
        principal_before = int(row["principal_balance"] or 0) if row else 0
        bonus_before = int(row["bonus_balance"] or 0) if row else 0
        refund_offset_before = int(row["refund_offset_balance"] or 0) if row else 0
        if delta < 0 and before + delta < 0:
            raise ValueError("錢包餘額不足")

        debit = abs(delta) if delta < 0 else 0
        if delta < 0:
            if tx_type in BONUS_ONLY_DEBIT_TYPES:
                if bonus_before < debit:
                    raise ValueError("錢包贈額不足")
                principal_after = principal_before
                bonus_after = bonus_before - debit
                refund_offset_after = refund_offset_before
            elif tx_type in PRINCIPAL_ONLY_DEBIT_TYPES:
                if principal_before < debit:
                    raise ValueError("可用本金不足")
                principal_after = principal_before - debit
                bonus_after = bonus_before
                refund_offset_after = refund_offset_before + (debit if tx_type == "refund" else 0)
            else:
                bonus_used = min(bonus_before, debit)
                principal_used = debit - bonus_used
                if principal_before < principal_used:
                    raise ValueError("錢包餘額不足")
                principal_after = principal_before - principal_used
                bonus_after = bonus_before - bonus_used
                refund_offset_after = refund_offset_before
        else:
            if tx_type in BONUS_CREDIT_TYPES:
                principal_after = principal_before
                bonus_after = bonus_before + delta
            else:
                principal_after = principal_before + delta
                bonus_after = bonus_before
            refund_offset_after = refund_offset_before

        after = before + delta
        now_iso = get_taipei_now_iso()

        if row is None:
            conn.execute(
                """
                INSERT INTO customer_wallets (
                    customer_discord_id, balance, principal_balance,
                    bonus_balance, refund_offset_balance, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    customer_id,
                    after,
                    principal_after,
                    bonus_after,
                    refund_offset_after,
                    now_iso,
                ),
            )
        else:
            conn.execute(
                """
                UPDATE customer_wallets
                SET balance=?, principal_balance=?, bonus_balance=?,
                    refund_offset_balance=?, updated_at=?
                WHERE customer_discord_id=?
                """,
                (
                    after,
                    principal_after,
                    bonus_after,
                    refund_offset_after,
                    now_iso,
                    customer_id,
                ),
            )

        cur = conn.execute(
            """
            INSERT INTO wallet_transactions (
                customer_discord_id, amount, balance_before, balance_after, type,
                order_channel_id, order_no, operator_discord_id,
                operator_display_name, note, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                customer_id,
                delta,
                before,
                after,
                tx_type,
                order_channel_id,
                order_no,
                str(operator_discord_id) if operator_discord_id is not None else None,
                operator_display_name,
                note,
                now_iso,
            ),
        )
        conn.commit()
        return {
            "transaction_id": cur.lastrowid,
            "customer_discord_id": customer_id,
            "amount": delta,
            "balance_before": before,
            "balance_after": after,
            "principal_before": principal_before,
            "principal_after": principal_after,
            "bonus_before": bonus_before,
            "bonus_after": bonus_after,
            "refund_offset_before": refund_offset_before,
            "refund_offset_after": refund_offset_after,
            "type": tx_type,
            "order_channel_id": order_channel_id,
            "order_no": order_no,
            "operator_discord_id": str(operator_discord_id) if operator_discord_id is not None else None,
            "operator_display_name": operator_display_name,
            "note": note,
            "created_at": now_iso,
        }


def get_wallet_transaction_by_id(
    transaction_id: int,
    *,
    db_file: str | Path | None = None,
) -> dict[str, Any] | None:
    ensure_wallet_tables(db_file)
    path = _db_path(db_file)
    with sqlite3.connect(path, timeout=15) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT * FROM wallet_transactions WHERE id=? LIMIT 1",
            (int(transaction_id),),
        ).fetchone()
        return dict(row) if row else None


def list_wallet_transaction_totals_by_type(
    *,
    customer_id: str | int | None = None,
    db_file: str | Path | None = None,
) -> dict[str, int]:
    ensure_wallet_tables(db_file)
    path = _db_path(db_file)
    with sqlite3.connect(path, timeout=15) as conn:
        where = ""
        params: list[Any] = []
        if customer_id is not None:
            where = "WHERE customer_discord_id = ?"
            params.append(str(customer_id))
        rows = conn.execute(
            f"""
            SELECT type, COALESCE(SUM(amount), 0) AS total
            FROM wallet_transactions
            {where}
            GROUP BY type
            """,
            params,
        ).fetchall()
        return {str(tx_type): int(total or 0) for tx_type, total in rows]


def reverse_wallet_transaction(
    transaction_id: int,
    *,
    operator_discord_id: str | int | None = None,
    operator_display_name: str | None = None,
    note: str | None = None,
    db_file: str | Path | None = None,
) -> dict[str, Any]:
    original = get_wallet_transaction_by_id(transaction_id, db_file=db_file)
    if original is None:
        raise ValueError("找不到錢包交易紀錄")

    if str(original.get("type") or "").startswith("reversal:"):
        raise ValueError("反向交易不能再次反轉")

    reversal_order_no = f"wallet-reversal:{int(transaction_id)}"
    existing = find_wallet_transaction(
        customer_id=original["customer_discord_id"],
        order_no=reversal_order_no,
        tx_type=f"reversal:{original['type']}",
        db_file=db_file,
    )
    if existing:
        return existing

    delta = -int(original["amount"] or 0)
    return adjust_wallet_balance(
        original["customer_discord_id"],
        delta,
        tx_type=f"reversal:{original['type']}",
        order_no=reversal_order_no,
        operator_discord_id=operator_discord_id,
        operator_display_name=operator_display_name,
        note=note or f"反轉錢包交易 #{transaction_id}",
        db_file=db_file,
    )