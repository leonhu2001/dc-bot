import sqlite3
from pathlib import Path

from views import review


def _prepare_order_db(db_file: Path) -> None:
    conn = sqlite3.connect(db_file)
    try:
        conn.executescript(
            """
            CREATE TABLE web_orders (
                id INTEGER PRIMARY KEY,
                ticket_channel_id TEXT,
                dispatch_message_id TEXT,
                bot_order_no TEXT,
                category TEXT,
                item TEXT,
                customer_display_name TEXT
            );

            CREATE TABLE order_assignments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                order_id INTEGER NOT NULL,
                worker_discord_id TEXT NOT NULL,
                worker_display_name TEXT,
                role_type TEXT,
                is_active INTEGER NOT NULL DEFAULT 1,
                assigned_at TEXT
            );
            """
        )
        conn.execute(
            """
            INSERT INTO web_orders (
                id,
                ticket_channel_id,
                dispatch_message_id,
                bot_order_no,
                category,
                item,
                customer_display_name
            )
            VALUES (1, '555', '777', 'R-1', '陪玩', '娛樂陪', 'Boss')
            """
        )
        conn.execute(
            """
            INSERT INTO order_assignments (
                order_id,
                worker_discord_id,
                worker_display_name,
                role_type,
                is_active,
                assigned_at
            )
            VALUES (1, '200', '莫莫', '陪玩', 1, '2026-09-26T18:00:00')
            """
        )
        conn.commit()
    finally:
        conn.close()


def test_post_close_embed_reflects_review_tip_and_favorite(tmp_path, monkeypatch):
    db_file = tmp_path / "post_close.db"
    _prepare_order_db(db_file)
    monkeypatch.setattr(review, "_web_db_path", lambda: db_file)
    review.ensure_review_tables()

    conn = sqlite3.connect(db_file)
    try:
        conn.execute(
            """
            INSERT INTO order_reviews (
                order_id,
                ticket_channel_id,
                staff_discord_id,
                staff_display_name,
                customer_discord_id,
                rating,
                created_at,
                updated_at
            )
            VALUES (1, '555', '200', '莫莫', '100', 5, 'now', 'now')
            """
        )
        conn.execute(
            """
            INSERT INTO staff_favorites (
                customer_discord_id,
                staff_discord_id,
                staff_display_name,
                created_at
            )
            VALUES ('100', '200', '莫莫', 'now')
            """
        )
        conn.execute(
            """
            INSERT INTO worker_tips (
                order_id,
                ticket_channel_id,
                customer_discord_id,
                worker_discord_id,
                worker_display_name,
                amount,
                payment_method,
                payment_status,
                payout_status,
                created_at,
                updated_at
            )
            VALUES (
                1,
                '555',
                '100',
                '200',
                '莫莫',
                140,
                '我的錢包',
                'paid',
                'unpaid',
                'now',
                'now'
            )
            """
        )
        conn.commit()
    finally:
        conn.close()

    embed = review.build_post_close_status_embed(555, 100)
    fields = {field.name: field.value for field in embed.fields}

    assert "5/5" in fields["⭐ 評價"]
    assert "140T" in fields["🍗 雞腿"]
    assert "已付款" in fields["🍗 雞腿"]
    assert "已收藏" in fields["❤️ 收藏"]
