import sqlite3

from services.web_sync import event_store


def _setup_db(path):
    with sqlite3.connect(path) as conn:
        conn.executescript(
            """
            CREATE TABLE web_orders (
                id INTEGER PRIMARY KEY,
                ticket_channel_id TEXT,
                dispatch_channel_id TEXT,
                dispatch_message_id TEXT,
                category TEXT,
                item TEXT,
                quantity INTEGER,
                amount INTEGER,
                customer_discord_id TEXT,
                customer_display_name TEXT
            );

            CREATE TABLE sync_events (
                id INTEGER PRIMARY KEY,
                order_id INTEGER NOT NULL,
                event_type TEXT NOT NULL,
                retry_count INTEGER NOT NULL DEFAULT 0,
                payload_json TEXT,
                status TEXT NOT NULL DEFAULT 'pending',
                error_message TEXT,
                processed_at TEXT
            );

            INSERT INTO web_orders (
                id,
                ticket_channel_id,
                dispatch_channel_id,
                dispatch_message_id,
                category,
                item,
                quantity,
                amount,
                customer_discord_id,
                customer_display_name
            )
            VALUES (1, '10', '20', '30', '三角洲', '護航', 1, 1000, '40', '客人');
            """
        )
        conn.commit()


def test_order_created_retry_claim_is_atomic_between_workers(tmp_path):
    db_file = tmp_path / "web-sync.db"
    _setup_db(db_file)

    with sqlite3.connect(db_file) as conn:
        conn.execute(
            """
            INSERT INTO sync_events (
                id,
                order_id,
                event_type,
                retry_count,
                payload_json,
                status,
                error_message,
                processed_at
            )
            VALUES (1, 1, 'order_created', 3, '{}', 'failed', 'old failure', datetime('now'))
            """
        )
        conn.commit()

    first = event_store.fetch_order_created_retry_events(
        db_file=db_file,
        limit=10,
    )
    second = event_store.fetch_order_created_retry_events(
        db_file=db_file,
        limit=10,
    )

    assert [row["event_id"] for row in first] == [1]
    assert second == []

    with sqlite3.connect(db_file) as conn:
        row = conn.execute(
            """
            SELECT status, error_message, processed_at
            FROM sync_events
            WHERE id = 1
            """
        ).fetchone()

    assert row[0] == "processing"
    assert row[1] is None
    assert row[2] is not None


def test_order_created_retry_claim_only_recovers_stale_processing(tmp_path):
    db_file = tmp_path / "web-sync.db"
    _setup_db(db_file)

    with sqlite3.connect(db_file) as conn:
        conn.executemany(
            """
            INSERT INTO sync_events (
                id,
                order_id,
                event_type,
                retry_count,
                payload_json,
                status,
                processed_at
            )
            VALUES (?, 1, 'order_created', 2, '{}', 'processing', ?)
            """,
            [
                (1, "2026-10-16 02:00:00"),
                (2, "2000-01-01 00:00:00"),
                (3, None),
            ],
        )
        conn.commit()

    # Make row 1 definitely fresh relative to the SQLite clock used by the store.
    with sqlite3.connect(db_file) as conn:
        conn.execute(
            "UPDATE sync_events SET processed_at = datetime('now') WHERE id = 1"
        )
        conn.commit()

    rows = event_store.fetch_order_created_retry_events(
        db_file=db_file,
        limit=10,
        stale_processing_minutes=10,
    )

    assert [row["event_id"] for row in rows] == [2, 3]

    with sqlite3.connect(db_file) as conn:
        statuses = dict(
            conn.execute(
                "SELECT id, status FROM sync_events ORDER BY id"
            ).fetchall()
        )

    assert statuses == {
        1: "processing",
        2: "processing",
        3: "processing",
    }


def test_mark_order_created_processing_refreshes_processing_timestamp(tmp_path):
    db_file = tmp_path / "web-sync.db"
    _setup_db(db_file)

    with sqlite3.connect(db_file) as conn:
        conn.execute(
            """
            INSERT INTO sync_events (
                id,
                order_id,
                event_type,
                retry_count,
                payload_json,
                status,
                error_message,
                processed_at
            )
            VALUES (
                1,
                1,
                'order_created',
                3,
                '{}',
                'failed',
                'old failure',
                '2000-01-01 00:00:00'
            )
            """
        )
        conn.commit()

    event_store.mark_order_created_processing(1, db_file=db_file)

    with sqlite3.connect(db_file) as conn:
        row = conn.execute(
            """
            SELECT status, error_message, processed_at
            FROM sync_events
            WHERE id = 1
            """
        ).fetchone()

    assert row[0] == "processing"
    assert row[1] is None
    assert row[2] != "2000-01-01 00:00:00"
