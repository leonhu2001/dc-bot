from __future__ import annotations

from starlette.requests import Request


_MOBILE_UA_MARKERS = (
    "iphone",
    "ipad",
    "ipod",
    "android",
    "mobile",
)


def choose_ui_surface(request: Request) -> str:
    """Choose the server-rendered UI surface for this request.

    Desktop/mobile selection must not depend on CSS viewport width. Client Hints
    take priority when present; the user-agent is the compatibility fallback.
    Business logic and APIs remain shared, while templates/assets can branch on
    this single value.
    """
    client_hint = str(request.headers.get("sec-ch-ua-mobile") or "").strip().lower()
    if client_hint == "?1":
        return "mobile"
    if client_hint == "?0":
        return "desktop"

    user_agent = str(request.headers.get("user-agent") or "").lower()
    if any(marker in user_agent for marker in _MOBILE_UA_MARKERS):
        return "mobile"

    return "desktop"
