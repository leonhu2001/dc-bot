import sqlite3

from web.app.services import customer_portal


def _setup_db(path):
    with sqlite3.connect(path) as conn:
        conn.executescript(
            """
            CREATE TABLE web_orders (
                id INTEGER PRIMARY KEY,
                bot_order_no TEXT,
                ticket_channel_id TEXT,
                customer_discord_id TEXT,
                customer_display_name TEXT,
                category TEXT,
                item TEXT,
                quantity INTEGER,
                amount INTEGER,
                customer_pay_amount INTEGER,
                payment_method TEXT,
                status TEXT,
                created_at TEXT,
                updated_at TEXT
            );

            CREATE TABLE order_assignments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                order_id INTEGER,
                worker_discord_id TEXT,
                worker_display_name TEXT,
                role_type TEXT,
                is_active INTEGER,
                assigned_at TEXT
            );

            CREATE TABLE payment_reviews (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                review_no TEXT,
                source_type TEXT,
                source_id TEXT,
                customer_discord_id TEXT,
                amount INTEGER,
                payment_method TEXT,
                status TEXT,
                rejected_reason TEXT,
                created_at TEXT,
                updated_at TEXT
            );

            CREATE TABLE support_calls (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ticket_channel_id TEXT,
                status TEXT,
                called_at TEXT,
                claimed_at TEXT,
                claimed_by_discord_id TEXT,
                claimed_by_display_name TEXT,
                resolved_at TEXT
            );
            """
        )
        conn.commit()


def test_customer_orders_are_scoped_to_logged_in_customer(tmp_path):
    db_path = tmp_path / "web_dashboard.db"
    _setup_db(db_path)

    with sqlite3.connect(db_path) as conn:
        conn.executescript(
            """
            INSERT INTO web_orders (
                id, bot_order_no, ticket_channel_id, customer_discord_id,
                category, item, quantity, amount, customer_pay_amount,
                payment_method, status, created_at, updated_at
            )
            VALUES
                (1, 'MO-1', '1001', 'A', '三角洲', '娛樂陪', 1, 500, 450, '轉帳', 'active', '2026-10-02 01:00:00', '2026-10-02 02:00:00'),
                (2, 'MO-2', '1002', 'B', '三角洲', '頂護', 1, 600, 600, '錢包', 'closed', '2026-10-01 01:00:00', '2026-10-01 02:00:00');
            """
        )
        conn.commit()

    orders = customer_portal.list_customer_orders(
        "A",
        guild_id="999",
        db_file=db_path,
    )

    assert len(orders) == 1
    assert orders[0]["id"] == 1
    assert orders[0]["amount_text"] == "450T"
    assert orders[0]["ticket_url"] == "https://discord.com/channels/999/1001"

    assert customer_portal.get_customer_order(
        "A",
        2,
        guild_id="999",
        db_file=db_path,
    ) is None


def test_customer_order_aggregates_payment_support_and_staff(tmp_path):
    db_path = tmp_path / "web_dashboard.db"
    _setup_db(db_path)

    with sqlite3.connect(db_path) as conn:
        conn.executescript(
            """
            INSERT INTO web_orders (
                id, bot_order_no, ticket_channel_id, customer_discord_id,
                category, item, quantity, amount, payment_method, status,
                created_at, updated_at
            )
            VALUES
                (10, 'MO-10', '1010', 'A', '三角洲', '護航', 2, 1000, '轉帳', 'accepted_pending_pay', '2026-10-02 01:00:00', '2026-10-02 02:00:00');

            INSERT INTO order_assignments (
                order_id, worker_discord_id, worker_display_name,
                role_type, is_active, assigned_at
            )
            VALUES
                (10, 'W1', '阿甲', 'worker', 1, '2026-10-02 01:20:00'),
                (10, 'W2', '阿乙', 'worker', 1, '2026-10-02 01:25:00');

            INSERT INTO payment_reviews (
                review_no, source_type, source_id, customer_discord_id,
                amount, payment_method, status, created_at, updated_at
            )
            VALUES
                ('PAY-10', 'order', '10', 'A', 1000, '轉帳', 'pending_review', '2026-10-02T01:30:00+08:00', '2026-10-02T01:30:00+08:00');

            INSERT INTO support_calls (
                ticket_channel_id, status, called_at, claimed_at,
                claimed_by_display_name
            )
            VALUES
                ('1010', 'claimed', '2026-10-02T01:35:00+08:00', '2026-10-02T01:36:00+08:00', '客服小丸');
            """
        )
        conn.commit()

    order = customer_portal.get_customer_order(
        "A",
        10,
        guild_id="999",
        db_file=db_path,
    )

    assert order is not None
    assert order["status_label"] == "等待付款"
    assert order["payment"]["status_label"] == "付款審核中"
    assert order["support"]["status_label"] == "客服處理中"
    assert [item["worker_display_name"] for item in order["active_assignments"]] == ["阿甲", "阿乙"]


def test_customer_portal_snapshot_counts_actionable_states(tmp_path):
    db_path = tmp_path / "web_dashboard.db"
    _setup_db(db_path)

    with sqlite3.connect(db_path) as conn:
        conn.executescript(
            """
            INSERT INTO web_orders (
                id, ticket_channel_id, customer_discord_id,
                category, item, quantity, amount, payment_method, status,
                created_at, updated_at
            )
            VALUES
                (1, '2001', 'A', '三角洲', 'A', 1, 100, '待付款', 'waiting_acceptance', '2026-10-02 01:00:00', '2026-10-02 01:00:00'),
                (2, '2002', 'A', '三角洲', 'B', 1, 200, '轉帳', 'accepted_pending_pay', '2026-10-02 01:00:00', '2026-10-02 01:00:00'),
                (3, '2003', 'A', '三角洲', 'C', 1, 300, '錢包', 'closed', '2026-10-01 01:00:00', '2026-10-01 01:00:00');

            INSERT INTO support_calls (
                ticket_channel_id, status, called_at
            )
            VALUES
                ('2001', 'open', '2026-10-02T01:05:00+08:00');
            """
        )
        conn.commit()

    snapshot = customer_portal.build_customer_portal_snapshot(
        "A",
        guild_id="999",
        db_file=db_path,
    )

    assert snapshot["open_count"] == 2
    assert snapshot["pending_payment_count"] == 1
    assert snapshot["support_waiting_count"] == 1
    assert snapshot["total_count"] == 3
    assert [item["id"] for item in snapshot["history_orders"]] == [3]
