from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from services.wallet_service import get_wallet_fund_breakdown


TAIPEI_TZ = timezone(timedelta(hours=8))
ROOT = Path(__file__).resolve().parents[1]
DEFAULT_BOT_DB = ROOT / "bot.db"
DEFAULT_WEB_DB = ROOT / "web_dashboard.db"


def _bot_db_path(value: str | Path | None = None) -> Path:
    return Path(value) if value is not None else DEFAULT_BOT_DB


def _web_db_path(value: str | Path | None = None) -> Path:
    return Path(value) if value is not None else DEFAULT_WEB_DB


def _now_text() -> str:
    return datetime.now(TAIPEI_TZ).isoformat(timespec="seconds")


def ensure_wallet_refund_tables(bot_db: str | Path | None = None) -> None:
    path = _bot_db_path(bot_db)
    with sqlite3.connect(path, timeout=15) as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS wallet_refund_requests (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                refund_no TEXT UNIQUE,
                customer_discord_id TEXT NOT NULL,
                refundable_principal INTEGER NOT NULL,
                balance_snapshot INTEGER NOT NULL,
                topup_bonus_snapshot INTEGER NOT NULL DEFAULT 0,
                status TEXT NOT NULL DEFAULT 'pending',
                requested_by_discord_id TEXT,
                requested_by_display_name TEXT,
                reason TEXT,
                principal_transaction_id INTEGER,
                bonus_transaction_id INTEGER,
                vip_total_before INTEGER,
                vip_total_after INTEGER,
                vip_level_before TEXT,
                vip_level_after TEXT,
                error_text TEXT,
                requested_at TEXT NOT NULL,
                processing_at TEXT,
                completed_at TEXT,
                updated_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_wallet_refund_pending
                ON wallet_refund_requests(status, id);
            CREATE INDEX IF NOT EXISTS idx_wallet_refund_customer
                ON wallet_refund_requests(customer_discord_id, id DESC);
            """
        )
        conn.commit()


def _remaining_topup_bonus(customer_id: str | int, *, bot_db: str | Path | None = None) -> int:
    path = _bot_db_path(bot_db)
    with sqlite3.connect(path, timeout=15) as conn:
        row = conn.execute(
            """
            SELECT COALESCE(SUM(CASE
                WHEN type='topup_bonus' AND amount > 0 THEN amount
                WHEN type='topup_bonus_reversal' AND amount < 0 THEN amount
                ELSE 0 END), 0)
            FROM wallet_transactions
            WHERE customer_discord_id=?
            """,
            (str(customer_id),),
        ).fetchone()
    return max(0, int(row[0] or 0) if row else 0)


def has_redeemed_current_month_vip_benefit(
    customer_id: str | int,
    *,
    web_db: str | Path | None = None,
    now: datetime | None = None,
) -> bool:
    path = _web_db_path(web_db)
    if not path.exists():
        return False
    current = now or datetime.now(TAIPEI_TZ)
    if current.tzinfo is None:
        current = current.replace(tzinfo=TAIPEI_TZ)
    month = current.astimezone(TAIPEI_TZ).strftime("%Y-%m")
    try:
        with sqlite3.connect(path, timeout=15) as conn:
            exists = conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='vip_monthly_benefits'"
            ).fetchone()
            if not exists:
                return False
            row = conn.execute(
                """
                SELECT 1
                FROM vip_monthly_benefits
                WHERE customer_id=? AND month_key=? AND status='redeemed'
                LIMIT 1
                """,
                (str(customer_id), month),
            ).fetchone()
            return row is not None
    except sqlite3.Error:
        return False


def get_wallet_refund_preview(
    customer_id: str | int,
    *,
    bot_db: str | Path | None = None,
    web_db: str | Path | None = None,
) -> dict[str, Any]:
    funds = get_wallet_fund_breakdown(customer_id, db_file=_bot_db_path(bot_db))
    bonus = min(
        int(funds.get("nonrefundable_credit") or 0),
        _remaining_topup_bonus(customer_id, bot_db=bot_db),
    )
    redeemed = has_redeemed_current_month_vip_benefit(customer_id, web_db=web_db)
    return {
        **funds,
        "topup_bonus_to_cancel": bonus,
        "manual_review_required": bool(redeemed),
        "can_refund": int(funds.get("refundable_principal") or 0) > 0 and not redeemed,
    }


def create_wallet_refund_request(
    *,
    customer_id: str | int,
    requested_by_discord_id: str | int | None,
    requested_by_display_name: str | None,
    reason: str | None,
    bot_db: str | Path | None = None,
    web_db: str | Path | None = None,
) -> dict[str, Any]:
    ensure_wallet_refund_tables(bot_db)
    preview = get_wallet_refund_preview(customer_id, bot_db=bot_db, web_db=web_db)
    principal = int(preview["refundable_principal"] or 0)
    if principal <= 0:
        raise ValueError("目前沒有可退款的實付儲值本金。")
    if preview["manual_review_required"]:
        raise ValueError("本月已有 VIP 月福利使用紀錄，請先人工結算福利價值後再處理退款。")

    path = _bot_db_path(bot_db)
    now_text = _now_text()
    with sqlite3.connect(path, timeout=15) as conn:
        conn.row_factory = sqlite3.Row
        conn.execute("BEGIN IMMEDIATE")
        pending = conn.execute(
            """
            SELECT * FROM wallet_refund_requests
            WHERE customer_discord_id=? AND status IN ('pending','processing')
            ORDER BY id DESC LIMIT 1
            """,
            (str(customer_id),),
        ).fetchone()
        if pending is not None:
            conn.rollback()
            return dict(pending)

        cur = conn.execute(
            """
            INSERT INTO wallet_refund_requests (
                customer_discord_id, refundable_principal, balance_snapshot,
                topup_bonus_snapshot, status, requested_by_discord_id,
                requested_by_display_name, reason, requested_at, updated_at
            ) VALUES (?, ?, ?, ?, 'pending', ?, ?, ?, ?, ?)
            """,
            (
                str(customer_id), principal, int(preview["balance"] or 0),
                int(preview["topup_bonus_to_cancel"] or 0),
                str(requested_by_discord_id) if requested_by_discord_id else None,
                str(requested_by_display_name or "").strip() or None,
                str(reason or "").strip() or "顧客申請退還未使用儲值本金",
                now_text, now_text,
            ),
        )
        row_id = int(cur.lastrowid)
        refund_no = f"RF-{datetime.now(TAIPEI_TZ).strftime('%Y%m%d')}-{row_id:04d}"
        conn.execute("UPDATE wallet_refund_requests SET refund_no=? WHERE id=?", (refund_no, row_id))
        conn.commit()
        row = conn.execute("SELECT * FROM wallet_refund_requests WHERE id=?", (row_id,)).fetchone()
        return dict(row)


def get_pending_wallet_refunds(
    *, limit: int = 20, bot_db: str | Path | None = None,
) -> list[dict[str, Any]]:
    ensure_wallet_refund_tables(bot_db)
    with sqlite3.connect(_bot_db_path(bot_db), timeout=15) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT * FROM wallet_refund_requests WHERE status='pending' ORDER BY id ASC LIMIT ?",
            (max(1, min(int(limit or 20), 100)),),
        ).fetchall()
        return [dict(row) for row in rows]


def mark_wallet_refund_processing(refund_id: int, *, bot_db: str | Path | None = None) -> bool:
    ensure_wallet_refund_tables(bot_db)
    now_text = _now_text()
    with sqlite3.connect(_bot_db_path(bot_db), timeout=15) as conn:
        cur = conn.execute(
            """
            UPDATE wallet_refund_requests
            SET status='processing', processing_at=?, updated_at=?, error_text=NULL
            WHERE id=? AND status='pending'
            """,
            (now_text, now_text, int(refund_id)),
        )
        conn.commit()
        return int(cur.rowcount or 0) == 1


def mark_wallet_refund_completed(
    refund_id: int, *, principal_transaction_id: int,
    bonus_transaction_id: int | None, vip_total_before: int,
    vip_total_after: int, vip_level_before: str, vip_level_after: str,
    bot_db: str | Path | None = None,
) -> None:
    now_text = _now_text()
    with sqlite3.connect(_bot_db_path(bot_db), timeout=15) as conn:
        conn.execute(
            """
            UPDATE wallet_refund_requests
            SET status='completed', principal_transaction_id=?, bonus_transaction_id=?,
                vip_total_before=?, vip_total_after=?, vip_level_before=?, vip_level_after=?,
                completed_at=?, updated_at=?, error_text=NULL
            WHERE id=?
            """,
            (
                int(principal_transaction_id),
                int(bonus_transaction_id) if bonus_transaction_id is not None else None,
                int(vip_total_before), int(vip_total_after),
                str(vip_level_before), str(vip_level_after),
                now_text, now_text, int(refund_id),
            ),
        )
        conn.commit()


def reset_wallet_refund_error(
    refund_id: int, error_text: str, *, bot_db: str | Path | None = None,
) -> None:
    now_text = _now_text()
    with sqlite3.connect(_bot_db_path(bot_db), timeout=15) as conn:
        conn.execute(
            """
            UPDATE wallet_refund_requests
            SET status='error', error_text=?, updated_at=?
            WHERE id=?
            """,
            (str(error_text or "")[:1000], now_text, int(refund_id)),
        )
        conn.commit()
