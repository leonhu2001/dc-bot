import json
import sqlite3

from tools.repair_assignment_role_types import (
    apply_assignment_role_repairs,
    audit_assignment_role_types,
)


PROTECTOR = "1500234130871550004"
COMPANION = "1500751059239440575"


def _setup_db(path):
    with sqlite3.connect(path) as conn:
        conn.executescript(
            """
            CREATE TABLE web_orders (
                id INTEGER PRIMARY KEY,
                status TEXT,
                item TEXT
            );

            CREATE TABLE order_assignments (
                id INTEGER PRIMARY KEY,
                order_id INTEGER NOT NULL,
                worker_discord_id TEXT NOT NULL,
                worker_display_name TEXT,
                role_type TEXT,
                is_active INTEGER NOT NULL DEFAULT 1
            );

            CREATE TABLE order_acceptance_claims (
                id INTEGER PRIMARY KEY,
                order_id INTEGER NOT NULL,
                staff_discord_id TEXT NOT NULL,
                staff_role_ids_json TEXT
            );
            """
        )

        conn.executemany(
            """
            INSERT INTO web_orders(id, status, item)
            VALUES (?, ?, ?)
            """,
            [
                (1, "closed", "陪玩"),
                (2, "closed", "技術陪"),
                (3, "closed", "舊單"),
            ],
        )

        conn.executemany(
            """
            INSERT INTO order_assignments(
                id,
                order_id,
                worker_discord_id,
                worker_display_name,
                role_type
            )
            VALUES (?, ?, ?, ?, ?)
            """,
            [
                (10, 1, "A", "Companion", "booster"),
                (11, 2, "B", "Protector", "worker"),
                (12, 3, "C", "Unknown", "worker"),
            ],
        )

        conn.executemany(
            """
            INSERT INTO order_acceptance_claims(
                id,
                order_id,
                staff_discord_id,
                staff_role_ids_json
            )
            VALUES (?, ?, ?, ?)
            """,
            [
                (20, 1, "A", json.dumps([COMPANION])),
                (21, 2, "B", json.dumps([PROTECTOR])),
                (22, 3, "C", json.dumps(["unknown-role"])),
            ],
        )
        conn.commit()


def test_role_repair_only_changes_evidence_backed_mismatches(
    tmp_path,
):
    db_file = tmp_path / "web_dashboard.db"
    backup_dir = tmp_path / "archive"
    _setup_db(db_file)

    before = audit_assignment_role_types(db_file)

    assert before.evidence_backed_count == 2
    assert before.invalid_role_type_count == 2
    assert [
        (row.assignment_id, row.expected_role_type)
        for row in before.repairs
    ] == [
        (10, "companion"),
        (11, "booster"),
    ]

    backup_path, changed = apply_assignment_role_repairs(
        db_file,
        backup_dir=backup_dir,
    )

    assert backup_path.exists()
    assert changed == 2

    after = audit_assignment_role_types(db_file)
    assert after.repairs == ()
    assert after.invalid_role_type_count == 1

    with sqlite3.connect(db_file) as conn:
        rows = conn.execute(
            """
            SELECT id, role_type
            FROM order_assignments
            ORDER BY id
            """
        ).fetchall()

    assert rows == [
        (10, "companion"),
        (11, "booster"),
        (12, "worker"),
    ]

    with sqlite3.connect(backup_path) as conn:
        backup_rows = conn.execute(
            """
            SELECT id, role_type
            FROM order_assignments
            ORDER BY id
            """
        ).fetchall()

    assert backup_rows == [
        (10, "booster"),
        (11, "worker"),
        (12, "worker"),
    ]
