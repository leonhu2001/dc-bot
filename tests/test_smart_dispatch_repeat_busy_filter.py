from pathlib import Path
import sqlite3

from views.smart_dispatch import _exclude_busy_notification_ids


def _setup_db(path: Path) -> None:
    with sqlite3.connect(path) as conn:
        conn.executescript(
            """
            CREATE TABLE web_orders (
                id INTEGER PRIMARY KEY,
                status TEXT NOT NULL
            );

            CREATE TABLE order_assignments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                order_id INTEGER NOT NULL,
                worker_discord_id TEXT NOT NULL,
                is_active INTEGER NOT NULL DEFAULT 1,
                assigned_at TEXT
            );

            INSERT INTO web_orders (id, status) VALUES
                (1, 'active'),
                (2, 'accepted_pending_pay'),
                (3, 'waiting_acceptance'),
                (4, 'closed');

            INSERT INTO order_assignments (
                order_id,
                worker_discord_id,
                is_active,
                assigned_at
            ) VALUES
                (1, 'busy-active', 1, '2026-10-18 12:00:00'),
                (2, 'busy-payment', 1, '2026-10-18 12:10:00'),
                (3, 'busy-waiting', 1, '2026-10-18 12:15:00'),
                (4, 'idle-closed', 1, '2026-10-18 12:20:00');
            """
        )
        conn.commit()


def test_dispatch_notifications_exclude_staff_with_active_orders(tmp_path):
    db_path = tmp_path / "web_dashboard.db"
    _setup_db(db_path)

    assert _exclude_busy_notification_ids(
        [
            "busy-active",
            "busy-payment",
            "busy-waiting",
            "idle-closed",
            "idle-new",
        ],
        db_file=db_path,
    ) == ["idle-closed", "idle-new"]
