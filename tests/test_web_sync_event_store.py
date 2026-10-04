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

            CREATE TABLE order_assignments (
                id INTEGER PRIMARY KEY,
                order_id INTEGER NOT NULL,
                worker_discord_id TEXT NOT NULL,
                worker_display_name TEXT,
                role_type TEXT,
                is_active INTEGER NOT NULL DEFAULT 1
            );
            """
        )
        conn.execute(
            """
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
            VALUES (1, '10', '20', '30', '三角洲', '護航', 1, 1000, '40', '客人')
            """
        )
        conn.commit()


def test_claim_pending_events_is_atomic_between_workers(tmp_path):
    db_file = tmp_path / "web-sync.db"
    _setup_db(db_file)

    with sqlite3.connect(db_file) as conn:
        conn.execute(
            """
            INSERT INTO sync_events (
                id, order_id, event_type, payload_json, status
            )
            VALUES (1, 1, 'order_updated', '{}', 'pending')
            """
        )
        conn.commit()

    first = event_store.claim_pending_events(
        db_file=db_file,
        limit=10,
    )
    second = event_store.claim_pending_events(
        db_file=db_file,
        limit=10,
    )

    assert [row["event_id"] for row in first] == [1]
    assert second == []

    with sqlite3.connect(db_file) as conn:
        status = conn.execute(
            "SELECT status FROM sync_events WHERE id = 1"
        ).fetchone()[0]
    assert status == "processing"


def test_claim_pending_events_recovers_stale_processing_rows(tmp_path):
    db_file = tmp_path / "web-sync.db"
    _setup_db(db_file)

    with sqlite3.connect(db_file) as conn:
        conn.execute(
            """
            INSERT INTO sync_events (
                id,
                order_id,
                event_type,
                payload_json,
                status,
                processed_at
            )
            VALUES (
                1,
                1,
                'order_updated',
                '{}',
                'processing',
                datetime('now', '-20 minutes')
            )
            """
        )
        conn.commit()

    rows = event_store.claim_pending_events(
        db_file=db_file,
        stale_processing_minutes=10,
    )

    assert [row["event_id"] for row in rows] == [1]


def test_claim_pending_events_leaves_acceptance_events_for_other_worker(tmp_path):
    db_file = tmp_path / "web-sync.db"
    _setup_db(db_file)

    with sqlite3.connect(db_file) as conn:
        conn.executemany(
            """
            INSERT INTO sync_events (
                id, order_id, event_type, payload_json, status
            )
            VALUES (?, 1, ?, '{}', 'pending')
            """,
            [
                (1, "order_claimed"),
                (2, "order_unclaimed"),
                (3, "order_updated"),
            ],
        )
        conn.commit()

    rows = event_store.claim_pending_events(db_file=db_file)

    assert [row["event_id"] for row in rows] == [3]

    with sqlite3.connect(db_file) as conn:
        statuses = dict(
            conn.execute(
                "SELECT id, status FROM sync_events ORDER BY id"
            ).fetchall()
        )
    assert statuses == {
        1: "pending",
        2: "pending",
        3: "processing",
    }


def test_event_store_keeps_assignment_role_types(tmp_path):
    db_file = tmp_path / "web-sync.db"
    _setup_db(db_file)

    with sqlite3.connect(db_file) as conn:
        conn.executemany(
            """
            INSERT INTO order_assignments (
                id,
                order_id,
                worker_discord_id,
                worker_display_name,
                role_type,
                is_active
            )
            VALUES (?, 1, ?, ?, ?, ?)
            """,
            [
                (1, "101", "打手 A", "booster", 1),
                (2, "202", "陪玩 B", "companion", 1),
                (3, "303", "停用", "booster", 0),
            ],
        )
        conn.commit()

    rows = event_store.get_assignments(1, db_file=db_file)

    assert [
        (row["worker_discord_id"], row["role_type"])
        for row in rows
    ] == [
        ("101", "booster"),
        ("202", "companion"),
    ]


def test_mark_event_failed_retries_then_stops(tmp_path):
    db_file = tmp_path / "web-sync.db"
    _setup_db(db_file)

    with sqlite3.connect(db_file) as conn:
        conn.execute(
            """
            INSERT INTO sync_events (
                id, order_id, event_type, payload_json, status, retry_count
            )
            VALUES (1, 1, 'order_updated', '{}', 'processing', 0)
            """
        )
        conn.commit()

    event_store.mark_event_failed(
        1,
        "first failure",
        0,
        db_file=db_file,
    )
    with sqlite3.connect(db_file) as conn:
        row = conn.execute(
            "SELECT status, retry_count FROM sync_events WHERE id = 1"
        ).fetchone()
    assert row == ("pending", 1)

    event_store.mark_event_failed(
        1,
        "last failure",
        2,
        db_file=db_file,
    )
    with sqlite3.connect(db_file) as conn:
        row = conn.execute(
            """
            SELECT status, retry_count, error_message
            FROM sync_events
            WHERE id = 1
            """
        ).fetchone()
    assert row == ("failed", 3, "last failure")



def test_order_created_bundle_and_link_updates(tmp_path):
    db_file = tmp_path / "web-sync.db"
    _setup_db(db_file)

    with sqlite3.connect(db_file) as conn:
        conn.executescript(
            """
            CREATE TABLE order_acceptance_meta (
                order_id INTEGER PRIMARY KEY,
                required_staff_count INTEGER,
                specified_staff_ids_json TEXT,
                allowed_role_ids_json TEXT,
                required_game_role_ids_json TEXT
            );

            CREATE TABLE web_order_submission_meta (
                order_id INTEGER PRIMARY KEY,
                request_key TEXT,
                extra_requirements TEXT,
                terms_version TEXT,
                terms_accepted_at TEXT,
                submission_payload_json TEXT
            );
            """
        )
        conn.execute(
            """
            INSERT INTO order_acceptance_meta (
                order_id,
                required_staff_count,
                specified_staff_ids_json,
                allowed_role_ids_json,
                required_game_role_ids_json
            )
            VALUES (1, 2, '["101"]', '["201"]', '["301"]')
            """
        )
        conn.execute(
            """
            INSERT INTO web_order_submission_meta (
                order_id,
                request_key,
                extra_requirements,
                terms_version,
                terms_accepted_at,
                submission_payload_json
            )
            VALUES (1, 'req-1', '備註', 'v1', '2026-10-04T00:00:00', '{}')
            """
        )
        conn.commit()

    bundle = event_store.load_order_created_bundle(1, db_file=db_file)

    assert bundle["order"]["id"] == 1
    assert bundle["acceptance"]["required_staff_count"] == 2
    assert bundle["submission"]["request_key"] == "req-1"

    event_store.update_order_created_links(
        1,
        ticket_channel_id=111,
        dispatch_channel_id=222,
        dispatch_message_id=333,
        db_file=db_file,
    )

    with sqlite3.connect(db_file) as conn:
        links = conn.execute(
            """
            SELECT ticket_channel_id, dispatch_channel_id, dispatch_message_id
            FROM web_orders
            WHERE id = 1
            """
        ).fetchone()

    assert links == ("111", "222", "333")


def test_order_created_retry_store_transitions_and_filters(tmp_path):
    db_file = tmp_path / "web-sync.db"
    _setup_db(db_file)

    with sqlite3.connect(db_file) as conn:
        conn.executemany(
            """
            INSERT INTO sync_events (
                id,
                order_id,
                event_type,
                payload_json,
                status,
                retry_count,
                error_message
            )
            VALUES (?, 1, ?, '{}', ?, ?, ?)
            """,
            [
                (1, "order_created", "failed", 2, "retry me"),
                (2, "order_created", "failed", 20, "stop"),
                (3, "order_updated", "failed", 1, "other"),
            ],
        )
        conn.commit()

    rows = event_store.fetch_order_created_retry_events(
        db_file=db_file,
        limit=10,
    )

    assert [row["event_id"] for row in rows] == [1]

    event_store.mark_order_created_processing(1, db_file=db_file)

    with sqlite3.connect(db_file) as conn:
        row = conn.execute(
            """
            SELECT status, error_message
            FROM sync_events
            WHERE id = 1
            """
        ).fetchone()

    assert row == ("processing", None)
