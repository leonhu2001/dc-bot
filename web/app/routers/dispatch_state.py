import asyncio
import json
import sqlite3
import time

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, StreamingResponse

from services.dispatch_presence import (
    count_online_dispatch_workers,
    get_online_dispatch_support_ids,
)
from web.app.config import config
from web.app.services.dispatch_access import (
    can_use_dispatch,
    touch_dispatch_user_presence,
)
from web.app.services.order_service import VISIBLE_DISPATCH_STATUSES

router = APIRouter(tags=["dispatch_state"])

_VISIBLE_STATUS_VALUES = tuple(VISIBLE_DISPATCH_STATUSES)
_VISIBLE_STATUS_PLACEHOLDERS = ", ".join("?" for _ in _VISIBLE_STATUS_VALUES)
_DISPATCH_EVENT_CACHE_TTL_SECONDS = 1.0
_dispatch_event_cache: dict | None = None
_dispatch_event_cache_expires_at = 0.0
_dispatch_event_cache_lock = asyncio.Lock()


def get_sqlite_path() -> str:
    url = config.DATABASE_URL
    if not url.startswith("sqlite:///"):
        raise RuntimeError("Only sqlite DATABASE_URL is supported for dispatch state")
    return url.replace("sqlite:///", "", 1)


def _dispatch_presence_snapshot() -> dict:
    return {
        "online_companion_count": count_online_dispatch_workers(),
        "online_support_count": len(get_online_dispatch_support_ids()),
    }


def _dispatch_order_rows() -> list[sqlite3.Row]:
    conn = sqlite3.connect(get_sqlite_path())
    conn.row_factory = sqlite3.Row

    try:
        return conn.execute(
            f"""
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
            WHERE status IN ({_VISIBLE_STATUS_PLACEHOLDERS})
            ORDER BY id ASC
            """,
            _VISIBLE_STATUS_VALUES,
        ).fetchall()
    finally:
        conn.close()


def _dispatch_state_snapshot(*, include_orders: bool) -> dict:
    rows = _dispatch_order_rows()
    orders = []

    for row in rows:
        order_key = str(row["bot_order_no"] or f"WEB-{row['id']}")
        orders.append(
            {
                "id": row["id"],
                "key": order_key,
                "bot_order_no": row["bot_order_no"],
                "ticket_channel_id": row["ticket_channel_id"],
                "dispatch_message_id": row["dispatch_message_id"],
                "customer": (
                    row["customer_display_name"]
                    or row["customer_discord_id"]
                    or ""
                ),
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
        (
            f"{order['id']}:{order['key']}:{order['updated_at']}:"
            f"{order['amount']}:{order['quantity']}:{order['status']}"
        )
        for order in orders
    )

    snapshot = {
        "count": len(orders),
        "keys": [order["key"] for order in orders],
        "signature": signature,
    }

    if include_orders:
        snapshot["orders"] = orders

    return snapshot


def _build_dispatch_event_snapshot() -> dict:
    return {
        **_dispatch_state_snapshot(include_orders=False),
        **_dispatch_presence_snapshot(),
    }


async def _shared_dispatch_event_snapshot() -> dict:
    """Reuse one compact DB snapshot across all SSE clients for one second."""
    global _dispatch_event_cache, _dispatch_event_cache_expires_at

    now = time.monotonic()
    cached = _dispatch_event_cache
    if cached is not None and now < _dispatch_event_cache_expires_at:
        return dict(cached)

    async with _dispatch_event_cache_lock:
        now = time.monotonic()
        cached = _dispatch_event_cache
        if cached is not None and now < _dispatch_event_cache_expires_at:
            return dict(cached)

        snapshot = await asyncio.to_thread(_build_dispatch_event_snapshot)
        _dispatch_event_cache = dict(snapshot)
        _dispatch_event_cache_expires_at = now + _DISPATCH_EVENT_CACHE_TTL_SECONDS
        return dict(snapshot)


@router.get("/dispatch/state")
async def dispatch_state(request: Request):
    user = request.session.get("user")
    if not user:
        return JSONResponse(
            {"ok": False, "error": "not_logged_in"},
            status_code=401,
        )

    if not can_use_dispatch(user):
        return JSONResponse(
            {"ok": False, "error": "forbidden"},
            status_code=403,
        )

    presence_online, support_presence_online = touch_dispatch_user_presence(user)
    state_snapshot, presence_snapshot = await asyncio.gather(
        asyncio.to_thread(_dispatch_state_snapshot, include_orders=True),
        asyncio.to_thread(_dispatch_presence_snapshot),
    )

    return {
        "ok": True,
        "presence_online": presence_online,
        "support_presence_online": support_presence_online,
        **presence_snapshot,
        **state_snapshot,
    }


@router.get("/dispatch/events")
async def dispatch_events(request: Request):
    user = request.session.get("user")
    if not user:
        return JSONResponse(
            {"ok": False, "error": "not_logged_in"},
            status_code=401,
        )

    if not can_use_dispatch(user):
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
                await asyncio.to_thread(touch_dispatch_user_presence, user)
                last_presence_touch = now

            snapshot = await _shared_dispatch_event_snapshot()
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
                heartbeat = {
                    "ok": True,
                    "heartbeat": True,
                    **snapshot,
                }
                yield f"data: {json.dumps(heartbeat, ensure_ascii=False)}\n\n"
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
