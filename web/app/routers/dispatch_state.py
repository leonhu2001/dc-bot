import asyncio
import json
import sqlite3
import time

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, StreamingResponse

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


def _dispatch_event_snapshot() -> dict:
    conn = sqlite3.connect(get_sqlite_path())
    conn.row_factory = sqlite3.Row

    try:
        rows = conn.execute(
            """
            SELECT
                id,
                bot_order_no,
                updated_at,
                amount,
                quantity,
                status
            FROM web_orders
            WHERE status IN ('active', 'waiting_acceptance', 'accepted_pending_pay')
            ORDER BY id ASC
            """
        ).fetchall()
    finally:
        conn.close()

    keys = [
        str(row["bot_order_no"] or f"WEB-{row['id']}")
        for row in rows
    ]
    signature = "|".join(
        (
            f"{row['id']}:{row['bot_order_no'] or f'WEB-{row['id']}'}:"
            f"{row['updated_at'] or ''}:{row['amount'] or 0}:"
            f"{row['quantity'] or 0}:{row['status'] or ''}"
        )
        for row in rows
    )

    return {
        "count": len(rows),
        "keys": keys,
        "signature": signature,
    }


def _touch_dispatch_stream_presence(user: dict) -> None:
    display_name = (
        user.get("global_name")
        or user.get("display_name")
        or user.get("username")
        or user.get("id")
    )

    if user.get("is_worker") or user.get("is_companion"):
        touch_dispatch_presence(
            str(user.get("id") or ""),
            display_name=display_name,
        )

    if user.get("is_manager") or user.get("is_customer_service"):
        touch_dispatch_support_presence(
            str(user.get("id") or ""),
            display_name=display_name,
        )


@router.get("/dispatch/events")
async def dispatch_events(request: Request):
    user = request.session.get("user")
    if not user:
        return JSONResponse(
            {"ok": False, "error": "not_logged_in"},
            status_code=401,
        )

    if not (
        user.get("is_admin")
        or user.get("is_worker")
        or user.get("is_companion")
        or user.get("is_customer_service")
    ):
        return JSONResponse(
            {"ok": False, "error": "forbidden"},
            status_code=403,
        )

    async def event_stream():
        last_signature = None
        last_presence_touch = 0.0
        last_heartbeat = 0.0

        yield "retry: 3000\n\n"

        while True:
            if await request.is_disconnected():
                return

            now = time.monotonic()

            if now - last_presence_touch >= 20:
                _touch_dispatch_stream_presence(user)
                last_presence_touch = now

            snapshot = _dispatch_event_snapshot()
            signature = snapshot["signature"]

            if last_signature is None or signature != last_signature:
                payload = {
                    "ok": True,
                    "initial": last_signature is None,
                    **snapshot,
                }
                yield f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"
                last_signature = signature
                last_heartbeat = now
            elif now - last_heartbeat >= 15:
                yield ": keep-alive\n\n"
                last_heartbeat = now

            await asyncio.sleep(1)

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "X-Accel-Buffering": "no",
        },
    )
