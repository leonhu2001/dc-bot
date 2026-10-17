from __future__ import annotations

import json
import sqlite3

from sqlalchemy import text

from services import promotion_benefits as promotion


def reserve_in_session(
    db,
    *,
    selection_id: int | str,
    customer_discord_id: str | int,
    order_id: int,
) -> None:
    issued_id = promotion.decode_selection_id(selection_id)
    if issued_id is None:
        raise ValueError("福利券識別碼錯誤。")
    result = db.execute(
        text(
            """
            UPDATE promotion_issued_benefits
            SET status='reserved', reserved_order_id=:order_id
            WHERE id=:issued_id
              AND customer_discord_id=:customer_id
              AND status='active'
              AND remaining_uses > 0
              AND (expires_at IS NULL OR expires_at > :now)
            """
        ),
        {
            "order_id": int(order_id),
            "issued_id": int(issued_id),
            "customer_id": str(customer_discord_id),
            "now": promotion._now_text(),
        },
    )
    if int(result.rowcount or 0) != 1:
        raise ValueError("這張優惠福利已被使用、保留、過期，或不屬於此會員。")


def release_for_order(order_id: int) -> int:
    promotion.ensure_promotion_benefit_tables()
    now = promotion._now_text()
    with sqlite3.connect(promotion.DEFAULT_WEB_DB, timeout=15) as conn:
        result = conn.execute(
            """
            UPDATE promotion_issued_benefits
            SET status=CASE
                    WHEN expires_at IS NOT NULL AND expires_at <= ? THEN 'expired'
                    ELSE 'active'
                END,
                reserved_order_id=NULL
            WHERE reserved_order_id=? AND status='reserved'
            """,
            (now, int(order_id)),
        )
        conn.commit()
        return int(result.rowcount or 0)


def _order_discount_amount(conn: sqlite3.Connection, order_id: int, issued_id: int) -> int:
    try:
        row = conn.execute(
            "SELECT price_snapshot_json FROM web_orders WHERE id=? LIMIT 1",
            (int(order_id),),
        ).fetchone()
    except sqlite3.Error:
        return 0
    if row is None:
        return 0
    try:
        snapshot = json.loads(str(row[0] or "{}"))
    except Exception:
        return 0
    if not isinstance(snapshot, dict):
        return 0
    preview = snapshot.get("preview") if isinstance(snapshot.get("preview"), dict) else snapshot
    finance = preview.get("finance") if isinstance(preview, dict) and isinstance(preview.get("finance"), dict) else {}
    try:
        stored_id = int(finance.get("promotion_benefit_id") or 0)
    except (TypeError, ValueError):
        stored_id = 0
    if stored_id != int(issued_id):
        return 0
    try:
        return max(0, int(finance.get("promotion_discount_amount") or 0))
    except (TypeError, ValueError):
        return 0


def redeem_for_order(order_id: int) -> int:
    """Consume reserved promotion benefits after a successfully closed order.

    One-shot coupons are consumed once. Fixed-cash balance coupons deduct only
    the amount actually used by this order; their remaining balance survives as
    long as both balance and usage count remain positive.
    """
    promotion.ensure_promotion_benefit_tables()
    now = promotion._now_text()
    with sqlite3.connect(promotion.DEFAULT_WEB_DB, timeout=15) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            """
            SELECT * FROM promotion_issued_benefits
            WHERE reserved_order_id=? AND status='reserved'
            """,
            (int(order_id),),
        ).fetchall()
        changed = 0
        for raw in rows:
            row = dict(raw)
            rules = promotion._json_load(row.get("rules_snapshot_json"), {})
            remaining_uses = max(0, int(row.get("remaining_uses") or 0) - 1)
            remaining_value = row.get("remaining_value")

            if (
                str(rules.get("consume_mode") or "one_shot") == "balance"
                and str(rules.get("effect_kind") or "") == promotion.EFFECT_FIXED_CASH
            ):
                used = _order_discount_amount(conn, int(order_id), int(row["id"]))
                current_balance = max(0.0, float(remaining_value or 0))
                remaining_value = max(0.0, current_balance - used)
                still_available = remaining_uses > 0 and remaining_value > 0.0001
            else:
                still_available = remaining_uses > 0

            status = promotion.ACTIVE if still_available else promotion.REDEEMED
            conn.execute(
                """
                UPDATE promotion_issued_benefits
                SET status=?, remaining_uses=?, remaining_value=?,
                    reserved_order_id=NULL, redeemed_order_id=?, redeemed_at=?
                WHERE id=? AND status='reserved'
                """,
                (
                    status,
                    remaining_uses,
                    remaining_value,
                    int(order_id),
                    now,
                    int(row["id"]),
                ),
            )
            changed += 1
        conn.commit()
        return changed
