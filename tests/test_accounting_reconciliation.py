import sqlite3
from pathlib import Path

from web.app.services.accounting_reconciliation import (
    build_accounting_reconciliation_snapshot,
)


def _create_bot_db(path: Path) -> None:
    with sqlite3.connect(path) as conn:
        conn.executescript(
            """
            CREATE TABLE customer_wallets (
                customer_discord_id TEXT PRIMARY KEY,
                balance INTEGER NOT NULL,
                updated_at TEXT
            );

            CREATE TABLE wallet_transactions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                customer_discord_id TEXT NOT NULL,
                amount INTEGER NOT NULL,
                balance_before INTEGER NOT NULL,
                balance_after INTEGER NOT NULL,
                type TEXT NOT NULL,
                order_channel_id TEXT,
                order_no TEXT,
                operator_discord_id TEXT,
                operator_display_name TEXT,
                note TEXT,
                created_at TEXT NOT NULL
            );

            CREATE TABLE topup_orders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                topup_no TEXT UNIQUE,
                customer_discord_id TEXT NOT NULL,
                amount INTEGER NOT NULL,
                status TEXT NOT NULL,
                rebate_amount INTEGER NOT NULL DEFAULT 0,
                credited_amount INTEGER NOT NULL DEFAULT 0,
                wallet_transaction_id INTEGER,
                bonus_transaction_id INTEGER
            );
            """
        )

        conn.execute(
            """
            INSERT INTO customer_wallets(
                customer_discord_id,
                balance,
                updated_at
            )
            VALUES('customer-1', 800, '2026-10-02T01:00:00+08:00')
            """
        )

        conn.execute(
            """
            INSERT INTO wallet_transactions(
                id,
                customer_discord_id,
                amount,
                balance_before,
                balance_after,
                type,
                order_no,
                created_at
            )
            VALUES(
                1,
                'customer-1',
                1000,
                0,
                1000,
                'topup',
                'TOPUP-20261002-0001',
                '2026-10-02T01:00:00+08:00'
            )
            """
        )

        conn.execute(
            """
            INSERT INTO wallet_transactions(
                id,
                customer_discord_id,
                amount,
                balance_before,
                balance_after,
                type,
                order_no,
                created_at
            )
            VALUES(
                2,
                'customer-1',
                -200,
                1000,
                800,
                'payment',
                'MO20261002001',
                '2026-10-02T01:05:00+08:00'
            )
            """
        )

        conn.execute(
            """
            INSERT INTO topup_orders(
                id,
                topup_no,
                customer_discord_id,
                amount,
                status,
                rebate_amount,
                credited_amount,
                wallet_transaction_id,
                bonus_transaction_id
            )
            VALUES(
                1,
                'TOPUP-20261002-0001',
                'customer-1',
                1000,
                'completed',
                0,
                1000,
                1,
                NULL
            )
            """
        )


def _create_web_db(path: Path) -> None:
    with sqlite3.connect(path) as conn:
        conn.executescript(
            """
            CREATE TABLE web_orders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                bot_order_no TEXT,
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

            CREATE TABLE worker_tips (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                receipt_id TEXT,
                customer_discord_id TEXT NOT NULL,
                worker_discord_id TEXT NOT NULL,
                amount INTEGER NOT NULL,
                payment_method TEXT NOT NULL,
                payment_status TEXT NOT NULL,
                payout_status TEXT NOT NULL,
                wallet_transaction_id INTEGER
            );
            """
        )

        conn.execute(
            """
            INSERT INTO web_orders(
                id,
                bot_order_no,
                customer_discord_id,
                amount,
                customer_pay_amount,
                payout_base_amount,
                payment_method,
                customer_service_discord_id,
                customer_service_display_name,
                status
            )
            VALUES(
                1,
                'MO20261002001',
                'customer-1',
                200,
                200,
                200,
                '我的錢包',
                'cs-1',
                '客服一號',
                'closed'
            )
            """
        )

        conn.execute(
            """
            INSERT INTO order_assignments(
                order_id,
                worker_discord_id,
                has_named_bonus,
                is_active
            )
            VALUES(1, 'worker-1', 0, 1)
            """
        )

        conn.execute(
            """
            INSERT INTO worker_payouts(
                order_id,
                worker_discord_id,
                final_payout,
                payout_status
            )
            VALUES(1, 'worker-1', 160, 'unpaid')
            """
        )

        conn.execute(
            """
            INSERT INTO customer_service_payouts(
                order_id,
                customer_service_discord_id,
                payout_amount,
                payout_status
            )
            VALUES(1, 'cs-1', 10, 'unpaid')
            """
        )


def _healthy_root(tmp_path: Path) -> Path:
    _create_bot_db(tmp_path / "bot.db")
    _create_web_db(tmp_path / "web_dashboard.db")
    return tmp_path


def _issue_codes(snapshot: dict) -> set[str]:
    return {
        str(issue["code"])
        for issue in snapshot["issues"]
    }


def test_healthy_accounting_snapshot_has_no_issues(tmp_path):
    root = _healthy_root(tmp_path)

    snapshot = build_accounting_reconciliation_snapshot(root)

    assert snapshot["status"] == "ok"
    assert snapshot["issue_count"] == 0
    assert snapshot["critical_count"] == 0
    assert snapshot["warning_count"] == 0


def test_wallet_chain_break_is_detected(tmp_path):
    root = _healthy_root(tmp_path)

    with sqlite3.connect(root / "bot.db") as conn:
        conn.execute(
            """
            INSERT INTO wallet_transactions(
                id,
                customer_discord_id,
                amount,
                balance_before,
                balance_after,
                type,
                order_no,
                created_at
            )
            VALUES(
                3,
                'customer-1',
                50,
                999,
                1049,
                'adjustment',
                'ADJ-1',
                '2026-10-02T01:10:00+08:00'
            )
            """
        )
        conn.execute(
            """
            UPDATE customer_wallets
            SET balance = 1049
            WHERE customer_discord_id = 'customer-1'
            """
        )

    snapshot = build_accounting_reconciliation_snapshot(root)

    assert "wallet_chain_break" in _issue_codes(snapshot)
    assert snapshot["critical_count"] >= 1


def test_completed_topup_amount_mismatch_is_detected(tmp_path):
    root = _healthy_root(tmp_path)

    with sqlite3.connect(root / "bot.db") as conn:
        conn.execute(
            """
            UPDATE topup_orders
            SET credited_amount = 999
            WHERE id = 1
            """
        )

    snapshot = build_accounting_reconciliation_snapshot(root)

    assert "topup_credited_amount_mismatch" in _issue_codes(snapshot)


def test_paid_wallet_tip_without_wallet_transaction_is_detected(tmp_path):
    root = _healthy_root(tmp_path)

    with sqlite3.connect(root / "web_dashboard.db") as conn:
        conn.execute(
            """
            INSERT INTO worker_tips(
                id,
                receipt_id,
                customer_discord_id,
                worker_discord_id,
                amount,
                payment_method,
                payment_status,
                payout_status,
                wallet_transaction_id
            )
            VALUES(
                7,
                'MO20261002001',
                'customer-1',
                'worker-1',
                100,
                '我的錢包',
                'paid',
                'unpaid',
                9999
            )
            """
        )

    snapshot = build_accounting_reconciliation_snapshot(root)

    assert "tip_wallet_tx_missing" in _issue_codes(snapshot)


def test_worker_payout_mismatch_is_detected(tmp_path):
    root = _healthy_root(tmp_path)

    with sqlite3.connect(root / "web_dashboard.db") as conn:
        conn.execute(
            """
            UPDATE worker_payouts
            SET final_payout = 159
            WHERE order_id = 1
            """
        )

    snapshot = build_accounting_reconciliation_snapshot(root)

    assert "worker_payout_amount_mismatch" in _issue_codes(snapshot)

    issue = next(
        item
        for item in snapshot["issues"]
        if item["code"] == "worker_payout_amount_mismatch"
    )
    assert issue["order_id"] == 1
    assert issue["repairable"] is True
    assert issue["repair_action"] == "recalculate_unpaid_payouts"
    assert snapshot["repairable_count"] >= 1


def test_wallet_order_missing_payment_transaction_is_detected(tmp_path):
    root = _healthy_root(tmp_path)

    with sqlite3.connect(root / "bot.db") as conn:
        conn.execute("DELETE FROM wallet_transactions WHERE id = 2")
        conn.execute(
            """
            UPDATE customer_wallets
            SET balance = 1000
            WHERE customer_discord_id = 'customer-1'
            """
        )

    snapshot = build_accounting_reconciliation_snapshot(root)

    assert "wallet_order_tx_missing" in _issue_codes(snapshot)

def test_unpaid_stored_order_does_not_require_payout_rows(tmp_path):
    root = _healthy_root(tmp_path)

    with sqlite3.connect(root / "web_dashboard.db") as conn:
        conn.execute(
            """
            INSERT INTO web_orders(
                id,
                bot_order_no,
                customer_discord_id,
                amount,
                customer_pay_amount,
                payout_base_amount,
                payment_method,
                customer_service_discord_id,
                customer_service_display_name,
                status
            )
            VALUES(
                2,
                'MO20261002002',
                'customer-2',
                300,
                300,
                300,
                '待付款',
                NULL,
                NULL,
                'stored'
            )
            """
        )

    snapshot = build_accounting_reconciliation_snapshot(root)

    stored_order_issues = [
        issue
        for issue in snapshot["issues"]
        if issue["reference"] == "MO20261002002"
    ]

    assert stored_order_issues == []

def test_paid_historical_payout_is_not_repriced_by_current_formula(tmp_path):
    root = _healthy_root(tmp_path)

    with sqlite3.connect(root / "web_dashboard.db") as conn:
        conn.execute(
            """
            UPDATE worker_payouts
            SET final_payout = 159,
                payout_status = 'paid',
                paid_at = '2026-10-02 01:30:00'
            WHERE order_id = 1
            """
        )

    snapshot = build_accounting_reconciliation_snapshot(root)

    codes = _issue_codes(snapshot)

    assert "worker_payout_amount_mismatch" not in codes


def test_cancelled_unpaid_live_payout_is_void_repairable(tmp_path):
    root = _healthy_root(tmp_path)

    with sqlite3.connect(root / "web_dashboard.db") as conn:
        conn.execute(
            """
            UPDATE web_orders
            SET status = 'cancelled'
            WHERE id = 1
            """
        )

    snapshot = build_accounting_reconciliation_snapshot(root)

    issue = next(
        item
        for item in snapshot["issues"]
        if item["code"] == "cancelled_order_has_live_payout"
    )

    assert issue["order_id"] == 1
    assert issue["repairable"] is True
    assert issue["repair_action"] == "void_cancelled_payouts"

def test_unpaid_payout_still_uses_current_formula_reconciliation(tmp_path):
    root = _healthy_root(tmp_path)

    with sqlite3.connect(root / "web_dashboard.db") as conn:
        conn.execute(
            """
            UPDATE worker_payouts
            SET final_payout = 159,
                payout_status = 'unpaid',
                paid_at = NULL
            WHERE order_id = 1
            """
        )

    snapshot = build_accounting_reconciliation_snapshot(root)

    issue = next(
        item
        for item in snapshot["issues"]
        if item["code"] == "worker_payout_amount_mismatch"
    )

    assert issue["repairable"] is True
    assert issue["repair_action"] == "recalculate_unpaid_payouts"


def test_missing_customer_service_payout_remains_visible(tmp_path):
    root = _healthy_root(tmp_path)

    with sqlite3.connect(root / "web_dashboard.db") as conn:
        conn.execute(
            "DELETE FROM customer_service_payouts WHERE order_id = 1"
        )

    snapshot = build_accounting_reconciliation_snapshot(root)

    assert "customer_service_payout_count" in _issue_codes(snapshot)

def test_wallet_order_amount_mismatch_exposes_exact_repair_action(tmp_path):
    root = _healthy_root(tmp_path)

    with sqlite3.connect(root / "web_dashboard.db") as conn:
        conn.execute(
            "ALTER TABLE web_orders ADD COLUMN ticket_channel_id TEXT"
        )
        conn.execute(
            """
            UPDATE web_orders
            SET customer_pay_amount = 250,
                amount = 250,
                ticket_channel_id = 'ticket-1'
            WHERE id = 1
            """
        )

    with sqlite3.connect(root / "bot.db") as conn:
        conn.execute(
            """
            UPDATE wallet_transactions
            SET order_channel_id = 'ticket-1'
            WHERE id = 2
            """
        )

    snapshot = build_accounting_reconciliation_snapshot(root)

    issue = next(
        item
        for item in snapshot["issues"]
        if item["code"] == "wallet_order_amount_mismatch"
    )

    assert issue["order_id"] == 1
    assert issue["repairable"] is True
    assert issue["repair_action"] == "queue_wallet_order_reconciliation"
    assert issue["repair_label"] == "補扣 50T"
    assert issue["expected"] == -250
    assert issue["actual"] == -200


def test_legacy_tip_reference_is_warning_when_financial_linkage_matches(tmp_path):
    root = _healthy_root(tmp_path)

    with sqlite3.connect(root / "bot.db") as conn:
        conn.execute(
            """
            INSERT INTO wallet_transactions(
                id,
                customer_discord_id,
                amount,
                balance_before,
                balance_after,
                type,
                order_no,
                created_at
            )
            VALUES(
                3,
                'customer-1',
                -100,
                800,
                700,
                'tip_payment',
                'MO20260922002',
                '2026-10-02T01:10:00+08:00'
            )
            """
        )
        conn.execute(
            """
            UPDATE customer_wallets
            SET balance = 700
            WHERE customer_discord_id = 'customer-1'
            """
        )

    with sqlite3.connect(root / "web_dashboard.db") as conn:
        conn.execute(
            """
            INSERT INTO worker_tips(
                id,
                receipt_id,
                customer_discord_id,
                worker_discord_id,
                amount,
                payment_method,
                payment_status,
                payout_status,
                wallet_transaction_id
            )
            VALUES(
                1,
                'MO20260922002',
                'customer-1',
                'worker-1',
                100,
                '我的錢包',
                'paid',
                'unpaid',
                3
            )
            """
        )

    snapshot = build_accounting_reconciliation_snapshot(root)

    issue = next(
        item
        for item in snapshot["issues"]
        if item["code"] == "tip_wallet_reference_mismatch"
    )

    assert issue["severity"] == "warning"
    assert "舊格式" in issue["title"]

