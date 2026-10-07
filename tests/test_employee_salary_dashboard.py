from __future__ import annotations

import sqlite3

from web.app.routers import payouts


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
                payout_status TEXT
            );

            CREATE TABLE customer_service_payouts (
                id INTEGER PRIMARY KEY,
                order_id INTEGER,
                customer_service_discord_id TEXT,
                customer_service_display_name TEXT,
                payout_amount INTEGER,
                payout_status TEXT
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
        conn.commit()
    finally:
        conn.close()


def test_employee_salary_ledger_includes_tips_and_category_totals(tmp_path, monkeypatch):
    db_file = tmp_path / "salary.db"
    _create_salary_db(db_file)

    monkeypatch.setattr(payouts, "my_payout_db_path", lambda: str(db_file))
    monkeypatch.setattr(payouts, "_taipei_current_month", lambda: "2026-10")

    ledger = payouts.build_employee_salary_ledger("123")

    assert ledger["summary"]["pending"] == 350
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
