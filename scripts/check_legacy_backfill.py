from __future__ import annotations

import sqlite3
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
WEB_DB = PROJECT_ROOT / "web_dashboard.db"
BOT_DB = PROJECT_ROOT / "bot.db"


def count(conn: sqlite3.Connection, sql: str) -> int:
    return int(conn.execute(sql).fetchone()[0] or 0)


def main() -> None:
    web = sqlite3.connect(WEB_DB)
    bot = sqlite3.connect(BOT_DB)
    try:
        print(f"bot_db={BOT_DB}")
        print(f"web_db={WEB_DB}")
        print("bot_orders_total=", count(bot, "SELECT COUNT(*) FROM orders"))
        print("web_orders_total=", count(web, "SELECT COUNT(*) FROM web_orders"))
        print("worker_payouts_total=", count(web, "SELECT COUNT(*) FROM worker_payouts"))
        print("customer_service_payouts_total=", count(web, "SELECT COUNT(*) FROM customer_service_payouts"))
        print("")
        print("web_status_counts:")
        for row in web.execute("SELECT status, COUNT(*) FROM web_orders GROUP BY status ORDER BY status"):
            print(row)
        print("")
        print("latest_web_orders:")
        for row in web.execute("""
            SELECT id, bot_order_no, ticket_channel_id, category, item, amount, status
            FROM web_orders
            ORDER BY id DESC
            LIMIT 20
        """):
            print(row)
    finally:
        web.close()
        bot.close()


if __name__ == "__main__":
    main()
