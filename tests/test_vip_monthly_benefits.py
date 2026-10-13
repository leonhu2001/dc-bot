import json
import sqlite3

import pytest
from datetime import datetime, timezone, timedelta

from services.vip_monthly_benefits import (
    BLACK_DIAMOND_CHOICE,
    MONTHLY_COUPON_200,
    MONTHLY_COUPON_500,
    OCTOBER_2026_USED_200_CUSTOMERS,
    REVOKED,
    get_customer_vip_monthly_snapshot,
    list_available_cash_benefits,
    redeem_cash_benefits_for_channel,
    release_cash_benefits_for_channel,
    reserve_cash_benefit_for_channel,
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
        conn.execute(
            """
            CREATE TABLE orders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                customer_id TEXT,
                amount INTEGER,
                status TEXT,
                closed_at TEXT
            )
            """
        )
        for customer_id, data in rows:
            conn.execute(
                "INSERT INTO customers(customer_id, data_json) VALUES (?, ?)",
                (str(customer_id), json.dumps(data, ensure_ascii=False)),
            )
            last_order_at = str(data.get("monthly_activity_order_at") or data.get("last_order_at") or "").strip()
            if last_order_at:
                conn.execute(
                    """
                    INSERT INTO orders(customer_id, amount, status, closed_at)
                    VALUES (?, ?, 'closed', ?)
                    """,
                    (
                        str(customer_id),
                        int(data.get("monthly_activity_spend", data.get("total_spent", 0)) or 0),
                        last_order_at,
                    ),
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
                    "last_order_at": "2026-10-10T12:00:00+08:00",
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
        bot_db=bot_db,
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


def _rewrite_customer_data(bot_db, customer_id: str, mutate):
    with sqlite3.connect(bot_db) as conn:
        row = conn.execute(
            "SELECT data_json FROM customers WHERE customer_id=?",
            (str(customer_id),),
        ).fetchone()
        assert row is not None
        data = json.loads(row[0])
        mutate(data)
        conn.execute(
            "UPDATE customers SET data_json=? WHERE customer_id=?",
            (json.dumps(data, ensure_ascii=False), str(customer_id)),
        )
        conn.commit()


def test_downgrade_revokes_unused_higher_tier_monthly_benefits_and_reupgrade_restores(tmp_path):
    bot_db = tmp_path / "bot.db"
    web_db = tmp_path / "web_dashboard.db"
    customer_id = "black-to-platinum"
    _make_bot_db(
        bot_db,
        [
            (
                customer_id,
                {
                    "total_spent": 88888,
                    "vip_level_index": 6,
                    "last_order_at": "2026-11-05T10:00:00+08:00",
                },
            )
        ],
    )
    now = datetime(2026, 11, 5, 12, tzinfo=TAIPEI_TZ)

    black = get_customer_vip_monthly_snapshot(
        customer_id,
        now=now,
        bot_db=bot_db,
        web_db=web_db,
    )
    assert black["current_level"] == "黑鑽魔丸"
    assert {row["benefit_key"] for row in black["cash_benefits"]} == {
        MONTHLY_COUPON_200,
        MONTHLY_COUPON_500,
    }
    assert black["black_diamond_available"] is True

    def downgrade(data):
        data["vip_level_index"] = 3
        data["vip_progress_base_total_spent"] = 88888
        data["vip_progress_reset_active"] = True
        data["last_level_manual_fixed_at"] = "2026-11-05T11:00:00+08:00"

    _rewrite_customer_data(bot_db, customer_id, downgrade)
    platinum = get_customer_vip_monthly_snapshot(
        customer_id,
        now=now,
        bot_db=bot_db,
        web_db=web_db,
    )

    assert platinum["current_level"] == "白金魔丸"
    assert [row["benefit_key"] for row in platinum["cash_benefits"]] == [
        MONTHLY_COUPON_200
    ]
    assert platinum["black_diamond"] is None
    assert platinum["black_diamond_entitled"] is False
    assert platinum["black_diamond_available"] is False

    raw = {
        row["benefit_key"]: row["status"]
        for row in _benefit_rows(web_db, customer_id, "2026-11")
    }
    assert raw[MONTHLY_COUPON_200] == "available"
    assert raw[MONTHLY_COUPON_500] == REVOKED
    assert raw[BLACK_DIAMOND_CHOICE] == REVOKED

    with pytest.raises(ValueError, match="目前 VIP 等級沒有黑鑽尊享福利"):
        reserve_black_diamond_choice(
            customer_id,
            "entertainment_2h",
            now=now,
            bot_db=bot_db,
            web_db=web_db,
        )

    def upgrade_again(data):
        data["vip_level_index"] = 6
        data["vip_progress_reset_active"] = False
        data.pop("vip_progress_base_total_spent", None)
        data.pop("last_level_manual_fixed_at", None)

    _rewrite_customer_data(bot_db, customer_id, upgrade_again)
    restored = get_customer_vip_monthly_snapshot(
        customer_id,
        now=now,
        bot_db=bot_db,
        web_db=web_db,
    )
    assert {row["benefit_key"] for row in restored["cash_benefits"]} == {
        MONTHLY_COUPON_200,
        MONTHLY_COUPON_500,
    }
    assert restored["black_diamond_available"] is True


def test_releasing_reserved_black_benefit_after_downgrade_revokes_instead_of_reopening(tmp_path):
    bot_db = tmp_path / "bot.db"
    web_db = tmp_path / "web_dashboard.db"
    customer_id = "reserved-then-downgraded"
    _make_bot_db(
        bot_db,
        [
            (
                customer_id,
                {
                    "total_spent": 88888,
                    "vip_level_index": 6,
                    "last_order_at": "2026-11-05T10:00:00+08:00",
                },
            )
        ],
    )
    now = datetime(2026, 11, 5, 12, tzinfo=TAIPEI_TZ)
    reserve_black_diamond_choice(
        customer_id,
        "entertainment_2h",
        now=now,
        bot_db=bot_db,
        web_db=web_db,
    )

    def downgrade(data):
        data["vip_level_index"] = 3
        data["vip_progress_base_total_spent"] = 88888
        data["vip_progress_reset_active"] = True
        data["last_level_manual_fixed_at"] = "2026-11-05T11:00:00+08:00"

    _rewrite_customer_data(bot_db, customer_id, downgrade)
    assert release_black_diamond_choice(
        customer_id,
        month_key="2026-11",
        now=now,
        web_db=web_db,
        bot_db=bot_db,
    ) is True

    raw = {
        row["benefit_key"]: row["status"]
        for row in _benefit_rows(web_db, customer_id, "2026-11")
    }
    assert raw[BLACK_DIAMOND_CHOICE] == REVOKED


def test_monthly_cash_benefit_reserve_release_and_redeem_by_channel(tmp_path):
    bot_db = tmp_path / "bot.db"
    web_db = tmp_path / "web_dashboard.db"
    customer_id = "monthly-cash-user"
    _make_bot_db(
        bot_db,
        [(
            customer_id,
            {
                "total_spent": 30000,
                "vip_level_index": 3,
                "last_order_at": "2026-11-05T10:00:00+08:00",
            },
        )],
    )
    now = datetime(2026, 11, 5, 12, tzinfo=TAIPEI_TZ)

    available = list_available_cash_benefits(
        customer_id,
        now=now,
        bot_db=bot_db,
        web_db=web_db,
    )
    assert len(available) == 1
    assert available[0]["benefit_key"] == MONTHLY_COUPON_200
    assert available[0]["amount"] == 200

    benefit_id = available[0]["id"]
    reserved = reserve_cash_benefit_for_channel(
        benefit_id=benefit_id,
        customer_id=customer_id,
        channel_id="ticket-1",
        now=now,
        bot_db=bot_db,
        web_db=web_db,
    )
    assert reserved["status"] == "reserved"
    assert reserved["reserved_channel_id"] == "ticket-1"

    with pytest.raises(ValueError, match="已使用、已保留或已失效"):
        reserve_cash_benefit_for_channel(
            benefit_id=benefit_id,
            customer_id=customer_id,
            channel_id="ticket-2",
            now=now,
            bot_db=bot_db,
            web_db=web_db,
        )

    assert release_cash_benefits_for_channel(
        "ticket-1",
        now=now,
        bot_db=bot_db,
        web_db=web_db,
    ) == 1
    assert list_available_cash_benefits(
        customer_id,
        now=now,
        bot_db=bot_db,
        web_db=web_db,
    )[0]["id"] == benefit_id

    reserve_cash_benefit_for_channel(
        benefit_id=benefit_id,
        customer_id=customer_id,
        channel_id="ticket-3",
        now=now,
        bot_db=bot_db,
        web_db=web_db,
    )
    assert redeem_cash_benefits_for_channel(
        "ticket-3",
        now=now,
        web_db=web_db,
    ) == 1
    assert list_available_cash_benefits(
        customer_id,
        now=now,
        bot_db=bot_db,
        web_db=web_db,
        ensure_synced=False,
    ) == []


def test_white_diamond_monthly_benefits_require_5000_recent_spend(tmp_path):
    bot_db = tmp_path / "bot.db"
    web_db = tmp_path / "web_dashboard.db"
    customer_id = "white-diamond-activity"
    _make_bot_db(
        bot_db,
        [(
            customer_id,
            {
                "total_spent": 50000,
                "vip_level_index": 5,
                "last_order_at": "2026-11-05T10:00:00+08:00",
                "monthly_activity_spend": 4999,
            },
        )],
    )
    now = datetime(2026, 11, 5, 12, tzinfo=TAIPEI_TZ)

    snapshot = get_customer_vip_monthly_snapshot(
        customer_id,
        now=now,
        bot_db=bot_db,
        web_db=web_db,
    )
    assert snapshot["recent_spend"] == 4999
    assert snapshot["recent_spend_required"] == 5000
    assert snapshot["monthly_spend_eligible"] is False
    assert snapshot["cash_benefits"] == []

    with sqlite3.connect(bot_db) as conn:
        conn.execute(
            "UPDATE orders SET amount=5000 WHERE customer_id=?",
            (customer_id,),
        )
        conn.commit()

    unlocked = get_customer_vip_monthly_snapshot(
        customer_id,
        now=now,
        bot_db=bot_db,
        web_db=web_db,
    )
    assert unlocked["monthly_spend_eligible"] is True
    assert {row["benefit_key"] for row in unlocked["cash_benefits"]} == {
        MONTHLY_COUPON_200,
        MONTHLY_COUPON_500,
    }


def test_pre_policy_monthly_benefit_is_not_retroactively_revoked_by_activity_gate(tmp_path):
    bot_db = tmp_path / "bot.db"
    web_db = tmp_path / "web_dashboard.db"
    customer_id = "grandfathered-october"
    _make_bot_db(
        bot_db,
        [(
            customer_id,
            {
                "total_spent": 50000,
                "vip_level_index": 5,
                "last_order_at": "2026-10-10T10:00:00+08:00",
            },
        )],
    )

    before_policy = datetime(2026, 10, 10, 12, tzinfo=TAIPEI_TZ)
    first = get_customer_vip_monthly_snapshot(
        customer_id,
        now=before_policy,
        bot_db=bot_db,
        web_db=web_db,
    )
    assert len(first["cash_benefits"]) == 2

    with sqlite3.connect(bot_db) as conn:
        conn.execute(
            "UPDATE orders SET closed_at='2026-08-01T10:00:00+08:00' WHERE customer_id=?",
            (customer_id,),
        )
        conn.commit()

    after_policy = datetime(2026, 10, 15, 12, tzinfo=TAIPEI_TZ)
    grandfathered = get_customer_vip_monthly_snapshot(
        customer_id,
        now=after_policy,
        bot_db=bot_db,
        web_db=web_db,
    )
    assert grandfathered["recent_spend"] == 0
    assert grandfathered["monthly_spend_eligible"] is False
    assert {row["benefit_key"] for row in grandfathered["cash_benefits"]} == {
        MONTHLY_COUPON_200,
        MONTHLY_COUPON_500,
    }
