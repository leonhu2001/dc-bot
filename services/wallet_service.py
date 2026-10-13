from __future__ import annotations

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
        if added_principal:
            conn.execute(
                "ALTER TABLE customer_wallets ADD COLUMN principal_balance INTEGER NOT NULL DEFAULT 0"
            )
        if added_bonus:
            conn.execute(
                "ALTER TABLE customer_wallets ADD COLUMN bonus_balance INTEGER NOT NULL DEFAULT 0"
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
    """Return total, refundable/tip-eligible principal and non-cash bonus balances."""
    ensure_wallet_tables(db_file)
    path = _db_path(db_file)
    with sqlite3.connect(path, timeout=15) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            """
            SELECT balance, principal_balance, bonus_balance
            FROM customer_wallets
            WHERE customer_discord_id=?
            """,
            (str(customer_id),),
        ).fetchone()
        if row is None:
            return {"balance": 0, "principal_balance": 0, "bonus_balance": 0}
        return {
            "balance": int(row["balance"] or 0),
            "principal_balance": int(row["principal_balance"] or 0),
            "bonus_balance": int(row["bonus_balance"] or 0),
        }


def get_refundable_wallet_balance(
    customer_id: str | int,
    db_file: str | Path | None = None,
) -> int:
    return int(get_wallet_balance_breakdown(customer_id, db_file)["principal_balance"])


def get_tip_eligible_wallet_balance(
    customer_id: str | int,
    db_file: str | Path | None = None,
) -> int:
    return get_refundable_wallet_balance(customer_id, db_file)


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
    limit: int = 10,
    db_file: str | Path | None = None,
) -> list[dict[str, Any]]:
    ensure_wallet_tables(db_file)
    path = _db_path(db_file)
    safe_limit = max(1, min(int(limit or 10), 25))
    with sqlite3.connect(path, timeout=15) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            """
            SELECT
                id, customer_discord_id, amount, balance_before, balance_after,
                type, order_channel_id, order_no, operator_discord_id,
                operator_display_name, note, created_at
            FROM wallet_transactions
            WHERE customer_discord_id = ?
            ORDER BY id DESC
            LIMIT ?
            """,
            (str(customer_id), safe_limit),
        ).fetchall()
        return [dict(row) for row in rows]


def _apply_bucket_change(
    *,
    principal_before: int,
    bonus_before: int,
    amount: int,
    tx_type: str,
    allow_negative: bool,
) -> tuple[int, int]:
    principal_after = int(principal_before)
    bonus_after = int(bonus_before)

    if amount > 0:
        if tx_type in BONUS_CREDIT_TYPES:
            bonus_after += amount
        else:
            principal_after += amount
        return principal_after, bonus_after

    debit = abs(int(amount))
    total_before = principal_before + bonus_before
    if debit > total_before and not allow_negative:
        raise ValueError(
            f"錢包餘額不足，目前餘額 {total_before:,}T，無法扣除 {debit:,}T。"
        )

    if tx_type in PRINCIPAL_ONLY_DEBIT_TYPES:
        if debit > principal_before and not allow_negative:
            if tx_type == "tip_payment":
                raise ValueError(
                    "雞腿只能使用實付本金。"
                    f"目前可用本金 {principal_before:,}T，無法支付 {debit:,}T。"
                )
            raise ValueError(
                f"可退款實付本金不足，目前可退款 {principal_before:,}T。"
            )
        principal_after -= debit
        return principal_after, bonus_after

    if tx_type in BONUS_ONLY_DEBIT_TYPES:
        if debit > bonus_before and not allow_negative:
            raise ValueError(
                f"贈額不足，目前贈額 {bonus_before:,}T，無法撤銷 {debit:,}T。"
            )
        bonus_after -= debit
        return principal_after, bonus_after

    # 一般消費固定先使用實付本金，再使用贈額；避免先花贈額後把本金全額退回。
    principal_used = min(max(0, principal_before), debit)
    principal_after -= principal_used
    remaining = debit - principal_used
    if remaining > 0:
        bonus_after -= remaining

    return principal_after, bonus_after


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

    normalized_order_no = str(order_no or "").strip() or None
    normalized_order_channel_id = str(order_channel_id or "").strip() or None
    normalized_type = str(tx_type)

    with sqlite3.connect(path, timeout=15) as conn:
        conn.row_factory = sqlite3.Row
        conn.execute("BEGIN IMMEDIATE")

        if normalized_type == "payment" and normalized_order_channel_id:
            existing = conn.execute(
                """
                SELECT *
                FROM wallet_transactions
                WHERE customer_discord_id=? AND order_channel_id=? AND type='payment'
                ORDER BY id ASC
                LIMIT 1
                """,
                (str(customer_id), normalized_order_channel_id),
            ).fetchone()
            if existing is not None:
                if int(existing["amount"] or 0) != amount:
                    raise ValueError(
                        "同一訂單票口已有不同金額的錢包扣款；已拒絕再次扣款，請通知客服確認。"
                    )
                conn.rollback()
                result = dict(existing)
                result["idempotent_replay"] = True
                return result

        if normalized_order_no:
            existing = conn.execute(
                """
                SELECT *
                FROM wallet_transactions
                WHERE customer_discord_id=? AND order_no=? AND type=?
                ORDER BY id ASC
                LIMIT 1
                """,
                (str(customer_id), normalized_order_no, normalized_type),
            ).fetchone()
            if existing is not None:
                if int(existing["amount"] or 0) != amount:
                    raise ValueError(
                        "同一錢包交易識別碼已存在，但金額不同；已拒絕重複入帳。"
                    )
                conn.rollback()
                result = dict(existing)
                result["idempotent_replay"] = True
                return result

        row = conn.execute(
            """
            SELECT balance, principal_balance, bonus_balance
            FROM customer_wallets
            WHERE customer_discord_id=?
            """,
            (str(customer_id),),
        ).fetchone()
        before = int(row["balance"] or 0) if row else 0
        principal_before = int(row["principal_balance"] or 0) if row else 0
        bonus_before = int(row["bonus_balance"] or 0) if row else 0

        principal_after, bonus_after = _apply_bucket_change(
            principal_before=principal_before,
            bonus_before=bonus_before,
            amount=amount,
            tx_type=normalized_type,
            allow_negative=allow_negative,
        )
        after = principal_after + bonus_after
        if after < 0 and not allow_negative:
            raise ValueError(
                f"錢包餘額不足，目前餘額 {before:,}T，無法扣除 {abs(amount):,}T。"
            )

        now_text = get_taipei_now_iso()
        conn.execute(
            """
            INSERT INTO customer_wallets(
                customer_discord_id, balance, principal_balance, bonus_balance, updated_at
            ) VALUES(?,?,?,?,?)
            ON CONFLICT(customer_discord_id)
            DO UPDATE SET
                balance=excluded.balance,
                principal_balance=excluded.principal_balance,
                bonus_balance=excluded.bonus_balance,
                updated_at=excluded.updated_at
            """,
            (
                str(customer_id),
                after,
                principal_after,
                bonus_after,
                now_text,
            ),
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
                str(customer_id), amount, before, after, normalized_type,
                normalized_order_channel_id, normalized_order_no,
                str(operator_discord_id) if operator_discord_id else None,
                str(operator_display_name or "").strip() or None,
                str(note or "").strip() or None,
                now_text,
            ),
        )
        tx_id = int(cur.lastrowid)
        conn.commit()

        transaction = {
            "id": tx_id,
            "customer_discord_id": str(customer_id),
            "amount": amount,
            "balance_before": before,
            "balance_after": after,
            "principal_before": principal_before,
            "principal_after": principal_after,
            "bonus_before": bonus_before,
            "bonus_after": bonus_after,
            "type": normalized_type,
            "order_no": normalized_order_no,
            "order_channel_id": normalized_order_channel_id,
            "note": note,
            "created_at": now_text,
            "idempotent_replay": False,
        }

    if operator_discord_id:
        try:
            from web.app.services.audit_trail import write_sqlite_audit_log

            audit_db_file = Path(db_file).with_name("web_dashboard.db") if db_file is not None else None
            write_sqlite_audit_log(
                admin_discord_id=str(operator_discord_id),
                action="wallet_adjustment",
                target_type="customer_wallet",
                target_id=str(customer_id),
                before={
                    "customer_discord_id": str(customer_id),
                    "balance": before,
                    "principal_balance": principal_before,
                    "bonus_balance": bonus_before,
                },
                after={
                    "customer_discord_id": str(customer_id),
                    "balance": after,
                    "principal_balance": principal_after,
                    "bonus_balance": bonus_after,
                    "amount": amount,
                    "transaction_id": tx_id,
                    "transaction_type": normalized_type,
                    "order_no": normalized_order_no,
                    "order_channel_id": str(order_channel_id) if order_channel_id is not None else None,
                    "note": str(note or "").strip() or None,
                    "operator_display_name": str(operator_display_name or "").strip() or None,
                },
                reason=str(note or "").strip() or None,
                db_file=audit_db_file,
            )
        except Exception as exc:
            print(
                f"[audit] wallet log failed tx_id={tx_id}: {type(exc).__name__}: {exc}",
                flush=True,
            )

    return transaction
