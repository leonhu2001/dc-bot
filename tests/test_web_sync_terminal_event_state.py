import sqlite3

from services.web_sync.event_store import mark_event_failed


def test_completed_sync_event_cannot_regress_to_failed(tmp_path):
    db_file = tmp_path / "web_dashboard.db"
    with sqlite3.connect(db_file) as conn:
        conn.execute(
            """
            CREATE TABLE sync_events (
                id INTEGER PRIMARY KEY,
                status TEXT NOT NULL,
                error_message TEXT,
                retry_count INTEGER NOT NULL DEFAULT 0,
                processed_at TEXT
            )
            """
        )
        conn.execute(
            """
            INSERT INTO sync_events(id, status, error_message, retry_count, processed_at)
            VALUES(349, 'done', NULL, 4, '2026-10-16 09:00:00')
            """
        )
        conn.commit()

    mark_event_failed(
        349,
        "name 'old_order_amount' is not defined",
        4,
        db_file=db_file,
        max_retries=5,
    )

    with sqlite3.connect(db_file) as conn:
        row = conn.execute(
            "SELECT status, error_message, retry_count, processed_at FROM sync_events WHERE id=349"
        ).fetchone()

    assert row == ('done', None, 4, '2026-10-16 09:00:00')
