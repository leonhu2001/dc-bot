import sqlite3

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from services.dispatch_presence import (
    touch_dispatch_presence,
    touch_dispatch_support_presence,
)
from web.app.config import config

router = APIRouter(tags=["dispatch_state"])


def get_sqlite_path() -> str:
    url = config.DATABASE_URL
    if not url.startswith("sqlite:///"):
        raise RuntimeError("Only sqlite DATABASE_URL is supported for dispatch state")
    return url.replace("sqlite:///", "", 1)


@router.get("/dispatch/state")
async def dispatch_state(request: Request):
    user = request.session.get("user")
    if not user:
        return JSONResponse({"ok": False, "error": "not_logged_in"}, status_code=401)

    display_name = (
        user.get("global_name")
        or user.get("display_name")
        or user.get("username")
        or user.get("id")
    )
    presence_online = bool(
        user.get("is_worker")
        or user.get("is_companion")
    )
    support_presence_online = bool(
        user.get("is_manager")
        or user.get("is_customer_service")
    )

    if presence_online:
        touch_dispatch_presence(
            str(user.get("id") or ""),
            display_name=display_name,
        )

    if support_presence_online:
        touch_dispatch_support_presence(
            str(user.get("id") or ""),
            display_name=display_name,
        )

    conn = sqlite3.connect(get_sqlite_path())
    conn.row_factory = sqlite3.Row

    try:
        rows = conn.execute(
            """
            SELECT
                id,
                bot_order_no,
                ticket_channel_id,
                dispatch_message_id,
                customer_display_name,
                customer_discord_id,
                category,
                item,
                quantity,
                amount,
                status,
                updated_at,
                created_at
            FROM web_orders
            WHERE status IN ('active', 'waiting_acceptance', 'accepted_pending_pay')
            ORDER BY id ASC
            """
        ).fetchall()

        orders = []
        for row in rows:
            order_key = row["bot_order_no"] or f"WEB-{row['id']}"
            orders.append(
                {
                    "id": row["id"],
                    "key": order_key,
                    "bot_order_no": row["bot_order_no"],
                    "ticket_channel_id": row["ticket_channel_id"],
                    "dispatch_message_id": row["dispatch_message_id"],
                    "customer": row["customer_display_name"] or row["customer_discord_id"] or "",
                    "category": row["category"] or "",
                    "item": row["item"] or "",
                    "quantity": row["quantity"] or 0,
                    "amount": row["amount"] or 0,
                    "status": row["status"] or "",
                    "updated_at": row["updated_at"] or "",
                    "created_at": row["created_at"] or "",
                }
            )

        signature = "|".join(
            f"{order['id']}:{order['key']}:{order['updated_at']}:{order['amount']}:{order['quantity']}"
            for order in orders
        )

        return {
            "ok": True,
            "presence_online": presence_online,
            "support_presence_online": support_presence_online,
            "count": len(orders),
            "keys": [order["key"] for order in orders],
            "signature": signature,
            "orders": orders,
        }
    finally:
        conn.close()
