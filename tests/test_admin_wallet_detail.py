import sqlite3

from web.app.routers import admin_wallets


def test_wallet_detail_without_wallet_row_returns_empty_wallet(tmp_path, monkeypatch):
    bot_db = tmp_path / "bot.db"
    web_db = tmp_path / "web_dashboard.db"

    monkeypatch.setattr(admin_wallets, "bot_db_path", lambda: bot_db)
    monkeypatch.setattr(admin_wallets, "web_dashboard_db_path", lambda: web_db)

    wallet, transactions = admin_wallets.fetch_wallet_detail("123456789")

    assert wallet["customer_discord_id"] == "123456789"
    assert wallet["balance"] == 0
    assert wallet["balance_text"] == "0T"
    assert transactions == []


def test_wallet_detail_recovers_balance_from_orphan_transaction(tmp_path, monkeypatch):
    bot_db = tmp_path / "bot.db"
    web_db = tmp_path / "web_dashboard.db"

    monkeypatch.setattr(admin_wallets, "bot_db_path", lambda: bot_db)
    monkeypatch.setattr(admin_wallets, "web_dashboard_db_path", lambda: web_db)

    admin_wallets.ensure_wallet_tables()

    with sqlite3.connect(bot_db) as conn:
        conn.execute(
            """
            INSERT INTO wallet_transactions(
                customer_discord_id, amount, balance_before, balance_after, type,
                order_channel_id, order_no, operator_discord_id,
                operator_display_name, note, created_at
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                "987654321",
                500,
                1000,
                1500,
                "adjustment",
                None,
                "TEST-1",
                None,
                None,
                "test",
                "2026-09-26T05:40:00+08:00",
            ),
        )
        conn.commit()

    wallet, transactions = admin_wallets.fetch_wallet_detail("987654321")

    assert wallet["balance"] == 1500
    assert wallet["balance_text"] == "1,500T"
    assert wallet["updated_at_text"] == "2026/09/26 05:40"
    assert len(transactions) == 1
