import json
import sqlite3
from datetime import datetime, timedelta, timezone

from services.vip_monthly_benefits import (
    BLACK_DIAMOND_CHOICE,
    MONTHLY_COUPON_200,
    MONTHLY_COUPON_500,
    sync_current_month_vip_benefits,
)


TAIPEI_TZ = timezone(timedelta(hours=8))


def _make_bot_db(path, customer_id: str, data: dict) -> None:
    with sqlite3.connect(path) as conn:
        conn.execute(
            """
            CREATE TABLE customers (
                customer_id TEXT PRIMARY KEY,
                data_json TEXT
            )
            """
        )
        conn.execute(
            "INSERT INTO customers(customer_id, data_json) VALUES (?, ?)",
            (customer_id, json.dumps(data, ensure_ascii=False)),
        )
        conn.commit()


def _rows(web_db, customer_id: str, month_key: str):
    with sqlite3.connect(web_db) as conn:
        conn.row_factory = sqlite3.Row
        return [
            dict(row)
            for row in conn.execute(
                """
                SELECT * FROM vip_monthly_benefits
                WHERE customer_id=? AND month_key=?
                ORDER BY benefit_key
                """,
                (customer_id, month_key),
            ).fetchall()
        ]


def test_topup_only_or_inactive_member_does_not_receive_monthly_assets(tmp_path):
    bot_db = tmp_path / "bot.db"
    web_db = tmp_path / "web.db"
    customer_id = "inactive-black"
    _make_bot_db(
        bot_db,
        customer_id,
        {
            "total_spent": 88888,
            "vip_level_index": 6,
            # Black diamond is not yet retention-due at 45 days, but monthly
            # asset issuance requires a real completed order within 30 days.
            "last_order_at": "2026-09-20T12:00:00+08:00",
        },
    )

    now = datetime(2026, 11, 5, 12, tzinfo=TAIPEI_TZ)
    result = sync_current_month_vip_benefits(
        now=now,
        bot_db=bot_db,
        web_db=web_db,
    )

    assert result["eligible_customer_count"] == 0
    assert _rows(web_db, customer_id, "2026-11") == []


def test_recent_real_order_issues_all_black_diamond_monthly_assets(tmp_path):
    bot_db = tmp_path / "bot.db"
    web_db = tmp_path / "web.db"
    customer_id = "active-black"
    _make_bot_db(
        bot_db,
        customer_id,
        {
            "total_spent": 88888,
            "vip_level_index": 6,
            "last_order_at": "2026-11-01T12:00:00+08:00",
        },
    )

    now = datetime(2026, 11, 5, 12, tzinfo=TAIPEI_TZ)
    result = sync_current_month_vip_benefits(
        now=now,
        bot_db=bot_db,
        web_db=web_db,
    )

    assert result["eligible_customer_count"] == 1
    assert {
        row["benefit_key"]
        for row in _rows(web_db, customer_id, "2026-11")
    } == {MONTHLY_COUPON_200, MONTHLY_COUPON_500, BLACK_DIAMOND_CHOICE}


def test_existing_monthly_asset_is_not_revoked_when_activity_window_expires(tmp_path):
    bot_db = tmp_path / "bot.db"
    web_db = tmp_path / "web.db"
    customer_id = "active-then-idle"
    _make_bot_db(
        bot_db,
        customer_id,
        {
            "total_spent": 25000,
            "vip_level_index": 4,
            "last_order_at": "2026-10-01T12:00:00+08:00",
        },
    )

    issued_at = datetime(2026, 10, 10, 12, tzinfo=TAIPEI_TZ)
    sync_current_month_vip_benefits(
        now=issued_at,
        bot_db=bot_db,
        web_db=web_db,
    )
    before = _rows(web_db, customer_id, "2026-10")
    assert len(before) == 1
    assert before[0]["benefit_key"] == MONTHLY_COUPON_200
    assert before[0]["status"] == "available"

    # Same month, now outside the 30-day activity window. The existing benefit
    # stays valid because inactivity only blocks issuance/reactivation.
    later = datetime(2026, 10, 31, 23, tzinfo=TAIPEI_TZ)
    sync_current_month_vip_benefits(
        now=later,
        bot_db=bot_db,
        web_db=web_db,
    )
    after = _rows(web_db, customer_id, "2026-10")
    assert len(after) == 1
    assert after[0]["status"] == "available"
