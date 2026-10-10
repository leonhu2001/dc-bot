from __future__ import annotations

import sqlite3
from collections import OrderedDict
from datetime import datetime, timedelta, timezone
from pathlib import Path

from web.app.config import config


PENDING = "pending"
APPROVED = "approved"
REJECTED = "rejected"
CANCELLED = "cancelled"

_STATUS_LABELS = {
    PENDING: "待確認",
    APPROVED: "已完成",
    REJECTED: "已拒絕",
    CANCELLED: "已取消",
}


def _now_text() -> str:
    tz = timezone(timedelta(hours=8))
    return datetime.now(tz).replace(tzinfo=None, microsecond=0).isoformat(sep=" ")


def db_path() -> str:
    url = str(getattr(config, "DATABASE_URL", "") or "")
    if url.startswith("sqlite:///"):
        return url.replace("sqlite:///", "", 1)
    return str(Path.cwd() / "web_dashboard.db")


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(db_path(), timeout=15)
    conn.row_factory = sqlite3.Row
    return conn


def ensure_payout_split_tables() -> None:
    conn = _connect()
    try:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS payout_split_requests (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                order_id INTEGER NOT NULL,
                order_no TEXT,
                from_worker_discord_id TEXT NOT NULL,
                from_worker_display_name TEXT,
                to_worker_discord_id TEXT NOT NULL,
                to_worker_display_name TEXT,
                amount INTEGER NOT NULL,
                hours REAL,
                reason TEXT,
                status TEXT NOT NULL DEFAULT 'pending',
                settlement_mode TEXT NOT NULL DEFAULT 'order_payout',
                requested_by_discord_id TEXT NOT NULL,
                requested_by_display_name TEXT,
                decided_by_discord_id TEXT,
                decided_by_display_name TEXT,
                decision_note TEXT,
                from_before_amount INTEGER,
                from_after_amount INTEGER,
                to_before_amount INTEGER,
                to_after_amount INTEGER,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                decided_at TEXT
            )
            """
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_payout_splits_order_status "
            "ON payout_split_requests(order_id, status)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_payout_splits_from_worker "
            "ON payout_split_requests(from_worker_discord_id, status)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_payout_splits_to_worker "
            "ON payout_split_requests(to_worker_discord_id, status)"
        )
        conn.commit()
    finally:
        conn.close()


def _display_name(row: sqlite3.Row, prefix: str) -> str:
    discord_id = str(row[f"{prefix}_discord_id"] or "")
    return str(row[f"{prefix}_display_name"] or discord_id or "未知人員")


def list_eligible_orders(worker_discord_id: str) -> list[dict]:
    """Return closed, unpaid orders where this worker can split pay to a co-worker."""
    ensure_payout_split_tables()
    worker_id = str(worker_discord_id or "").strip()
    if not worker_id:
        return []

    conn = _connect()
    try:
        rows = conn.execute(
            """
            SELECT
                w.id AS order_id,
                COALESCE(NULLIF(w.bot_order_no, ''), 'WEB-' || w.id) AS order_no,
                w.category,
                w.item,
                w.quantity,
                COALESCE(NULLIF(w.closed_at, ''), NULLIF(w.updated_at, ''), NULLIF(w.created_at, '')) AS order_date,
                mine.worker_display_name AS source_display_name,
                COALESCE(mine.final_payout, 0) AS source_amount,
                COALESCE(mine.payout_status, 'unpaid') AS source_status,
                other.worker_discord_id AS target_discord_id,
                other.worker_display_name AS target_display_name,
                COALESCE(other.final_payout, 0) AS target_amount,
                COALESCE(other.payout_status, 'unpaid') AS target_status
            FROM worker_payouts mine
            JOIN web_orders w ON w.id = mine.order_id
            JOIN worker_payouts other
              ON other.order_id = mine.order_id
             AND other.worker_discord_id <> mine.worker_discord_id
            WHERE mine.worker_discord_id = ?
              AND w.status = 'closed'
            ORDER BY order_date DESC, w.id DESC, other.id ASC
            """,
            (worker_id,),
        ).fetchall()

        pending_rows = conn.execute(
            """
            SELECT order_id, COALESCE(SUM(amount), 0) AS reserved_amount
            FROM payout_split_requests
            WHERE from_worker_discord_id = ?
              AND status = 'pending'
            GROUP BY order_id
            """,
            (worker_id,),
        ).fetchall()
        reserved_by_order = {
            int(row["order_id"]): int(row["reserved_amount"] or 0)
            for row in pending_rows
        }

        grouped: OrderedDict[int, dict] = OrderedDict()
        for row in rows:
            order_id = int(row["order_id"])
            source_status = str(row["source_status"] or "unpaid")
            target_status = str(row["target_status"] or "unpaid")

            if source_status != "unpaid" or target_status != "unpaid":
                continue

            if order_id not in grouped:
                source_amount = max(0, int(row["source_amount"] or 0))
                reserved_amount = max(0, int(reserved_by_order.get(order_id, 0)))
                grouped[order_id] = {
                    "order_id": order_id,
                    "order_no": str(row["order_no"] or f"WEB-{order_id}"),
                    "category": str(row["category"] or ""),
                    "item": str(row["item"] or ""),
                    "quantity": int(row["quantity"] or 0),
                    "order_date": str(row["order_date"] or ""),
                    "source_display_name": str(row["source_display_name"] or worker_id),
                    "source_amount": source_amount,
                    "reserved_amount": reserved_amount,
                    "available_amount": max(0, source_amount - reserved_amount),
                    "targets": [],
                }

            grouped[order_id]["targets"].append(
                {
                    "discord_id": str(row["target_discord_id"] or ""),
                    "display_name": str(row["target_display_name"] or row["target_discord_id"] or "未知人員"),
                    "current_amount": int(row["target_amount"] or 0),
                }
            )

        return [
            order
            for order in grouped.values()
            if order["available_amount"] > 0 and order["targets"]
        ]
    finally:
        conn.close()


def _get_worker_payout(conn: sqlite3.Connection, order_id: int, worker_id: str) -> sqlite3.Row | None:
    return conn.execute(
        """
        SELECT id, order_id, worker_discord_id, worker_display_name,
               COALESCE(final_payout, 0) AS final_payout,
               COALESCE(payout_status, 'unpaid') AS payout_status,
               note
        FROM worker_payouts
        WHERE order_id = ? AND worker_discord_id = ?
        ORDER BY id ASC
        LIMIT 1
        """,
        (int(order_id), str(worker_id)),
    ).fetchone()


def create_payout_split(
    *,
    order_id: int,
    from_worker_discord_id: str,
    from_worker_display_name: str,
    to_worker_discord_id: str,
    amount: int,
    hours: float | None = None,
    reason: str | None = None,
) -> int:
    ensure_payout_split_tables()
    source_id = str(from_worker_discord_id or "").strip()
    target_id = str(to_worker_discord_id or "").strip()
    transfer_amount = int(amount or 0)

    if not source_id or not target_id:
        raise ValueError("分帳人員資料不完整。")
    if source_id == target_id:
        raise ValueError("不能把薪資分給自己。")
    if transfer_amount <= 0:
        raise ValueError("分帳金額必須大於 0。")

    normalized_hours: float | None = None
    if hours not in (None, ""):
        try:
            normalized_hours = float(hours)
        except (TypeError, ValueError):
            raise ValueError("時數格式不正確。") from None
        if normalized_hours <= 0:
            raise ValueError("時數必須大於 0。")
        if normalized_hours > 48:
            raise ValueError("單次分帳時數不可超過 48 小時。")

    clean_reason = str(reason or "").strip()
    if not clean_reason:
        raise ValueError("請填寫分帳原因，例如實際陪玩時數不同。")
    if len(clean_reason) > 500:
        clean_reason = clean_reason[:500]

    conn = _connect()
    try:
        conn.execute("BEGIN IMMEDIATE")

        order = conn.execute(
            """
            SELECT id, status, COALESCE(NULLIF(bot_order_no, ''), 'WEB-' || id) AS order_no
            FROM web_orders
            WHERE id = ?
            LIMIT 1
            """,
            (int(order_id),),
        ).fetchone()
        if order is None:
            raise ValueError("找不到這張訂單。")
        if str(order["status"] or "") != "closed":
            raise ValueError("只有已結單的訂單才能進行內部分帳。")

        source = _get_worker_payout(conn, int(order_id), source_id)
        target = _get_worker_payout(conn, int(order_id), target_id)
        if source is None:
            raise ValueError("你不是這張訂單的分潤人員。")
        if target is None:
            raise ValueError("收款人必須是同一張訂單的接單人員。")
        if str(source["payout_status"] or "") != "unpaid":
            raise ValueError("這張單的薪資已經發放，為了保護歷史帳務不能直接分帳。")
        if str(target["payout_status"] or "") != "unpaid":
            raise ValueError("對方這張單的薪資已經發放，不能再直接分帳。")

        reserved = conn.execute(
            """
            SELECT COALESCE(SUM(amount), 0)
            FROM payout_split_requests
            WHERE order_id = ?
              AND from_worker_discord_id = ?
              AND status = 'pending'
            """,
            (int(order_id), source_id),
        ).fetchone()[0]
        available = int(source["final_payout"] or 0) - int(reserved or 0)
        if transfer_amount > available:
            raise ValueError(f"可分帳金額只剩 {max(0, available)}T，請降低金額或先取消其他待確認申請。")

        now = _now_text()
        cursor = conn.execute(
            """
            INSERT INTO payout_split_requests (
                order_id, order_no,
                from_worker_discord_id, from_worker_display_name,
                to_worker_discord_id, to_worker_display_name,
                amount, hours, reason, status, settlement_mode,
                requested_by_discord_id, requested_by_display_name,
                created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending', 'order_payout', ?, ?, ?, ?)
            """,
            (
                int(order_id),
                str(order["order_no"] or f"WEB-{order_id}"),
                source_id,
                str(from_worker_display_name or source["worker_display_name"] or source_id),
                target_id,
                str(target["worker_display_name"] or target_id),
                transfer_amount,
                normalized_hours,
                clean_reason,
                source_id,
                str(from_worker_display_name or source["worker_display_name"] or source_id),
                now,
                now,
            ),
        )
        split_id = int(cursor.lastrowid)
        conn.commit()
        return split_id
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _append_reason(existing: str | None, addition: str) -> str:
    current = str(existing or "").strip()
    if not current:
        return addition[:1000]
    if addition in current:
        return current[:1000]
    return f"{current}｜{addition}"[:1000]


def _set_worker_override(
    conn: sqlite3.Connection,
    *,
    order_id: int,
    worker_id: str,
    display_name: str,
    new_amount: int,
    reason: str,
    actor_id: str,
    actor_name: str,
) -> None:
    existing = conn.execute(
        """
        SELECT id, reason
        FROM worker_payout_overrides
        WHERE order_id = ? AND worker_discord_id = ?
        ORDER BY id ASC
        LIMIT 1
        """,
        (int(order_id), str(worker_id)),
    ).fetchone()
    now = _now_text()

    if existing is None:
        conn.execute(
            """
            INSERT INTO worker_payout_overrides (
                order_id, worker_discord_id, worker_display_name,
                manual_final_payout, reason,
                created_by_discord_id, created_by_display_name,
                created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                int(order_id), str(worker_id), str(display_name or worker_id),
                int(new_amount), reason,
                str(actor_id), str(actor_name or actor_id), now, now,
            ),
        )
    else:
        conn.execute(
            """
            UPDATE worker_payout_overrides
            SET worker_display_name = ?,
                manual_final_payout = ?,
                reason = ?,
                created_by_discord_id = ?,
                created_by_display_name = ?,
                updated_at = ?
            WHERE id = ?
            """,
            (
                str(display_name or worker_id),
                int(new_amount),
                _append_reason(existing["reason"], reason),
                str(actor_id), str(actor_name or actor_id), now,
                int(existing["id"]),
            ),
        )


def decide_payout_split(
    *,
    split_id: int,
    actor_discord_id: str,
    actor_display_name: str,
    approve: bool,
    is_manager: bool = False,
    decision_note: str | None = None,
) -> dict:
    ensure_payout_split_tables()
    actor_id = str(actor_discord_id or "").strip()
    if not actor_id:
        raise ValueError("登入資料不完整。")

    conn = _connect()
    try:
        conn.execute("BEGIN IMMEDIATE")
        split = conn.execute(
            "SELECT * FROM payout_split_requests WHERE id = ? LIMIT 1",
            (int(split_id),),
        ).fetchone()
        if split is None:
            raise ValueError("找不到這筆分帳申請。")
        if str(split["status"] or "") != PENDING:
            raise ValueError("這筆分帳已經處理過了。")

        target_id = str(split["to_worker_discord_id"] or "")
        if actor_id != target_id and not is_manager:
            raise ValueError("只有收款人或總管可以確認這筆分帳。")

        now = _now_text()
        clean_note = str(decision_note or "").strip()[:500]

        if not approve:
            conn.execute(
                """
                UPDATE payout_split_requests
                SET status = 'rejected',
                    decided_by_discord_id = ?,
                    decided_by_display_name = ?,
                    decision_note = ?,
                    decided_at = ?, updated_at = ?
                WHERE id = ?
                """,
                (actor_id, str(actor_display_name or actor_id), clean_note, now, now, int(split_id)),
            )
            conn.commit()
            return {"id": int(split_id), "status": REJECTED}

        source_id = str(split["from_worker_discord_id"] or "")
        order_id = int(split["order_id"])
        amount = int(split["amount"] or 0)
        source = _get_worker_payout(conn, order_id, source_id)
        target = _get_worker_payout(conn, order_id, target_id)

        if source is None or target is None:
            raise ValueError("這張訂單的薪資資料已改變，無法完成分帳。")
        if str(source["payout_status"] or "") != "unpaid" or str(target["payout_status"] or "") != "unpaid":
            raise ValueError("薪資已經發放，為了保護歷史帳務，這筆分帳不能直接套用。")

        source_before = int(source["final_payout"] or 0)
        target_before = int(target["final_payout"] or 0)
        if amount <= 0 or amount > source_before:
            raise ValueError(f"轉出人的目前可用薪資只有 {max(0, source_before)}T，無法完成這筆分帳。")

        source_after = source_before - amount
        target_after = target_before + amount
        split_reason = f"內部分帳 #{int(split_id)}（{source_id} → {target_id}，{amount}T）"

        _set_worker_override(
            conn,
            order_id=order_id,
            worker_id=source_id,
            display_name=str(source["worker_display_name"] or source_id),
            new_amount=source_after,
            reason=split_reason,
            actor_id=actor_id,
            actor_name=actor_display_name,
        )
        _set_worker_override(
            conn,
            order_id=order_id,
            worker_id=target_id,
            display_name=str(target["worker_display_name"] or target_id),
            new_amount=target_after,
            reason=split_reason,
            actor_id=actor_id,
            actor_name=actor_display_name,
        )

        conn.execute(
            """
            UPDATE worker_payouts
            SET final_payout = ?,
                note = CASE
                    WHEN COALESCE(note, '') = '' THEN ?
                    ELSE note || '｜' || ?
                END,
                updated_at = ?
            WHERE id = ?
            """,
            (source_after, split_reason, split_reason, now, int(source["id"])),
        )
        conn.execute(
            """
            UPDATE worker_payouts
            SET final_payout = ?,
                note = CASE
                    WHEN COALESCE(note, '') = '' THEN ?
                    ELSE note || '｜' || ?
                END,
                updated_at = ?
            WHERE id = ?
            """,
            (target_after, split_reason, split_reason, now, int(target["id"])),
        )

        conn.execute(
            """
            UPDATE payout_split_requests
            SET status = 'approved',
                decided_by_discord_id = ?,
                decided_by_display_name = ?,
                decision_note = ?,
                from_before_amount = ?, from_after_amount = ?,
                to_before_amount = ?, to_after_amount = ?,
                decided_at = ?, updated_at = ?
            WHERE id = ?
            """,
            (
                actor_id, str(actor_display_name or actor_id), clean_note,
                source_before, source_after, target_before, target_after,
                now, now, int(split_id),
            ),
        )
        conn.commit()
        return {
            "id": int(split_id),
            "status": APPROVED,
            "from_before_amount": source_before,
            "from_after_amount": source_after,
            "to_before_amount": target_before,
            "to_after_amount": target_after,
        }
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def cancel_payout_split(
    *,
    split_id: int,
    actor_discord_id: str,
    actor_display_name: str,
    is_manager: bool = False,
) -> None:
    ensure_payout_split_tables()
    actor_id = str(actor_discord_id or "").strip()
    conn = _connect()
    try:
        conn.execute("BEGIN IMMEDIATE")
        split = conn.execute(
            "SELECT * FROM payout_split_requests WHERE id = ? LIMIT 1",
            (int(split_id),),
        ).fetchone()
        if split is None:
            raise ValueError("找不到這筆分帳申請。")
        if str(split["status"] or "") != PENDING:
            raise ValueError("只有待確認的分帳可以取消。")
        if actor_id != str(split["from_worker_discord_id"] or "") and not is_manager:
            raise ValueError("只有發起人或總管可以取消這筆分帳。")

        now = _now_text()
        conn.execute(
            """
            UPDATE payout_split_requests
            SET status = 'cancelled',
                decided_by_discord_id = ?,
                decided_by_display_name = ?,
                decided_at = ?, updated_at = ?
            WHERE id = ?
            """,
            (actor_id, str(actor_display_name or actor_id), now, now, int(split_id)),
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def list_payout_splits(
    worker_discord_id: str,
    *,
    include_all: bool = False,
    limit: int = 100,
) -> list[dict]:
    ensure_payout_split_tables()
    worker_id = str(worker_discord_id or "").strip()
    limit = max(1, min(int(limit or 100), 300))

    conn = _connect()
    try:
        if include_all:
            rows = conn.execute(
                "SELECT * FROM payout_split_requests ORDER BY id DESC LIMIT ?",
                (limit,),
            ).fetchall()
        else:
            rows = conn.execute(
                """
                SELECT *
                FROM payout_split_requests
                WHERE from_worker_discord_id = ? OR to_worker_discord_id = ?
                ORDER BY id DESC
                LIMIT ?
                """,
                (worker_id, worker_id, limit),
            ).fetchall()

        result: list[dict] = []
        for row in rows:
            item = dict(row)
            status = str(item.get("status") or PENDING)
            source_id = str(item.get("from_worker_discord_id") or "")
            target_id = str(item.get("to_worker_discord_id") or "")
            item["status_label"] = _STATUS_LABELS.get(status, status)
            item["from_worker_display_name"] = str(item.get("from_worker_display_name") or source_id)
            item["to_worker_display_name"] = str(item.get("to_worker_display_name") or target_id)
            item["can_approve"] = status == PENDING and (include_all or worker_id == target_id)
            item["can_cancel"] = status == PENDING and (include_all or worker_id == source_id)
            if worker_id == source_id:
                item["direction_label"] = "轉出"
                item["counterparty_name"] = item["to_worker_display_name"]
            elif worker_id == target_id:
                item["direction_label"] = "轉入"
                item["counterparty_name"] = item["from_worker_display_name"]
            else:
                item["direction_label"] = "管理"
                item["counterparty_name"] = f"{item['from_worker_display_name']} → {item['to_worker_display_name']}"
            result.append(item)
        return result
    finally:
        conn.close()
