import sqlite3

from tools.repair_stale_bot_claims import (
    apply_stale_bot_claim_repairs,
    audit_stale_bot_claims,
)


def _setup(web_db, bot_db):
    with sqlite3.connect(web_db) as web:
        web.executescript(
            """
            CREATE TABLE web_orders (
                id INTEGER PRIMARY KEY,
                status TEXT,
                ticket_channel_id TEXT,
                dispatch_message_id TEXT
            );

            INSERT INTO web_orders VALUES
                (1, 'closed', '100', '1000'),
                (2, 'cancelled', '200', '2000'),
                (3, 'stored', '300', '3000'),
                (4, 'active', '400', '4000');
            """
        )
        web.commit()

    with sqlite3.connect(bot_db) as bot:
        bot.executescript(
            """
            CREATE TABLE claims (
                dispatch_message_id INTEGER PRIMARY KEY,
                source_channel_id INTEGER,
                status TEXT,
                locked INTEGER
            );

            INSERT INTO claims VALUES
                (1000, 100, 'active', 0),
                (9999, 200, 'accepted_pending_pay', 0),
                (3000, 300, 'stored', 1),
                (4000, 400, 'active', 0),
                (5000, 500, 'active', 0);
            """
        )
        bot.commit()


def test_stale_claim_repair_deletes_only_final_linked_rows(tmp_path):
    web_db = tmp_path / "web_dashboard.db"
    bot_db = tmp_path / "bot.db"
    backup_dir = tmp_path / "archive"
    _setup(web_db, bot_db)

    before = audit_stale_bot_claims(
        web_db=web_db,
        bot_db=bot_db,
    )

    assert before.total_claims == 5
    assert [
        (row.dispatch_message_id, row.linked_order_id)
        for row in before.stale_claims
    ] == [
        (1000, 1),
        (9999, 2),
    ]

    backup_path, changed = apply_stale_bot_claim_repairs(
        web_db=web_db,
        bot_db=bot_db,
        backup_dir=backup_dir,
    )

    assert changed == 2
    assert backup_path.exists()

    after = audit_stale_bot_claims(
        web_db=web_db,
        bot_db=bot_db,
    )
    assert after.stale_claims == ()

    with sqlite3.connect(bot_db) as bot:
        remaining = bot.execute(
            """
            SELECT dispatch_message_id
            FROM claims
            ORDER BY dispatch_message_id
            """
        ).fetchall()

    assert remaining == [
        (3000,),
        (4000,),
        (5000,),
    ]

    with sqlite3.connect(backup_path) as backup:
        original = backup.execute(
            "SELECT COUNT(*) FROM claims"
        ).fetchone()[0]

    assert original == 5
