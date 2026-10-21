import asyncio
import time

from starlette.concurrency import run_in_threadpool

from web.app.services.discord_service import get_member_role_ids

_ADMIN_ROLE_CACHE_TTL_SECONDS = 5.0
_role_cache: dict[str, tuple[float, tuple[str, ...]]] = {}
_role_locks: dict[str, asyncio.Lock] = {}


async def get_admin_member_role_ids(
    discord_user_id: str,
    *,
    force_refresh: bool = False,
) -> list[str]:
    """Return live Discord roles while collapsing duplicate admin-page lookups.

    Ordinary admin GET requests may reuse a successful lookup for a few seconds,
    which prevents one page load from issuing several identical Discord API
    calls. Sensitive pages and write operations pass ``force_refresh=True`` and
    therefore always verify live before continuing.
    """
    user_id = str(discord_user_id or "").strip()
    if not user_id:
        return []

    now = time.monotonic()
    cached = _role_cache.get(user_id)
    if not force_refresh and cached and cached[0] > now:
        return list(cached[1])

    lock = _role_locks.setdefault(user_id, asyncio.Lock())
    async with lock:
        now = time.monotonic()
        cached = _role_cache.get(user_id)
        if not force_refresh and cached and cached[0] > now:
            return list(cached[1])

        role_ids = await run_in_threadpool(get_member_role_ids, user_id)
        normalized = tuple(str(role_id) for role_id in role_ids)
        _role_cache[user_id] = (
            time.monotonic() + _ADMIN_ROLE_CACHE_TTL_SECONDS,
            normalized,
        )
        return list(normalized)


def clear_admin_role_cache() -> None:
    """Clear cached role data. Primarily useful for tests and maintenance hooks."""
    _role_cache.clear()
    _role_locks.clear()
