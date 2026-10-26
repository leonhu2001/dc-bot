from __future__ import annotations

from pathlib import Path
from typing import Any

from web.app.services import roulette_redraw_service
from web.app.services import roulette_service
from web.app.services.roulette_redraw_service import ensure_redraw_tables, get_redraw_state


def is_roulette_order(order: dict[str, Any]) -> bool:
    """Return whether an order was created as a roulette order.

    ``order_rule_key`` is mutable business metadata: a manager-created rule can
    later be renamed or repurposed. ``item`` is copied onto the order when the
    order is created. Requiring both means an older order cannot retroactively
    become roulette merely because its former rule key is reused.
    """
    rule_key = str(order.get("order_rule_key") or "").strip()
    item_snapshot = str(order.get("item") or "").strip()
    return (
        rule_key in roulette_service.ROULETTE_RULE_KEYS
        and roulette_service.ROULETTE_ITEM_LABEL in item_snapshot
    )


def install_identity_policy() -> None:
    """Make roulette_service draw/context checks use this one identity policy."""
    roulette_service._is_roulette_order = is_roulette_order


def list_admin_roulette_orders(*, limit: int = 100) -> list[dict[str, Any]]:
    """List only orders whose creation snapshot and rule metadata both match."""
    ensure_redraw_tables()
    safe_limit = max(1, min(int(limit or 100), 250))
    keys = tuple(sorted(roulette_service.ROULETTE_RULE_KEYS))
    placeholders = ",".join("?" for _ in keys)

    with roulette_redraw_service._connect() as conn:
        rows = conn.execute(
            f"""
            SELECT *
            FROM web_orders
            WHERE order_rule_key IN ({placeholders})
              AND item LIKE ?
            ORDER BY id DESC
            LIMIT ?
            """,
            (
                *keys,
                f"%{roulette_service.ROULETTE_ITEM_LABEL}%",
                safe_limit,
            ),
        ).fetchall()

    output: list[dict[str, Any]] = []
    for raw in rows:
        order = dict(raw)
        if not is_roulette_order(order):
            continue
        state = get_redraw_state(int(order["id"]))
        output.append(
            {
                "id": int(order["id"]),
                "order_no": str(order.get("bot_order_no") or f"WEB-{order['id']}"),
                "customer_name": str(
                    order.get("customer_display_name")
                    or order.get("customer_username")
                    or order.get("customer_discord_id")
                    or "未紀錄"
                ),
                "customer_discord_id": str(order.get("customer_discord_id") or ""),
                "status": str(order.get("status") or "").strip().lower(),
                "ticket_channel_id": str(order.get("ticket_channel_id") or ""),
                "final_draw": state["final_draw"],
                "remaining": state["remaining"],
                "total_granted": state["total_granted"],
                "attempt_count": state["attempt_count"],
                "history": state["history"],
                "grants": state["grants"],
            }
        )
    return output


def notify_ready_roulette_orders(
    *,
    db_file: str | Path | None = None,
    limit: int = 20,
) -> int:
    """Send ready prompts only to orders that satisfy the immutable identity rule."""
    roulette_service.ensure_roulette_feature(db_file)
    safe_limit = max(1, min(int(limit or 20), 100))
    keys = tuple(sorted(roulette_service.ROULETTE_RULE_KEYS))
    placeholders = ",".join("?" for _ in keys)

    with roulette_service._connect(db_file) as conn:
        rows = conn.execute(
            f"""
            SELECT
                id,
                customer_discord_id,
                bot_order_no,
                ticket_channel_id,
                item,
                status,
                order_rule_key
            FROM web_orders
            WHERE status IN ('active', 'stored')
              AND ticket_channel_id IS NOT NULL
              AND TRIM(CAST(ticket_channel_id AS TEXT)) <> ''
              AND order_rule_key IN ({placeholders})
              AND item LIKE ?
            ORDER BY id ASC
            LIMIT ?
            """,
            (
                *keys,
                f"%{roulette_service.ROULETTE_ITEM_LABEL}%",
                safe_limit,
            ),
        ).fetchall()

    sent = 0
    for raw_row in rows:
        order = dict(raw_row)
        if not is_roulette_order(order):
            continue
        order_id = int(order.get("id") or 0)
        if order_id <= 0:
            continue

        with roulette_service._connect(db_file) as conn:
            existing = conn.execute(
                """
                SELECT status
                FROM roulette_ready_notifications
                WHERE order_id = ?
                LIMIT 1
                """,
                (order_id,),
            ).fetchone()
            if existing is not None and str(existing["status"] or "") == "sent":
                continue

            conn.execute(
                """
                INSERT INTO roulette_ready_notifications (
                    order_id,
                    status,
                    attempts,
                    updated_at
                )
                VALUES (?, 'pending', 0, ?)
                ON CONFLICT(order_id)
                DO UPDATE SET
                    attempts = roulette_ready_notifications.attempts + 1,
                    updated_at = excluded.updated_at
                """,
                (order_id, roulette_service._now_iso()),
            )
            conn.commit()

        try:
            message_id = roulette_service._send_ready_notification(order)
        except Exception as exc:
            with roulette_service._connect(db_file) as conn:
                conn.execute(
                    """
                    UPDATE roulette_ready_notifications
                    SET status = 'failed',
                        last_error = ?,
                        updated_at = ?
                    WHERE order_id = ?
                    """,
                    (
                        f"{type(exc).__name__}: {exc}"[:1000],
                        roulette_service._now_iso(),
                        order_id,
                    ),
                )
                conn.commit()
            continue

        with roulette_service._connect(db_file) as conn:
            conn.execute(
                """
                UPDATE roulette_ready_notifications
                SET status = 'sent',
                    message_id = ?,
                    notified_at = ?,
                    last_error = NULL,
                    updated_at = ?
                WHERE order_id = ?
                """,
                (
                    message_id,
                    roulette_service._now_iso(),
                    roulette_service._now_iso(),
                    order_id,
                ),
            )
            conn.commit()
        sent += 1

    return sent
