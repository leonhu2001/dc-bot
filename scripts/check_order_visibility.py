from pathlib import Path
import sqlite3
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from web.app.config import config


def sqlite_path_from_database_url(database_url: str) -> str:
    if not database_url.startswith("sqlite:///"):
        raise RuntimeError(f"Only sqlite database is supported by this check: {database_url}")
    return database_url.replace("sqlite:///", "", 1)


def main() -> None:
    db_path = sqlite_path_from_database_url(config.DATABASE_URL)
    conn = sqlite3.connect(db_path)

    print(f"db={db_path}")
    print("status_counts:")
    for row in conn.execute("SELECT status, COUNT(*) FROM web_orders GROUP BY status ORDER BY status"):
        print(row)

    print("\nadmin_default_should_show_active_only:")
    for row in conn.execute("SELECT id, bot_order_no, status, category, item FROM web_orders WHERE status='active' ORDER BY id DESC LIMIT 10"):
        print(row)

    conn.close()


if __name__ == "__main__":
    main()
