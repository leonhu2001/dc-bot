from __future__ import annotations

import threading
import time
from collections.abc import Callable

import requests

from web.app.config import config


DISCORD_API_BASE = "https://discord.com/api/v10"
_CACHE_TTL_SECONDS = 60.0
_cache_lock = threading.Lock()
_cache_expires_at = 0.0
_cache_members: list[dict] = []


def _member_display_name(member: dict) -> str:
    user = member.get("user") if isinstance(member, dict) else None
    if not isinstance(user, dict):
        user = {}

    for value in (
        member.get("nick") if isinstance(member, dict) else None,
        user.get("global_name"),
        user.get("username"),
        user.get("id"),
    ):
        text = str(value or "").strip()
        if text:
            return text
    return "Discord 會員"


def _fetch_all_guild_members() -> list[dict]:
    token = str(getattr(config, "DISCORD_BOT_TOKEN", "") or "").strip()
    guild_id = str(getattr(config, "DISCORD_GUILD_ID", "") or "").strip()
    if not token or not guild_id:
        raise RuntimeError("Discord guild member source is not configured")

    headers = {
        "Authorization": f"Bot {token}",
        "Content-Type": "application/json",
    }
    url = f"{DISCORD_API_BASE}/guilds/{guild_id}/members"
    after = ""
    members_by_id: dict[str, dict] = {}

    while True:
        params: dict[str, str | int] = {"limit": 1000}
        if after:
            params["after"] = after

        response = requests.get(url, headers=headers, params=params, timeout=15)
        if response.status_code != 200:
            raise RuntimeError(
                f"Failed to list Discord guild members: HTTP {response.status_code}"
            )

        batch = response.json()
        if not isinstance(batch, list):
            raise RuntimeError("Discord guild member response was not a list")

        for member in batch:
            if not isinstance(member, dict):
                continue
            user = member.get("user")
            if not isinstance(user, dict) or bool(user.get("bot")):
                continue
            discord_id = str(user.get("id") or "").strip()
            if not discord_id:
                continue
            members_by_id[discord_id] = {
                "customer_discord_id": discord_id,
                "display_name": _member_display_name(member),
                "last_seen": "",
            }

        if len(batch) < 1000:
            break

        last_member = batch[-1] if batch else {}
        last_user = last_member.get("user") if isinstance(last_member, dict) else {}
        next_after = str(last_user.get("id") or "").strip() if isinstance(last_user, dict) else ""
        if not next_after or next_after == after:
            break
        after = next_after

    members = list(members_by_id.values())
    members.sort(
        key=lambda item: (
            str(item.get("display_name") or "").casefold(),
            str(item.get("customer_discord_id") or ""),
        )
    )
    return members


def _cached_guild_members() -> list[dict]:
    global _cache_expires_at, _cache_members

    now = time.monotonic()
    with _cache_lock:
        if _cache_members and now < _cache_expires_at:
            return [dict(item) for item in _cache_members]

    fresh = _fetch_all_guild_members()
    with _cache_lock:
        _cache_members = [dict(item) for item in fresh]
        _cache_expires_at = time.monotonic() + _CACHE_TTL_SECONDS
    return fresh


def install_benefit_member_source(target_module) -> None:
    """Make the benefit recipient picker use every real member in the guild.

    The historical picker only queried web_orders, so members who had never
    purchased anything could not receive a benefit. Discord is now canonical;
    the old order-backed source remains a fail-safe when Discord is unavailable.
    """

    original: Callable[..., list[dict]] = target_module._customer_options

    def _guild_customer_options(limit: int = 400) -> list[dict]:
        del limit  # The benefit picker intentionally exposes the whole guild.
        try:
            return _cached_guild_members()
        except Exception as exc:
            print(
                f"[benefits] guild member list unavailable, using order fallback: "
                f"{type(exc).__name__}: {exc}",
                flush=True,
            )
            return original(limit=1000)

    target_module._customer_options = _guild_customer_options
