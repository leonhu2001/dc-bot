import sqlite3

from scripts.repair_legacy_tip_wallet_references import repair


def _make_web_db(path):
    with sqlite3.connect(path) as conn:
        conn.execute(
            """
            CREATE TABLE worker_tips (
                id INTEGER PRIMARY KEY,
                receipt_id TEXT,
                customer_discord_id TEXT,
                amount INTEGER,
                payment_method TEXT,
                payment_status TEXT,
                wallet_transaction_id INTEGER
            )
            """
        )
        conn.execute(
            """
            INSERT INTO worker_tips
            VALUES (1, 'MO20260922002', '836929629222600714', 100, '我的錢包', 'paid', 62)
            """
        )
        conn.commit()


def _make_bot_db(path):
    with sqlite3.connect(path) as conn:
        conn.execute(
            """
            CREATE TABLE wallet_transactions (
                id INTEGER PRIMARY KEY,
                customer_discord_id TEXT,
                amount INTEGER,
                balance_before INTEGER,
                balance_after INTEGER,
                type TEXT,
                order_no TEXT
            )
            """
        )
        conn.execute(
            """
            INSERT INTO wallet_transactions
            VALUES (62, '836929629222600714', -100, 500, 400, 'tip_payment', 'MO20260922002')
            """
        )
        conn.commit()


def _tx(path):
    with sqlite3.connect(path) as conn:
        return conn.execute(
            """
            SELECT amount, balance_before, balance_after, order_no
            FROM wallet_transactions
            WHERE id = 62
            """
        ).fetchone()


def test_tip_reference_repair_is_dry_run_by_default(tmp_path):
    _make_web_db(tmp_path / "web_dashboard.db")
    _make_bot_db(tmp_path / "bot.db")

    assert repair(root=tmp_path, tip_id=1, apply=False) == 0
    assert _tx(tmp_path / "bot.db") == (
        -100,
        500,
        400,
        "MO20260922002",
    )


def test_tip_reference_repair_changes_only_reference_and_creates_backup(tmp_path):
    _make_web_db(tmp_path / "web_dashboard.db")
    _make_bot_db(tmp_path / "bot.db")

    assert repair(root=tmp_path, tip_id=1, apply=True) == 0
    assert _tx(tmp_path / "bot.db") == (
        -100,
        500,
        400,
        "MO20260922002:TIP-1",
    )

    backups = list((tmp_path / "_archive").glob("bot_tip_reference_*.db"))
    assert len(backups) == 1

    assert _tx(backups[0]) == (
        -100,
        500,
        400,
        "MO20260922002",
    )


def test_tip_reference_repair_refuses_mismatched_wallet_data(tmp_path):
    _make_web_db(tmp_path / "web_dashboard.db")
    _make_bot_db(tmp_path / "bot.db")

    with sqlite3.connect(tmp_path / "bot.db") as conn:
        conn.execute(
            "UPDATE wallet_transactions SET amount = -99 WHERE id = 62"
        )
        conn.commit()

    assert repair(root=tmp_path, tip_id=1, apply=True) == 2
    assert _tx(tmp_path / "bot.db")[-1] == "MO20260922002"
    assert not (tmp_path / "_archive").exists()
