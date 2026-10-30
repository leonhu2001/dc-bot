from __future__ import annotations

import asyncio
import json
import time

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, StreamingResponse

from web.app.routers.dispatch_state import (
    _public_dispatch_snapshot,
    _shared_dispatch_event_snapshot,
)
from web.app.services.dispatch_access import can_use_dispatch


router = APIRouter(tags=["dispatch-background-alerts"])

# Keep the same bounded-session behavior as the dispatch lobby SSE. Reconnecting
# creates a fresh HTTP response and therefore lets SessionMiddleware refresh the
# signed session cookie. Unlike /dispatch/events, this stream never touches the
# dispatch-presence tracker: browsing another page must not make someone appear
# online in the dispatch lobby.
_BACKGROUND_SSE_SESSION_REFRESH_SECONDS = 4 * 60 * 60
_BACKGROUND_HEARTBEAT_SECONDS = 30


def _dispatch_user_or_response(request: Request):
    user = request.session.get("user")
    if not user:
        return None, JSONResponse(
            {"ok": False, "error": "not_logged_in"},
            status_code=401,
        )
    if not can_use_dispatch(user):
        return None, JSONResponse(
            {"ok": False, "error": "forbidden"},
            status_code=403,
        )
    return user, None


def _background_payload(snapshot: dict, user: dict | None, *, initial: bool) -> dict:
    """Return the minimum payload needed for a desktop new-order alert.

    Deliberately omit customer, amount, service detail and claim metadata. The
    browser only needs the order keys that this user is currently eligible to
    claim; opening /dispatch remains the source of full order information.
    """
    public_snapshot = _public_dispatch_snapshot(snapshot, user)
    alert_keys = sorted({str(key) for key in public_snapshot.get("alert_keys") or []})
    return {
        "ok": True,
        "initial": bool(initial),
        "alert_keys": alert_keys,
    }


@router.get("/dispatch/alerts/config")
async def dispatch_background_alert_config(request: Request):
    _user, response = _dispatch_user_or_response(request)
    if response is not None:
        return response
    return {
        "ok": True,
        "allowed": True,
    }


@router.get("/dispatch/alerts/events")
async def dispatch_background_alert_events(request: Request):
    user, response = _dispatch_user_or_response(request)
    if response is not None:
        return response

    async def event_stream():
        stream_started = time.monotonic()
        last_alert_signature: str | None = None
        last_heartbeat = 0.0

        yield "retry: 5000\n\n"

        while True:
            if await request.is_disconnected():
                return

            now = time.monotonic()
            if now - stream_started >= _BACKGROUND_SSE_SESSION_REFRESH_SECONDS:
                return

            snapshot = await _shared_dispatch_event_snapshot()
            payload = _background_payload(
                snapshot,
                user,
                initial=last_alert_signature is None,
            )
            signature = "|".join(payload["alert_keys"])

            if last_alert_signature is None or signature != last_alert_signature:
                yield f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"
                last_alert_signature = signature
                last_heartbeat = now
            elif now - last_heartbeat >= _BACKGROUND_HEARTBEAT_SECONDS:
                heartbeat = {
                    "ok": True,
                    "heartbeat": True,
                    "alert_keys": payload["alert_keys"],
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
