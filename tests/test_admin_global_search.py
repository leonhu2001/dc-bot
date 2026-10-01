import sqlite3
from pathlib import Path

from web.app.services import admin_global_search


def _setup_web_db(path: Path):
    with sqlite3.connect(path) as conn:
        conn.executescript(
            """
            CREATE TABLE web_users (
                discord_id TEXT PRIMARY KEY,
                username TEXT,
                global_name TEXT,
                last_login_at TEXT
            );

            CREATE TABLE web_orders (
                id INTEGER PRIMARY KEY,
                bot_order_no TEXT,
                ticket_channel_id TEXT,
                customer_discord_id TEXT,
                customer_display_name TEXT,
                category TEXT,
                item TEXT,
                quantity INTEGER,
                amount INTEGER,
                customer_pay_amount INTEGER,
                payment_method TEXT,
                status TEXT,
                created_at TEXT
            );

            CREATE TABLE payment_reviews (
                id INTEGER PRIMARY KEY,
                review_no TEXT,
                source_type TEXT,
                source_id TEXT,
                ticket_channel_id TEXT,
                customer_discord_id TEXT,
                customer_display_name TEXT,
                amount INTEGER,
                payment_method TEXT,
                status TEXT,
                created_at TEXT
            );

            CREATE TABLE order_reviews (
                id INTEGER PRIMARY KEY,
                receipt_id TEXT,
                ticket_channel_id TEXT,
                customer_discord_id TEXT,
                customer_display_name TEXT,
                staff_discord_id TEXT,
                staff_display_name TEXT,
                rating INTEGER,
                comment TEXT,
                created_at TEXT
            );

            CREATE TABLE support_calls (
                id INTEGER PRIMARY KEY,
                ticket_channel_id TEXT,
                customer_discord_id TEXT,
                customer_display_name TEXT,
                status TEXT,
                called_at TEXT,
                claimed_by_discord_id TEXT,
                claimed_by_display_name TEXT
            );

            CREATE TABLE ticket_archives (
                id INTEGER PRIMARY KEY,
                ticket_channel_id TEXT,
                ticket_channel_name TEXT,
                order_id INTEGER,
                order_no TEXT,
                customer_discord_id TEXT,
                customer_display_name TEXT,
                customer_service_discord_id TEXT,
                customer_service_display_name TEXT,
                message_count INTEGER,
                closed_at TEXT
            );

            INSERT INTO web_users
            VALUES ('100', 'boss100', '大老闆', '2026-10-02 01:00:00');

            INSERT INTO web_orders
            VALUES (
                10, 'MO20261002001', '555', '100', '大老闆',
                '三角洲', '頂護', 1, 1000, 900, '轉帳', 'active',
                '2026-10-02 02:00:00'
            );

            INSERT INTO payment_reviews
            VALUES (
                1, 'PAY-20261002-0001', 'order', '10', '555',
                '100', '大老闆', 900, '轉帳', 'pending_review',
                '2026-10-02T02:10:00+08:00'
            );

            INSERT INTO order_reviews
            VALUES (
                1, 'MO20261002001', '555', '100', '大老闆',
                '200', '陪玩A', 5, '很好', '2026-10-02T03:00:00+08:00'
            );

            INSERT INTO support_calls
            VALUES (
                1, '555', '100', '大老闆', 'claimed',
                '2026-10-02T02:20:00+08:00', '300', '客服A'
            );

            INSERT INTO ticket_archives
            VALUES (
                1, '555', '已結單-大老闆', 10, 'MO20261002001',
                '100', '大老闆', '300', '客服A', 25,
                '2026-10-02T04:00:00+08:00'
            );
            """
        )
        conn.commit()


def _setup_bot_db(path: Path):
    with sqlite3.connect(path) as conn:
        conn.executescript(
            """
            CREATE TABLE customer_wallets (
                customer_discord_id TEXT PRIMARY KEY,
                balance INTEGER,
                updated_at TEXT
            );

            CREATE TABLE wallet_transactions (
                id INTEGER PRIMARY KEY,
                customer_discord_id TEXT,
                amount INTEGER,
                balance_before INTEGER,
                balance_after INTEGER,
                type TEXT,
                order_channel_id TEXT,
                order_no TEXT,
                operator_discord_id TEXT,
                operator_display_name TEXT,
                note TEXT,
                created_at TEXT
            );

            CREATE TABLE topup_orders (
                id INTEGER PRIMARY KEY,
                topup_no TEXT,
                customer_discord_id TEXT,
                customer_display_name TEXT,
                amount INTEGER,
                payment_method TEXT,
                bank_last5 TEXT,
                payment_reference TEXT,
                status TEXT,
                credited_amount INTEGER,
                created_at TEXT
            );

            CREATE TABLE customers (
                customer_id INTEGER PRIMARY KEY,
                total_spent INTEGER,
                points INTEGER,
                completed_orders INTEGER,
                last_order_at TEXT,
                level TEXT,
                data_json TEXT
            );

            INSERT INTO customer_wallets
            VALUES ('100', 1500, '2026-10-02T04:00:00+08:00');

            INSERT INTO wallet_transactions
            VALUES (
                1, '100', 500, 1000, 1500, 'topup', NULL, NULL,
                '300', '客服A', '測試儲值', '2026-10-02T04:00:00+08:00'
            );

            INSERT INTO topup_orders
            VALUES (
                1, 'TOPUP-20261002-0001', '100', '大老闆', 500,
                'bank_transfer', '12345', '12345', 'completed', 525,
                '2026-10-02T03:50:00+08:00'
            );

            INSERT INTO customers
            VALUES (
                100, 12000, 120, 18, '2026-10-02T04:00:00+08:00',
                '黃金魔丸', '{}'
            );
            """
        )
        conn.commit()


def test_search_payment_order_topup_and_ticket_resolve_same_customer(tmp_path):
    _setup_web_db(tmp_path / "web_dashboard.db")
    _setup_bot_db(tmp_path / "bot.db")

    for query in (
        "PAY-20261002-0001",
        "MO20261002001",
        "TOPUP-20261002-0001",
        "555",
    ):
        result = admin_global_search.search_admin_customers(
            query,
            root=tmp_path,
        )

        assert result["count"] >= 1
        assert result["results"][0]["customer_discord_id"] == "100"
        assert result["results"][0]["customer_display_name"] == "大老闆"


def test_search_by_nickname_and_discord_id(tmp_path):
    _setup_web_db(tmp_path / "web_dashboard.db")
    _setup_bot_db(tmp_path / "bot.db")

    by_name = admin_global_search.search_admin_customers(
        "大老闆",
        root=tmp_path,
    )
    assert by_name["results"][0]["customer_discord_id"] == "100"

    by_id = admin_global_search.search_admin_customers(
        "100",
        root=tmp_path,
    )
    assert by_id["results"][0]["customer_discord_id"] == "100"
    assert by_id["results"][0]["score"] == 100


def test_customer_360_aggregates_all_customer_sources(tmp_path):
    _setup_web_db(tmp_path / "web_dashboard.db")
    _setup_bot_db(tmp_path / "bot.db")

    customer = admin_global_search.build_customer_360(
        "100",
        root=tmp_path,
    )

    assert customer["identity"]["display_name"] == "大老闆"
    assert customer["wallet"]["balance"] == 1500
    assert customer["wallet"]["balance_text"] == "1,500T"
    assert customer["vip"]["level"] == "黃金魔丸"
    assert customer["vip"]["total_spent"] == 12000
    assert customer["counts"] == {
        "orders": 1,
        "payments": 1,
        "topups": 1,
        "reviews": 1,
        "support_calls": 1,
        "tickets": 1,
        "wallet_transactions": 1,
    }
    assert customer["orders"][0]["order_no"] == "MO20261002001"
    assert customer["payments"][0]["review_no"] == "PAY-20261002-0001"
    assert customer["topups"][0]["topup_no"] == "TOPUP-20261002-0001"
    assert customer["reviews"][0]["rating"] == 5
    assert customer["support_calls"][0]["status_label"] == "客服處理中"
    assert customer["tickets"][0]["ticket_channel_id"] == "555"


def test_unknown_customer_returns_empty_but_safe_bundle(tmp_path):
    _setup_web_db(tmp_path / "web_dashboard.db")
    _setup_bot_db(tmp_path / "bot.db")

    customer = admin_global_search.build_customer_360(
        "999",
        root=tmp_path,
    )

    assert customer["customer_id"] == "999"
    assert customer["counts"]["orders"] == 0
    assert customer["wallet"]["balance"] == 0
    assert customer["vip"]["found"] is False
