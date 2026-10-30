from __future__ import annotations

import os
from datetime import datetime, timezone
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

import aiohttp

from services.market.providers.base import (
    MarketSourceItem,
    MarketSourceSnapshot,
    MarketSourceUnavailable,
    normalize_source_snapshot,
)


SOURCE_NAME = "852941-tw-public"
DEFAULT_BASE_URL = "https://app.852941.xyz"
TAIPEI = ZoneInfo("Asia/Taipei")


def _parse_source_time(payload: dict) -> datetime:
    raw = str(
        payload.get("latest_market_time")
        or payload.get("snapshot_group_time")
        or ""
    ).strip()
    if not raw:
        raise MarketSourceUnavailable("852941 source did not provide a market timestamp")

    try:
        local = datetime.strptime(raw, "%Y-%m-%d %H:%M:%S").replace(tzinfo=TAIPEI)
    except ValueError as exc:
        raise MarketSourceUnavailable("852941 source returned an invalid market timestamp") from exc
    return local.astimezone(timezone.utc)


def _display_name(source_item_id: str, category: str, tier: int | None) -> str:
    """Keep the source's real ammunition identity whenever it has one.

    Some 852941 rows expose only a synthetic key such as ``.300BLK_3``. Those
    need a readable fallback. Other rows expose the actual ammunition name in
    ``bullet_name`` (for example ``.357 Magnum FMJ`` or ``.45 ACP AP``); using
    category+tier for those rows would collapse multiple distinct rounds into
    the same visible label.
    """
    item_id = str(source_item_id or "").strip()
    caliber = str(category or "").strip()
    if not item_id:
        return f"{caliber} {tier}級" if tier is not None else caliber

    if tier is not None and caliber:
        normalized = item_id.casefold()
        generic_ids = {
            f"{caliber}_{tier}".casefold(),
            f"{caliber}-{tier}".casefold(),
            f"{caliber} {tier}".casefold(),
        }
        if normalized in generic_ids:
            return f"{caliber} {tier}級"

    return item_id


def _build_snapshot(
    *,
    game_key: str,
    last_updated_payload: object,
    dashboard_payload: object,
    fetched_at: datetime | None = None,
) -> MarketSourceSnapshot:
    if game_key != "delta_force":
        raise MarketSourceUnavailable(f"852941 provider does not support game '{game_key}'")
    if not isinstance(last_updated_payload, dict) or last_updated_payload.get("status") != "success":
        raise MarketSourceUnavailable("852941 last_updated response is not healthy")
    if not isinstance(dashboard_payload, dict) or dashboard_payload.get("status") != "success":
        raise MarketSourceUnavailable("852941 dashboard response is not healthy")

    source_updated_at = _parse_source_time(last_updated_payload)
    raw_data = dashboard_payload.get("data")
    if not isinstance(raw_data, dict):
        raise MarketSourceUnavailable("852941 dashboard did not contain market data")

    items: list[MarketSourceItem] = []
    for raw_category, rows in raw_data.items():
        category = str(raw_category or "").strip()
        if not category or not isinstance(rows, list):
            continue

        for row in rows:
            if not isinstance(row, dict):
                continue
            source_item_id = str(row.get("bullet_name") or "").strip()
            try:
                price = int(row.get("current_price"))
            except (TypeError, ValueError):
                continue
            try:
                tier = int(row.get("tier"))
            except (TypeError, ValueError):
                tier = None

            if not source_item_id or price <= 0:
                continue
            if tier is not None and not 1 <= tier <= 10:
                tier = None

            items.append(
                MarketSourceItem(
                    source_item_id=source_item_id,
                    name=_display_name(source_item_id, category, tier),
                    price=price,
                    category=category,
                    tier=tier,
                )
            )

    return normalize_source_snapshot(
        MarketSourceSnapshot(
            source_name=SOURCE_NAME,
            game_key=game_key,
            fetched_at=fetched_at or datetime.now(timezone.utc),
            source_updated_at=source_updated_at,
            items=tuple(items),
        )
    )


class Public852941Provider:
    """Read-only adapter for the public Taiwan/Garena market dashboard.

    The provider only performs anonymous GET requests to endpoints referenced by
    the public website itself. It does not send cookies, credentials, writes, or
    feedback requests. Third-party recommendation/safety scores are deliberately
    ignored; only stable item identity, current price, caliber and tier enter the
    canonical Market DB.
    """

    def __init__(self, *, base_url: str | None = None, timeout_seconds: int = 12) -> None:
        configured = str(base_url or os.getenv("MARKET_852941_BASE_URL") or DEFAULT_BASE_URL).strip()
        self.base_url = configured.rstrip("/")
        parsed = urlparse(self.base_url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("MARKET_852941_BASE_URL must be an absolute HTTP(S) URL")
        self._source_host = parsed.netloc.lower()
        self.timeout_seconds = max(3, min(int(timeout_seconds), 30))

    async def _get_json(self, session: aiohttp.ClientSession, path: str) -> object:
        url = f"{self.base_url}{path}"
        try:
            async with session.get(url, allow_redirects=True) as response:
                if response.status != 200:
                    raise MarketSourceUnavailable(
                        f"852941 GET {path} returned HTTP {response.status}"
                    )
                if str(response.url.host or "").lower() != self._source_host.split(":", 1)[0]:
                    raise MarketSourceUnavailable("852941 source redirected to an unexpected host")
                try:
                    return await response.json(content_type=None)
                except Exception as exc:
                    raise MarketSourceUnavailable(
                        f"852941 GET {path} did not return valid JSON"
                    ) from exc
        except MarketSourceUnavailable:
            raise
        except (aiohttp.ClientError, TimeoutError) as exc:
            raise MarketSourceUnavailable(f"852941 GET {path} failed") from exc

    async def fetch(self, game_key: str) -> MarketSourceSnapshot:
        timeout = aiohttp.ClientTimeout(total=self.timeout_seconds, connect=min(6, self.timeout_seconds))
        headers = {
            "Accept": "application/json",
            "Accept-Language": "zh-TW,zh;q=0.9",
            "User-Agent": "MowanEntertainment-MarketReader/1.0 (+read-only public market data)",
        }
        async with aiohttp.ClientSession(timeout=timeout, headers=headers) as session:
            # Read the source timestamp first. If the source updates between the
            # two GETs, assigning the slightly older timestamp is safer than
            # labelling old prices with a newer snapshot time.
            last_updated = await self._get_json(session, "/api/last_updated")
            dashboard = await self._get_json(session, "/api/dashboard")

        return _build_snapshot(
            game_key=game_key,
            last_updated_payload=last_updated,
            dashboard_payload=dashboard,
        )
