from __future__ import annotations

import sqlite3
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any

from core.vip_levels import BASE_MEMBER_LEVELS, get_topup_rebate_percent

TAIPEI_TZ = timezone(timedelta(hours=8))


def _now_iso() -> str:
    return datetime.now(TAIPEI_TZ).isoformat(timespec="seconds")


def _db_path(db_file: str | Path | None = None) -> Path:
    if db_file is not None:
        return Path(db_file)
    root = Path(__file__).resolve().parents[1]
    return root / "bot.db"


def ensure_topup_tables(db_file: str | Path | None = None) -> None:
    path = _db_path(db_file)
    with sqlite3.connect(path, timeout=15) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS topup_orders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                topup_no TEXT UNIQUE,
                customer_discord_id TEXT NOT NULL,
                customer_display_name TEXT,
                amount INTEGER NOT NULL,
                payment_method TEXT NOT NULL DEFAULT 'bank_transfer',
                bank_last5 TEXT,
                payment_note TEXT,
                source TEXT NOT NULL DEFAULT 'web',
                status TEXT NOT NULL DEFAULT 'pending_payment',
                vip_total_before INTEGER,
                vip_total_after INTEGER,
                vip_level_before TEXT,
                vip_level_after TEXT,
                rebate_percent INTEGER NOT NULL DEFAULT 0,
                rebate_amount INTEGER NOT NULL DEFAULT 0,
                credited_amount INTEGER NOT NULL DEFAULT 0,
                wallet_transaction_id INTEGER,
                bonus_transaction_id INTEGER,
                submitted_at TEXT,
                approved_at TEXT,
                approved_by_discord_id TEXT,
                approved_by_display_name TEXT,
                completed_at TEXT,
                rejected_at TEXT,
                rejected_by_discord_id TEXT,
                rejected_reason TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_topup_orders_customer ON topup_orders(customer_discord_id, id DESC)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_topup_orders_status ON topup_orders(status, id ASC)"
        )
        conn.commit()


def _make_topup_no(conn: sqlite3.Connection, row_id: int, now: datetime | None = None) -> str:
    now = now or datetime.now(TAIPEI_TZ)
    return f"TOPUP-{now.strftime('%Y%m%d')}-{int(row_id):04d}"


def create_topup_order(
    *,
    customer_discord_id: str | int,
    customer_display_name: str | None,
    amount: int,
    source: str,
    payment_method: str = "bank_transfer",
    db_file: str | Path | None = None,
) -> dict[str, Any]:
    ensure_topup_tables(db_file)
    amount = int(amount or 0)
    if amount <= 0:
        raise ValueError("儲值金額必須大於 0。")
    if amount > 1_000_000:
        raise ValueError("單筆儲值金額超過系統上限，請聯絡客服。")

    path = _db_path(db_file)
    now = datetime.now(TAIPEI_TZ)
    now_text = now.isoformat(timespec="seconds")

    with sqlite3.connect(path, timeout=15) as conn:
        conn.row_factory = sqlite3.Row
        cur = conn.execute(
            """
            INSERT INTO topup_orders (
                customer_discord_id, customer_display_name, amount,
                payment_method, source, status, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, 'pending_payment', ?, ?)
            """,
            (
                str(customer_discord_id),
                str(customer_display_name or "").strip() or None,
                amount,
                str(payment_method or "bank_transfer"),
                str(source or "web"),
                now_text,
                now_text,
            ),
        )
        row_id = int(cur.lastrowid)
        topup_no = _make_topup_no(conn, row_id, now)
        conn.execute("UPDATE topup_orders SET topup_no=? WHERE id=?", (topup_no, row_id))
        conn.commit()
        row = conn.execute("SELECT * FROM topup_orders WHERE id=?", (row_id,)).fetchone()
        return dict(row)


def submit_topup_payment(
    topup_id: int,
    *,
    customer_discord_id: str | int,
    bank_last5: str,
    payment_note: str | None = None,
    db_file: str | Path | None = None,
) -> dict[str, Any]:
    ensure_topup_tables(db_file)
    last5 = "".join(ch for ch in str(bank_last5 or "") if ch.isdigit())
    if len(last5) != 5:
        raise ValueError("銀行帳號末五碼請輸入 5 位數字。")

    path = _db_path(db_file)
    now_text = _now_iso()
    with sqlite3.connect(path, timeout=15) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT * FROM topup_orders WHERE id=?", (int(topup_id),)).fetchone()
        if row is None or str(row["customer_discord_id"]) != str(customer_discord_id):
            raise ValueError("找不到這筆儲值單。")
        if str(row["status"]) not in {"pending_payment", "pending_review"}:
            raise ValueError("這筆儲值單目前不能送出付款資料。")

        conn.execute(
            """
            UPDATE topup_orders
            SET bank_last5=?, payment_note=?, status='pending_review',
                submitted_at=COALESCE(submitted_at, ?), updated_at=?
            WHERE id=?
            """,
            (last5, str(payment_note or "").strip() or None, now_text, now_text, int(topup_id)),
        )
        conn.commit()
        return dict(conn.execute("SELECT * FROM topup_orders WHERE id=?", (int(topup_id),)).fetchone())


def cancel_topup_order(
    topup_id: int,
    *,
    customer_discord_id: str | int,
    db_file: str | Path | None = None,
) -> dict[str, Any]:
    ensure_topup_tables(db_file)
    path = _db_path(db_file)
    now_text = _now_iso()
    with sqlite3.connect(path, timeout=15) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT * FROM topup_orders WHERE id=?", (int(topup_id),)).fetchone()
        if row is None or str(row["customer_discord_id"]) != str(customer_discord_id):
            raise ValueError("找不到這筆儲值單。")
        if str(row["status"]) not in {"pending_payment", "pending_review"}:
            raise ValueError("這筆儲值單目前不能取消。")
        conn.execute(
            "UPDATE topup_orders SET status='cancelled', updated_at=? WHERE id=?",
            (now_text, int(topup_id)),
        )
        conn.commit()
        return dict(conn.execute("SELECT * FROM topup_orders WHERE id=?", (int(topup_id),)).fetchone())


def approve_topup_order(
    topup_id: int,
    *,
    operator_discord_id: str | int,
    operator_display_name: str | None,
    db_file: str | Path | None = None,
) -> dict[str, Any]:
    """客服核准付款。真正錢包/VIP入帳由 Bot worker 執行。"""
    ensure_topup_tables(db_file)
    path = _db_path(db_file)
    now_text = _now_iso()
    with sqlite3.connect(path, timeout=15) as conn:
        conn.row_factory = sqlite3.Row
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute("SELECT * FROM topup_orders WHERE id=?", (int(topup_id),)).fetchone()
        if row is None:
            raise ValueError("找不到這筆儲值單。")
        if str(row["status"]) != "pending_review":
            raise ValueError("只有等待審核的儲值單可以核准。")
        conn.execute(
            """
            UPDATE topup_orders
            SET status='approved_pending_credit', approved_at=?,
                approved_by_discord_id=?, approved_by_display_name=?, updated_at=?
            WHERE id=?
            """,
            (
                now_text,
                str(operator_discord_id),
                str(operator_display_name or "").strip() or None,
                now_text,
                int(topup_id),
            ),
        )
        conn.commit()
        return dict(conn.execute("SELECT * FROM topup_orders WHERE id=?", (int(topup_id),)).fetchone())


def reject_topup_order(
    topup_id: int,
    *,
    operator_discord_id: str | int,
    reason: str | None,
    db_file: str | Path | None = None,
) -> dict[str, Any]:
    ensure_topup_tables(db_file)
    path = _db_path(db_file)
    now_text = _now_iso()
    with sqlite3.connect(path, timeout=15) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT * FROM topup_orders WHERE id=?", (int(topup_id),)).fetchone()
        if row is None:
            raise ValueError("找不到這筆儲值單。")
        if str(row["status"]) not in {"pending_review", "pending_payment"}:
            raise ValueError("這筆儲值單目前不能駁回。")
        conn.execute(
            """
            UPDATE topup_orders
            SET status='rejected', rejected_at=?, rejected_by_discord_id=?,
                rejected_reason=?, updated_at=?
            WHERE id=?
            """,
            (
                now_text,
                str(operator_discord_id),
                str(reason or "").strip() or None,
                now_text,
                int(topup_id),
            ),
        )
        conn.commit()
        return dict(conn.execute("SELECT * FROM topup_orders WHERE id=?", (int(topup_id),)).fetchone())


def list_customer_topups(
    customer_discord_id: str | int,
    *,
    limit: int = 20,
    db_file: str | Path | None = None,
) -> list[dict[str, Any]]:
    ensure_topup_tables(db_file)
    path = _db_path(db_file)
    limit = max(1, min(int(limit or 20), 100))
    with sqlite3.connect(path, timeout=15) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT * FROM topup_orders WHERE customer_discord_id=? ORDER BY id DESC LIMIT ?",
            (str(customer_discord_id), limit),
        ).fetchall()
        return [dict(row) for row in rows]


def list_topups_for_admin(
    *,
    status: str | None = None,
    limit: int = 100,
    db_file: str | Path | None = None,
) -> list[dict[str, Any]]:
    ensure_topup_tables(db_file)
    path = _db_path(db_file)
    limit = max(1, min(int(limit or 100), 300))
    with sqlite3.connect(path, timeout=15) as conn:
        conn.row_factory = sqlite3.Row
        if status:
            rows = conn.execute(
                "SELECT * FROM topup_orders WHERE status=? ORDER BY id DESC LIMIT ?",
                (str(status), limit),
            ).fetchall()
        else:
            rows = conn.execute("SELECT * FROM topup_orders ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
        return [dict(row) for row in rows]


def get_topup_order(topup_id: int, db_file: str | Path | None = None) -> dict[str, Any] | None:
    ensure_topup_tables(db_file)
    path = _db_path(db_file)
    with sqlite3.connect(path, timeout=15) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT * FROM topup_orders WHERE id=?", (int(topup_id),)).fetchone()
        return dict(row) if row else None


def get_pending_credit_topups(
    *,
    limit: int = 20,
    db_file: str | Path | None = None,
) -> list[dict[str, Any]]:
    ensure_topup_tables(db_file)
    path = _db_path(db_file)
    with sqlite3.connect(path, timeout=15) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT * FROM topup_orders WHERE status='approved_pending_credit' ORDER BY id ASC LIMIT ?",
            (max(1, min(int(limit or 20), 100)),),
        ).fetchall()
        return [dict(row) for row in rows]


def calculate_topup_preview(total_spent_before: int, amount: int) -> dict[str, Any]:
    total_spent_before = max(0, int(total_spent_before or 0))
    amount = max(0, int(amount or 0))
    total_after = total_spent_before + amount

    def level_for(total: int) -> dict[str, Any]:
        current = dict(BASE_MEMBER_LEVELS[0])
        for level in BASE_MEMBER_LEVELS:
            if total >= int(level["threshold"]):
                current = dict(level)
            else:
                break
        return current

    old_level = level_for(total_spent_before)
    new_level = level_for(total_after)
    rebate_percent = get_topup_rebate_percent(str(new_level["name"]))
    rebate_amount = amount * rebate_percent // 100
    return {
        "vip_total_before": total_spent_before,
        "vip_total_after": total_after,
        "vip_level_before": str(old_level["name"]),
        "vip_level_after": str(new_level["name"]),
        "rebate_percent": rebate_percent,
        "rebate_amount": rebate_amount,
        "credited_amount": amount + rebate_amount,
    }


def mark_topup_processing(topup_id: int, db_file: str | Path | None = None) -> bool:
    ensure_topup_tables(db_file)
    path = _db_path(db_file)
    with sqlite3.connect(path, timeout=15) as conn:
        cur = conn.execute(
            "UPDATE topup_orders SET status='crediting', updated_at=? WHERE id=? AND status='approved_pending_credit'",
            (_now_iso(), int(topup_id)),
        )
        conn.commit()
        return int(cur.rowcount or 0) == 1


def mark_topup_completed(
    topup_id: int,
    *,
    preview: dict[str, Any],
    wallet_transaction_id: int,
    bonus_transaction_id: int | None,
    db_file: str | Path | None = None,
) -> None:
    ensure_topup_tables(db_file)
    path = _db_path(db_file)
    now_text = _now_iso()
    with sqlite3.connect(path, timeout=15) as conn:
        conn.execute(
            """
            UPDATE topup_orders
            SET status='completed', vip_total_before=?, vip_total_after=?,
                vip_level_before=?, vip_level_after=?, rebate_percent=?,
                rebate_amount=?, credited_amount=?, wallet_transaction_id=?,
                bonus_transaction_id=?, completed_at=?, updated_at=?
            WHERE id=?
            """,
            (
                int(preview["vip_total_before"]),
                int(preview["vip_total_after"]),
                str(preview["vip_level_before"]),
                str(preview["vip_level_after"]),
                int(preview["rebate_percent"]),
                int(preview["rebate_amount"]),
                int(preview["credited_amount"]),
                int(wallet_transaction_id),
                int(bonus_transaction_id) if bonus_transaction_id is not None else None,
                now_text,
                now_text,
                int(topup_id),
            ),
        )
        conn.commit()


def reset_topup_credit_error(topup_id: int, db_file: str | Path | None = None) -> None:
    path = _db_path(db_file)
    with sqlite3.connect(path, timeout=15) as conn:
        conn.execute(
            "UPDATE topup_orders SET status='approved_pending_credit', updated_at=? WHERE id=? AND status='crediting'",
            (_now_iso(), int(topup_id)),
        )
        conn.commit()


def topup_status_label(status: str | None) -> str:
    return {
        "pending_payment": "等待付款",
        "pending_review": "等待客服審核",
        "approved_pending_credit": "已核准・等待入帳",
        "crediting": "入帳中",
        "completed": "儲值完成",
        "rejected": "已駁回",
        "cancelled": "已取消",
    }.get(str(status or ""), str(status or "未知"))
