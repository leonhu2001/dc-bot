from __future__ import annotations

import sqlite3

import pytest

from web.app.routers import payouts
from web.app.services import internal_transfers


def _create_schema(path):
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
                bot_order_no TEXT,
                status TEXT,
                category TEXT,
                item TEXT,
                customer_display_name TEXT,
                customer_discord_id TEXT,
                created_at TEXT,
                updated_at TEXT,
                closed_at TEXT
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
                ticket_channel_id TEXT NOT NULL DEFAULT '',
                worker_discord_id TEXT NOT NULL,
                worker_display_name TEXT,
                amount INTEGER NOT NULL,
                payment_method TEXT NOT NULL DEFAULT 'test',
                payment_status TEXT NOT NULL DEFAULT 'paid',
                payout_status TEXT NOT NULL DEFAULT 'unpaid',
                created_at TEXT NOT NULL DEFAULT '',
                updated_at TEXT NOT NULL DEFAULT ''
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
        conn.commit()
    finally:
        conn.close()


def _seed(path):
    conn = sqlite3.connect(path)
    try:
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
        conn.execute(
            """
            INSERT INTO web_orders (
                id, bot_order_no, status, category, item,
                customer_display_name, customer_discord_id,
                created_at, updated_at, closed_at
            ) VALUES (
                1, 'MW-001', 'closed', '英雄聯盟', '娛樂陪',
                '老闆', 'customer-1',
                '2026-10-11 01:00:00', '2026-10-11 02:00:00', '2026-10-11 02:00:00'
            )
            """
        )
        conn.execute(
            """
            INSERT INTO worker_payouts (
                order_id, worker_discord_id, worker_display_name,
                final_payout, payout_status, created_at, updated_at
            ) VALUES (
                1, 'employee-a', '小玄', 500, 'unpaid',
                '2026-10-11 02:00:00', '2026-10-11 02:00:00'
            )
            """
        )
        conn.commit()
    finally:
        conn.close()


@pytest.fixture
def transfer_db(tmp_path, monkeypatch):
    path = tmp_path / "internal_transfers.db"
    _create_schema(path)
    _seed(path)
    monkeypatch.setattr(internal_transfers, "db_path", lambda: str(path))
    monkeypatch.setattr(payouts, "my_payout_db_path", lambda: str(path))
    internal_transfers.ensure_internal_transfer_tables()
    return path


def test_employee_request_waits_for_customer_service_and_reserves_balance(transfer_db):
    result = internal_transfers.create_internal_transfer(
        actor_discord_id="employee-a",
        actor_display_name="小玄",
        from_employee_discord_id="employee-a",
        to_employee_discord_id="employee-b",
        amount=200,
        reason="實際陪玩時數不同",
    )

    assert result["status"] == "pending"
    assert result["auto_approved"] is False

    balance = internal_transfers.get_available_unpaid_balance("employee-a")
    assert balance["base_unpaid"] == 500
    assert balance["reserved_amount"] == 200
    assert balance["available_amount"] == 300

    conn = sqlite3.connect(transfer_db)
    try:
        count = conn.execute("SELECT COUNT(*) FROM employee_payroll_adjustments").fetchone()[0]
        assert count == 0
    finally:
        conn.close()


def test_customer_service_approval_creates_zero_sum_payroll_adjustments(transfer_db):
    result = internal_transfers.create_internal_transfer(
        actor_discord_id="employee-a",
        actor_display_name="小玄",
        from_employee_discord_id="employee-a",
        to_employee_discord_id="employee-b",
        amount=200,
        reason="補分時數",
    )

    approved = internal_transfers.review_internal_transfer(
        transfer_id=result["id"],
        reviewer_discord_id="cs-1",
        reviewer_display_name="客服一號",
        approve=True,
        reviewer_is_customer_service=True,
    )
    assert approved["status"] == "approved"

    conn = sqlite3.connect(transfer_db)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            """
            SELECT employee_discord_id, direction, amount, payout_status
            FROM employee_payroll_adjustments
            ORDER BY direction
            """
        ).fetchall()
        assert len(rows) == 2
        amounts = {row["employee_discord_id"]: row["amount"] for row in rows}
        assert amounts == {"employee-a": -200, "employee-b": 200}
        assert sum(amounts.values()) == 0
        assert {row["payout_status"] for row in rows} == {"unpaid"}
    finally:
        conn.close()

    assert internal_transfers.get_available_unpaid_balance("employee-a")["available_amount"] == 300
    assert internal_transfers.get_available_unpaid_balance("employee-b")["available_amount"] == 200


def test_customer_service_created_transfer_is_immediately_approved(transfer_db):
    result = internal_transfers.create_internal_transfer(
        actor_discord_id="cs-1",
        actor_display_name="客服一號",
        from_employee_discord_id="employee-a",
        to_employee_discord_id="employee-b",
        amount=125,
        reason="客服依雙方回報調整",
        actor_is_customer_service=True,
    )

    assert result["status"] == "approved"
    assert result["auto_approved"] is True

    conn = sqlite3.connect(transfer_db)
    try:
        transfer_status = conn.execute(
            "SELECT status FROM employee_internal_transfers WHERE id = ?",
            (result["id"],),
        ).fetchone()[0]
        count = conn.execute(
            "SELECT COUNT(*) FROM employee_payroll_adjustments WHERE transfer_id = ?",
            (result["id"],),
        ).fetchone()[0]
        assert transfer_status == "approved"
        assert count == 2
    finally:
        conn.close()


def test_recipient_does_not_need_same_order_or_any_order(transfer_db):
    result = internal_transfers.create_internal_transfer(
        actor_discord_id="cs-1",
        actor_display_name="客服一號",
        from_employee_discord_id="employee-a",
        to_employee_discord_id="employee-b",
        amount=80,
        reason="跨單內部分配",
        actor_is_customer_service=True,
    )
    assert result["status"] == "approved"
    assert internal_transfers.get_available_unpaid_balance("employee-b")["available_amount"] == 80


def test_employee_cannot_transfer_from_someone_else(transfer_db):
    with pytest.raises(ValueError, match="只能從自己的待發放薪資"):
        internal_transfers.create_internal_transfer(
            actor_discord_id="employee-b",
            actor_display_name="麻糬",
            from_employee_discord_id="employee-a",
            to_employee_discord_id="employee-b",
            amount=50,
            reason="不允許代扣別人",
        )


def test_only_customer_service_or_manager_can_review(transfer_db):
    result = internal_transfers.create_internal_transfer(
        actor_discord_id="employee-a",
        actor_display_name="小玄",
        from_employee_discord_id="employee-a",
        to_employee_discord_id="employee-b",
        amount=100,
        reason="等待客服",
    )

    with pytest.raises(ValueError, match="只有客服或總管"):
        internal_transfers.review_internal_transfer(
            transfer_id=result["id"],
            reviewer_discord_id="employee-b",
            reviewer_display_name="麻糬",
            approve=True,
        )


def test_pending_reservation_prevents_overcommit(transfer_db):
    internal_transfers.create_internal_transfer(
        actor_discord_id="employee-a",
        actor_display_name="小玄",
        from_employee_discord_id="employee-a",
        to_employee_discord_id="employee-b",
        amount=400,
        reason="第一筆",
    )

    with pytest.raises(ValueError, match="只有 100T"):
        internal_transfers.create_internal_transfer(
            actor_discord_id="employee-a",
            actor_display_name="小玄",
            from_employee_discord_id="employee-a",
            to_employee_discord_id="employee-b",
            amount=101,
            reason="第二筆超額",
        )


def test_employee_salary_ledger_includes_signed_internal_transfer(transfer_db):
    result = internal_transfers.create_internal_transfer(
        actor_discord_id="cs-1",
        actor_display_name="客服一號",
        from_employee_discord_id="employee-a",
        to_employee_discord_id="employee-b",
        amount=200,
        reason="補分",
        actor_is_customer_service=True,
    )
    assert result["status"] == "approved"

    _, _, source_totals = payouts.build_my_payout_rows("employee-a", status="unpaid")
    _, _, recipient_totals = payouts.build_my_payout_rows("employee-b", status="unpaid")
    assert source_totals["unpaid_total"] == 300
    assert recipient_totals["unpaid_total"] == 200

    recipient_ledger = payouts.build_employee_salary_ledger("employee-b")
    transfer_items = [
        item for item in recipient_ledger["items"]
        if item["category_key"] == "internal_transfer"
    ]
    assert len(transfer_items) == 1
    assert transfer_items[0]["amount"] == 200
    assert "來自 小玄" in transfer_items[0]["service_label"]


def test_adjustment_payout_status_can_be_settled_independently(transfer_db):
    result = internal_transfers.create_internal_transfer(
        actor_discord_id="cs-1",
        actor_display_name="客服一號",
        from_employee_discord_id="employee-a",
        to_employee_discord_id="employee-b",
        amount=75,
        reason="調整",
        actor_is_customer_service=True,
    )
    assert result["status"] == "approved"

    conn = sqlite3.connect(transfer_db)
    try:
        effective_month = conn.execute(
            """
            SELECT substr(effective_at, 1, 7)
            FROM employee_payroll_adjustments
            WHERE transfer_id = ? AND direction = 'incoming'
            """,
            (result["id"],),
        ).fetchone()[0]
    finally:
        conn.close()

    internal_transfers.mark_employee_adjustments(
        employee_discord_id="employee-b",
        target_status="paid",
        month=effective_month,
    )

    conn = sqlite3.connect(transfer_db)
    try:
        source_status = conn.execute(
            """
            SELECT payout_status FROM employee_payroll_adjustments
            WHERE transfer_id = ? AND direction = 'outgoing'
            """,
            (result["id"],),
        ).fetchone()[0]
        recipient_status = conn.execute(
            """
            SELECT payout_status FROM employee_payroll_adjustments
            WHERE transfer_id = ? AND direction = 'incoming'
            """,
            (result["id"],),
        ).fetchone()[0]
        assert source_status == "unpaid"
        assert recipient_status == "paid"
    finally:
        conn.close()
