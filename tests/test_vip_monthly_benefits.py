import json
import sqlite3
from datetime import datetime, timezone, timedelta

from services.vip_monthly_benefits import (
    BLACK_DIAMOND_CHOICE,
    MONTHLY_COUPON_200,
    MONTHLY_COUPON_500,
    OCTOBER_2026_USED_200_CUSTOMERS,
    get_customer_vip_monthly_snapshot,
    mark_month_announcement_sent,
    redeem_black_diamond_choice,
    release_black_diamond_choice,
    reserve_black_diamond_choice,
    sync_current_month_vip_benefits,
)


TAIPEI_TZ = timezone(timedelta(hours=8))


def _make_bot_db(path, rows):
    with sqlite3.connect(path) as conn:
        conn.execute(
            """
            CREATE TABLE customers (
                customer_id TEXT PRIMARY KEY,
                data_json TEXT
            )
            """
        )
        for customer_id, data in rows:
            conn.execute(
                "INSERT INTO customers(customer_id, data_json) VALUES (?, ?)",
                (str(customer_id), json.dumps(data, ensure_ascii=False)),
            )
        conn.commit()


def _benefit_rows(web_db, customer_id, month_key):
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
                (str(customer_id), month_key),
            ).fetchall()
        ]


def test_monthly_benefits_do_not_accumulate_and_black_gets_all_three(tmp_path):
    bot_db = tmp_path / "bot.db"
    web_db = tmp_path / "web_dashboard.db"
    customer_id = "999"
    _make_bot_db(
        bot_db,
        [
            (
                customer_id,
                {
                    "total_spent": 88888,
                    "vip_level_index": 6,
                    "last_order_at": "2026-10-01T12:00:00+08:00",
                },
            )
        ],
    )

    october = datetime(2026, 10, 10, 12, tzinfo=TAIPEI_TZ)
    result = sync_current_month_vip_benefits(
        now=october,
        bot_db=bot_db,
        web_db=web_db,
    )
    assert result["issued_count"] == 3
    assert result["announcement_needed"] is False
    assert {
        row["benefit_key"]
        for row in _benefit_rows(web_db, customer_id, "2026-10")
    } == {MONTHLY_COUPON_200, MONTHLY_COUPON_500, BLACK_DIAMOND_CHOICE}

    again = sync_current_month_vip_benefits(
        now=october,
        bot_db=bot_db,
        web_db=web_db,
    )
    assert again["issued_count"] == 0

    november = datetime(2026, 11, 1, 0, 5, tzinfo=TAIPEI_TZ)
    next_month = sync_current_month_vip_benefits(
        now=november,
        bot_db=bot_db,
        web_db=web_db,
    )
    assert next_month["issued_count"] == 3
    assert next_month["announcement_needed"] is True
    assert len(_benefit_rows(web_db, customer_id, "2026-11")) == 3
    assert len(_benefit_rows(web_db, customer_id, "2026-10")) == 3

    mark_month_announcement_sent("2026-11", now=november, web_db=web_db)
    announced = sync_current_month_vip_benefits(
        now=november,
        bot_db=bot_db,
        web_db=web_db,
    )
    assert announced["announcement_needed"] is False


def test_expired_vip_does_not_receive_new_month_benefits(tmp_path):
    bot_db = tmp_path / "bot.db"
    web_db = tmp_path / "web_dashboard.db"
    _make_bot_db(
        bot_db,
        [
            (
                "888",
                {
                    "total_spent": 25000,
                    "vip_level_index": 4,
                    "last_order_at": "2026-01-01T00:00:00+08:00",
                },
            )
        ],
    )

    now = datetime(2026, 11, 1, 8, tzinfo=TAIPEI_TZ)
    sync_current_month_vip_benefits(now=now, bot_db=bot_db, web_db=web_db)
    assert _benefit_rows(web_db, "888", "2026-11") == []


def test_october_legacy_used_customers_are_recorded_as_redeemed_200_only(tmp_path):
    bot_db = tmp_path / "bot.db"
    web_db = tmp_path / "web_dashboard.db"
    _make_bot_db(bot_db, [])

    now = datetime(2026, 10, 10, 20, tzinfo=TAIPEI_TZ)
    sync_current_month_vip_benefits(now=now, bot_db=bot_db, web_db=web_db)

    for customer_id in OCTOBER_2026_USED_200_CUSTOMERS:
        rows = _benefit_rows(web_db, customer_id, "2026-10")
        assert len(rows) == 1
        assert rows[0]["benefit_key"] == MONTHLY_COUPON_200
        assert rows[0]["status"] == "redeemed"
        assert rows[0]["source"] == "legacy_import"


def test_black_diamond_choice_reserve_release_and_redeem(tmp_path):
    bot_db = tmp_path / "bot.db"
    web_db = tmp_path / "web_dashboard.db"
    customer_id = "777"
    _make_bot_db(
        bot_db,
        [
            (
                customer_id,
                {
                    "total_spent": 88888,
                    "vip_level_index": 6,
                    "last_order_at": "2026-11-01T00:00:00+08:00",
                },
            )
        ],
    )
    now = datetime(2026, 11, 5, 12, tzinfo=TAIPEI_TZ)

    reserved = reserve_black_diamond_choice(
        customer_id,
        "entertainment_2h",
        now=now,
        bot_db=bot_db,
        web_db=web_db,
    )
    assert reserved["status"] == "reserved"
    assert reserved["choice_key"] == "entertainment_2h"

    assert release_black_diamond_choice(
        customer_id,
        month_key="2026-11",
        now=now,
        web_db=web_db,
    ) is True

    snapshot = get_customer_vip_monthly_snapshot(
        customer_id,
        now=now,
        bot_db=bot_db,
        web_db=web_db,
    )
    assert snapshot["black_diamond_available"] is True

    reserve_black_diamond_choice(
        customer_id,
        "secret_space_1000w",
        now=now,
        bot_db=bot_db,
        web_db=web_db,
    )
    assert redeem_black_diamond_choice(
        customer_id,
        month_key="2026-11",
        now=now,
        web_db=web_db,
    ) is True

    redeemed = get_customer_vip_monthly_snapshot(
        customer_id,
        now=now,
        bot_db=bot_db,
        web_db=web_db,
        ensure_synced=False,
    )
    assert redeemed["black_diamond_available"] is False
    assert redeemed["black_diamond"]["status"] == "redeemed"
