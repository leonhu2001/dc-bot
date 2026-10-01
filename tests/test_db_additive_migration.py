from sqlalchemy import create_engine, text

from shared.db import ensure_sqlite_additive_columns


def test_historical_discount_column_is_added_to_existing_web_orders():
    engine = create_engine("sqlite:///:memory:")

    with engine.begin() as conn:
        conn.execute(
            text(
                """
                CREATE TABLE web_orders (
                    id INTEGER PRIMARY KEY,
                    amount INTEGER NOT NULL DEFAULT 0
                )
                """
            )
        )

    ensure_sqlite_additive_columns(engine)

    with engine.begin() as conn:
        columns = {
            str(row[1])
            for row in conn.execute(
                text("PRAGMA table_info(web_orders)")
            ).fetchall()
        }

    assert "historical_discount_amount" in columns


def test_historical_discount_migration_is_idempotent():
    engine = create_engine("sqlite:///:memory:")

    with engine.begin() as conn:
        conn.execute(
            text(
                """
                CREATE TABLE web_orders (
                    id INTEGER PRIMARY KEY,
                    amount INTEGER NOT NULL DEFAULT 0
                )
                """
            )
        )

    ensure_sqlite_additive_columns(engine)
    ensure_sqlite_additive_columns(engine)

    with engine.begin() as conn:
        columns = [
            str(row[1])
            for row in conn.execute(
                text("PRAGMA table_info(web_orders)")
            ).fetchall()
        ]

    assert columns.count("historical_discount_amount") == 1
