from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from core.vip_levels import VIP_LEVELS
from services.vip_review_store import build_vip_review_snapshot


TAIPEI_TZ = timezone(timedelta(hours=8))
ROOT = Path(__file__).resolve().parents[1]
DEFAULT_WEB_DB = ROOT / "web_dashboard.db"
DEFAULT_BOT_DB = ROOT / "bot.db"

AVAILABLE = "available"
RESERVED = "reserved"
REDEEMED = "redeemed"
REVOKED = "revoked"

MONTHLY_COUPON_200 = "monthly_coupon_200"
MONTHLY_COUPON_500 = "monthly_coupon_500"
BLACK_DIAMOND_CHOICE = "free_secret_space"
MONTHLY_BENEFIT_KEYS = (
    MONTHLY_COUPON_200,
    MONTHLY_COUPON_500,
    BLACK_DIAMOND_CHOICE,
)

BLACK_DIAMOND_CHOICES: dict[str, str] = {
    "secret_space_1000w": "機密航天保底 1000w",
    "entertainment_2h": "娛樂陪 2H",
}

BENEFIT_LABELS: dict[str, str] = {
    MONTHLY_COUPON_200: "VIP 每月 200T 折現券",
    MONTHLY_COUPON_500: "VIP 每月額外 500T 折現券",
    BLACK_DIAMOND_CHOICE: "黑鑽每月尊享福利",
}

MONTHLY_CASH_AMOUNTS: dict[str, int] = {
    MONTHLY_COUPON_200: 200,
    MONTHLY_COUPON_500: 500,
}

# 2026/10 上線前已由人工發放並使用過 200T 月券的會員。
# 這是一次性資料遷移，唯一鍵會確保重啟不會重複寫入。
OCTOBER_2026_USED_200_CUSTOMERS = (
    "343024638164598784",
    "448915700145192961",
    "836929629222600714",
)


def _web_db_path(web_db: str | Path | None = None) -> Path:
    return Path(web_db) if web_db is not None else DEFAULT_WEB_DB


def _bot_db_path(bot_db: str | Path | None = None) -> Path:
    return Path(bot_db) if bot_db is not None else DEFAULT_BOT_DB


def _now() -> datetime:
    return datetime.now(TAIPEI_TZ)


def _normalize_now(value: datetime | None) -> datetime:
    current = value or _now()
    if current.tzinfo is None:
        current = current.replace(tzinfo=TAIPEI_TZ)
    return current.astimezone(TAIPEI_TZ)


def _month_key(now: datetime) -> str:
    return now.strftime("%Y-%m")


def _next_month_start(now: datetime) -> datetime:
    if now.month == 12:
        return datetime(now.year + 1, 1, 1, tzinfo=TAIPEI_TZ)
    return datetime(now.year, now.month + 1, 1, tzinfo=TAIPEI_TZ)


def _benefit_keys_for_level(level_name: str) -> set[str]:
    for level in VIP_LEVELS:
        if str(level.get("name") or "") == str(level_name or ""):
            return {
                str(key)
                for key in level.get("benefit_keys", [])
                if str(key) in MONTHLY_BENEFIT_KEYS
            }
    return set()


def ensure_vip_monthly_tables(web_db: str | Path | None = None) -> None:
    path = _web_db_path(web_db)
    with sqlite3.connect(path, timeout=15) as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS vip_monthly_benefits (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                customer_id TEXT NOT NULL,
                month_key TEXT NOT NULL,
                benefit_key TEXT NOT NULL,
                benefit_label TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'available',
                choice_key TEXT,
                reserved_at TEXT,
                reserved_channel_id TEXT,
                redeemed_at TEXT,
                issued_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                source TEXT NOT NULL DEFAULT 'system'
            );

            CREATE UNIQUE INDEX IF NOT EXISTS uq_vip_monthly_benefit
            ON vip_monthly_benefits(customer_id, month_key, benefit_key);

            CREATE INDEX IF NOT EXISTS ix_vip_monthly_benefits_month_status
            ON vip_monthly_benefits(month_key, status, benefit_key);

            CREATE TABLE IF NOT EXISTS vip_monthly_refresh_state (
                month_key TEXT PRIMARY KEY,
                refreshed_at TEXT NOT NULL,
                announced_at TEXT
            );
            """
        )
        conn.commit()


def _seed_october_2026_used_200(
    conn: sqlite3.Connection,
    *,
    now_text: str,
) -> int:
    inserted = 0
    for customer_id in OCTOBER_2026_USED_200_CUSTOMERS:
        cur = conn.execute(
            """
            INSERT OR IGNORE INTO vip_monthly_benefits (
                customer_id,
                month_key,
                benefit_key,
                benefit_label,
                status,
                redeemed_at,
                issued_at,
                updated_at,
                source
            ) VALUES (?, '2026-10', ?, ?, 'redeemed', ?, ?, ?, 'legacy_import')
            """,
            (
                customer_id,
                MONTHLY_COUPON_200,
                BENEFIT_LABELS[MONTHLY_COUPON_200],
                now_text,
                now_text,
                now_text,
            ),
        )
        inserted += int(cur.rowcount or 0)
    return inserted


def sync_current_month_vip_benefits(
    *,
    now: datetime | None = None,
    web_db: str | Path | None = None,
    bot_db: str | Path | None = None,
) -> dict[str, Any]:
    """Synchronize current-month benefits to each member's current tier.

    Unused monthly benefits above the member's current effective tier are
    revoked immediately. Redeemed benefits remain immutable history, and an
    already-reserved black-diamond redemption may finish normally. If the
    member becomes eligible again in the same month, a previously revoked
    unused benefit is reactivated instead of issuing a duplicate row.
    """
    current = _normalize_now(now)
    month = _month_key(current)
    now_text = current.isoformat(timespec="seconds")
    path = _web_db_path(web_db)
    ensure_vip_monthly_tables(path)

    snapshot = build_vip_review_snapshot(
        db_file=_bot_db_path(bot_db),
        view="all",
        now=current,
    )
    member_rows = list(snapshot.get("rows") or [])

    issued = 0
    revoked = 0
    reactivated = 0
    eligible_customers = 0
    legacy_seeded = 0
    first_refresh = False
    entitlement_by_customer: dict[str, set[str]] = {}

    with sqlite3.connect(path, timeout=15) as conn:
        conn.row_factory = sqlite3.Row
        legacy_seeded = _seed_october_2026_used_200(conn, now_text=now_text)

        for row in member_rows:
            customer_id = str(row.get("customer_id") or "").strip()
            if not customer_id:
                continue

            keys = _benefit_keys_for_level(str(row.get("current_level") or ""))
            entitlement_by_customer[customer_id] = keys

            if bool(row.get("is_due")) or not keys:
                # Due members do not receive/reactivate a new benefit, but an
                # already-issued current-tier benefit is not revoked only for
                # becoming due. Tier eligibility remains the revocation rule.
                continue

            eligible_customers += 1
            for benefit_key in MONTHLY_BENEFIT_KEYS:
                if benefit_key not in keys:
                    continue

                existing = conn.execute(
                    """
                    SELECT id, status
                    FROM vip_monthly_benefits
                    WHERE customer_id=? AND month_key=? AND benefit_key=?
                    LIMIT 1
                    """,
                    (customer_id, month, benefit_key),
                ).fetchone()

                if existing is None:
                    cur = conn.execute(
                        """
                        INSERT INTO vip_monthly_benefits (
                            customer_id,
                            month_key,
                            benefit_key,
                            benefit_label,
                            status,
                            issued_at,
                            updated_at,
                            source
                        ) VALUES (?, ?, ?, ?, 'available', ?, ?, 'system')
                        """,
                        (
                            customer_id,
                            month,
                            benefit_key,
                            BENEFIT_LABELS[benefit_key],
                            now_text,
                            now_text,
                        ),
                    )
                    issued += int(cur.rowcount or 0)
                elif str(existing["status"] or "") == REVOKED:
                    cur = conn.execute(
                        """
                        UPDATE vip_monthly_benefits
                        SET status='available',
                            choice_key=NULL,
                            reserved_at=NULL,
                            reserved_channel_id=NULL,
                            redeemed_at=NULL,
                            updated_at=?
                        WHERE id=? AND status='revoked'
                        """,
                        (now_text, int(existing["id"])),
                    )
                    reactivated += int(cur.rowcount or 0)

        available_rows = conn.execute(
            """
            SELECT id, customer_id, benefit_key
            FROM vip_monthly_benefits
            WHERE month_key=? AND status='available'
            """,
            (month,),
        ).fetchall()
        for benefit_row in available_rows:
            customer_id = str(benefit_row["customer_id"] or "")
            benefit_key = str(benefit_row["benefit_key"] or "")
            current_keys = entitlement_by_customer.get(customer_id, set())
            if benefit_key in current_keys:
                continue
            cur = conn.execute(
                """
                UPDATE vip_monthly_benefits
                SET status='revoked',
                    choice_key=NULL,
                    reserved_at=NULL,
                    reserved_channel_id=NULL,
                    updated_at=?
                WHERE id=? AND status='available'
                """,
                (now_text, int(benefit_row["id"])),
            )
            revoked += int(cur.rowcount or 0)

        state = conn.execute(
            "SELECT month_key, refreshed_at, announced_at FROM vip_monthly_refresh_state WHERE month_key=?",
            (month,),
        ).fetchone()
        if state is None:
            first_refresh = True
            bootstrap_announced_at = (
                now_text
                if month == "2026-10" and current.day > 1
                else None
            )
            conn.execute(
                """
                INSERT INTO vip_monthly_refresh_state (month_key, refreshed_at, announced_at)
                VALUES (?, ?, ?)
                """,
                (month, now_text, bootstrap_announced_at),
            )
        else:
            conn.execute(
                "UPDATE vip_monthly_refresh_state SET refreshed_at=? WHERE month_key=?",
                (now_text, month),
            )
        conn.commit()

        state = conn.execute(
            "SELECT announced_at FROM vip_monthly_refresh_state WHERE month_key=?",
            (month,),
        ).fetchone()
        announcement_needed = bool(state is not None and not state["announced_at"])

    return {
        "month_key": month,
        "issued_count": issued,
        "revoked_count": revoked,
        "reactivated_count": reactivated,
        "eligible_customer_count": eligible_customers,
        "legacy_seeded_count": legacy_seeded,
        "first_refresh": first_refresh,
        "announcement_needed": announcement_needed,
        "expires_at": _next_month_start(current).isoformat(timespec="seconds"),
    }


def mark_month_announcement_sent(
    month_key: str,
    *,
    now: datetime | None = None,
    web_db: str | Path | None = None,
) -> None:
    ensure_vip_monthly_tables(web_db)
    current = _normalize_now(now)
    with sqlite3.connect(_web_db_path(web_db), timeout=15) as conn:
        conn.execute(
            """
            UPDATE vip_monthly_refresh_state
            SET announced_at=?
            WHERE month_key=?
            """,
            (current.isoformat(timespec="seconds"), str(month_key)),
        )
        conn.commit()


def _current_member_status(
    customer_id: str,
    *,
    now: datetime,
    bot_db: str | Path | None,
) -> dict[str, Any]:
    snapshot = build_vip_review_snapshot(
        db_file=_bot_db_path(bot_db),
        view="all",
        now=now,
    )
    for row in snapshot.get("rows") or []:
        if str(row.get("customer_id") or "") == customer_id:
            return dict(row)
    return {
        "customer_id": customer_id,
        "current_level": "普通魔丸",
        "current_index": 0,
        "is_due": False,
    }


def get_customer_vip_monthly_snapshot(
    customer_id: str | int,
    *,
    now: datetime | None = None,
    web_db: str | Path | None = None,
    bot_db: str | Path | None = None,
    ensure_synced: bool = True,
) -> dict[str, Any]:
    current = _normalize_now(now)
    month = _month_key(current)
    customer = str(customer_id)
    if ensure_synced:
        sync_current_month_vip_benefits(
            now=current,
            web_db=web_db,
            bot_db=bot_db,
        )
    else:
        ensure_vip_monthly_tables(web_db)

    member_status = _current_member_status(
        customer,
        now=current,
        bot_db=bot_db,
    )
    level_name = str(member_status.get("current_level") or "普通魔丸")
    level_keys = _benefit_keys_for_level(level_name)

    with sqlite3.connect(_web_db_path(web_db), timeout=15) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            """
            SELECT *
            FROM vip_monthly_benefits
            WHERE customer_id=? AND month_key=?
            ORDER BY id ASC
            """,
            (customer, month),
        ).fetchall()

    raw_by_key = {str(row["benefit_key"]): dict(row) for row in rows}
    by_key = {
        key: row
        for key, row in raw_by_key.items()
        if key in level_keys and str(row.get("status") or "") != REVOKED
    }
    cash_rows = [
        by_key[key]
        for key in (MONTHLY_COUPON_200, MONTHLY_COUPON_500)
        if key in by_key
    ]
    black_entitled = BLACK_DIAMOND_CHOICE in level_keys
    black_row = by_key.get(BLACK_DIAMOND_CHOICE) if black_entitled else None
    black_suspended = bool(
        black_entitled
        and member_status.get("is_due")
        and black_row is None
    )

    return {
        "month_key": month,
        "current_level": level_name,
        "is_due": bool(member_status.get("is_due")),
        "benefits": list(by_key.values()),
        "by_key": by_key,
        "cash_benefits": cash_rows,
        "black_diamond": black_row,
        "black_diamond_entitled": black_entitled,
        "black_diamond_suspended": black_suspended,
        "black_diamond_available": bool(
            black_entitled
            and black_row
            and str(black_row.get("status")) == AVAILABLE
        ),
    }


def list_available_cash_benefits(
    customer_id: str | int,
    *,
    now: datetime | None = None,
    web_db: str | Path | None = None,
    bot_db: str | Path | None = None,
    ensure_synced: bool = True,
) -> list[dict[str, Any]]:
    """Return current-month VIP cash vouchers that can be selected now."""
    snapshot = get_customer_vip_monthly_snapshot(
        customer_id,
        now=now,
        web_db=web_db,
        bot_db=bot_db,
        ensure_synced=ensure_synced,
    )
    result: list[dict[str, Any]] = []
    for row in snapshot.get("cash_benefits") or []:
        if str(row.get("status") or "") != AVAILABLE:
            continue
        benefit_key = str(row.get("benefit_key") or "")
        amount = int(MONTHLY_CASH_AMOUNTS.get(benefit_key, 0) or 0)
        if amount <= 0:
            continue
        item = dict(row)
        item["amount"] = amount
        item["title"] = str(row.get("benefit_label") or BENEFIT_LABELS.get(benefit_key) or benefit_key)
        result.append(item)
    return result


def get_available_cash_benefit(
    benefit_id: str | int,
    *,
    customer_id: str | int,
    now: datetime | None = None,
    web_db: str | Path | None = None,
    bot_db: str | Path | None = None,
) -> dict[str, Any] | None:
    wanted = str(benefit_id)
    for row in list_available_cash_benefits(
        customer_id,
        now=now,
        web_db=web_db,
        bot_db=bot_db,
    ):
        if str(row.get("id")) == wanted:
            return row
    return None


def reserve_cash_benefit_for_channel(
    *,
    benefit_id: str | int,
    customer_id: str | int,
    channel_id: str | int,
    now: datetime | None = None,
    web_db: str | Path | None = None,
    bot_db: str | Path | None = None,
) -> dict[str, Any]:
    """Atomically reserve one current-month VIP cash voucher for an order channel."""
    current = _normalize_now(now)
    sync_current_month_vip_benefits(now=current, web_db=web_db, bot_db=bot_db)
    month = _month_key(current)
    now_text = current.isoformat(timespec="seconds")
    path = _web_db_path(web_db)
    ensure_vip_monthly_tables(path)

    with sqlite3.connect(path, timeout=15) as conn:
        conn.row_factory = sqlite3.Row
        cur = conn.execute(
            """
            UPDATE vip_monthly_benefits
            SET status='reserved',
                reserved_at=?,
                reserved_channel_id=?,
                updated_at=?
            WHERE id=?
              AND customer_id=?
              AND month_key=?
              AND benefit_key IN (?, ?)
              AND status='available'
            """,
            (
                now_text,
                str(channel_id),
                now_text,
                int(benefit_id),
                str(customer_id),
                month,
                MONTHLY_COUPON_200,
                MONTHLY_COUPON_500,
            ),
        )
        if int(cur.rowcount or 0) != 1:
            raise ValueError("這張 VIP 每月折現券已使用、已保留或已失效。")
        conn.commit()
        row = conn.execute(
            "SELECT * FROM vip_monthly_benefits WHERE id=? LIMIT 1",
            (int(benefit_id),),
        ).fetchone()
    return dict(row)


def release_cash_benefits_for_channel(
    channel_id: str | int,
    *,
    now: datetime | None = None,
    web_db: str | Path | None = None,
    bot_db: str | Path | None = None,
) -> int:
    """Release reserved VIP cash vouchers when an order is cancelled."""
    current = _normalize_now(now)
    current_month = _month_key(current)
    now_text = current.isoformat(timespec="seconds")
    path = _web_db_path(web_db)
    ensure_vip_monthly_tables(path)

    with sqlite3.connect(path, timeout=15) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            """
            SELECT id, customer_id, month_key, benefit_key
            FROM vip_monthly_benefits
            WHERE reserved_channel_id=?
              AND benefit_key IN (?, ?)
              AND status='reserved'
            """,
            (str(channel_id), MONTHLY_COUPON_200, MONTHLY_COUPON_500),
        ).fetchall()

        released = 0
        for row in rows:
            member_status = _current_member_status(
                str(row["customer_id"]),
                now=current,
                bot_db=bot_db,
            )
            eligible_keys = _benefit_keys_for_level(str(member_status.get("current_level") or "普通魔丸"))
            next_status = (
                AVAILABLE
                if str(row["month_key"]) == current_month and str(row["benefit_key"]) in eligible_keys
                else REVOKED
            )
            cur = conn.execute(
                """
                UPDATE vip_monthly_benefits
                SET status=?,
                    reserved_at=NULL,
                    reserved_channel_id=NULL,
                    updated_at=?
                WHERE id=? AND status='reserved'
                """,
                (next_status, now_text, int(row["id"])),
            )
            released += int(cur.rowcount or 0)
        conn.commit()
    return released


def redeem_cash_benefits_for_channel(
    channel_id: str | int,
    *,
    now: datetime | None = None,
    web_db: str | Path | None = None,
) -> int:
    """Finalize reserved VIP cash vouchers when an order is closed."""
    current = _normalize_now(now)
    now_text = current.isoformat(timespec="seconds")
    path = _web_db_path(web_db)
    ensure_vip_monthly_tables(path)
    with sqlite3.connect(path, timeout=15) as conn:
        cur = conn.execute(
            """
            UPDATE vip_monthly_benefits
            SET status='redeemed',
                redeemed_at=?,
                updated_at=?
            WHERE reserved_channel_id=?
              AND benefit_key IN (?, ?)
              AND status='reserved'
            """,
            (now_text, now_text, str(channel_id), MONTHLY_COUPON_200, MONTHLY_COUPON_500),
        )
        conn.commit()
        return int(cur.rowcount or 0)


def reserve_black_diamond_choice(
    customer_id: str | int,
    choice_key: str,
    *,
    now: datetime | None = None,
    web_db: str | Path | None = None,
    bot_db: str | Path | None = None,
) -> dict[str, Any]:
    choice = str(choice_key or "").strip()
    if choice not in BLACK_DIAMOND_CHOICES:
        raise ValueError("不支援的黑鑽福利選項")

    current = _normalize_now(now)
    sync_current_month_vip_benefits(
        now=current,
        web_db=web_db,
        bot_db=bot_db,
    )
    customer = str(customer_id)
    member_status = _current_member_status(
        customer,
        now=current,
        bot_db=bot_db,
    )
    current_keys = _benefit_keys_for_level(
        str(member_status.get("current_level") or "普通魔丸")
    )
    if BLACK_DIAMOND_CHOICE not in current_keys:
        raise ValueError("目前 VIP 等級沒有黑鑽尊享福利，無法兌換。")

    month = _month_key(current)
    now_text = current.isoformat(timespec="seconds")

    with sqlite3.connect(_web_db_path(web_db), timeout=15) as conn:
        conn.row_factory = sqlite3.Row
        cur = conn.execute(
            """
            UPDATE vip_monthly_benefits
            SET status='reserved',
                choice_key=?,
                reserved_at=?,
                reserved_channel_id=NULL,
                updated_at=?
            WHERE customer_id=?
              AND month_key=?
              AND benefit_key=?
              AND status='available'
            """,
            (
                choice,
                now_text,
                now_text,
                customer,
                month,
                BLACK_DIAMOND_CHOICE,
            ),
        )
        if int(cur.rowcount or 0) != 1:
            raise ValueError("本月黑鑽尊享福利目前不可兌換，可能已使用、兌換中或暫停發放。")
        conn.commit()
        row = conn.execute(
            """
            SELECT * FROM vip_monthly_benefits
            WHERE customer_id=? AND month_key=? AND benefit_key=?
            LIMIT 1
            """,
            (customer, month, BLACK_DIAMOND_CHOICE),
        ).fetchone()
    return dict(row)


def bind_black_diamond_reservation_channel(
    customer_id: str | int,
    channel_id: str | int,
    *,
    month_key: str | None = None,
    now: datetime | None = None,
    web_db: str | Path | None = None,
) -> None:
    current = _normalize_now(now)
    month = str(month_key or _month_key(current))
    with sqlite3.connect(_web_db_path(web_db), timeout=15) as conn:
        conn.execute(
            """
            UPDATE vip_monthly_benefits
            SET reserved_channel_id=?, updated_at=?
            WHERE customer_id=? AND month_key=? AND benefit_key=? AND status='reserved'
            """,
            (
                str(channel_id),
                current.isoformat(timespec="seconds"),
                str(customer_id),
                month,
                BLACK_DIAMOND_CHOICE,
            ),
        )
        conn.commit()


def release_black_diamond_choice(
    customer_id: str | int,
    *,
    month_key: str | None = None,
    now: datetime | None = None,
    web_db: str | Path | None = None,
    bot_db: str | Path | None = None,
) -> bool:
    current = _normalize_now(now)
    month = str(month_key or _month_key(current))
    customer = str(customer_id)
    member_status = _current_member_status(
        customer,
        now=current,
        bot_db=bot_db,
    )
    current_keys = _benefit_keys_for_level(
        str(member_status.get("current_level") or "普通魔丸")
    )
    next_status = AVAILABLE if BLACK_DIAMOND_CHOICE in current_keys else REVOKED
    with sqlite3.connect(_web_db_path(web_db), timeout=15) as conn:
        cur = conn.execute(
            """
            UPDATE vip_monthly_benefits
            SET status=?,
                choice_key=NULL,
                reserved_at=NULL,
                reserved_channel_id=NULL,
                updated_at=?
            WHERE customer_id=? AND month_key=? AND benefit_key=? AND status='reserved'
            """,
            (
                next_status,
                current.isoformat(timespec="seconds"),
                customer,
                month,
                BLACK_DIAMOND_CHOICE,
            ),
        )
        conn.commit()
        return int(cur.rowcount or 0) == 1


def redeem_black_diamond_choice(
    customer_id: str | int,
    *,
    month_key: str | None = None,
    now: datetime | None = None,
    web_db: str | Path | None = None,
) -> bool:
    current = _normalize_now(now)
    month = str(month_key or _month_key(current))
    now_text = current.isoformat(timespec="seconds")
    with sqlite3.connect(_web_db_path(web_db), timeout=15) as conn:
        cur = conn.execute(
            """
            UPDATE vip_monthly_benefits
            SET status='redeemed',
                redeemed_at=?,
                updated_at=?
            WHERE customer_id=? AND month_key=? AND benefit_key=? AND status='reserved'
            """,
            (
                now_text,
                now_text,
                str(customer_id),
                month,
                BLACK_DIAMOND_CHOICE,
            ),
        )
        conn.commit()
        return int(cur.rowcount or 0) == 1


def benefit_status_label(status: str | None) -> str:
    return {
        AVAILABLE: "可使用",
        RESERVED: "兌換中",
        REDEEMED: "已使用",
        REVOKED: "已失效（目前等級不符）",
    }.get(str(status or ""), str(status or "未知"))
