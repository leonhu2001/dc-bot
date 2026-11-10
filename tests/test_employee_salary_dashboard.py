from __future__ import annotations

import sqlite3

from web.app.routers import payouts
from web.app.services.worker_performance import build_worker_performance_map


def _create_salary_db(path):
    conn = sqlite3.connect(path)
    try:
        conn.executescript(
            """
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
                id INTEGER PRIMARY KEY,
                order_id INTEGER,
                worker_discord_id TEXT,
                worker_display_name TEXT,
                final_payout INTEGER,
                payout_status TEXT
            );

            CREATE TABLE worker_tips (
                id INTEGER PRIMARY KEY,
                order_id INTEGER,
                worker_discord_id TEXT,
                worker_display_name TEXT,
                amount INTEGER,
                payment_status TEXT,
                payout_status TEXT,
                customer_discord_id TEXT,
                customer_display_name TEXT,
                created_at TEXT,
                paid_at TEXT
            );

            CREATE TABLE customer_service_payouts (
                id INTEGER PRIMARY KEY,
                order_id INTEGER,
                customer_service_discord_id TEXT,
                customer_service_display_name TEXT,
                payout_amount INTEGER,
                payout_status TEXT
            );

            CREATE TABLE order_reports (
                id INTEGER PRIMARY KEY,
                order_id INTEGER,
                status TEXT
            );
            """
        )

        conn.executemany(
            """
            INSERT INTO web_orders (
                id, bot_order_no, status, category, item,
                customer_display_name, customer_discord_id,
                created_at, updated_at, closed_at
            ) VALUES (?, ?, 'closed', ?, ?, '老闆', '999', ?, ?, ?)
            """,
            [
                (
                    1,
                    "MW-1001",
                    "delta",
                    "技術陪",
                    "2026-10-03 10:00:00",
                    "2026-10-03 11:00:00",
                    "2026-10-03 11:00:00",
                ),
                (
                    2,
                    "MW-0990",
                    "delta",
                    "娛樂陪",
                    "2026-09-18 10:00:00",
                    "2026-09-18 11:00:00",
                    "2026-09-18 11:00:00",
                ),
            ],
        )

        conn.executemany(
            """
            INSERT INTO worker_payouts (
                id, order_id, worker_discord_id, worker_display_name,
                final_payout, payout_status
            ) VALUES (?, ?, '123', '測試陪玩', ?, ?)
            """,
            [
                (1, 1, 500, "paid"),
                (2, 2, 300, "unpaid"),
            ],
        )

        conn.executemany(
            """
            INSERT INTO worker_tips (
                id, order_id, worker_discord_id, worker_display_name,
                amount, payment_status, payout_status
            ) VALUES (?, ?, '123', '測試陪玩', ?, 'paid', ?)
            """,
            [
                (1, 1, 100, "paid"),
                (2, 2, 50, "unpaid"),
            ],
        )

        conn.execute(
            """
            INSERT INTO customer_service_payouts (
                id, order_id, customer_service_discord_id,
                customer_service_display_name, payout_amount, payout_status
            ) VALUES (1, 1, '123', '測試陪玩', 80, 'paid')
            """
        )
        conn.execute(
            """
            INSERT INTO order_reports(id, order_id, status)
            VALUES (1, 1, 'approved')
            """
        )
        conn.commit()
    finally:
        conn.close()


def test_employee_salary_ledger_includes_tips_and_report_gate(tmp_path, monkeypatch):
    db_file = tmp_path / "salary.db"
    _create_salary_db(db_file)

    monkeypatch.setattr(payouts, "my_payout_db_path", lambda: str(db_file))
    monkeypatch.setattr(payouts, "_taipei_current_month", lambda: "2026-10")

    ledger = payouts.build_employee_salary_ledger("123")

    assert ledger["summary"]["pending"] == 50
    assert ledger["summary"]["pending_count"] == 1
    assert ledger["summary"]["locked"] == 300
    assert ledger["summary"]["locked_count"] == 1
    assert ledger["summary"]["current_month_paid"] == 680
    assert ledger["summary"]["lifetime"] == 1030
    assert ledger["summary"]["paid_total"] == 680
    assert ledger["summary"]["all_count"] == 5

    assert ledger["categories"]["service"] == {"count": 2, "total": 800}
    assert ledger["categories"]["tip"] == {"count": 2, "total": 150}
    assert ledger["categories"]["customer_service"] == {"count": 1, "total": 80}

    tip_items = [item for item in ledger["items"] if item["category_key"] == "tip"]
    assert len(tip_items) == 2
    assert {item["status_label"] for item in tip_items} == {"已發放", "待發放"}
    assert all(item["category_label"] == "🍗 雞腿" for item in tip_items)

    locked_service = next(
        item
        for item in ledger["items"]
        if item["order_no"] == "MW-0990" and item["category_key"] == "service"
    )
    assert locked_service["financial_state"] == "locked"
    assert locked_service["report_status"] == "missing"
    assert locked_service["status_label"] == "未填寫報單"


def test_employee_salary_ledger_is_scoped_to_requested_discord_user(tmp_path, monkeypatch):
    db_file = tmp_path / "salary.db"
    _create_salary_db(db_file)

    conn = sqlite3.connect(db_file)
    try:
        conn.execute(
            """
            INSERT INTO worker_payouts (
                id, order_id, worker_discord_id, worker_display_name,
                final_payout, payout_status
            ) VALUES (3, 1, '456', '別人', 9999, 'paid')
            """
        )
        conn.commit()
    finally:
        conn.close()

    monkeypatch.setattr(payouts, "my_payout_db_path", lambda: str(db_file))
    monkeypatch.setattr(payouts, "_taipei_current_month", lambda: "2026-10")

    ledger = payouts.build_employee_salary_ledger("123")

    assert ledger["summary"]["lifetime"] == 1030
    assert all(item["amount"] != 9999 for item in ledger["items"])


def test_employee_salary_pending_report_is_locked(tmp_path, monkeypatch):
    db_file = tmp_path / "salary.db"
    _create_salary_db(db_file)

    conn = sqlite3.connect(db_file)
    try:
        conn.execute(
            """
            INSERT INTO order_reports(id, order_id, status)
            VALUES (2, 2, 'pending')
            """
        )
        conn.commit()
    finally:
        conn.close()

    monkeypatch.setattr(payouts, "my_payout_db_path", lambda: str(db_file))
    monkeypatch.setattr(payouts, "_taipei_current_month", lambda: "2026-10")

    ledger = payouts.build_employee_salary_ledger("123")
    service_item = next(
        item
        for item in ledger["items"]
        if item["order_no"] == "MW-0990" and item["category_key"] == "service"
    )

    assert service_item["financial_state"] == "locked"
    assert service_item["status_label"] == "報單待審核"
    assert ledger["summary"]["pending"] == 50
    assert ledger["summary"]["locked"] == 300

def test_profile_tip_without_web_order_is_in_employee_salary_month_and_totals(
    tmp_path, monkeypatch,
):
    db_file = tmp_path / "salary.db"
    _create_salary_db(db_file)
    with sqlite3.connect(db_file) as conn:
        conn.execute(
            """
            INSERT INTO worker_tips
                (id, order_id, worker_discord_id, worker_display_name, amount,
                 payment_status, payout_status, customer_discord_id,
                 customer_display_name, created_at, paid_at)
            VALUES
                (23,NULL,'123','測試陪玩',135,'paid','unpaid','999',
                 '送雞腿老闆','2026-11-09T01:02:03','2026-11-09T01:03:00')
            """
        )
        conn.execute(
            """
            INSERT INTO worker_tips
                (id, order_id, worker_discord_id, worker_display_name, amount,
                 payment_status, payout_status, customer_discord_id,
                 customer_display_name, created_at, paid_at)
            VALUES
                (24,NULL,'123','測試陪玩',700,'pending_review','unpaid','999',
                 '尚未審核','2026-11-09T01:04:00',NULL)
            """
        )
    monkeypatch.setattr(payouts, "my_payout_db_path", lambda: str(db_file))
    monkeypatch.setattr(payouts, "_taipei_current_month", lambda: "2026-11")

    unpaid, paid, totals = payouts.build_my_payout_rows("123", month="2026-11")
    assert totals["unpaid_total"] == 135
    assert totals["unpaid_count"] == 1
    assert totals["paid_total"] == 0
    assert [item["order_no"] for item in unpaid[0]["items"]] == ["TIP-23"]
    assert unpaid[0]["items"][0]["customer_name"] == "送雞腿老闆"

    months = {item["value"] for item in payouts.get_my_payout_month_options()}
    assert "2026-11" in months
    ledger = payouts.build_employee_salary_ledger("123")
    tip = next(item for item in ledger["items"] if item["order_no"] == "TIP-23")
    assert tip["service_label"] == "老闆加雞腿"
    assert tip["amount"] == 135
    assert tip["financial_state"] == "unpaid"
    assert tip["status_label"] == "待發放"
    assert ledger["categories"]["tip"]["total"] == 285

    # Tips stay payable even though none (order-attached or independent) count
    # toward employee service performance for the 5,000T monthly target.
    october_performance = build_worker_performance_map(
        str(db_file), month="2026-10", employee_ids={"123"}
    )
    assert october_performance == {"123": 500}
    november_performance = build_worker_performance_map(
        str(db_file), month="2026-11", employee_ids={"123"}
    )
    assert november_performance == {}
