from __future__ import annotations

import asyncio

import discord

from core.config import config_int
from services.dispatch_presence import (
    count_online_dispatch_companions_for_role,
    count_online_dispatch_workers,
    has_online_dispatch_support,
)


# 舊 formatter 保留給相容測試 / 其他呼叫點；Discord 實際顯示已改為男女陪分流。
DEFAULT_IDLE_CHANNEL_NAME = "⚫┃暫無陪玩"
DEFAULT_SUPPORT_IDLE_CHANNEL_NAME = "🛎️┃點單・客服中心"
SUPPORT_ONLINE_CHANNEL_NAME = "🟢┃點單・客服值班中"

FEMALE_COMPANION_ROLE_ID = "1482080315798192210"
MALE_COMPANION_ROLE_ID = "1500751059239440575"
DEFAULT_MALE_ONLINE_CHANNEL_ID = 1538270089785245856


def format_dispatch_presence_channel_name(count: int) -> str:
    online_count = max(0, int(count or 0))
    if online_count <= 0:
        return DEFAULT_IDLE_CHANNEL_NAME
    return f"🟢┃在線陪玩：{online_count}"


def format_companion_presence_channel_name(
    label: str,
    icon: str,
    count: int,
) -> str:
    online_count = max(0, int(count or 0))
    light = "🟢" if online_count > 0 else "⚫"
    return f"{icon}┃{label}・{light}{online_count}人在線"


async def _rename_presence_channel(
    bot: discord.Client,
    *,
    channel_id: int,
    target_name: str,
    reason: str,
) -> None:
    if not int(channel_id or 0):
        return

    channel = bot.get_channel(int(channel_id))
    if channel is None or not hasattr(channel, "edit"):
        return

    if str(getattr(channel, "name", "")) == target_name:
        return

    await channel.edit(
        name=target_name,
        reason=reason,
    )


async def dispatch_presence_channel_loop(
    bot: discord.Client,
    *,
    channel_id: int,
    interval_seconds: int = 30,
) -> None:
    """Synchronize the female + male companion presence channels.

    ``channel_id`` is the historical DISPATCH_ONLINE_CHANNEL_ID config key and
    now points to the female companion channel.  Keeping the call signature lets
    deployed config migrate cleanly without a runtime override in bot.py.
    """
    female_channel_id = int(channel_id or 0)
    male_channel_id = config_int(
        "DISPATCH_MALE_ONLINE_CHANNEL_ID",
        DEFAULT_MALE_ONLINE_CHANNEL_ID,
    )

    if not female_channel_id and not male_channel_id:
        return

    await bot.wait_until_ready()

    while not bot.is_closed():
        try:
            female_count = count_online_dispatch_companions_for_role(
                FEMALE_COMPANION_ROLE_ID
            )
            male_count = count_online_dispatch_companions_for_role(
                MALE_COMPANION_ROLE_ID
            )

            await _rename_presence_channel(
                bot,
                channel_id=female_channel_id,
                target_name=format_companion_presence_channel_name(
                    "女陪",
                    "👩",
                    female_count,
                ),
                reason="Sync female companion online count",
            )
            await _rename_presence_channel(
                bot,
                channel_id=male_channel_id,
                target_name=format_companion_presence_channel_name(
                    "男陪",
                    "🧑",
                    male_count,
                ),
                reason="Sync male companion online count",
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
