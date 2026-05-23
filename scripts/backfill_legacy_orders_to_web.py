from __future__ import annotations

import argparse
import json
import re
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
BOT_DB = PROJECT_ROOT / "bot.db"
WEB_DB = PROJECT_ROOT / "web_dashboard.db"

CATEGORY_LABELS = {
    "basic": "基礎單",
    "fun": "趣味單",
    "farm": "代解代肝",
    "season": "賽季限定活動",
    "valorant": "Valorant",
}

VALID_STATUSES = {"active", "stored", "closed", "cancelled"}


def now_text() -> str:
    return datetime.utcnow().isoformat(timespec="seconds")


def load_json(value: Any, default: Any) -> Any:
    if value is None or value == "":
        return default
    if isinstance(value, (dict, list)):
        return value
    try:
        return json.loads(str(value))
    except Exception:
        return default


def to_int(value: Any, default: int | None = None) -> int | None:
    try:
        if value is None or value == "":
            return default
        return int(value)
    except Exception:
        return default


def parse_amount(value: Any) -> int:
    if value is None or value == "":
        return 0
    try:
        return max(0, int(value))
    except Exception:
        text = str(value).replace(",", "")
        nums = [int(x) for x in re.findall(r"\d+", text)]
        if not nums:
            return 0
        if "+" in text and len(nums) >= 2:
            return sum(nums)
        return nums[0]


def table_columns(conn: sqlite3.Connection, table_name: str) -> set[str]:
    return {row[1] for row in conn.execute(f"PRAGMA table_info({table_name})")}


def table_exists(conn: sqlite3.Connection, table_name: str) -> bool:
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
        (table_name,),
    ).fetchone()
    return row is not None


def row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    return {key: row[key] for key in row.keys()}


def normalize_order(row: sqlite3.Row, order_cols: set[str]) -> tuple[int, dict[str, Any]]:
    raw = row_to_dict(row)
    channel_id = to_int(raw.get("channel_id"))
    if channel_id is None:
        raise ValueError("orders row missing channel_id")

    if "data" in order_cols:
        data = load_json(raw.get("data"), {})
    else:
        data = load_json(raw.get("data_json"), {})

    if not isinstance(data, dict):
        data = {}

    for key in [
        "customer_id",
        "order_no",
        "category",
        "item",
        "quantity",
        "companion_preference",
        "payment_method",
        "amount",
        "status",
        "dispatch_message_id",
        "dispatch_channel_id",
        "created_at",
        "closed_at",
        "stored_at",
        "store_reason",
        "resume_at",
        "note",
    ]:
        if key in raw and raw.get(key) is not None:
            data[key] = raw.get(key)

    if "store_reason" in data and "stored_reason" not in data:
        data["stored_reason"] = data.get("store_reason")
    if "resume_at" in data and "stored_expected_time" not in data:
        data["stored_expected_time"] = data.get("resume_at")

    return channel_id, data


def normalize_claim(row: sqlite3.Row, claim_cols: set[str]) -> tuple[int | None, dict[str, Any]]:
    raw = row_to_dict(row)

    if "data" in claim_cols:
        message_id = to_int(raw.get("message_id"))
        data = load_json(raw.get("data"), {})
    else:
        message_id = to_int(raw.get("dispatch_message_id"))
        data = load_json(raw.get("data_json"), {})

    if not isinstance(data, dict):
        data = {}

    for key in [
        "customer_id",
        "source_channel_id",
        "dispatch_channel_id",
        "category_label",
        "item",
        "quantity",
        "payment_method",
        "companion_preference",
        "status",
    ]:
        if key in raw and raw.get(key) is not None:
            data[key] = raw.get(key)

    if "companion_ids" in raw:
        data["companion"] = load_json(raw.get("companion_ids"), [])
    if "booster_ids" in raw:
        data["booster"] = load_json(raw.get("booster_ids"), [])
    if "locked" in raw:
        data["locked"] = bool(raw.get("locked"))

    return message_id, data


def id_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, set):
        values = list(value)
    elif isinstance(value, list):
        values = value
    else:
        values = load_json(value, [])
        if not isinstance(values, list):
            values = []
    result: list[str] = []
    for item in values:
        item_int = to_int(item)
        if item_int is not None:
            result.append(str(item_int))
    return sorted(set(result))


def normalize_status(data: dict[str, Any]) -> str:
    status = str(data.get("status") or "").lower().strip()
    if data.get("closed") or data.get("reward_counted"):
        status = "closed"
    if not status:
        status = "active"
    if status not in VALID_STATUSES:
        status = "active"
    return status


def staff_name(web: sqlite3.Connection, discord_id: str) -> str:
    row = web.execute(
        """
        SELECT display_name, global_name, username
        FROM web_staff_members
        WHERE discord_id = ?
        """,
        (str(discord_id),),
    ).fetchone()
    if row:
        return row[0] or row[1] or row[2] or str(discord_id)
    return str(discord_id)


def find_existing_web_order(web: sqlite3.Connection, *, ticket_channel_id: str, dispatch_message_id: str | None, bot_order_no: str | None) -> int | None:
    candidates: list[tuple[str, str]] = [("ticket_channel_id", ticket_channel_id)]
    if dispatch_message_id:
        candidates.append(("dispatch_message_id", dispatch_message_id))
    if bot_order_no:
        candidates.append(("bot_order_no", bot_order_no))

    for column, value in candidates:
        row = web.execute(f"SELECT id FROM web_orders WHERE {column} = ? LIMIT 1", (value,)).fetchone()
        if row:
            return int(row[0])
    return None


def upsert_web_order(web: sqlite3.Connection, channel_id: int, data: dict[str, Any], claim: dict[str, Any] | None, *, dry_run: bool) -> tuple[int | None, bool]:
    claim = claim or {}
    status = normalize_status(data)
    dispatch_message_id = to_int(data.get("dispatch_message_id")) or to_int(claim.get("dispatch_message_id"))
    dispatch_channel_id = to_int(data.get("dispatch_channel_id")) or to_int(claim.get("dispatch_channel_id"))
    bot_order_no = data.get("order_no") or data.get("receipt_id")
    category = data.get("category") or claim.get("category_label") or "舊資料"
    category = CATEGORY_LABELS.get(str(category), str(category))
    item = data.get("item") or claim.get("item") or "舊訂單"
    quantity = to_int(data.get("quantity") or claim.get("quantity"), 1) or 1
    amount = parse_amount(data.get("amount") or data.get("total_amount") or data.get("reward_amount"))
    payment_method = data.get("payment_method") or claim.get("payment_method")
    customer_id = to_int(data.get("customer_id") or claim.get("customer_id"))
    customer_display_name = data.get("customer_display_name") or (str(customer_id) if customer_id else None)
    created_at = data.get("created_at") or data.get("closed_at") or data.get("stored_at") or now_text()
    note_parts = ["legacy_backfill"]
    if data.get("stored_reason"):
        note_parts.append(f"存單原因：{data.get('stored_reason')}")
    if data.get("stored_expected_time"):
        note_parts.append(f"預計恢復：{data.get('stored_expected_time')}")
    if data.get("note"):
        note_parts.append(str(data.get("note")))
    note = "｜".join(note_parts)

    web_id = find_existing_web_order(
        web,
        ticket_channel_id=str(channel_id),
        dispatch_message_id=str(dispatch_message_id) if dispatch_message_id else None,
        bot_order_no=str(bot_order_no) if bot_order_no else None,
    )

    values = {
        "bot_order_no": str(bot_order_no) if bot_order_no else None,
        "ticket_channel_id": str(channel_id),
        "dispatch_channel_id": str(dispatch_channel_id) if dispatch_channel_id else None,
        "dispatch_message_id": str(dispatch_message_id) if dispatch_message_id else None,
        "customer_discord_id": str(customer_id) if customer_id else None,
        "customer_display_name": customer_display_name,
        "category": category,
        "item": str(item),
        "quantity": quantity,
        "amount": amount,
        "payment_method": str(payment_method) if payment_method else None,
        "status": status,
        "note": note,
        "created_at": str(created_at) if created_at else now_text(),
        "updated_at": now_text(),
    }

    if dry_run:
        return web_id, web_id is None

    if web_id is None:
        cur = web.execute(
            """
            INSERT INTO web_orders (
                bot_order_no, ticket_channel_id, dispatch_channel_id, dispatch_message_id,
                customer_discord_id, customer_display_name, category, item, quantity, amount,
                payment_method, status, note, created_at, updated_at
            ) VALUES (
                :bot_order_no, :ticket_channel_id, :dispatch_channel_id, :dispatch_message_id,
                :customer_discord_id, :customer_display_name, :category, :item, :quantity, :amount,
                :payment_method, :status, :note, :created_at, :updated_at
            )
            """,
            values,
        )
        web_id = int(cur.lastrowid)
        return web_id, True

    values["id"] = web_id
    web.execute(
        """
        UPDATE web_orders
        SET bot_order_no = COALESCE(:bot_order_no, bot_order_no),
            ticket_channel_id = COALESCE(:ticket_channel_id, ticket_channel_id),
            dispatch_channel_id = COALESCE(:dispatch_channel_id, dispatch_channel_id),
            dispatch_message_id = COALESCE(:dispatch_message_id, dispatch_message_id),
            customer_discord_id = COALESCE(:customer_discord_id, customer_discord_id),
            customer_display_name = COALESCE(:customer_display_name, customer_display_name),
            category = :category,
            item = :item,
            quantity = :quantity,
            amount = CASE WHEN COALESCE(amount, 0) = 0 THEN :amount ELSE amount END,
            payment_method = COALESCE(:payment_method, payment_method),
            status = :status,
            note = COALESCE(note, :note),
            updated_at = :updated_at
        WHERE id = :id
        """,
        values,
    )
    return web_id, False


def add_assignments(web: sqlite3.Connection, order_id: int, worker_ids: list[str], *, role_type: str, dry_run: bool) -> int:
    inserted = 0
    for worker_id in sorted(set(worker_ids)):
        exists = web.execute(
            """
            SELECT id FROM order_assignments
            WHERE order_id = ? AND worker_discord_id = ? AND role_type = ?
            LIMIT 1
            """,
            (order_id, worker_id, role_type),
        ).fetchone()
        if exists:
            continue
        inserted += 1
        if dry_run:
            continue
        web.execute(
            """
            INSERT INTO order_assignments (
                order_id, worker_discord_id, worker_display_name, role_type,
                is_active, has_named_bonus, assigned_at
            ) VALUES (?, ?, ?, ?, 1, 0, ?)
            """,
            (order_id, worker_id, staff_name(web, worker_id), role_type, now_text()),
        )
    return inserted


def create_payouts_if_missing(web: sqlite3.Connection, order_id: int, *, dry_run: bool) -> tuple[int, int]:
    order = web.execute("SELECT amount, customer_service_discord_id, customer_service_display_name FROM web_orders WHERE id = ?", (order_id,)).fetchone()
    if not order:
        return 0, 0
    amount = int(order[0] or 0)
    if amount <= 0:
        return 0, 0

    worker_count_existing = web.execute("SELECT COUNT(*) FROM worker_payouts WHERE order_id = ?", (order_id,)).fetchone()[0]
    service_count_existing = web.execute("SELECT COUNT(*) FROM customer_service_payouts WHERE order_id = ?", (order_id,)).fetchone()[0]
    assignments = web.execute(
        """
        SELECT worker_discord_id, worker_display_name, has_named_bonus
        FROM order_assignments
        WHERE order_id = ? AND is_active = 1
        ORDER BY assigned_at, id
        """,
        (order_id,),
    ).fetchall()

    worker_inserted = 0
    service_inserted = 0

    if worker_count_existing == 0 and assignments:
        gross_share = amount // len(assignments)
        for worker_id, worker_name, has_named_bonus in assignments:
            base_payout = int(gross_share * 0.80)
            named_bonus = int(gross_share * 0.05) if has_named_bonus else 0
            final_payout = base_payout + named_bonus
            worker_inserted += 1
            if dry_run:
                continue
            web.execute(
                """
                INSERT INTO worker_payouts (
                    order_id, worker_discord_id, worker_display_name, gross_share,
                    base_rate, base_payout, named_bonus_rate, named_bonus_amount,
                    has_named_bonus, final_payout, payout_status, note, created_at, updated_at
                ) VALUES (?, ?, ?, ?, 0.80, ?, 0.05, ?, ?, ?, 'unpaid', 'legacy_backfill', ?, ?)
                """,
                (
                    order_id,
                    str(worker_id),
                    worker_name or str(worker_id),
                    gross_share,
                    base_payout,
                    named_bonus,
                    1 if has_named_bonus else 0,
                    final_payout,
                    now_text(),
                    now_text(),
                ),
            )

    if service_count_existing == 0:
        service_id = order[1]
        service_name = order[2]
        if not service_id:
            service_id = "legacy_unassigned_service"
            service_name = "舊資料未指定客服"
        service_inserted = 1
        if not dry_run:
            web.execute(
                """
                INSERT INTO customer_service_payouts (
                    order_id, customer_service_discord_id, customer_service_display_name,
                    rate, payout_amount, payout_status, note, created_at, updated_at
                ) VALUES (?, ?, ?, 0.05, ?, 'unpaid', 'legacy_backfill', ?, ?)
                """,
                (order_id, str(service_id), service_name or str(service_id), int(amount * 0.05), now_text(), now_text()),
            )

    return worker_inserted, service_inserted


def main() -> None:
    parser = argparse.ArgumentParser(description="Backfill legacy bot.db orders into web_dashboard.db")
    parser.add_argument("--bot-db", default=str(BOT_DB))
    parser.add_argument("--web-db", default=str(WEB_DB))
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    bot_db = Path(args.bot_db)
    web_db = Path(args.web_db)

    if not bot_db.exists():
        raise SystemExit(f"bot db not found: {bot_db}")
    if not web_db.exists():
        raise SystemExit(f"web db not found: {web_db}")

    bot = sqlite3.connect(bot_db)
    bot.row_factory = sqlite3.Row
    web = sqlite3.connect(web_db)
    web.row_factory = sqlite3.Row

    try:
        if not table_exists(bot, "orders"):
            raise SystemExit("bot.db missing orders table")
        if not table_exists(web, "web_orders"):
            raise SystemExit("web_dashboard.db missing web_orders table")

        order_cols = table_columns(bot, "orders")
        claim_cols = table_columns(bot, "claims") if table_exists(bot, "claims") else set()

        claims_by_message: dict[int, dict[str, Any]] = {}
        claims_by_source: dict[int, dict[str, Any]] = {}
        if claim_cols:
            for row in bot.execute("SELECT * FROM claims").fetchall():
                message_id, claim = normalize_claim(row, claim_cols)
                if message_id is not None:
                    claims_by_message[int(message_id)] = claim
                source_id = to_int(claim.get("source_channel_id"))
                if source_id is not None:
                    claims_by_source[int(source_id)] = claim

        total = inserted = updated = assignments_added = worker_payouts = service_payouts = 0
        status_counts: dict[str, int] = {}

        for row in bot.execute("SELECT * FROM orders").fetchall():
            total += 1
            channel_id, data = normalize_order(row, order_cols)
            dispatch_message_id = to_int(data.get("dispatch_message_id"))
            claim = None
            if dispatch_message_id is not None:
                claim = claims_by_message.get(dispatch_message_id)
            if claim is None:
                claim = claims_by_source.get(channel_id)

            status = normalize_status(data)
            status_counts[status] = status_counts.get(status, 0) + 1

            web_id, was_inserted = upsert_web_order(web, channel_id, data, claim, dry_run=args.dry_run)
            if was_inserted:
                inserted += 1
            else:
                updated += 1

            if web_id is None:
                continue

            if claim:
                worker_ids = id_list(claim.get("booster")) + id_list(claim.get("companion"))
                assignments_added += add_assignments(web, web_id, worker_ids, role_type="legacy", dry_run=args.dry_run)

            wp, sp = create_payouts_if_missing(web, web_id, dry_run=args.dry_run)
            worker_payouts += wp
            service_payouts += sp

        if args.dry_run:
            web.rollback()
        else:
            web.commit()

        print(f"dry_run={args.dry_run}")
        print(f"legacy_orders_total={total}")
        print(f"web_orders_inserted={inserted}")
        print(f"web_orders_updated={updated}")
        print(f"assignments_added={assignments_added}")
        print(f"worker_payouts_added={worker_payouts}")
        print(f"customer_service_payouts_added={service_payouts}")
        print("status_counts:")
        for status, count in sorted(status_counts.items()):
            print(f"  {status}: {count}")

    finally:
        bot.close()
        web.close()


if __name__ == "__main__":
    main()
