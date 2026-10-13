from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path

from services.worker_tips import (
    configure_worker_tip_store,
    ensure_worker_tip_tables,
)


def _root_dir() -> Path:
    return Path(__file__).resolve().parents[1]

def _web_db_path() -> Path:
    return _root_dir() / "web_dashboard.db"

def _now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")

def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(_web_db_path(), timeout=15)
    conn.row_factory = sqlite3.Row
    return conn

def ensure_review_tables() -> None:
    # Review/favorite/tip tables are one operational schema group. Keep the
    # historical one-call ensure contract while worker_tips owns its own DDL.
    configure_worker_tip_store(db_path_provider=_web_db_path)
    ensure_worker_tip_tables()
    conn = _connect()
    try:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS order_reviews (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                order_id INTEGER,
                ticket_channel_id TEXT,
                dispatch_message_id TEXT,
                receipt_id TEXT,
                staff_discord_id TEXT NOT NULL,
                staff_display_name TEXT,
                customer_discord_id TEXT,
                customer_display_name TEXT,
                customer_name_public INTEGER NOT NULL DEFAULT 0,
                rating INTEGER NOT NULL,
                comment TEXT,
                service_category TEXT,
                service_item TEXT,
                order_content TEXT,
                is_public INTEGER NOT NULL DEFAULT 1,
                is_hidden INTEGER NOT NULL DEFAULT 0,
                source TEXT NOT NULL DEFAULT 'discord',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_order_reviews_order_id
                ON order_reviews(order_id);

            CREATE INDEX IF NOT EXISTS idx_order_reviews_staff
                ON order_reviews(staff_discord_id);

            CREATE INDEX IF NOT EXISTS idx_order_reviews_ticket
                ON order_reviews(ticket_channel_id);

            CREATE TABLE IF NOT EXISTS order_review_skips (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                order_id INTEGER,
                ticket_channel_id TEXT,
                dispatch_message_id TEXT,
                receipt_id TEXT,
                customer_discord_id TEXT,
                staff_discord_id TEXT,
                skipped_all INTEGER NOT NULL DEFAULT 0,
                source TEXT NOT NULL DEFAULT 'discord',
                created_at TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_order_review_skips_order_id
                ON order_review_skips(order_id);

            CREATE INDEX IF NOT EXISTS idx_order_review_skips_ticket
                ON order_review_skips(ticket_channel_id);

            CREATE TABLE IF NOT EXISTS staff_favorites (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                customer_discord_id TEXT NOT NULL,
                staff_discord_id TEXT NOT NULL,
                staff_display_name TEXT,
                source TEXT NOT NULL DEFAULT 'post_close',
                created_at TEXT NOT NULL
            );

            CREATE UNIQUE INDEX IF NOT EXISTS idx_staff_favorites_unique
                ON staff_favorites(customer_discord_id, staff_discord_id);

            CREATE INDEX IF NOT EXISTS idx_staff_favorites_customer
                ON staff_favorites(customer_discord_id);

            CREATE INDEX IF NOT EXISTS idx_staff_favorites_staff
                ON staff_favorites(staff_discord_id);
            """
        )
        columns = {
            str(row["name"])
            for row in conn.execute(
                "PRAGMA table_info(order_reviews)"
            ).fetchall()
        }

        if "customer_display_name" not in columns:
            conn.execute(
                "ALTER TABLE order_reviews "
                "ADD COLUMN customer_display_name TEXT"
            )

        if "customer_name_public" not in columns:
            conn.execute(
                "ALTER TABLE order_reviews "
                "ADD COLUMN customer_name_public INTEGER NOT NULL DEFAULT 0"
            )

        conn.execute(
            """
            UPDATE order_reviews
            SET customer_name_public = 0
            WHERE customer_name_public IS NULL
            """
        )

        conn.commit()
    finally:
        conn.close()

def _find_order(ticket_channel_id: int | str | None, dispatch_message_id: int | str | None = None) -> sqlite3.Row | None:
    ensure_review_tables()
    conn = _connect()
    try:
        params: list[str] = []
        where: list[str] = []

        if ticket_channel_id is not None:
            where.append("ticket_channel_id = ?")
            params.append(str(ticket_channel_id))

        if dispatch_message_id is not None:
            where.append("dispatch_message_id = ?")
            params.append(str(dispatch_message_id))

        if not where:
            return None

        row = conn.execute(
            f"""
            SELECT *
            FROM web_orders
            WHERE {" OR ".join(where)}
            ORDER BY id DESC
            LIMIT 1
            """,
            params,
        ).fetchone()
        return row
    finally:
        conn.close()

def get_review_targets(ticket_channel_id: int | str | None, dispatch_message_id: int | str | None = None) -> tuple[sqlite3.Row | None, list[dict]]:
    order = _find_order(ticket_channel_id, dispatch_message_id)
    if order is None:
        return None, []

    conn = _connect()
    try:
        rows = conn.execute(
            """
            SELECT worker_discord_id, worker_display_name, role_type
            FROM order_assignments
            WHERE order_id = ?
              AND COALESCE(is_active, 1) = 1
            ORDER BY assigned_at ASC, id ASC
            """,
            (order["id"],),
        ).fetchall()

        targets = []
        seen = set()

        for row in rows:
            staff_id = str(row["worker_discord_id"] or "").strip()
            if not staff_id or staff_id in seen:
                continue

            seen.add(staff_id)
            targets.append(
                {
                    "staff_id": staff_id,
                    "display_name": str(row["worker_display_name"] or staff_id),
                    "role_type": str(row["role_type"] or ""),
                }
            )

        return order, targets
    finally:
        conn.close()

def _existing_reviews(order_id: int | None, ticket_channel_id: int | str | None) -> dict[str, sqlite3.Row]:
    ensure_review_tables()
    conn = _connect()
    try:
        if order_id is not None:
            rows = conn.execute(
                """
                SELECT *
                FROM order_reviews
                WHERE order_id = ?
                ORDER BY id DESC
                """,
                (order_id,),
            ).fetchall()
        else:
            rows = conn.execute(
                """
                SELECT *
                FROM order_reviews
                WHERE ticket_channel_id = ?
                ORDER BY id DESC
                """,
                (str(ticket_channel_id),),
            ).fetchall()

        result = {}
        for row in rows:
            staff_id = str(row["staff_discord_id"] or "")
            if staff_id and staff_id not in result:
                result[staff_id] = row
        return result
    finally:
        conn.close()

def _has_skipped_all(order_id: int | None, ticket_channel_id: int | str | None) -> bool:
    ensure_review_tables()
    conn = _connect()
    try:
        if order_id is not None:
            row = conn.execute(
                """
                SELECT id
                FROM order_review_skips
                WHERE order_id = ?
                  AND skipped_all = 1
                LIMIT 1
                """,
                (order_id,),
            ).fetchone()
        else:
            row = conn.execute(
                """
                SELECT id
                FROM order_review_skips
                WHERE ticket_channel_id = ?
                  AND skipped_all = 1
                LIMIT 1
                """,
                (str(ticket_channel_id),),
            ).fetchone()

        return row is not None
    finally:
        conn.close()

def build_review_status(ticket_channel_id: int | str, customer_id: int) -> tuple[sqlite3.Row | None, list[dict], bool]:
    order, targets = get_review_targets(ticket_channel_id)
    order_id = int(order["id"]) if order is not None else None
    existing = _existing_reviews(order_id, ticket_channel_id)
    skipped_all = _has_skipped_all(order_id, ticket_channel_id)

    enriched = []
    for target in targets:
        row = existing.get(str(target["staff_id"]))
        item = dict(target)
        item["reviewed"] = row is not None
        item["rating"] = int(row["rating"]) if row is not None else None
        item["comment"] = str(row["comment"] or "") if row is not None else ""
        item["customer_name_public"] = (
            bool(row["customer_name_public"])
            if row is not None and "customer_name_public" in row.keys()
            else False
        )
        item["skipped"] = skipped_all
        enriched.append(item)

    return order, enriched, skipped_all

def record_review_skip(
    *,
    order: sqlite3.Row | None,
    ticket_channel_id: int | str | None,
    dispatch_message_id: int | str | None,
    customer_id: int,
    targets: list[dict],
) -> None:
    ensure_review_tables()
    now = _now_iso()
    order_id = int(order["id"]) if order is not None else None
    receipt_id = str(order["bot_order_no"] or "") if order is not None else ""

    conn = _connect()
    try:
        existing = None
        if order_id is not None:
            existing = conn.execute(
                """
                SELECT id
                FROM order_review_skips
                WHERE order_id = ?
                  AND skipped_all = 1
                LIMIT 1
                """,
                (order_id,),
            ).fetchone()
        elif ticket_channel_id is not None:
            existing = conn.execute(
                """
                SELECT id
                FROM order_review_skips
                WHERE ticket_channel_id = ?
                  AND skipped_all = 1
                LIMIT 1
                """,
                (str(ticket_channel_id),),
            ).fetchone()

        if existing is None:
            conn.execute(
                """
                INSERT INTO order_review_skips (
                    order_id,
                    ticket_channel_id,
                    dispatch_message_id,
                    receipt_id,
                    customer_discord_id,
                    staff_discord_id,
                    skipped_all,
                    source,
                    created_at
                )
                VALUES (?, ?, ?, ?, ?, NULL, 1, 'discord', ?)
                """,
                (
                    order_id,
                    str(ticket_channel_id or ""),
                    str(dispatch_message_id or (order["dispatch_message_id"] if order is not None else "") or ""),
                    receipt_id,
                    str(customer_id),
                    now,
                ),
            )

        for target in targets:
            staff_id = str(target.get("staff_id") or "")
            if not staff_id:
                continue

            exists = None
            if order_id is not None:
                exists = conn.execute(
                    """
                    SELECT id
                    FROM order_review_skips
                    WHERE order_id = ?
                      AND staff_discord_id = ?
                    LIMIT 1
                    """,
                    (order_id, staff_id),
                ).fetchone()

            if exists is None:
                conn.execute(
                    """
                    INSERT INTO order_review_skips (
                        order_id,
                        ticket_channel_id,
                        dispatch_message_id,
                        receipt_id,
                        customer_discord_id,
                        staff_discord_id,
                        skipped_all,
                        source,
                        created_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, 0, 'discord', ?)
                    """,
                    (
                        order_id,
                        str(ticket_channel_id or ""),
                        str(dispatch_message_id or (order["dispatch_message_id"] if order is not None else "") or ""),
                        receipt_id,
                        str(customer_id),
                        staff_id,
                        now,
                    ),
                )

        conn.commit()
    finally:
        conn.close()

def record_member_review(
    *,
    order: sqlite3.Row | None,
    ticket_channel_id: int | str,
    staff_id: str,
    staff_display_name: str,
    customer_id: int,
    customer_display_name: str,
    customer_name_public: bool,
    rating: int,
    comment: str,
    order_content: str | None,
) -> tuple[bool, str]:
    ensure_review_tables()
    now = _now_iso()
    order_id = int(order["id"]) if order is not None else None

    conn = _connect()
    try:
        if order_id is not None:
            existing = conn.execute(
                """
                SELECT id
                FROM order_reviews
                WHERE order_id = ?
                  AND staff_discord_id = ?
                LIMIT 1
                """,
                (order_id, str(staff_id)),
            ).fetchone()
        else:
            existing = conn.execute(
                """
                SELECT id
                FROM order_reviews
                WHERE ticket_channel_id = ?
                  AND staff_discord_id = ?
                LIMIT 1
                """,
                (str(ticket_channel_id), str(staff_id)),
            ).fetchone()

        if existing is not None:
            return False, "這位成員已經評價過了，不能重複評價。"

        conn.execute(
            """
            INSERT INTO order_reviews (
                order_id,
                ticket_channel_id,
                dispatch_message_id,
                receipt_id,
                staff_discord_id,
                staff_display_name,
                customer_discord_id,
                customer_display_name,
                customer_name_public,
                rating,
                comment,
                service_category,
                service_item,
                order_content,
                is_public,
                is_hidden,
                source,
                created_at,
                updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, 0, 'discord', ?, ?)
            """,
            (
                order_id,
                str(ticket_channel_id),
                str(order["dispatch_message_id"] or "") if order is not None else "",
                str(order["bot_order_no"] or "") if order is not None else "",
                str(staff_id),
                str(staff_display_name or staff_id),
                str(customer_id),
                str(customer_display_name or "").strip(),
                1 if customer_name_public else 0,
                int(rating),
                str(comment or "").strip(),
                str(order["category"] or "") if order is not None else "",
                str(order["item"] or "") if order is not None else "",
                str(order_content or ""),
                now,
                now,
            ),
        )
        conn.commit()
        return True, "評價已送出。"
    finally:
        conn.close()

def get_staff_favorites(customer_id: int | str, staff_ids: list[str] | None = None) -> set[str]:
    ensure_review_tables()
    conn = _connect()
    try:
        params: list[str] = [str(customer_id)]
        where = "customer_discord_id = ?"

        if staff_ids:
            placeholders = ",".join("?" for _ in staff_ids)
            where += f" AND staff_discord_id IN ({placeholders})"
            params.extend(str(item) for item in staff_ids)

        rows = conn.execute(
            f"""
            SELECT staff_discord_id
            FROM staff_favorites
            WHERE {where}
            """,
            params,
        ).fetchall()

        return {str(row["staff_discord_id"]) for row in rows}
    finally:
        conn.close()

def _get_post_close_tip_rows(ticket_channel_id: int | str) -> list[sqlite3.Row]:
    ensure_review_tables()
    conn = _connect()
    try:
        return conn.execute(
            """
            SELECT
                worker_discord_id,
                worker_display_name,
                amount,
                payment_method,
                payment_status
            FROM worker_tips
            WHERE ticket_channel_id = ?
              AND payment_status <> 'cancelled'
            ORDER BY id ASC
            """,
            (str(ticket_channel_id),),
        ).fetchall()
    finally:
        conn.close()

def get_post_close_status(ticket_channel_id: int | str, customer_id: int | str) -> dict:
    _order, targets, skipped_all = build_review_status(
        ticket_channel_id,
        int(customer_id),
    )

    target_ids = [
        str(item.get("staff_id") or "")
        for item in targets
        if str(item.get("staff_id") or "")
    ]
    favorite_ids = get_staff_favorites(customer_id, target_ids)
    tip_rows = _get_post_close_tip_rows(ticket_channel_id)

    paid_total = 0
    pending_total = 0
    for row in tip_rows:
        amount = int(row["amount"] or 0)
        status = str(row["payment_status"] or "")
        if status == "paid":
            paid_total += amount
        elif status in {"pending", "pending_review"}:
            pending_total += amount

    return {
        "targets": targets,
        "skipped_all": bool(skipped_all),
        "favorite_ids": favorite_ids,
        "tip_rows": tip_rows,
        "tip_paid_total": paid_total,
        "tip_pending_total": pending_total,
    }

def add_staff_favorite(
    *,
    customer_id: int | str,
    staff_id: int | str,
    staff_display_name: str | None = None,
    source: str = "post_close",
) -> bool:
    ensure_review_tables()
    now = _now_iso()
    conn = _connect()
    try:
        before = conn.total_changes
        conn.execute(
            """
            INSERT OR IGNORE INTO staff_favorites (
                customer_discord_id,
                staff_discord_id,
                staff_display_name,
                source,
                created_at
            )
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                str(customer_id),
                str(staff_id),
                str(staff_display_name or staff_id),
                str(source or "post_close"),
                now,
            ),
        )
        conn.commit()
        return conn.total_changes > before
    finally:
        conn.close()

