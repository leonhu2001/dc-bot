from __future__ import annotations

from pathlib import Path
import sqlite3
import sys
from urllib.parse import unquote

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from web.app.config import config


def get_sqlite_path() -> Path:
    database_url = str(config.DATABASE_URL)

    if not database_url.startswith("sqlite:///"):
        raise RuntimeError(f"Only sqlite DATABASE_URL is supported by this script: {database_url}")

    raw_path = database_url.replace("sqlite:///", "", 1)
    raw_path = unquote(raw_path)

    # Linux absolute path: sqlite:////opt/dc-bot/web_dashboard.db -> /opt/dc-bot/web_dashboard.db
    if raw_path.startswith("/"):
        return Path(raw_path)

    # Windows absolute path: sqlite:///D:/DC bot/web_dashboard.db
    if len(raw_path) >= 3 and raw_path[1:3] == ":/":
        return Path(raw_path)

    return PROJECT_ROOT / raw_path


def cancel_order(identifier: str) -> None:
    db_path = get_sqlite_path()

    if not db_path.exists():
        raise FileNotFoundError(f"Database not found: {db_path}")

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row

    try:
        if identifier.isdigit():
            order = conn.execute(
                "SELECT id, bot_order_no, status FROM web_orders WHERE id = ?",
                (int(identifier),),
            ).fetchone()
        else:
            order = conn.execute(
                "SELECT id, bot_order_no, status FROM web_orders WHERE bot_order_no = ?",
                (identifier,),
            ).fetchone()

        if order is None:
            raise RuntimeError(f"找不到網站訂單：{identifier}")

        order_id = int(order["id"])

        conn.execute(
            "UPDATE web_orders SET status = 'cancelled', updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (order_id,),
        )
        conn.execute(
            """
            UPDATE order_assignments
            SET is_active = 0,
                has_named_bonus = 0,
                removed_at = CURRENT_TIMESTAMP
            WHERE order_id = ? AND is_active = 1
            """,
            (order_id,),
        )
        conn.execute(
            "UPDATE worker_payouts SET payout_status = 'void', updated_at = CURRENT_TIMESTAMP WHERE order_id = ?",
            (order_id,),
        )
        conn.execute(
            "UPDATE customer_service_payouts SET payout_status = 'void', updated_at = CURRENT_TIMESTAMP WHERE order_id = ?",
            (order_id,),
        )
        conn.commit()

        print(f"cancelled_web_order id={order_id} bot_order_no={order['bot_order_no']} old_status={order['status']}")
    finally:
        conn.close()


def main() -> None:
    if len(sys.argv) != 2:
        print("用法：python scripts/cancel_web_order.py WEB-4")
        print("或：python scripts/cancel_web_order.py 4")
        raise SystemExit(2)

    cancel_order(sys.argv[1].strip())


if __name__ == "__main__":
    main()
