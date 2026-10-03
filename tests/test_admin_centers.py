import sqlite3

from web.app.routers import admin_centers


def _make_web_db(path):
    with sqlite3.connect(path) as conn:
        conn.executescript(
            """
            CREATE TABLE web_staff_members (
                discord_id TEXT PRIMARY KEY,
                username TEXT,
                display_name TEXT,
                global_name TEXT,
                is_active INTEGER,
                is_customer_service INTEGER,
                is_worker INTEGER,
                is_companion INTEGER
            );

            CREATE TABLE staff_profiles (
                staff_discord_id TEXT PRIMARY KEY,
                profile_type TEXT,
                role_title TEXT,
                main_games TEXT,
                is_public INTEGER
            );

            CREATE TABLE web_orders (
                id INTEGER PRIMARY KEY,
                customer_discord_id TEXT,
                customer_display_name TEXT,
                status TEXT,
                amount INTEGER,
                customer_pay_amount INTEGER,
                created_at TEXT,
                updated_at TEXT
            );

            CREATE TABLE order_reviews (
                id INTEGER PRIMARY KEY,
                customer_discord_id TEXT,
                customer_display_name TEXT,
                staff_discord_id TEXT,
                staff_display_name TEXT,
                rating INTEGER,
                comment TEXT,
                service_item TEXT,
                is_public INTEGER,
                is_hidden INTEGER,
                created_at TEXT
            );

            CREATE TABLE worker_payouts (
                id INTEGER PRIMARY KEY,
                final_payout INTEGER,
                payout_status TEXT
            );

            CREATE TABLE customer_service_payouts (
                id INTEGER PRIMARY KEY,
                payout_amount INTEGER,
                payout_status TEXT
            );
            """
        )

        conn.execute(
            """
            INSERT INTO web_staff_members
            VALUES ('1','u1','雞腿',NULL,1,0,1,0)
            """
        )
        conn.execute(
            """
            INSERT INTO staff_profiles
            VALUES ('1','protector','護航','三角洲',1)
            """
        )
        conn.execute(
            """
            INSERT INTO web_orders
            VALUES (1,'100','老闆A','closed',500,450,'2026-10-01','2026-10-02')
            """
        )
        conn.execute(
            """
            INSERT INTO order_reviews
            VALUES (1,'100','老闆A','1','雞腿',5,'很好','技術陪',1,0,'2026-10-02')
            """
        )
        conn.execute(
            "INSERT INTO worker_payouts VALUES (1,300,'unpaid')"
        )
        conn.execute(
            "INSERT INTO customer_service_payouts VALUES (1,25,'paid')"
        )
        conn.commit()


def _make_bot_db(path):
    with sqlite3.connect(path) as conn:
        conn.execute(
            """
            CREATE TABLE customer_wallets (
                customer_discord_id TEXT PRIMARY KEY,
                balance INTEGER
            )
            """
        )
        conn.execute(
            "INSERT INTO customer_wallets VALUES ('100', 888)"
        )
        conn.commit()


def test_staff_and_customer_centers_share_operational_data(tmp_path, monkeypatch):
    web_db = tmp_path / "web_dashboard.db"
    bot_db = tmp_path / "bot.db"
    _make_web_db(web_db)
    _make_bot_db(bot_db)

    monkeypatch.setattr(admin_centers, "WEB_DB", web_db)
    monkeypatch.setattr(admin_centers, "BOT_DB", bot_db)

    staff = admin_centers._staff_snapshot()
    assert staff["stats"]["active"] == 1
    assert staff["stats"]["profiles"] == 1
    assert staff["rows"][0]["main_games"] == "三角洲"

    customers = admin_centers._customer_snapshot(include_wallets=True)
    assert customers["stats"]["customers"] == 1
    assert customers["stats"]["wallet_total"] == 888
    assert customers["rows"][0]["completed_spend"] == 450
    assert customers["rows"][0]["wallet_balance"] == 888
    assert customers["reviews"][0]["rating"] == 5


def test_finance_center_payout_summary_combines_staff_types(tmp_path, monkeypatch):
    web_db = tmp_path / "web_dashboard.db"
    _make_web_db(web_db)

    monkeypatch.setattr(admin_centers, "WEB_DB", web_db)

    payout = admin_centers._payout_snapshot()

    assert payout["unpaid_total"] == 300
    assert payout["unpaid_count"] == 1
    assert payout["paid_total"] == 25
    assert payout["paid_count"] == 1


def test_customer_center_does_not_expose_wallets_without_manager_access(tmp_path, monkeypatch):
    web_db = tmp_path / "web_dashboard.db"
    bot_db = tmp_path / "bot.db"
    _make_web_db(web_db)
    _make_bot_db(bot_db)

    monkeypatch.setattr(admin_centers, "WEB_DB", web_db)
    monkeypatch.setattr(admin_centers, "BOT_DB", bot_db)

    customers = admin_centers._customer_snapshot(include_wallets=False)

    assert customers["stats"]["wallet_count"] == 0
    assert customers["stats"]["wallet_total"] == 0
    assert customers["rows"][0]["wallet_balance"] == 0
