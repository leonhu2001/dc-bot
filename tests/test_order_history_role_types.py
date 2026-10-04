import sqlite3

from web.app.routers import order_history


def test_history_parse_plain_worker_id_defers_role_classification():
    assert order_history.history_parse_worker_option("123") == (
        "123",
        "",
    )


def test_history_parse_accepts_canonical_role_types():
    assert order_history.history_parse_worker_option(
        "123|booster"
    ) == ("123", "booster")
    assert order_history.history_parse_worker_option(
        "456|companion"
    ) == ("456", "companion")


def test_history_staff_options_use_canonical_assignment_roles(
    tmp_path,
    monkeypatch,
):
    db_file = tmp_path / "web_dashboard.db"

    with sqlite3.connect(db_file) as conn:
        conn.executescript(
            """
            CREATE TABLE web_staff_members (
                discord_id TEXT PRIMARY KEY,
                display_name TEXT,
                username TEXT,
                is_worker INTEGER,
                is_companion INTEGER,
                is_customer_service INTEGER,
                is_active INTEGER
            );
            """
        )
        conn.executemany(
            """
            INSERT INTO web_staff_members(
                discord_id,
                display_name,
                username,
                is_worker,
                is_companion,
                is_customer_service,
                is_active
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            [
                ("1", "Protector", "p", 1, 0, 0, 1),
                ("2", "Companion", "c", 0, 1, 0, 1),
                ("3", "Both", "b", 1, 1, 0, 1),
            ],
        )
        conn.commit()

    monkeypatch.setattr(
        order_history,
        "history_db_path",
        lambda: str(db_file),
    )

    options = order_history.history_staff_options()
    by_id = {
        item["id"]: item
        for item in options["workers"]
    }

    assert by_id["1"]["role_type"] == "booster"
    assert by_id["2"]["role_type"] == "companion"
    assert by_id["3"]["role_type"] == "booster"
