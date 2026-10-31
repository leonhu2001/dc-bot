from __future__ import annotations

import json
import os
import sys
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


DEFAULT_URL = "http://127.0.0.1:8000/health/market"


def _truthy(value: str | None, *, default: bool = False) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def main() -> int:
    url = str(os.getenv("MARKET_HEALTH_URL") or DEFAULT_URL).strip()
    require_push = _truthy(os.getenv("MARKET_HEALTH_REQUIRE_WEB_PUSH"), default=True)
    request = Request(url, headers={"User-Agent": "Mowan-Market-HealthProbe/1.0"})

    try:
        with urlopen(request, timeout=8) as response:
            raw = response.read().decode("utf-8", errors="replace")
            http_status = int(getattr(response, "status", 200))
    except HTTPError as exc:
        http_status = int(exc.code)
        raw = exc.read().decode("utf-8", errors="replace")
    except (URLError, TimeoutError, OSError) as exc:
        print(f"ERROR: market health endpoint unavailable: {type(exc).__name__}", file=sys.stderr)
        return 2

    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        print(f"ERROR: market health returned non-JSON response http={http_status}", file=sys.stderr)
        return 2

    status = str(payload.get("status") or "unknown")
    item_count = int(payload.get("item_count") or 0)
    age_seconds = payload.get("age_seconds")
    push_enabled = bool(payload.get("web_push_enabled"))
    ok = bool(payload.get("ok")) and http_status == 200

    print(
        "MARKET HEALTH",
        f"status={status}",
        f"http={http_status}",
        f"items={item_count}",
        f"age_seconds={age_seconds}",
        f"web_push_enabled={str(push_enabled).lower()}",
    )

    if not ok:
        return 1
    if item_count <= 0:
        print("ERROR: market health is ready but item_count is zero", file=sys.stderr)
        return 1
    if require_push and not push_enabled:
        print("ERROR: production Web Push is not enabled", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
