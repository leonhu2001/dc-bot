from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path
from urllib.parse import unquote

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from shared.db import create_all_tables
from web.app.config import config

BOT_DB = PROJECT_ROOT / "bot.db"

STATUS_MAP = {
    "active": "active",
    "stored": "stored",
    "closed": "closed",
    "cancelled": "cancelled",
    "canceled": "cancelled",
    "done": "closed",
    "complete": "closed",
    "completed": "closed",
}


def sqlite_path_from_url(database_url: str) -> Path:
    if database_url.startswith("sqlite:///"):
        raw = database_url.removeprefix("sqlite:///")
        if raw.startswith("/"):
            return Path(unquote(raw))
        return Path(unquote(raw))
    raise RuntimeError(f"只支援 sqlite DATABASE_URL，目前是：{database_url}")


def table_exists(conn: sqlite3.Connection, table_name: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=? LIMIT 1",
        (table_name,),
    ).fetchone()
    return row is not None


def parse_json_list(value: str | None) -> list[str]:
    if not value:
        return []
    try:
        data = json.loads(value)
    except Exception:
        return []
    if isinstance(data, list):
        return [str(item) for item in data if str(item)]
    return []


def normalize_status(value: str | None) -> str:
    raw = str(value or "active").strip().lower()
    return STATUS_MAP.get(raw, raw or "active")


def get_customer_map(bot: sqlite3.Connection) -> dict[str, str]:
    if not table_exists(bot, "customers"):
        return {}

    columns = [row[1] for row in bot.execute("PRAGMA table_info(customers)").fetchall()]
    id_col = "user_id" if "user_id" in columns else "discord_id" if "discord_id" in columns else "id" if "id" in columns else None
    name_col = None
    for candidate in ["display_name", "name", "username", "nickname"]:
        if candidate in columns:
            name_col = candidate
            break

    if not id_col or not name_col:
        return {}

    result: dict[str, str] = {}
    for customer_id, name in bot.execute(f"SELECT {id_col}, {name_col} FROM customers"):
        if customer_id and name:
            result[str(customer_id)] = str(name)
    return result


def get_staff_name(web: sqlite3.Connection, discord_id: str) -> str | None:
    if not table_exists(web, "web_staff_members"):
        return None
    row = web.execute(
        """
        SELECT display_name, global_name, username
        FROM web_staff_members
        WHERE discord_id = ?
        LIMIT 1
        """,
        (str(discord_id),),
    ).fetchone()
    if not row:
        return None
    return row[0] or row[1] or row[2]


def get_existing_web_order_id(web: sqlite3.Connection, order: sqlite3.Row) -> int | None:
    order_no = order["order_no"]
    channel_id = order["channel_id"]

    if order_no:
        row = web.execute(
            "SELECT id FROM web_orders WHERE bot_order_no = ? LIMIT 1",
            (str(order_no),),
        ).fetchone()
        if row:
            return int(row[0])

    if channel_id is not None:
        row = web.execute(
            "SELECT id FROM web_orders WHERE ticket_channel_id = ? LIMIT 1",
            (str(channel_id),),
        ).fetchone()
        if row:
            return int(row[0])

    return None


def upsert_web_order(
    web: sqlite3.Connection,
    order: sqlite3.Row,
    customer_names: dict[str, str],
    dry_run: bool,
) -> tuple[int | None, str]:
    customer_id = str(order["customer_id"]) if order["customer_id"] is not None else None
    customer_display_name = customer_names.get(customer_id or "") if customer_id else None

    existing_id = get_existing_web_order_id(web, order)

    values = {
        "bot_order_no": str(order["order_no"]) if order["order_no"] else None,
        "ticket_channel_id": str(order["channel_id"]) if order["channel_id"] is not None else None,
        "dispatch_channel_id": str(order["dispatch_channel_id"]) if order["dispatch_channel_id"] else None,
        "dispatch_message_id": str(order["dispatch_message_id"]) if order["dispatch_message_id"] else None,
        "customer_discord_id": customer_id,
        "customer_display_name": customer_display_name,
        "category": str(order["category"] or "legacy"),
        "item": str(order["item"] or "舊資料"),
        "quantity": int(order["quantity"] or 1),
        "amount": int(order["amount"] or 0),
        "payment_method": str(order["payment_method"]) if order["payment_method"] else None,
        "status": normalize_status(order["status"]),
        "customer_service_discord_id": "legacy_unassigned_service",
        "customer_service_display_name": "舊單未指定客服",
        "note": str(order["note"] or "舊訂單回填"),
        "created_at": order["created_at"],
        "updated_at": order["updated_at"] or order["closed_at"] or order["stored_at"] or order["created_at"],
    }

    if dry_run:
        return existing_id, "update" if existing_id else "insert"

    if existing_id:
        web.execute(
            """
            UPDATE web_orders
            SET bot_order_no = ?, ticket_channel_id = ?, dispatch_channel_id = ?, dispatch_message_id = ?,
                customer_discord_id = ?, customer_display_name = ?, category = ?, item = ?, quantity = ?,
                amount = ?, payment_method = ?, status = ?, note = ?, updated_at = ?
            WHERE id = ?
            """,
            (
                values["bot_order_no"],
                values["ticket_channel_id"],
                values["dispatch_channel_id"],
                values["dispatch_message_id"],
                values["customer_discord_id"],
                values["customer_display_name"],
                values["category"],
                values["item"],
                values["quantity"],
                values["amount"],
                values["payment_method"],
                values["status"],
                values["note"],
                values["updated_at"],
                existing_id,
            ),
        )
        return existing_id, "update"

    cursor = web.execute(
        """
        INSERT INTO web_orders (
            bot_order_no, ticket_channel_id, dispatch_channel_id, dispatch_message_id,
            customer_discord_id, customer_display_name, category, item, quantity,
            amount, payment_method, status, customer_service_discord_id,
            customer_service_display_name, note, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            values["bot_order_no"],
            values["ticket_channel_id"],
            values["dispatch_channel_id"],
            values["dispatch_message_id"],
            values["customer_discord_id"],
            values["customer_display_name"],
            values["category"],
            values["item"],
            values["quantity"],
            values["amount"],
            values["payment_method"],
            values["status"],
            values["customer_service_discord_id"],
            values["customer_service_display_name"],
            values["note"],
            values["created_at"],
            values["updated_at"],
        ),
    )
    return int(cursor.lastrowid), "insert"


def build_claim_map(bot: sqlite3.Connection) -> dict[str, sqlite3.Row]:
    if not table_exists(bot, "claims"):
        return {}
    claims = {}
    for claim in bot.execute("SELECT * FROM claims"):
        if claim["dispatch_message_id"] is not None:
            claims[str(claim["dispatch_message_id"])] = claim
    return claims


def add_assignment_if_missing(
    web: sqlite3.Connection,
    *,
    order_id: int,
    worker_id: str,
    role_type: str,
    is_active: bool,
    dry_run: bool,
) -> bool:
    existing = web.execute(
        """
        SELECT id FROM order_assignments
        WHERE order_id = ? AND worker_discord_id = ? AND is_active = 1
        LIMIT 1
        """,
        (order_id, str(worker_id)),
    ).fetchone()
    if existing:
        return False

    if dry_run:
        return True

    web.execute(
        """
        INSERT INTO order_assignments (
            order_id, worker_discord_id, worker_display_name, role_type,
            is_active, has_named_bonus, assigned_at
        ) VALUES (?, ?, ?, ?, ?, 0, datetime('now'))
        """,
        (
            order_id,
            str(worker_id),
            get_staff_name(web, worker_id) or str(worker_id),
            role_type,
            1 if is_active else 0,
        ),
    )
    return True


def backfill(dry_run: bool) -> None:
    web_db = sqlite_path_from_url(config.DATABASE_URL)
    if not BOT_DB.exists():
        raise RuntimeError(f"找不到 bot.db：{BOT_DB}")

    create_all_tables()

    bot = sqlite3.connect(BOT_DB)
    web = sqlite3.connect(web_db)
    bot.row_factory = sqlite3.Row
    web.row_factory = sqlite3.Row

    try:
        customer_names = get_customer_map(bot)
        claims = build_claim_map(bot)

        orders = list(bot.execute("SELECT * FROM orders ORDER BY created_at ASC"))

        inserted = 0
        updated = 0
        assignment_added = 0

        for order in orders:
            web_order_id, action = upsert_web_order(web, order, customer_names, dry_run)
            if action == "insert":
                inserted += 1
            else:
                updated += 1

            if web_order_id is None:
                continue

            dispatch_message_id = order["dispatch_message_id"]
            claim = claims.get(str(dispatch_message_id)) if dispatch_message_id else None

            if claim:
                order_status = normalize_status(order["status"])
                is_active_assignment = order_status == "active" and normalize_status(claim["status"]) == "active"
                worker_ids = parse_json_list(claim["booster_ids"])
                companion_ids = parse_json_list(claim["companion_ids"])

                for worker_id in worker_ids:
                    if add_assignment_if_missing(
                        web,
                        order_id=web_order_id,
                        worker_id=worker_id,
                        role_type="booster",
                        is_active=is_active_assignment,
                        dry_run=dry_run,
                    ):
                        assignment_added += 1

                for worker_id in companion_ids:
                    if add_assignment_if_missing(
                        web,
                        order_id=web_order_id,
                        worker_id=worker_id,
                        role_type="companion",
                        is_active=is_active_assignment,
                        dry_run=dry_run,
                    ):
                        assignment_added += 1

        if not dry_run:
            web.commit()

        print("dry_run=", dry_run)
        print("bot_orders_total=", len(orders))
        print("web_orders_inserted=", inserted)
        print("web_orders_updated=", updated)
        print("assignments_added=", assignment_added)

        print("web_status_counts:")
        for row in web.execute("SELECT status, COUNT(*) FROM web_orders GROUP BY status ORDER BY status"):
            print(tuple(row))

    finally:
        bot.close()
        web.close()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    backfill(dry_run=args.dry_run)


if __name__ == "__main__":
    main()
