import sqlite3

from services.wallet_service import (
    adjust_wallet_balance,
    get_wallet_balance,
)
from web.app.services.accounting_reconciliation import (
    build_accounting_reconciliation_snapshot,
)


def test_payment_adjustment_reference_is_idempotent(tmp_path):
    bot_db = tmp_path / "bot.db"

    adjust_wallet_balance(
        customer_id="customer-1",
        amount=2000,
        tx_type="topup",
        order_no="TOPUP-1",
        db_file=bot_db,
    )

    first = adjust_wallet_balance(
        customer_id="customer-1",
        amount=-500,
        tx_type="payment_adjustment",
        order_channel_id="ticket-1",
        order_no="WEB-1:AMOUNT-ADJ:9",
        db_file=bot_db,
    )
    second = adjust_wallet_balance(
        customer_id="customer-1",
        amount=-500,
        tx_type="payment_adjustment",
        order_channel_id="ticket-1",
        order_no="WEB-1:AMOUNT-ADJ:9",
        db_file=bot_db,
    )

    assert first["id"] == second["id"]
    assert get_wallet_balance("customer-1", bot_db) == 1500

    with sqlite3.connect(bot_db) as conn:
        count = conn.execute(
            """
            SELECT COUNT(*)
            FROM wallet_transactions
            WHERE customer_discord_id = ?
              AND type = ?
              AND order_no = ?
            """,
            (
                "customer-1",
                "payment_adjustment",
                "WEB-1:AMOUNT-ADJ:9",
            ),
        ).fetchone()[0]

    assert count == 1


def test_reconciliation_uses_payment_plus_adjustments_net(tmp_path):
    bot_db = tmp_path / "bot.db"
    web_db = tmp_path / "web_dashboard.db"

    adjust_wallet_balance(
        customer_id="customer-1",
        amount=2000,
        tx_type="topup",
        order_no="TOPUP-1",
        db_file=bot_db,
    )
    adjust_wallet_balance(
        customer_id="customer-1",
        amount=-652,
        tx_type="payment",
        order_channel_id="ticket-1",
        order_no="MO20261002001",
        db_file=bot_db,
    )
    adjust_wallet_balance(
        customer_id="customer-1",
        amount=-500,
        tx_type="payment_adjustment",
        order_channel_id="ticket-1",
        order_no="WEB-1:AMOUNT-ADJ:9",
        db_file=bot_db,
    )

    with sqlite3.connect(web_db) as conn:
        conn.executescript(
            """
            CREATE TABLE web_orders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                bot_order_no TEXT,
                ticket_channel_id TEXT,
                customer_discord_id TEXT,
                amount INTEGER NOT NULL DEFAULT 0,
                customer_pay_amount INTEGER,
                payout_base_amount INTEGER,
                payment_method TEXT,
                customer_service_discord_id TEXT,
                customer_service_display_name TEXT,
                status TEXT NOT NULL
            );

            CREATE TABLE order_assignments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                order_id INTEGER NOT NULL,
                worker_discord_id TEXT NOT NULL,
                has_named_bonus INTEGER NOT NULL DEFAULT 0,
                is_active INTEGER NOT NULL DEFAULT 1
            );

            CREATE TABLE worker_payouts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                order_id INTEGER NOT NULL,
                worker_discord_id TEXT NOT NULL,
                final_payout REAL NOT NULL DEFAULT 0,
                payout_status TEXT NOT NULL DEFAULT 'unpaid',
                paid_at TEXT
            );

            CREATE TABLE customer_service_payouts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                order_id INTEGER NOT NULL,
                customer_service_discord_id TEXT,
                payout_amount REAL NOT NULL DEFAULT 0,
                payout_status TEXT NOT NULL DEFAULT 'unpaid',
                paid_at TEXT
            );
            """
        )
        conn.execute(
            """
            INSERT INTO web_orders(
                id,
                bot_order_no,
                ticket_channel_id,
                customer_discord_id,
                amount,
                customer_pay_amount,
                payout_base_amount,
                payment_method,
                customer_service_discord_id,
                customer_service_display_name,
                status
            )
            VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                1,
                "MO20261002001",
                "ticket-1",
                "customer-1",
                1152,
                1152,
                1152,
                "我的錢包",
                "cs-1",
                "客服一號",
                "active",
            ),
        )

    snapshot = build_accounting_reconciliation_snapshot(tmp_path)

    payment_issues = [
        item
        for item in snapshot["issues"]
        if item["category"] == "order_payment"
    ]

    assert payment_issues == []
