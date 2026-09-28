import sqlite3

from web.app.routers import admin_payout_summary as report_module


def _create_report_db(path):
    conn = sqlite3.connect(path)
    try:
        conn.executescript(
            """
            CREATE TABLE web_orders (
                id INTEGER PRIMARY KEY,
                bot_order_no TEXT,
                category TEXT,
                item TEXT,
                customer_discord_id TEXT,
                customer_display_name TEXT,
                amount INTEGER,
                customer_pay_amount INTEGER,
                manual_discount_amount INTEGER,
                cash_coupon_amount INTEGER,
                store_absorbed_amount INTEGER,
                status TEXT,
                closed_at TEXT,
                updated_at TEXT,
                created_at TEXT
            );

            CREATE TABLE worker_payouts (
                order_id INTEGER,
                worker_discord_id TEXT,
                worker_display_name TEXT,
                final_payout INTEGER
            );

            CREATE TABLE customer_service_payouts (
                order_id INTEGER,
                payout_amount INTEGER
            );
            """
        )

        conn.executemany(
            """
            INSERT INTO web_orders (
                id,
                bot_order_no,
                category,
                item,
                customer_discord_id,
                customer_display_name,
                amount,
                customer_pay_amount,
                manual_discount_amount,
                cash_coupon_amount,
                store_absorbed_amount,
                status,
                closed_at,
                updated_at,
                created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    1,
                    "ORD-1",
                    "basic",
                    "Service A",
                    "customer-1",
                    "Customer",
                    1000,
                    1000,
                    100,
                    50,
                    25,
                    "closed",
                    "2026-09-10 12:00:00",
                    "2026-09-10 12:00:00",
                    "2026-09-10 12:00:00",
                ),
                (
                    2,
                    "ORD-2",
                    "basic",
                    "Service A",
                    "customer-1",
                    "Customer",
                    500,
                    500,
                    0,
                    0,
                    0,
                    "closed",
                    "2026-09-11 12:00:00",
                    "2026-09-11 12:00:00",
                    "2026-09-11 12:00:00",
                ),
                (
                    3,
                    "ORD-PREV",
                    "basic",
                    "Service A",
                    "customer-2",
                    "Previous Customer",
                    1000,
                    1000,
                    0,
                    0,
                    0,
                    "closed",
                    "2026-08-10 12:00:00",
                    "2026-08-10 12:00:00",
                    "2026-08-10 12:00:00",
                ),
            ],
        )

        conn.executemany(
            """
            INSERT INTO worker_payouts (
                order_id,
                worker_discord_id,
                worker_display_name,
                final_payout
            )
            VALUES (?, ?, ?, ?)
            """,
            [
                (1, "worker-1", "Worker", 700),
                (2, "worker-1", "Worker", 300),
                (3, "worker-2", "Previous Worker", 600),
            ],
        )

        conn.executemany(
            """
            INSERT INTO customer_service_payouts (
                order_id,
                payout_amount
            )
            VALUES (?, ?)
            """,
            [
                (1, 50),
                (2, 50),
                (3, 50),
            ],
        )
        conn.commit()
    finally:
        conn.close()


def test_operations_report_profitability_and_period_comparison(tmp_path, monkeypatch):
    db_file = tmp_path / "report.db"
    _create_report_db(db_file)

    monkeypatch.setattr(
        report_module,
        "db_path",
        lambda: str(db_file),
    )
    monkeypatch.setattr(
        report_module,
        "_report_period",
        lambda period: (
            "month",
            "2026-09-01 00:00:00",
            "本月",
            "2026-08-01 00:00:00",
            "2026-08-28 00:00:00",
            "上月同期",
        ),
    )

    report = report_module.build_operations_report("month")

    assert report["revenue"] == 1500
    assert report["worker_cost"] == 1000
    assert report["service_cost"] == 100
    assert report["payroll"] == 1100
    assert report["retained"] == 400
    assert report["retained_rate"] == 26.7
    assert report["payroll_rate"] == 73.3
    assert report["avg_order"] == 750

    assert report["percent_discount"] == 100
    assert report["fixed_discount"] == 50
    assert report["point_discount"] == 25
    assert report["discount_total"] == 175

    assert report["customer_count"] == 1
    assert report["repeat_customers"] == 1
    assert report["repeat_rate"] == 100.0

    service = report["service_rows"][0]
    assert service["label"] == "Service A"
    assert service["orders"] == 2
    assert service["revenue"] == 1500
    assert service["payroll"] == 1100
    assert service["retained"] == 400
    assert service["retained_rate"] == 26.7

    assert report["previous_label"] == "上月同期"
    assert report["comparison"]["revenue"]["rate"] == 50.0
    assert report["comparison"]["payroll"]["rate"] == 69.2
    assert report["comparison"]["retained"]["rate"] == 14.3
    assert report["comparison"]["avg_order"]["rate"] == -25.0
    assert report["comparison"]["order_count"]["rate"] == 100.0
    assert report["comparison"]["customer_count"]["rate"] == 0.0
