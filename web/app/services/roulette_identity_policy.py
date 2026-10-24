from __future__ import annotations

from pathlib import Path
from typing import Any

from services.order_rule_store import load_custom_rule_definitions
from services.order_rules import ORDER_RULES
from web.app.services import roulette_redraw_service, roulette_service


# This key belongs to the old 2026-10-07 fun order「說都不會話」.  The first
# roulette implementation accidentally adopted it as the roulette identity.
# Keep the exclusion explicit so historical rows can never be reclassified.
_MISIDENTIFIED_RULE_KEYS = {"admin_delta_desktop_fun_20261007053129_91eb"}
_ROULETTE_LABEL = "俄羅斯輪盤"


def _clean_label(value: Any) -> str:
    return "".join(str(value or "").split()).casefold()


def _live_roulette_rule_keys(
    db_file: str | Path | None = None,
) -> set[str]:
    """Resolve roulette products from the live catalog instead of a dated key."""
    keys: set[str] = {str(roulette_service.LEGACY_ROULETTE_RULE_KEY)}
    wanted = _clean_label(_ROULETTE_LABEL)

    for rule_key, rule in ORDER_RULES.items():
        if _clean_label(getattr(rule, "label", "")) == wanted:
            keys.add(str(rule_key))

    for rule_key, definition in load_custom_rule_definitions(db_file).items():
        payload = definition.get("payload") or {}
        label = payload.get("label") or payload.get("name") or ""
        if _clean_label(label) == wanted:
            keys.add(str(rule_key))

    keys.difference_update(_MISIDENTIFIED_RULE_KEYS)
    return {key for key in keys if key}


def _is_roulette_order(order: dict[str, Any]) -> bool:
    rule_key = str(order.get("order_rule_key") or "").strip()
    if rule_key in _MISIDENTIFIED_RULE_KEYS:
        return False
    if rule_key and rule_key in _live_roulette_rule_keys():
        return True

    # Historical rows may not have kept their rule key.  Only an exact item
    # name is accepted as fallback; substring matching caused unrelated fun
    # orders to leak into roulette management.
    return _clean_label(order.get("item")) == _clean_label(_ROULETTE_LABEL)


def _candidate_where(
    *,
    db_file: str | Path | None = None,
) -> tuple[str, list[Any]]:
    keys = sorted(_live_roulette_rule_keys(db_file))
    clauses = ["TRIM(COALESCE(item, '')) = ?"]
    params: list[Any] = [_ROULETTE_LABEL]
    if keys:
        placeholders = ",".join("?" for _ in keys)
        clauses.append(f"order_rule_key IN ({placeholders})")
        params.extend(keys)
    return "(" + " OR ".join(clauses) + ")", params


def _list_admin_roulette_orders(
    *,
    db_file: str | Path | None = None,
    limit: int = 100,
) -> list[dict[str, Any]]:
    roulette_redraw_service.ensure_redraw_tables(db_file)
    safe_limit = max(1, min(int(limit or 100), 250))
    where_sql, params = _candidate_where(db_file=db_file)

    with roulette_redraw_service._connect(db_file) as conn:
        rows = conn.execute(
            f"""
            SELECT *
            FROM web_orders
            WHERE {where_sql}
            ORDER BY id DESC
            LIMIT ?
            """,
            [*params, safe_limit],
        ).fetchall()

    output: list[dict[str, Any]] = []
    for raw in rows:
        order = dict(raw)
        if not _is_roulette_order(order):
            continue
        state = roulette_redraw_service.get_redraw_state(
            int(order["id"]),
            db_file=db_file,
        )
        output.append(
            {
                "id": int(order["id"]),
                "order_no": str(
                    order.get("bot_order_no") or f"WEB-{order['id']}"
                ),
                "customer_name": str(
                    order.get("customer_display_name")
                    or order.get("customer_username")
                    or order.get("customer_discord_id")
                    or "未紀錄"
                ),
                "customer_discord_id": str(
                    order.get("customer_discord_id") or ""
                ),
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


def _notify_ready_roulette_orders(
    *,
    db_file: str | Path | None = None,
    limit: int = 20,
) -> int:
    roulette_service.ensure_roulette_feature(db_file)
    safe_limit = max(1, min(int(limit or 20), 100))
    where_sql, params = _candidate_where(db_file=db_file)

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
              AND {where_sql}
            ORDER BY id ASC
            LIMIT ?
            """,
            [*params, safe_limit],
        ).fetchall()

    sent = 0
    for raw_row in rows:
        order = dict(raw_row)
        if not _is_roulette_order(order):
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
                    order_id, status, attempts, updated_at
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
                    SET status = 'failed', last_error = ?, updated_at = ?
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
            now = roulette_service._now_iso()
            conn.execute(
                """
                UPDATE roulette_ready_notifications
                SET status = 'sent', message_id = ?, notified_at = ?,
                    last_error = NULL, updated_at = ?
                WHERE order_id = ?
                """,
                (message_id, now, now, order_id),
            )
            conn.commit()
        sent += 1

    return sent


def install_roulette_identity_policy() -> None:
    """Install dynamic roulette identity without rewriting exported constants.

    ``ROULETTE_RULE_KEY`` and ``LEGACY_ROULETTE_RULE_KEY`` are public module
    constants used by migrations and tests. Reassigning one to the other at
    runtime makes two distinct historical identities collapse into the same key
    and can trigger unique-key collisions. Runtime recognition is handled by the
    dynamic resolver below instead.
    """
    roulette_service._is_roulette_order = _is_roulette_order
    roulette_service.notify_ready_roulette_orders = _notify_ready_roulette_orders
    roulette_redraw_service.list_admin_roulette_orders = (
        _list_admin_roulette_orders
    )


__all__ = [
    "install_roulette_identity_policy",
]
