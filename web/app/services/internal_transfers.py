from __future__ import annotations

from core.time_utils import utc_now_naive
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

from web.app.config import config


PENDING = "pending"
APPROVED = "approved"
REJECTED = "rejected"
CANCELLED = "cancelled"


def db_path() -> str:
    url = str(getattr(config, "DATABASE_URL", "") or "")
    if url.startswith("sqlite:///"):
        return url.replace("sqlite:///", "", 1)
    return str(Path.cwd() / "web_dashboard.db")


def _connect(database_path: str | None = None) -> sqlite3.Connection:
    conn = sqlite3.connect(database_path or db_path(), timeout=15)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def _now_text() -> str:
    return (utc_now_naive() + timedelta(hours=8)).strftime("%Y-%m-%d %H:%M:%S")


def ensure_internal_transfer_tables(database_path: str | None = None) -> None:
    conn = _connect(database_path)
    try:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS employee_internal_transfers (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                from_employee_discord_id TEXT NOT NULL,
                from_employee_display_name TEXT,
                to_employee_discord_id TEXT NOT NULL,
                to_employee_display_name TEXT,
                amount INTEGER NOT NULL,
                reason TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL DEFAULT 'pending',
                created_by_discord_id TEXT NOT NULL,
                created_by_display_name TEXT,
                created_by_role TEXT NOT NULL DEFAULT 'employee',
                reviewed_by_discord_id TEXT,
                reviewed_by_display_name TEXT,
                review_note TEXT,
                reviewed_at TEXT,
                approved_at TEXT,
                cancelled_at TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_employee_internal_transfers_from
            ON employee_internal_transfers(from_employee_discord_id, status);

            CREATE INDEX IF NOT EXISTS idx_employee_internal_transfers_to
            ON employee_internal_transfers(to_employee_discord_id, status);

            CREATE INDEX IF NOT EXISTS idx_employee_internal_transfers_status
            ON employee_internal_transfers(status, created_at);

            CREATE TABLE IF NOT EXISTS employee_payroll_adjustments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                transfer_id INTEGER NOT NULL,
                employee_discord_id TEXT NOT NULL,
                employee_display_name TEXT,
                counterparty_discord_id TEXT NOT NULL,
                counterparty_display_name TEXT,
                direction TEXT NOT NULL,
                amount INTEGER NOT NULL,
                reason TEXT NOT NULL DEFAULT '',
                payout_status TEXT NOT NULL DEFAULT 'unpaid',
                paid_at TEXT,
                effective_at TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY(transfer_id) REFERENCES employee_internal_transfers(id)
            );

            CREATE UNIQUE INDEX IF NOT EXISTS uq_employee_payroll_adjustment_leg
            ON employee_payroll_adjustments(transfer_id, direction);

            CREATE INDEX IF NOT EXISTS idx_employee_payroll_adjustments_employee
            ON employee_payroll_adjustments(employee_discord_id, payout_status, effective_at);
            """
        )
        conn.commit()
    finally:
        conn.close()


def _display_name(row: sqlite3.Row | dict | None, fallback: str = "") -> str:
    if not row:
        return str(fallback or "")
    getter = row.__getitem__ if isinstance(row, sqlite3.Row) else row.get
    for key in ("display_name", "global_name", "username", "discord_id"):
        try:
            value = getter(key)
        except Exception:
            value = None
        if str(value or "").strip():
            return str(value).strip()
    return str(fallback or "")


def _staff_row(conn: sqlite3.Connection, discord_id: str) -> sqlite3.Row | None:
    return conn.execute(
        """
        SELECT discord_id, username, display_name, global_name,
               COALESCE(is_customer_service, 0) AS is_customer_service,
               COALESCE(is_worker, 0) AS is_worker,
               COALESCE(is_companion, 0) AS is_companion,
               COALESCE(is_active, 0) AS is_active
        FROM web_staff_members
        WHERE CAST(discord_id AS TEXT) = ?
          AND COALESCE(is_active, 0) = 1
        LIMIT 1
        """,
        (str(discord_id),),
    ).fetchone()


def list_internal_employees(*, include_balances: bool = False) -> list[dict]:
    ensure_internal_transfer_tables()
    conn = _connect()
    try:
        rows = conn.execute(
            """
            SELECT discord_id, username, display_name, global_name,
                   COALESCE(is_customer_service, 0) AS is_customer_service,
                   COALESCE(is_worker, 0) AS is_worker,
                   COALESCE(is_companion, 0) AS is_companion
            FROM web_staff_members
            WHERE COALESCE(is_active, 0) = 1
            ORDER BY COALESCE(NULLIF(display_name, ''), NULLIF(global_name, ''), username, discord_id)
            """
        ).fetchall()

        result: list[dict] = []
        for row in rows:
            item = dict(row)
            item["name"] = _display_name(row, str(row["discord_id"] or ""))
            if include_balances:
                balance = _available_unpaid_balance(conn, str(row["discord_id"] or ""))
                item.update(balance)
            result.append(item)
        return result
    finally:
        conn.close()


def _sum_unpaid_sources(conn: sqlite3.Connection, discord_id: str) -> int:
    worker = conn.execute(
        """
        SELECT COALESCE(SUM(p.final_payout), 0)
        FROM worker_payouts p
        JOIN web_orders w ON w.id = p.order_id
        WHERE w.status = 'closed'
          AND CAST(p.worker_discord_id AS TEXT) = ?
          AND COALESCE(p.payout_status, 'unpaid') <> 'paid'
          AND COALESCE(p.final_payout, 0) > 0
        """,
        (discord_id,),
    ).fetchone()[0]

    tips = conn.execute(
        """
        SELECT COALESCE(SUM(t.amount), 0)
        FROM worker_tips t
        JOIN web_orders w ON w.id = t.order_id
        WHERE w.status = 'closed'
          AND t.payment_status = 'paid'
          AND CAST(t.worker_discord_id AS TEXT) = ?
          AND COALESCE(t.payout_status, 'unpaid') <> 'paid'
          AND COALESCE(t.amount, 0) > 0
        """,
        (discord_id,),
    ).fetchone()[0]

    customer_service = conn.execute(
        """
        SELECT COALESCE(SUM(p.payout_amount), 0)
        FROM customer_service_payouts p
        JOIN web_orders w ON w.id = p.order_id
        WHERE w.status = 'closed'
          AND CAST(p.customer_service_discord_id AS TEXT) = ?
          AND COALESCE(p.customer_service_discord_id, '') <> ''
          AND COALESCE(p.customer_service_discord_id, '') <> 'demo_customer_service'
          AND COALESCE(p.customer_service_display_name, '') <> '測試客服'
          AND COALESCE(p.payout_status, 'unpaid') <> 'paid'
          AND COALESCE(p.payout_amount, 0) > 0
        """,
        (discord_id,),
    ).fetchone()[0]

    return int(worker or 0) + int(tips or 0) + int(customer_service or 0)


def _available_unpaid_balance(
    conn: sqlite3.Connection,
    discord_id: str,
    *,
    exclude_pending_transfer_id: int | None = None,
) -> dict:
    discord_id = str(discord_id or "").strip()
    base = _sum_unpaid_sources(conn, discord_id)

    adjustment = conn.execute(
        """
        SELECT COALESCE(SUM(amount), 0)
        FROM employee_payroll_adjustments
        WHERE employee_discord_id = ?
          AND payout_status = 'unpaid'
        """,
        (discord_id,),
    ).fetchone()[0]

    if exclude_pending_transfer_id is None:
        reserved = conn.execute(
            """
            SELECT COALESCE(SUM(amount), 0)
            FROM employee_internal_transfers
            WHERE from_employee_discord_id = ?
              AND status = 'pending'
            """,
            (discord_id,),
        ).fetchone()[0]
    else:
        reserved = conn.execute(
            """
            SELECT COALESCE(SUM(amount), 0)
            FROM employee_internal_transfers
            WHERE from_employee_discord_id = ?
              AND status = 'pending'
              AND id <> ?
            """,
            (discord_id, int(exclude_pending_transfer_id)),
        ).fetchone()[0]

    gross_available = int(base or 0) + int(adjustment or 0)
    available = max(0, gross_available - int(reserved or 0))
    return {
        "base_unpaid": int(base or 0),
        "adjustment_unpaid": int(adjustment or 0),
        "reserved_amount": int(reserved or 0),
        "available_amount": int(available),
    }


def get_available_unpaid_balance(discord_id: str) -> dict:
    ensure_internal_transfer_tables()
    conn = _connect()
    try:
        return _available_unpaid_balance(conn, discord_id)
    finally:
        conn.close()


def _insert_adjustment_legs(
    conn: sqlite3.Connection,
    *,
    transfer_id: int,
    from_id: str,
    from_name: str,
    to_id: str,
    to_name: str,
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
        ) VALUES (?, ?, ?, ?, ?, 'outgoing', ?, ?, ?, ?, ?, ?)
        """,
        (
            int(transfer_id), from_id, from_name, to_id, to_name,
            -int(amount), str(reason), "unpaid", effective_at, effective_at, effective_at,
        ),
    )
    conn.execute(
        """
        INSERT INTO employee_payroll_adjustments (
            transfer_id, employee_discord_id, employee_display_name,
            counterparty_discord_id, counterparty_display_name,
            direction, amount, reason, payout_status,
            effective_at, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, 'incoming', ?, ?, ?, ?, ?, ?)
        """,
        (
            int(transfer_id), to_id, to_name, from_id, from_name,
            int(amount), str(reason), "unpaid", effective_at, effective_at, effective_at,
        ),
    )


def create_internal_transfer(
    *,
    actor_discord_id: str,
    actor_display_name: str,
    from_employee_discord_id: str,
    to_employee_discord_id: str,
    amount: int,
    reason: str,
    actor_is_customer_service: bool = False,
    actor_is_manager: bool = False,
) -> dict:
    ensure_internal_transfer_tables()
    actor_id = str(actor_discord_id or "").strip()
    from_id = str(from_employee_discord_id or "").strip()
    to_id = str(to_employee_discord_id or "").strip()
    actor_name = str(actor_display_name or actor_id).strip()
    clean_reason = str(reason or "").strip()[:500]

    if not actor_id:
        raise ValueError("登入資料不完整。")
    if not from_id or not to_id:
        raise ValueError("請選擇轉出人與收款人。")
    if from_id == to_id:
        raise ValueError("不能轉給自己。")

    try:
        amount = int(amount)
    except (TypeError, ValueError):
        raise ValueError("金額格式錯誤。")
    if amount <= 0:
        raise ValueError("轉帳金額必須大於 0T。")
    if amount > 1_000_000:
        raise ValueError("單筆內部轉帳上限為 1,000,000T。")
    if not clean_reason:
        raise ValueError("請填寫分錢原因，方便客服審核與之後對帳。")

    is_reviewer = bool(actor_is_customer_service or actor_is_manager)
    if not is_reviewer and from_id != actor_id:
        raise ValueError("一般員工只能從自己的待發放薪資發起轉帳。")

    conn = _connect()
    try:
        conn.execute("BEGIN IMMEDIATE")
        from_staff = _staff_row(conn, from_id)
        to_staff = _staff_row(conn, to_id)
        if from_staff is None:
            raise ValueError("轉出人目前不是有效的內部員工。")
        if to_staff is None:
            raise ValueError("收款人目前不是有效的內部員工。")

        from_name = _display_name(from_staff, from_id)
        to_name = _display_name(to_staff, to_id)
        balance = _available_unpaid_balance(conn, from_id)
        if int(balance["available_amount"]) < amount:
            raise ValueError(
                f"{from_name}目前可分的待發放薪資只有 {balance['available_amount']}T。"
            )

        now = _now_text()
        status = APPROVED if is_reviewer else PENDING
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
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                from_id, from_name, to_id, to_name, amount, clean_reason, status,
                actor_id, actor_name, actor_role,
                actor_id if is_reviewer else None,
                actor_name if is_reviewer else None,
                now if is_reviewer else None,
                now if is_reviewer else None,
                now, now,
            ),
        )
        transfer_id = int(cur.lastrowid)

        if is_reviewer:
            _insert_adjustment_legs(
                conn,
                transfer_id=transfer_id,
                from_id=from_id,
                from_name=from_name,
                to_id=to_id,
                to_name=to_name,
                amount=amount,
                reason=clean_reason,
                effective_at=now,
            )

        conn.commit()
        return {
            "id": transfer_id,
            "status": status,
            "auto_approved": is_reviewer,
            "from_name": from_name,
            "to_name": to_name,
            "amount": amount,
        }
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def review_internal_transfer(
    *,
    transfer_id: int,
    reviewer_discord_id: str,
    reviewer_display_name: str,
    approve: bool,
    reviewer_is_customer_service: bool = False,
    reviewer_is_manager: bool = False,
    review_note: str = "",
) -> dict:
    ensure_internal_transfer_tables()
    if not (reviewer_is_customer_service or reviewer_is_manager):
        raise ValueError("只有客服或總管可以審核內部轉帳。")

    reviewer_id = str(reviewer_discord_id or "").strip()
    reviewer_name = str(reviewer_display_name or reviewer_id).strip()
    clean_note = str(review_note or "").strip()[:500]
    if not reviewer_id:
        raise ValueError("登入資料不完整。")

    conn = _connect()
    try:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute(
            "SELECT * FROM employee_internal_transfers WHERE id = ? LIMIT 1",
            (int(transfer_id),),
        ).fetchone()
        if row is None:
            raise ValueError("找不到這筆內部轉帳。")
        if str(row["status"] or "") != PENDING:
            raise ValueError("這筆內部轉帳已經處理過了。")

        now = _now_text()
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
            return {"id": int(transfer_id), "status": REJECTED}

        from_id = str(row["from_employee_discord_id"] or "")
        to_id = str(row["to_employee_discord_id"] or "")
        amount = int(row["amount"] or 0)
        if _staff_row(conn, from_id) is None or _staff_row(conn, to_id) is None:
            raise ValueError("轉出人或收款人已不在有效員工名單，無法核准。")

        balance = _available_unpaid_balance(
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
        _insert_adjustment_legs(
            conn,
            transfer_id=int(transfer_id),
            from_id=from_id,
            from_name=str(row["from_employee_display_name"] or from_id),
            to_id=to_id,
            to_name=str(row["to_employee_display_name"] or to_id),
            amount=amount,
            reason=str(row["reason"] or ""),
            effective_at=now,
        )
        conn.commit()
        return {"id": int(transfer_id), "status": APPROVED}
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def cancel_internal_transfer(
    *,
    transfer_id: int,
    actor_discord_id: str,
    actor_is_customer_service: bool = False,
    actor_is_manager: bool = False,
) -> dict:
    ensure_internal_transfer_tables()
    actor_id = str(actor_discord_id or "").strip()
    conn = _connect()
    try:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute(
            "SELECT * FROM employee_internal_transfers WHERE id = ? LIMIT 1",
            (int(transfer_id),),
        ).fetchone()
        if row is None:
            raise ValueError("找不到這筆內部轉帳。")
        if str(row["status"] or "") != PENDING:
            raise ValueError("只有待審核的轉帳可以取消。")
        allowed = (
            actor_id == str(row["created_by_discord_id"] or "")
            or actor_id == str(row["from_employee_discord_id"] or "")
            or actor_is_customer_service
            or actor_is_manager
        )
        if not allowed:
            raise ValueError("你不能取消這筆轉帳。")
        now = _now_text()
        conn.execute(
            """
            UPDATE employee_internal_transfers
            SET status = 'cancelled', cancelled_at = ?, updated_at = ?
            WHERE id = ?
            """,
            (now, now, int(transfer_id)),
        )
        conn.commit()
        return {"id": int(transfer_id), "status": CANCELLED}
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def list_internal_transfers(
    viewer_discord_id: str,
    *,
    include_all: bool = False,
    limit: int = 200,
) -> list[dict]:
    ensure_internal_transfer_tables()
    viewer_id = str(viewer_discord_id or "").strip()
    conn = _connect()
    try:
        if include_all:
            rows = conn.execute(
                """
                SELECT * FROM employee_internal_transfers
                ORDER BY CASE status WHEN 'pending' THEN 0 ELSE 1 END,
                         id DESC
                LIMIT ?
                """,
                (max(1, min(int(limit), 500)),),
            ).fetchall()
        else:
            rows = conn.execute(
                """
                SELECT * FROM employee_internal_transfers
                WHERE from_employee_discord_id = ?
                   OR to_employee_discord_id = ?
                   OR created_by_discord_id = ?
                ORDER BY id DESC
                LIMIT ?
                """,
                (viewer_id, viewer_id, viewer_id, max(1, min(int(limit), 500))),
            ).fetchall()

        result = []
        for row in rows:
            item = dict(row)
            item["amount"] = int(item.get("amount") or 0)
            item["is_outgoing"] = str(item.get("from_employee_discord_id") or "") == viewer_id
            item["is_incoming"] = str(item.get("to_employee_discord_id") or "") == viewer_id
            item["can_cancel"] = (
                str(item.get("status") or "") == PENDING
                and (
                    str(item.get("created_by_discord_id") or "") == viewer_id
                    or str(item.get("from_employee_discord_id") or "") == viewer_id
                    or include_all
                )
            )
            result.append(item)
        return result
    finally:
        conn.close()


def list_payroll_adjustments(
    *,
    employee_discord_id: str | None = None,
    month: str = "",
    status: str = "all",
) -> list[dict]:
    ensure_internal_transfer_tables()
    clauses = ["1 = 1"]
    params: list[object] = []
    if employee_discord_id:
        clauses.append("employee_discord_id = ?")
        params.append(str(employee_discord_id))
    clean_month = str(month or "").strip()
    if clean_month:
        clauses.append("substr(effective_at, 1, 7) = ?")
        params.append(clean_month)
    clean_status = str(status or "all").strip().lower()
    if clean_status in {"paid", "unpaid"}:
        clauses.append("payout_status = ?")
        params.append(clean_status)

    conn = _connect()
    try:
        rows = conn.execute(
            f"""
            SELECT * FROM employee_payroll_adjustments
            WHERE {' AND '.join(clauses)}
            ORDER BY effective_at DESC, id DESC
            """,
            params,
        ).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


def mark_employee_adjustments(
    *,
    employee_discord_id: str,
    target_status: str,
    month: str = "",
) -> None:
    ensure_internal_transfer_tables()
    target = "paid" if str(target_status or "") == "paid" else "unpaid"
    employee_id = str(employee_discord_id or "").strip()
    if not employee_id:
        return
    clauses = ["employee_discord_id = ?"]
    params: list[object] = [employee_id]
    clean_month = str(month or "").strip()
    if clean_month:
        clauses.append("substr(effective_at, 1, 7) = ?")
        params.append(clean_month)
    now = _now_text()
    conn = _connect()
    try:
        conn.execute(
            f"""
            UPDATE employee_payroll_adjustments
            SET payout_status = ?,
                paid_at = ?,
                updated_at = ?
            WHERE {' AND '.join(clauses)}
            """,
            [target, now if target == "paid" else None, now, *params],
        )
        conn.commit()
    finally:
        conn.close()


def mark_bulk_adjustments(
    *,
    target_status: str,
    month: str = "",
    role: str = "all",
) -> None:
    ensure_internal_transfer_tables()
    target = "paid" if str(target_status or "") == "paid" else "unpaid"
    clauses = ["1 = 1"]
    params: list[object] = []
    clean_month = str(month or "").strip()
    if clean_month:
        clauses.append("substr(effective_at, 1, 7) = ?")
        params.append(clean_month)

    role_key = str(role or "all").strip().lower()
    if role_key in {"worker", "護航 / 陪玩"}:
        clauses.append(
            "employee_discord_id IN ("
            "SELECT discord_id FROM web_staff_members "
            "WHERE COALESCE(is_active,0)=1 AND (COALESCE(is_worker,0)=1 OR COALESCE(is_companion,0)=1)"
            ")"
        )
    elif role_key in {"customer_service", "客服"}:
        clauses.append(
            "employee_discord_id IN ("
            "SELECT discord_id FROM web_staff_members "
            "WHERE COALESCE(is_active,0)=1 AND COALESCE(is_customer_service,0)=1"
            ")"
        )

    now = _now_text()
    conn = _connect()
    try:
        conn.execute(
            f"""
            UPDATE employee_payroll_adjustments
            SET payout_status = ?, paid_at = ?, updated_at = ?
            WHERE {' AND '.join(clauses)}
            """,
            [target, now if target == "paid" else None, now, *params],
        )
        conn.commit()
    finally:
        conn.close()
