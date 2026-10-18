from __future__ import annotations

import sqlite3

import pytest

from services.wallet_service import get_wallet_balance, get_wallet_transactions
from web.app.services import internal_transfers
from web.app.services import internal_wallet_transfers


def _create_web_schema(path):
    conn = sqlite3.connect(path)
    try:
        conn.executescript(
            """
            CREATE TABLE web_staff_members (
                discord_id TEXT PRIMARY KEY,
                username TEXT,
                display_name TEXT,
                global_name TEXT,
                is_customer_service INTEGER NOT NULL DEFAULT 0,
                is_worker INTEGER NOT NULL DEFAULT 0,
                is_companion INTEGER NOT NULL DEFAULT 0,
                is_active INTEGER NOT NULL DEFAULT 1
            );

            CREATE TABLE web_orders (
                id INTEGER PRIMARY KEY,
                status TEXT
            );

            CREATE TABLE worker_payouts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                order_id INTEGER NOT NULL,
                worker_discord_id TEXT NOT NULL,
                worker_display_name TEXT,
                final_payout INTEGER NOT NULL DEFAULT 0,
                payout_status TEXT NOT NULL DEFAULT 'unpaid',
                paid_at TEXT,
                created_at TEXT,
                updated_at TEXT
            );

            CREATE TABLE worker_tips (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                order_id INTEGER,
                worker_discord_id TEXT NOT NULL,
                amount INTEGER NOT NULL,
                payment_status TEXT NOT NULL DEFAULT 'paid',
                payout_status TEXT NOT NULL DEFAULT 'unpaid'
            );

            CREATE TABLE customer_service_payouts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                order_id INTEGER NOT NULL,
                customer_service_discord_id TEXT NOT NULL,
                customer_service_display_name TEXT,
                payout_amount INTEGER NOT NULL DEFAULT 0,
                payout_status TEXT NOT NULL DEFAULT 'unpaid',
                paid_at TEXT,
                created_at TEXT,
                updated_at TEXT
            );
            """
        )
        conn.executemany(
            """
            INSERT INTO web_staff_members (
                discord_id, username, display_name,
                is_customer_service, is_worker, is_companion, is_active
            ) VALUES (?, ?, ?, ?, ?, ?, 1)
            """,
            [
                ("employee-a", "a", "小玄", 0, 1, 1),
                ("employee-b", "b", "麻糬", 0, 1, 1),
                ("cs-1", "cs", "客服一號", 1, 0, 0),
            ],
        )
        conn.execute("INSERT INTO web_orders(id, status) VALUES (1, 'closed')")
        conn.execute(
            """
            INSERT INTO worker_payouts (
                order_id, worker_discord_id, worker_display_name,
                final_payout, payout_status
            ) VALUES (1, 'employee-a', '小玄', 500, 'unpaid')
            """
        )
        conn.commit()
    finally:
        conn.close()


@pytest.fixture
def wallet_transfer_dbs(tmp_path, monkeypatch):
    web_path = tmp_path / "web_dashboard.db"
    wallet_path = tmp_path / "bot.db"
    _create_web_schema(web_path)
    monkeypatch.setattr(internal_transfers, "db_path", lambda: str(web_path))
    monkeypatch.setattr(internal_wallet_transfers, "wallet_db_path", lambda: str(wallet_path))
    internal_transfers.ensure_internal_transfer_tables()
    internal_wallet_transfers.ensure_internal_wallet_transfer_tables()
    return web_path, wallet_path


def test_employee_wallet_request_reserves_salary_until_review(wallet_transfer_dbs):
    _, wallet_path = wallet_transfer_dbs
    result = internal_wallet_transfers.create_internal_wallet_transfer(
        actor_discord_id="employee-a",
        actor_display_name="小玄",
        from_employee_discord_id="employee-a",
        amount=200,
        reason="轉入錢包點單",
    )

    assert result["status"] == "pending"
    assert result["auto_approved"] is False
    assert get_wallet_balance("employee-a", wallet_path) == 0
    assert internal_transfers.get_available_unpaid_balance("employee-a")["available_amount"] == 300


def test_customer_service_approval_moves_salary_to_source_own_wallet(wallet_transfer_dbs):
    web_path, wallet_path = wallet_transfer_dbs
    result = internal_wallet_transfers.create_internal_wallet_transfer(
        actor_discord_id="employee-a",
        actor_display_name="小玄",
        from_employee_discord_id="employee-a",
        amount=200,
        reason="轉入錢包點單",
    )

    approved = internal_wallet_transfers.review_internal_wallet_transfer(
        transfer_id=result["id"],
        reviewer_discord_id="cs-1",
        reviewer_display_name="客服一號",
        approve=True,
        reviewer_is_customer_service=True,
    )
    assert approved["status"] == "approved"
    assert get_wallet_balance("employee-a", wallet_path) == 200
    assert get_wallet_balance("cs-1", wallet_path) == 0
    assert internal_transfers.get_available_unpaid_balance("employee-a")["available_amount"] == 300

    txs = get_wallet_transactions("employee-a", db_file=wallet_path)
    assert len(txs) == 1
    assert txs[0]["type"] == internal_wallet_transfers.WALLET_TRANSACTION_TYPE
    assert txs[0]["amount"] == 200
    assert txs[0]["operator_discord_id"] == "cs-1"

    conn = sqlite3.connect(web_path)
    try:
        rows = conn.execute(
            """
            SELECT direction, amount
            FROM employee_payroll_adjustments
            WHERE transfer_id = ?
            """,
            (result["id"],),
        ).fetchall()
        assert rows == [("outgoing", -200)]
    finally:
        conn.close()


def test_customer_service_direct_wallet_transfer_uses_selected_source_not_actor(wallet_transfer_dbs):
    _, wallet_path = wallet_transfer_dbs
    result = internal_wallet_transfers.create_internal_wallet_transfer(
        actor_discord_id="cs-1",
        actor_display_name="客服一號",
        from_employee_discord_id="employee-a",
        amount=125,
        reason="客服代轉本人錢包",
        actor_is_customer_service=True,
    )

    assert result["status"] == "approved"
    assert result["auto_approved"] is True
    assert result["to_name"] == "我的錢包"
    assert get_wallet_balance("employee-a", wallet_path) == 125
    assert get_wallet_balance("cs-1", wallet_path) == 0


def test_rejected_wallet_request_never_credits_wallet(wallet_transfer_dbs):
    _, wallet_path = wallet_transfer_dbs
    result = internal_wallet_transfers.create_internal_wallet_transfer(
        actor_discord_id="employee-a",
        actor_display_name="小玄",
        from_employee_discord_id="employee-a",
        amount=150,
        reason="測試拒絕",
    )

    rejected = internal_wallet_transfers.review_internal_wallet_transfer(
        transfer_id=result["id"],
        reviewer_discord_id="cs-1",
        reviewer_display_name="客服一號",
        approve=False,
        reviewer_is_customer_service=True,
    )
    assert rejected["status"] == "rejected"
    assert get_wallet_balance("employee-a", wallet_path) == 0
    assert internal_transfers.get_available_unpaid_balance("employee-a")["available_amount"] == 500


def test_wallet_credit_failure_rolls_back_salary_adjustment(wallet_transfer_dbs, monkeypatch):
    web_path, wallet_path = wallet_transfer_dbs

    def fail_credit(*args, **kwargs):
        raise RuntimeError("simulated wallet failure")

    monkeypatch.setattr(internal_wallet_transfers, "_credit_wallet", fail_credit)

    with pytest.raises(RuntimeError, match="simulated wallet failure"):
        internal_wallet_transfers.create_internal_wallet_transfer(
            actor_discord_id="cs-1",
            actor_display_name="客服一號",
            from_employee_discord_id="employee-a",
            amount=100,
            reason="原子性測試",
            actor_is_customer_service=True,
        )

    assert get_wallet_balance("employee-a", wallet_path) == 0
    assert internal_transfers.get_available_unpaid_balance("employee-a")["available_amount"] == 500

    conn = sqlite3.connect(web_path)
    try:
        assert conn.execute("SELECT COUNT(*) FROM employee_internal_transfers").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM employee_payroll_adjustments").fetchone()[0] == 0
    finally:
        conn.close()
