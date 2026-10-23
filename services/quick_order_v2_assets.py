from __future__ import annotations

import hashlib
from functools import lru_cache
from pathlib import Path


PUBLIC_ORDER_PANEL_BASE_URL = "https://mowanentertainment.com/static/order_panels"
_STATIC_ORDER_PANEL_DIR = (
    Path(__file__).resolve().parents[1] / "web" / "app" / "static" / "order_panels"
)


@lru_cache(maxsize=32)
def public_order_panel_image_url(filename: str) -> str | None:
    """Return a cache-busted public URL for a deployed order-panel PNG.

    The image is served by the existing FastAPI /static mount. The file is read
    only once per bot process to compute a content hash; Discord then fetches the
    image directly from mowanentertainment.com. Deployments restart the bot after
    syncing artwork, so changing a PNG naturally refreshes this cache.
    """
    clean_name = Path(str(filename or "")).name
    if not clean_name.lower().endswith(".png"):
        return None

    path = _STATIC_ORDER_PANEL_DIR / clean_name
    if not path.is_file():
        return None

    try:
        data = path.read_bytes()
    except OSError:
        return None

    if not data.startswith(b"\x89PNG\r\n\x1a\n"):
        return None

    digest = hashlib.sha256(data).hexdigest()[:12]
    return f"{PUBLIC_ORDER_PANEL_BASE_URL}/{clean_name}?v={digest}"


__all__ = [
    "PUBLIC_ORDER_PANEL_BASE_URL",
    "public_order_panel_image_url",
]
