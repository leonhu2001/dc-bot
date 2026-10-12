from datetime import date, datetime
import sqlite3
import warnings

from shared.db import register_sqlite_datetime_adapters


def test_sqlite_datetime_adapters_are_explicit_and_warning_free():
    register_sqlite_datetime_adapters()

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always", DeprecationWarning)
        conn = sqlite3.connect(":memory:")
        try:
            conn.execute("CREATE TABLE sample (day TEXT, happened_at TEXT)")
            conn.execute(
                "INSERT INTO sample(day, happened_at) VALUES (?, ?)",
                (date(2026, 10, 13), datetime(2026, 10, 13, 12, 34, 56)),
            )
            row = conn.execute("SELECT day, happened_at FROM sample").fetchone()
        finally:
            conn.close()

    assert row == ("2026-10-13", "2026-10-13 12:34:56")
    assert not [
        item
        for item in caught
        if "default" in str(item.message).lower()
        and "adapter" in str(item.message).lower()
    ]
