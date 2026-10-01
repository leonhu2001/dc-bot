from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

OPEN_ORDER_STATUSES = {
    "pending_cs_dispatch",
    "waiting_acceptance",
    "accepted_pending_pay",
    "active",
    "stored",
}

ORDER_STATUS_LABELS = {
    "pending_cs_dispatch": "等待客服確認",
    "waiting_acceptance": "等待接單",
    "accepted_pending_pay": "等待付款",
    "active": "進行中",
    "stored": "存單中",
    "closed": "已完成",
    "cancelled": "已取消",
    "canceled": "已取消",
}

PAYMENT_STATUS_LABELS = {
    "pending_review": "付款審核中",
    "approved_pending_apply": "付款已核准，套用中",
    "applied": "付款已完成",
    "rejected": "付款未通過",
    "apply_error": "付款套用異常",
}

SUPPORT_STATUS_LABELS = {
    "open": "等待客服接手",
    "claimed": "客服處理中",
    "resolved": "已完成",
    "cancelled": "已結束",
}


def _db_path(db_file: str | Path | None = None) -> Path:
    if db_file is not None:
        return Path(db_file)
    return Path(__file__).resolve().parents[3] / "web_dashboard.db"


def _connect(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(path, timeout=15)
    conn.row_factory = sqlite3.Row
    return conn


def _table_exists(conn: sqlite3.Connection, name: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=? LIMIT 1",
        (str(name),),
    ).fetchone()
    return row is not None


def _format_amount(value: Any) -> str:
    try:
        amount = int(value or 0)
    except (TypeError, ValueError):
        amount = 0
    return f"{amount:,}T"


def _format_time(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return "-"
    return text.replace("T", " ")[:16]


def _ticket_url(guild_id: str | int | None, ticket_channel_id: Any) -> str | None:
    guild = str(guild_id or "").strip()
    channel = str(ticket_channel_id or "").strip()
    if not guild or not channel:
        return None
    return f"https://discord.com/channels/{guild}/{channel}"


def _payment_by_order(
    conn: sqlite3.Connection,
    order_ids: list[int],
) -> dict[int, dict[str, Any]]:
    if not order_ids or not _table_exists(conn, "payment_reviews"):
        return {}

    placeholders = ",".join("?" for _ in order_ids)
    rows = conn.execute(
        f"""
        SELECT *
        FROM payment_reviews
        WHERE source_type = 'order'
          AND source_id IN ({placeholders})
        ORDER BY id DESC
        """,
        [str(order_id) for order_id in order_ids],
    ).fetchall()

    result: dict[int, dict[str, Any]] = {}
    for row in rows:
        try:
            order_id = int(str(row["source_id"]))
        except (TypeError, ValueError):
            continue

        if order_id in result:
            continue

        data = dict(row)
        status = str(data.get("status") or "").strip().lower()
        result[order_id] = {
            "id": data.get("id"),
            "review_no": str(data.get("review_no") or ""),
            "status": status,
            "status_label": PAYMENT_STATUS_LABELS.get(status, status or "未送審"),
            "payment_method": str(data.get("payment_method") or ""),
            "amount_text": _format_amount(data.get("amount")),
            "rejected_reason": str(data.get("rejected_reason") or "").strip(),
            "created_at": _format_time(data.get("created_at")),
            "updated_at": _format_time(data.get("updated_at")),
        }

    return result


def _support_by_ticket(
    conn: sqlite3.Connection,
    ticket_channel_ids: list[str],
) -> dict[str, dict[str, Any]]:
    if not ticket_channel_ids or not _table_exists(conn, "support_calls"):
        return {}

    placeholders = ",".join("?" for _ in ticket_channel_ids)
    rows = conn.execute(
        f"""
        SELECT *
        FROM support_calls
        WHERE ticket_channel_id IN ({placeholders})
        ORDER BY id DESC
        """,
        ticket_channel_ids,
    ).fetchall()

    result: dict[str, dict[str, Any]] = {}
    for row in rows:
        ticket_id = str(row["ticket_channel_id"] or "").strip()
        if not ticket_id or ticket_id in result:
            continue

        data = dict(row)
        status = str(data.get("status") or "").strip().lower()
        result[ticket_id] = {
            "id": data.get("id"),
            "status": status,
            "status_label": SUPPORT_STATUS_LABELS.get(status, status or "未知"),
            "called_at": _format_time(data.get("called_at")),
            "claimed_at": _format_time(data.get("claimed_at")),
            "claimed_by_display_name": str(
                data.get("claimed_by_display_name")
                or data.get("claimed_by_discord_id")
                or ""
            ).strip(),
            "resolved_at": _format_time(data.get("resolved_at")),
        }

    return result


def _assignments_by_order(
    conn: sqlite3.Connection,
    order_ids: list[int],
) -> dict[int, list[dict[str, Any]]]:
    if not order_ids or not _table_exists(conn, "order_assignments"):
        return {}

    placeholders = ",".join("?" for _ in order_ids)
    rows = conn.execute(
        f"""
        SELECT
            order_id,
            worker_discord_id,
            worker_display_name,
            role_type,
            is_active,
            assigned_at
        FROM order_assignments
        WHERE order_id IN ({placeholders})
        ORDER BY id ASC
        """,
        order_ids,
    ).fetchall()

    result: dict[int, list[dict[str, Any]]] = {}
    for row in rows:
        order_id = int(row["order_id"])
        result.setdefault(order_id, []).append(
            {
                "worker_discord_id": str(row["worker_discord_id"] or ""),
                "worker_display_name": str(
                    row["worker_display_name"]
                    or row["worker_discord_id"]
                    or "服務人員"
                ),
                "role_type": str(row["role_type"] or ""),
                "is_active": bool(row["is_active"]),
                "assigned_at": _format_time(row["assigned_at"]),
            }
        )

    return result


def _order_to_public(
    row: sqlite3.Row | dict[str, Any],
    *,
    payment: dict[str, Any] | None,
    support: dict[str, Any] | None,
    assignments: list[dict[str, Any]],
    guild_id: str | int | None,
) -> dict[str, Any]:
    data = dict(row)
    order_id = int(data.get("id") or 0)
    status = str(data.get("status") or "").strip().lower()
    amount = data.get("customer_pay_amount")
    if amount is None:
        amount = data.get("amount")

    order_no = (
        data.get("bot_order_no")
        or (f"WEB-{order_id}" if order_id else "—")
    )

    ticket_channel_id = str(data.get("ticket_channel_id") or "").strip()

    return {
        "id": order_id,
        "order_no": str(order_no),
        "category": str(data.get("category") or ""),
        "item": str(data.get("item") or "訂單"),
        "quantity": int(data.get("quantity") or 1),
        "amount": int(amount or 0),
        "amount_text": _format_amount(amount),
        "payment_method": str(data.get("payment_method") or "待付款"),
        "status": status,
        "status_label": ORDER_STATUS_LABELS.get(status, status or "未知"),
        "is_open": status in OPEN_ORDER_STATUSES,
        "is_closed": status == "closed",
        "created_at": _format_time(data.get("created_at")),
        "updated_at": _format_time(data.get("updated_at")),
        "ticket_channel_id": ticket_channel_id,
        "ticket_url": _ticket_url(guild_id, ticket_channel_id),
        "payment": payment,
        "support": support,
        "assignments": assignments,
        "active_assignments": [
            item for item in assignments if item.get("is_active")
        ],
        "can_repeat": status in {"closed", "cancelled", "canceled"},
    }


def list_customer_orders(
    customer_id: str | int,
    *,
    guild_id: str | int | None = None,
    limit: int = 100,
    db_file: str | Path | None = None,
) -> list[dict[str, Any]]:
    customer_id = str(customer_id or "").strip()
    if not customer_id:
        return []

    path = _db_path(db_file)
    if not path.exists():
        return []

    safe_limit = max(1, min(int(limit or 100), 500))

    with _connect(path) as conn:
        if not _table_exists(conn, "web_orders"):
            return []

        rows = conn.execute(
            """
            SELECT *
            FROM web_orders
            WHERE CAST(customer_discord_id AS TEXT) = ?
            ORDER BY id DESC
            LIMIT ?
            """,
            (customer_id, safe_limit),
        ).fetchall()

        order_ids = [int(row["id"]) for row in rows]
        ticket_ids = [
            str(row["ticket_channel_id"])
            for row in rows
            if str(row["ticket_channel_id"] or "").strip()
        ]

        payments = _payment_by_order(conn, order_ids)
        supports = _support_by_ticket(conn, ticket_ids)
        assignments = _assignments_by_order(conn, order_ids)

        return [
            _order_to_public(
                row,
                payment=payments.get(int(row["id"])),
                support=supports.get(str(row["ticket_channel_id"] or "")),
                assignments=assignments.get(int(row["id"]), []),
                guild_id=guild_id,
            )
            for row in rows
        ]


def get_customer_order(
    customer_id: str | int,
    order_id: int,
    *,
    guild_id: str | int | None = None,
    db_file: str | Path | None = None,
) -> dict[str, Any] | None:
    customer_id = str(customer_id or "").strip()
    if not customer_id:
        return None

    path = _db_path(db_file)
    if not path.exists():
        return None

    with _connect(path) as conn:
        if not _table_exists(conn, "web_orders"):
            return None

        row = conn.execute(
            """
            SELECT *
            FROM web_orders
            WHERE id = ?
              AND CAST(customer_discord_id AS TEXT) = ?
            LIMIT 1
            """,
            (int(order_id), customer_id),
        ).fetchone()

        if row is None:
            return None

        payments = _payment_by_order(conn, [int(order_id)])
        ticket_id = str(row["ticket_channel_id"] or "").strip()
        supports = _support_by_ticket(conn, [ticket_id] if ticket_id else [])
        assignments = _assignments_by_order(conn, [int(order_id)])

        return _order_to_public(
            row,
            payment=payments.get(int(order_id)),
            support=supports.get(ticket_id),
            assignments=assignments.get(int(order_id), []),
            guild_id=guild_id,
        )


def build_customer_portal_snapshot(
    customer_id: str | int,
    *,
    guild_id: str | int | None = None,
    db_file: str | Path | None = None,
) -> dict[str, Any]:
    orders = list_customer_orders(
        customer_id,
        guild_id=guild_id,
        limit=100,
        db_file=db_file,
    )

    open_orders = [order for order in orders if order["is_open"]]
    pending_payment = [
        order
        for order in open_orders
        if (
            order["status"] == "accepted_pending_pay"
            or (
                order.get("payment")
                and order["payment"]["status"]
                in {"pending_review", "approved_pending_apply"}
            )
        )
    ]
    support_waiting = [
        order
        for order in open_orders
        if (
            order.get("support")
            and order["support"]["status"] in {"open", "claimed"}
        )
    ]

    return {
        "orders": orders,
        "open_orders": open_orders,
        "history_orders": [order for order in orders if not order["is_open"]],
        "recent_orders": orders[:6],
        "open_count": len(open_orders),
        "pending_payment_count": len(pending_payment),
        "support_waiting_count": len(support_waiting),
        "total_count": len(orders),
    }
