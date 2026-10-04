from __future__ import annotations

import asyncio

import discord

from services.dispatch_presence import (
    count_online_dispatch_workers,
    has_online_dispatch_support,
)


DEFAULT_IDLE_CHANNEL_NAME = "🚬┃排隊中。。。。。"
DEFAULT_SUPPORT_IDLE_CHANNEL_NAME = "🛎️┃點單・服務大廳"
SUPPORT_ONLINE_CHANNEL_NAME = "🟢┃點單・服務大廳"


def format_dispatch_presence_channel_name(count: int) -> str:
    online_count = max(0, int(count or 0))
    if online_count < 2:
        return DEFAULT_IDLE_CHANNEL_NAME
    return f"🟢┃{online_count}人在線"


async def dispatch_presence_channel_loop(
    bot: discord.Client,
    *,
    channel_id: int,
    interval_seconds: int = 30,
) -> None:
    if not int(channel_id or 0):
        return

    await bot.wait_until_ready()

    while not bot.is_closed():
        try:
            channel = bot.get_channel(int(channel_id))
            if channel is not None and hasattr(channel, "edit"):
                online_count = count_online_dispatch_workers()
                target_name = format_dispatch_presence_channel_name(online_count)

                if str(getattr(channel, "name", "")) != target_name:
                    await channel.edit(
                        name=target_name,
                        reason="Sync dispatch online worker count",
                    )
        except discord.Forbidden:
            print(
                "[dispatch-presence] missing Manage Channels permission",
                flush=True,
            )
        except discord.HTTPException as exc:
            print(
                f"[dispatch-presence] channel rename failed: {exc}",
                flush=True,
            )
        except Exception as exc:
            print(
                f"[dispatch-presence] loop error: {type(exc).__name__}: {exc}",
                flush=True,
            )

        await asyncio.sleep(max(15, int(interval_seconds or 30)))


def format_dispatch_support_channel_name(is_online: bool) -> str:
    return (
        SUPPORT_ONLINE_CHANNEL_NAME
        if bool(is_online)
        else DEFAULT_SUPPORT_IDLE_CHANNEL_NAME
    )


async def dispatch_support_presence_channel_loop(
    bot: discord.Client,
    *,
    channel_id: int,
    interval_seconds: int = 30,
) -> None:
    if not int(channel_id or 0):
        return

    await bot.wait_until_ready()

    while not bot.is_closed():
        try:
            channel = bot.get_channel(int(channel_id))
            if channel is not None and hasattr(channel, "edit"):
                target_name = format_dispatch_support_channel_name(
                    has_online_dispatch_support()
                )

                if str(getattr(channel, "name", "")) != target_name:
                    await channel.edit(
                        name=target_name,
                        reason="Sync dispatch support online state",
                    )
        except discord.Forbidden:
            print(
                "[dispatch-support-presence] missing Manage Channels permission",
                flush=True,
            )
        except discord.HTTPException as exc:
            print(
                f"[dispatch-support-presence] channel rename failed: {exc}",
                flush=True,
            )
        except Exception as exc:
            print(
                f"[dispatch-support-presence] loop error: "
                f"{type(exc).__name__}: {exc}",
                flush=True,
            )

        await asyncio.sleep(max(15, int(interval_seconds or 30)))
