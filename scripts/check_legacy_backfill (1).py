from __future__ import annotations

import sqlite3
import sys
from pathlib import Path
from urllib.parse import unquote

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from web.app.config import config

BOT_DB = PROJECT_ROOT / "bot.db"


def sqlite_path_from_url(database_url: str) -> Path:
    if database_url.startswith("sqlite:///"):
        raw = database_url.removeprefix("sqlite:///")
        if raw.startswith("/"):
            return Path(unquote(raw))
        return Path(unquote(raw))
    raise RuntimeError(f"只支援 sqlite DATABASE_URL，目前是：{database_url}")


def safe_count(conn: sqlite3.Connection, sql: str) -> int:
    try:
        return int(conn.execute(sql).fetchone()[0] or 0)
    except sqlite3.OperationalError:
        return 0


def main() -> None:
    web_db = sqlite_path_from_url(config.DATABASE_URL)

    bot = sqlite3.connect(BOT_DB)
    web = sqlite3.connect(web_db)

    try:
        print("bot_db=", BOT_DB)
        print("web_db=", web_db)
        print("bot_orders_total=", safe_count(bot, "SELECT COUNT(*) FROM orders"))
        print("bot_claims_total=", safe_count(bot, "SELECT COUNT(*) FROM claims"))
        print("web_orders_total=", safe_count(web, "SELECT COUNT(*) FROM web_orders"))
        print("web_assignments_total=", safe_count(web, "SELECT COUNT(*) FROM order_assignments"))

        print("web_status_counts:")
        for row in web.execute("SELECT status, COUNT(*) FROM web_orders GROUP BY status ORDER BY status"):
            print(tuple(row))

        print("latest_web_orders:")
        for row in web.execute("""
            SELECT id, bot_order_no, ticket_channel_id, category, item, amount, status
            FROM web_orders
            ORDER BY id DESC
            LIMIT 10
        """):
            print(tuple(row))
    finally:
        bot.close()
        web.close()


if __name__ == "__main__":
    main()
