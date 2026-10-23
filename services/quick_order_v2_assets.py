from __future__ import annotations

import hashlib
from functools import lru_cache
from pathlib import Path, PurePosixPath
from urllib.parse import quote


PUBLIC_ORDER_PANEL_BASE_URL = "https://mowanentertainment.com/static/order_panels"
PUBLIC_ORDER_PANEL_URL_REVISION = "r2"
_STATIC_ORDER_PANEL_DIR = (
    Path(__file__).resolve().parents[1] / "web" / "app" / "static" / "order_panels"
)


def _safe_relative_png_path(filename: str) -> PurePosixPath | None:
    raw = str(filename or "").strip().replace("\\", "/")
    if not raw:
        return None

    relative = PurePosixPath(raw)
    if relative.is_absolute():
        return None
    if any(part in {"", ".", ".."} for part in relative.parts):
        return None
    if relative.suffix.lower() != ".png":
        return None
    return relative


@lru_cache(maxsize=64)
def public_order_panel_image_url(filename: str) -> str | None:
    """Return a cache-busted public URL for deployed order-panel artwork.

    Root artwork and nested price-list artwork are both allowed, but traversal
    outside web/app/static/order_panels is rejected. Nginx serves this public
    artwork directory directly with cross-origin image headers so Discord can
    render the PNG inside embeds. The file is read only once per bot process to
    compute a content hash; deployments restart the bot after syncing artwork.
    """
    relative = _safe_relative_png_path(filename)
    if relative is None:
        return None

    root = _STATIC_ORDER_PANEL_DIR.resolve()
    path = root.joinpath(*relative.parts).resolve()
    if root not in path.parents:
        return None
    if not path.is_file():
        return None

    try:
        data = path.read_bytes()
    except OSError:
        return None

    if not data.startswith(b"\x89PNG\r\n\x1a\n"):
        return None

    digest = hashlib.sha256(data).hexdigest()[:12]
    public_path = quote(relative.as_posix(), safe="/")
    return (
        f"{PUBLIC_ORDER_PANEL_BASE_URL}/{public_path}"
        f"?v={PUBLIC_ORDER_PANEL_URL_REVISION}-{digest}"
    )


__all__ = [
    "PUBLIC_ORDER_PANEL_BASE_URL",
    "PUBLIC_ORDER_PANEL_URL_REVISION",
    "public_order_panel_image_url",
]
