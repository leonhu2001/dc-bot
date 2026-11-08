"""Sync the actual Discord VIP tier once after the owner-authorized VIP repair.

The single-order repair persists a database audit marker. It runs offline while
Bot/Web are stopped; this lightweight on-ready follow-up changes Discord roles
only if that marker exists and the corrected VIP amount is exactly 3000T.
"""
from __future__ import annotations

import asyncio
import sqlite3
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
_REPAIR_KEY = "20261108:owner-authorized-purge-MO20261108003-v1"
_CUSTOMER_ID = 519545372194656316


async def sync_repaired_member_tier(bot, guild_id: int) -> None:
    path = _REPO / "web_dashboard.db"
    if not path.is_file():
        return

    try:
        with sqlite3.connect(path, timeout=3) as conn:
            found = conn.execute(
                "SELECT 1 FROM one_time_data_repairs "
                "WHERE repair_key=? LIMIT 1",
                (_REPAIR_KEY,),
            ).fetchone()
    except sqlite3.Error:
        return

    if not found:
        return

    from services import rewards

    data = rewards.get_customer_reward_data(_CUSTOMER_ID)
    if int(data.get("total_spent", -1)) != 3000:
        print("[one-time-vip-role] skipped: VIP is not 3000T", flush=True)
        return

    guild = bot.get_guild(int(guild_id))
    if guild is None:
        print("[one-time-vip-role] skipped: Discord guild missing", flush=True)
        return

    try:
        member = await rewards.fetch_member_safely(guild, _CUSTOMER_ID)
        if member is None:
            print("[one-time-vip-role] skipped: member missing", flush=True)
            return
        notices = await rewards.ensure_reward_member_benefits(guild, member, data)
        print(
            "[one-time-vip-role] synced customer VIP role "
            f"customer={_CUSTOMER_ID} notices={notices!r}",
            flush=True,
        )
    except Exception as exc:
        print(
            f"[one-time-vip-role] sync failed: {type(exc).__name__}: {exc}",
            flush=True,
        )
