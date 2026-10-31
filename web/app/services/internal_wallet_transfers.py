from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from core.vip_levels import BASE_MEMBER_LEVELS, has_active_vip_progress_reset
from services.wallet_atomic_credit import credit_principal_in_connection
from services.wallet_service import ensure_wallet_tables
from web.app.services import internal_transfers as payroll


SELF_WALLET_DESTINATION = "__my_wallet__"
WALLET_TRANSACTION_TYPE = "salary_wallet_transfer"


def wallet_db_path() -> str:
    return str(Path(__file__).resolve().parents[3] / "bot.db")


def ensure_internal_wallet_transfer_tables() -> None:
    payroll.ensure_internal_transfer_tables()
    conn = payroll._connect()
    try:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS employee_internal_wallet_transfers (
                transfer_id INTEGER PRIMARY KEY,
                wallet_customer_discord_id TEXT NOT NULL,
                wallet_transaction_id INTEGER,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY(transfer_id) REFERENCES employee_internal_transfers(id)
            );

            CREATE INDEX IF NOT EXISTS idx_employee_internal_wallet_transfers_customer
            ON employee_internal_wallet_transfers(wallet_customer_discord_id, transfer_id);
            """
        )
        conn.commit()
    finally:
        conn.close()


def is_internal_wallet_transfer(transfer_id: int) -> bool:
    ensure_internal_wallet_transfer_tables()
    conn = payroll._connect()
    try:
        row = conn.execute(
            "SELECT 1 FROM employee_internal_wallet_transfers WHERE transfer_id = ? LIMIT 1",
            (int(transfer_id),),
        ).fetchone()
        return row is not None
    finally:
        conn.close()


def _connect_with_wallet() -> sqlite3.Connection:
    ensure_internal_wallet_transfer_tables()
    wallet_path = wallet_db_path()
    ensure_wallet_tables(wallet_path)
    conn = payroll._connect()
    conn.execute("ATTACH DATABASE ? AS walletdb", (wallet_path,))
    return conn


def _insert_outgoing_adjustment(
    conn: sqlite3.Connection,
    *,
    transfer_id: int,
    from_id: str,
    from_name: str,
    amount: int,
    reason: str,
    effective_at: str,
) -> None:
    conn.execute(
        """
        INSERT INTO employee_payroll_adjustments (
            transfer_id, employee_discord_id, employee_display_name,
            counterparty_discord_id, counterparty_display_name,
            direction, amount, reason, payout_status,
            effective_at, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, 'outgoing', ?, ?, 'unpaid', ?, ?, ?)
        """,
        (
            int(transfer_id),
            from_id,
            from_name,
            from_id,
            "我的錢包",
            -int(amount),
            str(reason),
            effective_at,
            effective_at,
            effective_at,
        ),
    )


def _credit_wallet(
    conn: sqlite3.Connection,
    *,
    transfer_id: int,
    wallet_customer_id: str,
    amount: int,
    operator_discord_id: str,
    operator_display_name: str,
    source_display_name: str,
    reason: str,
) -> int:
    wallet_id = str(wallet_customer_id or "").strip()
    if not wallet_id:
        raise ValueError("無法確認要入帳的本人錢包。")

    result = credit_principal_in_connection(
        conn,
        customer_id=wallet_id,
        amount=int(amount),
        tx_type=WALLET_TRANSACTION_TYPE,
        order_no=f"salary-wallet:{int(transfer_id)}",
        operator_discord_id=operator_discord_id,
        operator_display_name=operator_display_name,
        note=f"待發放薪資轉入本人錢包｜{source_display_name}｜{reason}",
        schema="walletdb",
    )
    return int(result["transaction_id"])


def _vip_level_index_for_total(total_spent: int) -> int:
    index = 0
    for i, level in enumerate(BASE_MEMBER_LEVELS):
        if int(total_spent) >= int(level["threshold"]):
            index = i
        else:
            break
    return index


def _effective_vip_level_index(data: dict) -> int:
    total_spent = int(data.get("total_spent", 0) or 0)
    cumulative_index = _vip_level_index_for_total(total_spent)
    try:
        stored_index = int(data.get("vip_level_index"))
    except (TypeError, ValueError):
        return cumulative_index
    stored_index = max(0, min(stored_index, len(BASE_MEMBER_LEVELS) - 1))
    if stored_index < cumulative_index and has_active_vip_progress_reset(data):
        try:
            base_total = int(data.get("vip_progress_base_total_spent") or 0)
        except (TypeError, ValueError):
            base_total = 0
        earned_after_reset = max(0, total_spent - base_total)
        virtual_total = int(BASE_MEMBER_LEVELS[stored_index]["threshold"]) + earned_after_reset
        progressed_index = _vip_level_index_for_total(virtual_total)
        return max(stored_index, min(progressed_index, len(BASE_MEMBER_LEVELS) - 1))
    return stored_index


def _add_wallet_transfer_vip_progress(
    conn: sqlite3.Connection,
    *,
    customer_id: str,
    amount: int,
    updated_at: str,
) -> None:
    """Count salary-to-own-wallet principal as VIP spend in the same transaction."""
    amount = int(amount)
    if amount <= 0:
        return

    customer_id_text = str(customer_id or "").strip()
    if not customer_id_text:
        return

    # Some lightweight test/maintenance databases only contain wallet tables.
    # In production bot.db the normalized customers table exists; when it does
    # not, wallet credit should still succeed instead of breaking payroll flow.
    customers_table = conn.execute(
        "SELECT 1 FROM walletdb.sqlite_master WHERE type='table' AND name='customers' LIMIT 1"
    ).fetchone()
    if customers_table is None:
        return

    try:
        customer_key: int | str = int(customer_id_text)
    except ValueError:
        customer_key = customer_id_text

    row = conn.execute(
        """
        SELECT customer_id, total_spent, points, completed_orders, last_order_at,
               level, platinum_channel_id, data_json
        FROM walletdb.customers
        WHERE customer_id = ?
        LIMIT 1
        """,
        (customer_key,),
    ).fetchone()

    if row is None:
        data: dict = {
            "total_spent": 0,
            "order_count": 0,
            "last_order_at": None,
            "points": 0,
            "point_adjustment": 0,
            "point_adjustment_logs": [],
            "platinum_channel_id": None,
            "manual_purchase_keys": [],
            "notes": [],
            "vip_level_index": 0,
            "vip_progress_base_total_spent": None,
            "vip_progress_reset_active": False,
            "vip_downgrade_logs": [],
        }
        completed_orders = 0
        last_order_at = None
        platinum_channel_id = None
    else:
        try:
            data = json.loads(row["data_json"] or "{}")
        except (TypeError, json.JSONDecodeError):
            data = {}
        if not isinstance(data, dict):
            data = {}
        data.setdefault("total_spent", int(row["total_spent"] or 0))
        data.setdefault("order_count", int(row["completed_orders"] or 0))
        data.setdefault("points", int(row["points"] or 0))
        data.setdefault("last_order_at", row["last_order_at"])
        completed_orders = int(row["completed_orders"] or data.get("order_count", 0) or 0)
        last_order_at = row["last_order_at"]
        platinum_channel_id = row["platinum_channel_id"]

    old_total = int(data.get("total_spent", 0) or 0)
    data["total_spent"] = old_total + amount
    try:
        stored_index = int(data.get("vip_level_index"))
    except (TypeError, ValueError):
        stored_index = None
    reset_active = has_active_vip_progress_reset(data)
    if stored_index is None:
        data["vip_level_index"] = _vip_level_index_for_total(int(data["total_spent"]))
        data["vip_progress_base_total_spent"] = None
        data["vip_progress_reset_active"] = False
    else:
        effective_index = _effective_vip_level_index(data)
        if effective_index > stored_index:
            data["vip_level_index"] = effective_index
            if reset_active:
                data["vip_progress_base_total_spent"] = int(data["total_spent"])
                data["vip_progress_reset_active"] = True
            else:
                data["vip_progress_base_total_spent"] = None
                data["vip_progress_reset_active"] = False

    effective_index = _effective_vip_level_index(data)
    level_name = str(BASE_MEMBER_LEVELS[effective_index]["name"])
    point_adjustment = int(data.get("point_adjustment", 0) or 0)
    points = max(0, int(data["total_spent"]) // 100 + point_adjustment)
    data["points"] = points

    conn.execute(
        """
        INSERT INTO walletdb.customers (
            customer_id, total_spent, points, completed_orders, last_order_at,
            level, platinum_channel_id, data_json, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(customer_id) DO UPDATE SET
            total_spent = excluded.total_spent,
            points = excluded.points,
            completed_orders = excluded.completed_orders,
            last_order_at = excluded.last_order_at,
            level = excluded.level,
            platinum_channel_id = excluded.platinum_channel_id,
            data_json = excluded.data_json,
            updated_at = excluded.updated_at
        """,
        (
            customer_key,
            int(data["total_spent"]),
            points,
            completed_orders,
            last_order_at,
            level_name,
            platinum_channel_id,
            json.dumps(data, ensure_ascii=False),
            updated_at,
        ),
    )


def create_internal_wallet_transfer(
    *,
    actor_discord_id: str,
    actor_display_name: str,
    from_employee_discord_id: str,
    amount: int,
    reason: str,
    actor_is_customer_service: bool = False,
    actor_is_manager: bool = False,
) -> dict:
    actor_id = str(actor_discord_id or "").strip()
    from_id = str(from_employee_discord_id or "").strip()
    actor_name = str(actor_display_name or actor_id).strip()
    clean_reason = str(reason or "").strip()[:500]

    if not actor_id or not from_id:
        raise ValueError("登入資料或轉出人不完整。")
    try:
        amount = int(amount)
    except (TypeError, ValueError) as exc:
        raise ValueError("金額格式錯誤。") from exc
    if amount <= 0:
        raise ValueError("轉帳金額必須大於 0T。")
    if amount > 1_000_000:
        raise ValueError("單筆內部轉帳上限為 1,000,000T。")
    if not clean_reason:
        raise ValueError("請填寫轉入錢包原因，方便客服審核與之後對帳。")

    is_reviewer = bool(actor_is_customer_service or actor_is_manager)
    if not is_reviewer and from_id != actor_id:
        raise ValueError("一般員工只能把自己的待發放薪資轉入自己的錢包。")

    conn = _connect_with_wallet()
    try:
        conn.execute("BEGIN IMMEDIATE")
        from_staff = payroll._staff_row(conn, from_id)
        if from_staff is None:
            raise ValueError("轉出人目前不是有效的內部員工。")

        from_name = payroll._display_name(from_staff, from_id)
        balance = payroll._available_unpaid_balance(conn, from_id)
        if int(balance["available_amount"]) < amount:
            raise ValueError(
                f"{from_name}目前可分的待發放薪資只有 {balance['available_amount']}T。"
            )

        now = payroll._now_text()
        status = payroll.APPROVED if is_reviewer else payroll.PENDING
        actor_role = "manager" if actor_is_manager else (
            "customer_service" if actor_is_customer_service else "employee"
        )

        cur = conn.execute(
            """
            INSERT INTO employee_internal_transfers (
                from_employee_discord_id, from_employee_display_name,
                to_employee_discord_id, to_employee_display_name,
                amount, reason, status,
                created_by_discord_id, created_by_display_name, created_by_role,
                reviewed_by_discord_id, reviewed_by_display_name,
                reviewed_at, approved_at, created_at, updated_at
            ) VALUES (?, ?, ?, '我的錢包', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                from_id,
                from_name,
                from_id,
                amount,
                clean_reason,
                status,
                actor_id,
                actor_name,
                actor_role,
                actor_id if is_reviewer else None,
                actor_name if is_reviewer else None,
                now if is_reviewer else None,
                now if is_reviewer else None,
                now,
                now,
            ),
        )
        transfer_id = int(cur.lastrowid)
        conn.execute(
            """
            INSERT INTO employee_internal_wallet_transfers (
                transfer_id, wallet_customer_discord_id,
                wallet_transaction_id, created_at, updated_at
            ) VALUES (?, ?, NULL, ?, ?)
            """,
            (transfer_id, from_id, now, now),
        )

        wallet_transaction_id = None
        if is_reviewer:
            _insert_outgoing_adjustment(
                conn,
                transfer_id=transfer_id,
                from_id=from_id,
                from_name=from_name,
                amount=amount,
                reason=clean_reason,
                effective_at=now,
            )
            wallet_transaction_id = _credit_wallet(
                conn,
                transfer_id=transfer_id,
                wallet_customer_id=from_id,
                amount=amount,
                operator_discord_id=actor_id,
                operator_display_name=actor_name,
                source_display_name=from_name,
                reason=clean_reason,
            )
            _add_wallet_transfer_vip_progress(
                conn,
                customer_id=from_id,
                amount=amount,
                updated_at=now,
            )
            conn.execute(
                """
                UPDATE employee_internal_wallet_transfers
                SET wallet_transaction_id = ?, updated_at = ?
                WHERE transfer_id = ?
                """,
                (wallet_transaction_id, now, transfer_id),
            )

        conn.commit()
        return {
            "id": transfer_id,
            "status": status,
            "auto_approved": is_reviewer,
            "from_name": from_name,
            "to_name": "我的錢包",
            "amount": amount,
            "wallet_transaction_id": wallet_transaction_id,
        }
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def review_internal_wallet_transfer(
    *,
    transfer_id: int,
    reviewer_discord_id: str,
    reviewer_display_name: str,
    approve: bool,
    reviewer_is_customer_service: bool = False,
    reviewer_is_manager: bool = False,
    review_note: str = "",
) -> dict:
    if not (reviewer_is_customer_service or reviewer_is_manager):
        raise ValueError("只有客服或總管可以審核內部轉帳。")

    reviewer_id = str(reviewer_discord_id or "").strip()
    reviewer_name = str(reviewer_display_name or reviewer_id).strip()
    clean_note = str(review_note or "").strip()[:500]
    if not reviewer_id:
        raise ValueError("登入資料不完整。")

    conn = _connect_with_wallet()
    try:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute(
            """
            SELECT t.*, w.wallet_customer_discord_id, w.wallet_transaction_id
            FROM employee_internal_transfers t
            JOIN employee_internal_wallet_transfers w ON w.transfer_id = t.id
            WHERE t.id = ?
            LIMIT 1
            """,
            (int(transfer_id),),
        ).fetchone()
        if row is None:
            raise ValueError("找不到這筆薪資轉錢包申請。")
        if str(row["status"] or "") != payroll.PENDING:
            raise ValueError("這筆內部轉帳已經處理過了。")

        now = payroll._now_text()
        if not approve:
            conn.execute(
                """
                UPDATE employee_internal_transfers
                SET status = 'rejected', reviewed_by_discord_id = ?,
                    reviewed_by_display_name = ?, review_note = ?,
                    reviewed_at = ?, updated_at = ?
                WHERE id = ?
                """,
                (reviewer_id, reviewer_name, clean_note, now, now, int(transfer_id)),
            )
            conn.commit()
            return {"id": int(transfer_id), "status": payroll.REJECTED}

        from_id = str(row["from_employee_discord_id"] or "")
        wallet_id = str(row["wallet_customer_discord_id"] or "")
        amount = int(row["amount"] or 0)
        if not from_id or wallet_id != from_id:
            raise ValueError("薪資轉錢包目的地異常，已停止入帳。")
        if payroll._staff_row(conn, from_id) is None:
            raise ValueError("轉出人已不在有效員工名單，無法核准。")

        balance = payroll._available_unpaid_balance(
            conn,
            from_id,
            exclude_pending_transfer_id=int(transfer_id),
        )
        if int(balance["available_amount"]) < amount:
            raise ValueError(
                f"轉出人目前可分的待發放薪資只剩 {balance['available_amount']}T，不能核准這筆 {amount}T。"
            )

        conn.execute(
            """
            UPDATE employee_internal_transfers
            SET status = 'approved', reviewed_by_discord_id = ?,
                reviewed_by_display_name = ?, review_note = ?,
                reviewed_at = ?, approved_at = ?, updated_at = ?
            WHERE id = ?
            """,
            (reviewer_id, reviewer_name, clean_note, now, now, now, int(transfer_id)),
        )
        from_name = str(row["from_employee_display_name"] or from_id)
        _insert_outgoing_adjustment(
            conn,
            transfer_id=int(transfer_id),
            from_id=from_id,
            from_name=from_name,
            amount=amount,
            reason=str(row["reason"] or ""),
            effective_at=now,
        )
        wallet_transaction_id = _credit_wallet(
            conn,
            transfer_id=int(transfer_id),
            wallet_customer_id=wallet_id,
            amount=amount,
            operator_discord_id=reviewer_id,
            operator_display_name=reviewer_name,
            source_display_name=from_name,
            reason=str(row["reason"] or ""),
        )
        _add_wallet_transfer_vip_progress(
            conn,
            customer_id=wallet_id,
            amount=amount,
            updated_at=now,
        )
        conn.execute(
            """
            UPDATE employee_internal_wallet_transfers
            SET wallet_transaction_id = ?, updated_at = ?
            WHERE transfer_id = ?
            """,
            (wallet_transaction_id, now, int(transfer_id)),
        )
        conn.commit()
        return {
            "id": int(transfer_id),
            "status": payroll.APPROVED,
            "wallet_transaction_id": wallet_transaction_id,
        }
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()