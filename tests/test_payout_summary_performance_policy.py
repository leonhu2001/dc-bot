from __future__ import annotations

import sqlite3

from web.app.services.payout_summary_policy import merge_summary_rows
from web.app.services.worker_performance import (
    MONTHLY_PERFORMANCE_TARGET,
    build_worker_performance_map,
    performance_progress,
)


def test_worker_performance_ignores_internal_payroll_transfers(tmp_path):
    db_file = tmp_path / "performance.db"
    conn = sqlite3.connect(db_file)
    try:
        conn.executescript(
            """
            CREATE TABLE web_orders (
                id INTEGER PRIMARY KEY,
                status TEXT,
                closed_at TEXT,
                updated_at TEXT,
                created_at TEXT
            );
            CREATE TABLE worker_payouts (
                id INTEGER PRIMARY KEY,
                order_id INTEGER,
                worker_discord_id TEXT,
                gross_share REAL,
                final_payout REAL
            );
            CREATE TABLE employee_payroll_adjustments (
                id INTEGER PRIMARY KEY,
                employee_discord_id TEXT,
                amount INTEGER,
                effective_at TEXT
            );
            """
        )
        conn.execute(
            "INSERT INTO web_orders VALUES (1, 'closed', '2026-10-05 12:00:00', '', '')"
        )
        conn.execute(
            "INSERT INTO web_orders VALUES (2, 'closed', '2026-10-10 12:00:00', '', '')"
        )
        conn.execute(
            "INSERT INTO worker_payouts VALUES (1, 1, 'staff-1', 3200, 2600)"
        )
        conn.execute(
            "INSERT INTO worker_payouts VALUES (2, 2, 'staff-1', 2800, 2250)"
        )
        # Internal payroll transfers affect settlement only. Performance continues
        # to use the approved final_payout basis from completed companion orders.
        conn.execute(
            "INSERT INTO employee_payroll_adjustments VALUES (1, 'staff-1', -1800, '2026-10-11 12:00:00')"
        )
        conn.commit()
    finally:
        conn.close()

    performance = build_worker_performance_map(
        str(db_file),
        month="2026-10",
        employee_ids={"staff-1"},
    )

    assert performance == {"staff-1": 4850}
    progress = performance_progress(performance["staff-1"])
    assert progress["target"] == MONTHLY_PERFORMANCE_TARGET == 5000
    assert progress["reached"] is False
    assert progress["remaining"] == 150


def test_dual_role_employee_is_one_row_with_one_performance_total():
    unpaid_rows = [
        {
            "discord_id": "123",
            "display_name": "雙身分人員",
            "role": "worker",
            "role_label": "護航 / 陪玩",
            "unpaid_total": 1000,
            "unpaid_count": 2,
            "locked_total": 0,
            "locked_count": 0,
            "paid_total": 0,
            "paid_count": 0,
            "performance_total": 6200,
            "items": [
                {
                    "order_no": "A",
                    "closed_date": "2026-10-10",
                    "role": "護航 / 陪玩",
                }
            ],
        }
    ]
    paid_rows = [
        {
            "discord_id": "123",
            "display_name": "雙身分人員",
            "role": "customer_service",
            "role_label": "客服",
            "unpaid_total": 0,
            "unpaid_count": 0,
            "locked_total": 0,
            "locked_count": 0,
            "paid_total": 300,
            "paid_count": 1,
            "performance_total": 6200,
            "items": [
                {
                    "order_no": "B",
                    "closed_date": "2026-10-09",
                    "role": "客服",
                }
            ],
        }
    ]

    rows = merge_summary_rows(unpaid_rows, paid_rows, [])

    assert len(rows) == 1
    row = rows[0]
    assert row["role"] == "all"
    assert row["role_label"] == "陪玩/客服"
    assert row["unpaid_total"] == 1000
    assert row["paid_total"] == 300
    assert row["total_count"] == 3
    # Same month-wide performance appears in each source status but is not doubled.
    assert row["performance_total"] == 6200
    assert {item["role"] for item in row["items"]} == {"陪玩", "客服"}


def test_paid_chicken_leg_tip_is_salary_but_not_performance(tmp_path):
    db_file = tmp_path / "tips_performance.db"
    conn = sqlite3.connect(db_file)
    try:
        conn.executescript("""
            CREATE TABLE web_orders (
                id INTEGER PRIMARY KEY,
                status TEXT,
                closed_at TEXT,
                updated_at TEXT,
                created_at TEXT
            );
            CREATE TABLE worker_payouts (
                id INTEGER PRIMARY KEY, order_id INTEGER,
                worker_discord_id TEXT, final_payout REAL
            );
            CREATE TABLE worker_tips (
                id INTEGER PRIMARY KEY, order_id INTEGER,
                worker_discord_id TEXT, payment_status TEXT, amount INTEGER
            );
        """)
        conn.execute("INSERT INTO web_orders VALUES (1, 'closed', '2026-11-10', '', '')")
        conn.execute("INSERT INTO worker_payouts VALUES (1,1,'staff-1',4850)")
        conn.execute("INSERT INTO worker_tips VALUES (1,1,'staff-1','paid',500)")
        conn.commit()
        # Employee salary remains 4,850 + 500, and the paid tip is not
        # deleted or changed by the sales-performance function.
        assert conn.execute(
            "SELECT SUM(amount) FROM worker_tips WHERE worker_discord_id='staff-1'"
        ).fetchone()[0] == 500
    finally:
        conn.close()

    performance = build_worker_performance_map(str(db_file), month="2026-11")
    assert performance == {"staff-1": 4850}
    assert not performance_progress(performance["staff-1"])["reached"]

    with sqlite3.connect(db_file) as conn:
        assert conn.execute("SELECT amount FROM worker_tips").fetchone()[0] == 500


def test_previous_month_bonus_basis_excludes_tips_without_querying_tip_table():
    from datetime import datetime, timezone
    from web.app.services.worker_bonus_payout import previous_month_performance

    class WageOnlyDb:
        def __init__(self):
            self.calls = 0

        def scalar(self, stmt):
            self.calls += 1
            return 4850

        def connection(self):
            raise AssertionError("tips must not be fetched for business performance")

    db = WageOnlyDb()
    assert previous_month_performance(
        db, "staff-1", now=datetime(2026, 12, 8, tzinfo=timezone.utc)
    ) == 4850
    assert db.calls == 1
