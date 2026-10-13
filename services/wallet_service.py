from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

from core.time_utils import get_taipei_now_iso


# Only money actually paid by the customer is refundable and may be used for
# 100%-to-worker tips. Free credits / VIP top-up rebates stay spendable on
# normal store services, but they are not cash-equivalent customer funds.
_REFUNDABLE_CREDIT_TYPES = frozenset({"topup"})
_BONUS_FIRST_DEBIT_TYPES = frozenset({
    "topup_bonus_reversal",
    "bonus_reversal",
})


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
            "CREATE INDEX IF NOT EXISTS idx_wallet_tx_reference "
            "ON wallet_transactions(customer_discord_id, order_no, type)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_wallet_tx_payment_channel "
            "ON wallet_transactions(customer_discord_id, order_channel_id, type)"
        )

        # Acceptance-payment wallet debits happen before a formal receipt/order_no
        # exists. The ticket channel is therefore the stable payment idempotency key.
        # Keep this as a trigger (rather than a unique-index migration) so historical
        # duplicate rows, if any, do not make startup fail while all future duplicate
        # debits are still blocked.
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

        # Even if historical duplicate references already exist, this trigger blocks
        # all future duplicates. This is safer than blindly deleting old financial rows.
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


def _consume_wallet_bucket(
    *,
    principal: int,
    bonus: int,
    debit: int,
    bonus_first: bool,
) -> tuple[int, int]:
    """Consume wallet buckets without ever making either source negative."""
    remaining = max(0, int(debit or 0))
    principal = max(0, int(principal or 0))
    bonus = max(0, int(bonus or 0))

    if bonus_first:
        take = min(bonus, remaining)
        bonus -= take
        remaining -= take
        take = min(principal, remaining)
        principal -= take
    else:
        take = min(principal, remaining)
        principal -= take
        remaining -= take
        take = min(bonus, remaining)
        bonus -= take

    return principal, bonus


def _wallet_fund_breakdown_from_conn(
    conn: sqlite3.Connection,
    customer_id: str | int,
    *,
    current_balance: int | None = None,
) -> dict[str, int]:
    """Rebuild refundable principal vs non-cash credit from the transaction ledger.

    Normal spending consumes paid principal first. This intentionally makes the
    refundable amount shrink as soon as a service is purchased, preventing a
    customer from spending free credit first and later refunding all paid cash.

    Historical/manual positive credits that are not an explicit `topup` are
    classified conservatively as non-refundable. Any legacy wallet balance that
    predates transaction history is also non-refundable because the system cannot
    prove it was paid cash.
    """
    customer = str(customer_id)
    principal = 0
    bonus = 0

    rows = conn.execute(
        """
        SELECT amount, type
        FROM wallet_transactions
        WHERE customer_discord_id = ?
        ORDER BY id ASC
        """,
        (customer,),
    ).fetchall()

    for row in rows:
        amount = int(row["amount"] or 0)
        tx_type = str(row["type"] or "").strip()

        if amount > 0:
            if tx_type in _REFUNDABLE_CREDIT_TYPES:
                principal += amount
            else:
                bonus += amount
            continue

        if amount < 0:
            principal, bonus = _consume_wallet_bucket(
                principal=principal,
                bonus=bonus,
                debit=abs(amount),
                bonus_first=tx_type in _BONUS_FIRST_DEBIT_TYPES,
            )

    if current_balance is None:
        row = conn.execute(
            "SELECT balance FROM customer_wallets WHERE customer_discord_id=?",
            (customer,),
        ).fetchone()
        current_balance = int(row["balance"] or 0) if row else 0

    balance = max(0, int(current_balance or 0))
    reconstructed = principal + bonus

    if reconstructed < balance:
        # Legacy balance without a traceable paid-cash source is usable store
        # credit, but it must not become refundable cash by assumption.
        bonus += balance - reconstructed
    elif reconstructed > balance:
        overflow = reconstructed - balance
        remove_bonus = min(bonus, overflow)
        bonus -= remove_bonus
        overflow -= remove_bonus
        if overflow > 0:
            principal = max(0, principal - overflow)

    return {
        "balance": balance,
        "refundable_principal": min(principal, balance),
        "nonrefundable_credit": max(0, balance - min(principal, balance)),
    }


def get_wallet_fund_breakdown(
    customer_id: str | int,
    db_file: str | Path | None = None,
) -> dict[str, int]:
    """Return total balance, refundable paid principal and non-cash credit."""
    ensure_wallet_tables(db_file)
    path = _db_path(db_file)
    with sqlite3.connect(path, timeout=15) as conn:
        conn.row_factory = sqlite3.Row
        return _wallet_fund_breakdown_from_conn(conn, customer_id)


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


def get_wallet_payment_transaction(
    customer_id: str | int,
    order_channel_id: str | int,
    *,
    db_file: str | Path | None = None,
) -> dict[str, Any] | None:
    """Return the original wallet debit for a Discord order ticket, if any."""
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
    """Return newest wallet transactions for one customer.

    Persistence stays centralized here so Discord/Web callers do not open the
    wallet tables independently.
    """
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

        # Idempotency checks must happen inside the same write transaction and before
        # balance calculation. A Discord order payment is keyed by ticket channel because
        # the formal receipt/order number is generated only after wallet debit succeeds.
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

        # Non-order flows and legacy callers can still use the formal reference key.
        if normalized_order_no:
            existing = conn.execute(
                """
                SELECT *
                FROM wallet_transactions
                WHERE customer_discord_id=? AND order_no=? AND type=?
                ORDER BY id ASC
                LIMIT 1
                """,
                (
                    str(customer_id),
                    normalized_order_no,
                    normalized_type,
                ),
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
            "SELECT balance FROM customer_wallets WHERE customer_discord_id=?",
            (str(customer_id),),
        ).fetchone()
        before = int(row["balance"] or 0) if row else 0

        if normalized_type == "tip_payment" and amount < 0:
            funds = _wallet_fund_breakdown_from_conn(
                conn,
                customer_id,
                current_balance=before,
            )
            principal = int(funds["refundable_principal"])
            if abs(amount) > principal:
                raise ValueError(
                    "雞腿／打賞只能使用實付儲值本金。"
                    f"目前可用本金 {principal:,}T，"
                    f"不足支付 {abs(amount):,}T。"
                )

        after = before + amount
        if after < 0 and not allow_negative:
            raise ValueError(
                f"錢包餘額不足，目前餘額 {before:,}T，"
                f"無法扣除 {abs(amount):,}T。"
            )

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
                str(customer_id), amount, before, after, normalized_type,
                normalized_order_channel_id,
                normalized_order_no,
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

            audit_db_file = (
                Path(db_file).with_name("web_dashboard.db")
                if db_file is not None
                else None
            )

            write_sqlite_audit_log(
                admin_discord_id=str(operator_discord_id),
                action="wallet_adjustment",
                target_type="customer_wallet",
                target_id=str(customer_id),
                before={
                    "customer_discord_id": str(customer_id),
                    "balance": before,
                },
                after={
                    "customer_discord_id": str(customer_id),
                    "balance": after,
                    "amount": amount,
                    "transaction_id": tx_id,
                    "transaction_type": normalized_type,
                    "order_no": normalized_order_no,
                    "order_channel_id": (
                        str(order_channel_id)
                        if order_channel_id is not None
                        else None
                    ),
                    "note": str(note or "").strip() or None,
                    "operator_display_name": (
                        str(operator_display_name or "").strip() or None
                    ),
                },
                reason=str(note or "").strip() or None,
                db_file=audit_db_file,
            )
        except Exception as exc:
            # Audit must never roll back an already committed wallet transaction.
            print(
                f"[audit] wallet log failed tx_id={tx_id}: "
                f"{type(exc).__name__}: {exc}",
                flush=True,
            )

    return transaction
