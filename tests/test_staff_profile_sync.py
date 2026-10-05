from __future__ import annotations

import sqlite3

from services.staff_profile_sync import (
    claim_staff_profile_refresh_events,
    enqueue_staff_profile_refresh,
    ensure_staff_profile_refresh_sync,
    mark_staff_profile_refresh_done,
    mark_staff_profile_refresh_failed,
)


def _create_source_tables(db_file) -> None:
    with sqlite3.connect(db_file) as conn:
        conn.executescript(
            """
            CREATE TABLE staff_profiles (
                staff_discord_id TEXT PRIMARY KEY,
                display_name TEXT,
                profile_type TEXT,
                role_title TEXT,
                main_games TEXT,
                service_tags TEXT,
                bio TEXT,
                card_image_url TEXT,
                forum_thread_id TEXT,
                forum_channel_id TEXT,
                panel_message_id TEXT,
                is_public INTEGER NOT NULL DEFAULT 1,
                updated_at TEXT
            );

            CREATE TABLE staff_favorites (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                customer_discord_id TEXT NOT NULL,
                staff_discord_id TEXT NOT NULL,
                created_at TEXT
            );

            CREATE TABLE order_reviews (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                staff_discord_id TEXT NOT NULL,
                rating INTEGER,
                is_public INTEGER NOT NULL DEFAULT 1,
                is_hidden INTEGER NOT NULL DEFAULT 0,
                comment TEXT,
                service_category TEXT,
                service_item TEXT,
                created_at TEXT
            );

            CREATE TABLE web_orders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                status TEXT NOT NULL
            );

            CREATE TABLE order_assignments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                order_id INTEGER NOT NULL,
                worker_discord_id TEXT NOT NULL,
                is_active INTEGER NOT NULL DEFAULT 1
            );
            """
        )
        conn.commit()


def _event_rows(db_file):
    with sqlite3.connect(db_file) as conn:
        conn.row_factory = sqlite3.Row
        return [
            dict(row)
            for row in conn.execute(
                "SELECT * FROM staff_profile_refresh_events ORDER BY id ASC"
            ).fetchall()
        ]


def test_profile_and_favorite_changes_share_one_durable_refresh_rule(tmp_path):
    db_file = tmp_path / "web_dashboard.db"
    _create_source_tables(db_file)
    ensure_staff_profile_refresh_sync(db_file=db_file)

    with sqlite3.connect(db_file) as conn:
        conn.execute(
            """
            INSERT INTO staff_profiles (
                staff_discord_id,
                display_name,
                profile_type,
                role_title,
                main_games,
                service_tags,
                bio,
                card_image_url,
                is_public,
                updated_at
            ) VALUES ('1001', 'A', '陪玩', '', '', '', '', '', 1, CURRENT_TIMESTAMP)
            """
        )
        conn.execute(
            "UPDATE staff_profiles SET display_name='B' WHERE staff_discord_id='1001'"
        )
        conn.execute(
            """
            INSERT INTO staff_favorites(customer_discord_id, staff_discord_id, created_at)
            VALUES ('customer', '1001', CURRENT_TIMESTAMP)
            """
        )
        conn.commit()

    pending = [row for row in _event_rows(db_file) if row["status"] == "pending"]
    assert len(pending) == 1
    assert pending[0]["staff_discord_id"] == "1001"

    claimed = claim_staff_profile_refresh_events(db_file=db_file)
    assert len(claimed) == 1
    first_event_id = claimed[0]["event_id"]

    # A second database change while the first event is processing must create a
    # newer pending event without breaking the retry path of the first event.
    with sqlite3.connect(db_file) as conn:
        conn.execute(
            "DELETE FROM staff_favorites WHERE customer_discord_id='customer' AND staff_discord_id='1001'"
        )
        conn.commit()

    mark_staff_profile_refresh_failed(
        first_event_id,
        "temporary Discord error",
        claimed[0]["retry_count"],
        db_file=db_file,
    )

    rows = _event_rows(db_file)
    assert any(row["id"] == first_event_id and row["status"] == "done" for row in rows)
    assert sum(row["status"] == "pending" for row in rows) == 1

    newer = claim_staff_profile_refresh_events(db_file=db_file)
    assert len(newer) == 1
    assert newer[0]["staff_discord_id"] == "1001"
    assert newer[0]["reason"] == "favorite_changed"


def test_review_assignment_and_order_status_changes_enqueue_refreshes(tmp_path):
    db_file = tmp_path / "web_dashboard.db"
    _create_source_tables(db_file)
    ensure_staff_profile_refresh_sync(db_file=db_file)

    with sqlite3.connect(db_file) as conn:
        conn.execute(
            """
            INSERT INTO order_reviews(
                staff_discord_id,
                rating,
                is_public,
                is_hidden,
                comment,
                created_at
            ) VALUES ('2002', 5, 1, 0, 'great', CURRENT_TIMESTAMP)
            """
        )
        conn.commit()

    review_events = claim_staff_profile_refresh_events(db_file=db_file)
    assert len(review_events) == 1
    assert review_events[0]["staff_discord_id"] == "2002"
    assert review_events[0]["reason"] == "review_changed"
    mark_staff_profile_refresh_done(review_events[0]["event_id"], db_file=db_file)

    with sqlite3.connect(db_file) as conn:
        order_id = conn.execute(
            "INSERT INTO web_orders(status) VALUES ('active')"
        ).lastrowid
        conn.execute(
            """
            INSERT INTO order_assignments(order_id, worker_discord_id, is_active)
            VALUES (?, '2002', 1)
            """,
            (order_id,),
        )
        conn.commit()

    assignment_events = claim_staff_profile_refresh_events(db_file=db_file)
    assert len(assignment_events) == 1
    assert assignment_events[0]["reason"] == "assignment_changed"
    mark_staff_profile_refresh_done(assignment_events[0]["event_id"], db_file=db_file)

    with sqlite3.connect(db_file) as conn:
        conn.execute("UPDATE web_orders SET status='closed' WHERE id=?", (order_id,))
        conn.commit()

    order_events = claim_staff_profile_refresh_events(db_file=db_file)
    assert len(order_events) == 1
    assert order_events[0]["staff_discord_id"] == "2002"
    assert order_events[0]["reason"] == "order_status_changed"


def test_stale_processing_event_is_superseded_by_newer_pending_event(tmp_path):
    db_file = tmp_path / "web_dashboard.db"
    _create_source_tables(db_file)
    ensure_staff_profile_refresh_sync(db_file=db_file)

    assert enqueue_staff_profile_refresh("3003", reason="first", db_file=db_file)
    claimed = claim_staff_profile_refresh_events(db_file=db_file)
    assert len(claimed) == 1
    first_event_id = claimed[0]["event_id"]

    assert enqueue_staff_profile_refresh("3003", reason="newer", db_file=db_file)

    with sqlite3.connect(db_file) as conn:
        conn.execute(
            """
            UPDATE staff_profile_refresh_events
            SET processed_at = datetime('now', '-20 minutes')
            WHERE id = ?
            """,
            (first_event_id,),
        )
        conn.commit()

    recovered = claim_staff_profile_refresh_events(
        db_file=db_file,
        stale_processing_minutes=10,
    )
    assert len(recovered) == 1
    assert recovered[0]["reason"] == "newer"

    rows = _event_rows(db_file)
    first_row = next(row for row in rows if row["id"] == first_event_id)
    assert first_row["status"] == "done"
    assert "superseded" in str(first_row["error_message"])
