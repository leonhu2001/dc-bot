from __future__ import annotations

import sqlite3

from web.app.services.payout_report_gate import payout_financial_state, payout_status_label


def test_order_salary_requires_approved_report_before_becoming_payable():
    assert payout_financial_state(payout_status="unpaid", report_status="missing", report_required=True) == "locked"
    assert payout_status_label(payout_status="unpaid", report_status="missing", report_required=True) == "未填寫報單"
    assert payout_status_label(payout_status="unpaid", report_status="pending", report_required=True) == "報單待審核"
    assert payout_status_label(payout_status="unpaid", report_status="changes_requested", report_required=True) == "報單需修改"
    assert payout_financial_state(payout_status="unpaid", report_status="approved", report_required=True) == "unpaid"
    assert payout_status_label(payout_status="unpaid", report_status="approved", report_required=True) == "待發放"
    assert payout_financial_state(payout_status="paid", report_status="missing", report_required=True) == "paid"


def _make_db(path):
    conn = sqlite3.connect(path)
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
            payout_status TEXT,
            paid_at TEXT
        );
        CREATE TABLE worker_tips (
            id INTEGER PRIMARY KEY,
            order_id INTEGER,
            worker_discord_id TEXT,
            worker_display_name TEXT,
            amount INTEGER,
            payment_status TEXT,
            payout_status TEXT,
            payout_paid_at TEXT,
            updated_at TEXT
        );
        CREATE TABLE customer_service_payouts (
            id INTEGER PRIMARY KEY,
            order_id INTEGER,
            customer_service_discord_id TEXT,
            customer_service_display_name TEXT,
            payout_amount INTEGER,
            payout_status TEXT,
            paid_at TEXT
        );
        CREATE TABLE order_reports (order_id INTEGER PRIMARY KEY, status TEXT);
        CREATE TABLE employee_payroll_adjustments (
            id INTEGER PRIMARY KEY,
            transfer_id INTEGER,
            employee_discord_id TEXT,
            employee_display_name TEXT,
            counterparty_display_name TEXT,
            direction TEXT,
            amount INTEGER,
            reason TEXT,
            payout_status TEXT,
            effective_at TEXT
        );
        CREATE TABLE web_staff_members (
            discord_id TEXT PRIMARY KEY,
            is_customer_service INTEGER,
            is_worker INTEGER,
            is_companion INTEGER
        );
        """
    )
    conn.execute(
        "INSERT INTO web_orders VALUES (1, 'MO-1', 'closed', '三角洲', '技術陪', '老闆', '9', '2026-10-14', '2026-10-14', '2026-10-14')"
    )
    conn.execute(
        "INSERT INTO worker_payouts VALUES (1, 1, '123', '測試陪玩', 500, 'unpaid', NULL)"
    )
    conn.execute("INSERT INTO order_reports VALUES (1, 'missing')")
    conn.commit()
    conn.close()


def test_individual_paid_action_cannot_release_report_locked_salary(tmp_path, monkeypatch):
    from web.app.routers import admin_payout_summary as payout

    db = tmp_path / "payout.db"
    _make_db(db)
    monkeypatch.setattr(payout, "db_path", lambda: str(db))
    monkeypatch.setattr(payout, "summary_db_path", lambda: str(db))
    monkeypatch.setattr(payout, "ensure_worker_tip_table", lambda: None)
    monkeypatch.setattr(payout, "ensure_internal_transfer_tables", lambda *args, **kwargs: None)
    monkeypatch.setattr(payout, "mark_employee_adjustments", lambda **kwargs: None)

    locked_rows, locked_totals = payout.fetch_rows("2026-10", "worker", "", "locked")
    unpaid_rows, unpaid_totals = payout.fetch_rows("2026-10", "worker", "", "unpaid")
    assert locked_totals["locked_count"] == 1
    assert locked_rows[0]["items"][0]["status_label"] == "未填寫報單"
    assert unpaid_totals["unpaid_count"] == 0
    assert unpaid_rows == []

    payout.update_summary_person_payout_status("2026-10", "worker", "123", "paid")
    conn = sqlite3.connect(db)
    assert conn.execute("SELECT payout_status FROM worker_payouts WHERE id=1").fetchone()[0] == "unpaid"
    conn.execute("UPDATE order_reports SET status='approved' WHERE order_id=1")
    conn.commit()
    conn.close()

    unpaid_rows, unpaid_totals = payout.fetch_rows("2026-10", "worker", "", "unpaid")
    assert unpaid_totals["unpaid_count"] == 1
    assert unpaid_rows[0]["items"][0]["status_label"] == "待發放"

    payout.update_summary_person_payout_status("2026-10", "worker", "123", "paid")
    conn = sqlite3.connect(db)
    try:
        assert conn.execute("SELECT payout_status FROM worker_payouts WHERE id=1").fetchone()[0] == "paid"
    finally:
        conn.close()


def test_bulk_paid_action_cannot_release_report_locked_salary(tmp_path, monkeypatch):
    from web.app.routers import admin_payout_summary as payout

    db = tmp_path / "bulk-payout.db"
    _make_db(db)
    monkeypatch.setattr(payout, "db_path", lambda: str(db))
    monkeypatch.setattr(payout, "summary_db_path", lambda: str(db))
    monkeypatch.setattr(payout, "ensure_worker_tip_table", lambda: None)
    monkeypatch.setattr(payout, "ensure_internal_transfer_tables", lambda *args, **kwargs: None)
    monkeypatch.setattr(payout, "mark_bulk_adjustments", lambda **kwargs: None)

    payout.update_summary_payout_status("2026-10", "worker", "paid")
    conn = sqlite3.connect(db)
    try:
        assert conn.execute("SELECT payout_status FROM worker_payouts WHERE id=1").fetchone()[0] == "unpaid"
        conn.execute("UPDATE order_reports SET status='approved' WHERE order_id=1")
        conn.commit()
    finally:
        conn.close()

    payout.update_summary_payout_status("2026-10", "worker", "paid")
    conn = sqlite3.connect(db)
    try:
        assert conn.execute("SELECT payout_status FROM worker_payouts WHERE id=1").fetchone()[0] == "paid"
    finally:
        conn.close()


def test_payout_summary_template_exposes_report_lock_state():
    from pathlib import Path

    source = (Path(__file__).resolve().parents[1] / "web/app/templates/admin_payout_summary.html").read_text(encoding="utf-8")
    assert "報單鎖定" in source
    assert "已發放（鎖定）" in source
    assert "item.status_label" in source
