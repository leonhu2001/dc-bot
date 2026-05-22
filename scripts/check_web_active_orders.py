from pathlib import Path
import sqlite3
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from web.app.config import config


def sqlite_path_from_url(url: str) -> str:
    prefix = "sqlite:///"
    if not url.startswith(prefix):
        raise RuntimeError(f"Only sqlite DATABASE_URL is supported by this check: {url}")
    return url[len(prefix):]


def main() -> None:
    db_path = sqlite_path_from_url(config.DATABASE_URL)
    print(f"db={db_path}")

    conn = sqlite3.connect(db_path)

    print("active_orders:")
    for row in conn.execute('''
        SELECT id, bot_order_no, ticket_channel_id, dispatch_message_id,
               customer_display_name, category, item, amount, status
        FROM web_orders
        WHERE status = 'active'
        ORDER BY id DESC
        LIMIT 20
    '''):
        print(row)

    print("\nstatus_counts:")
    for row in conn.execute('''
        SELECT status, COUNT(*)
        FROM web_orders
        GROUP BY status
        ORDER BY status
    '''):
        print(row)

    conn.close()


if __name__ == "__main__":
    main()
