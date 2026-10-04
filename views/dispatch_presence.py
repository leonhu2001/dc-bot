from __future__ import annotations

import asyncio

import discord

from services.dispatch_presence import (
    count_online_dispatch_workers,
    has_online_dispatch_support,
)


DEFAULT_IDLE_CHANNEL_NAME = "⚫┃暫無陪玩"
DEFAULT_SUPPORT_IDLE_CHANNEL_NAME = "🛎️┃點單・服務大廳"
SUPPORT_ONLINE_CHANNEL_NAME = "🟢┃點單・服務大廳"

DISPLAY_ONLY_PERMISSION_FIELDS = (
    "send_messages",
    "send_tts_messages",
    "add_reactions",
    "create_public_threads",
    "create_private_threads",
    "send_messages_in_threads",
    "read_message_history",
    "use_application_commands",
)


def format_dispatch_presence_channel_name(count: int) -> str:
    online_count = max(0, int(count or 0))
    if online_count <= 0:
        return DEFAULT_IDLE_CHANNEL_NAME
    return f"🟢┃在線陪玩：{online_count}"


def apply_display_only_permissions(
    overwrite: discord.PermissionOverwrite,
    *,
    reveal_channel: bool = False,
) -> bool:
    changed = False

    if reveal_channel and overwrite.view_channel is not True:
        overwrite.view_channel = True
        changed = True

    for field in DISPLAY_ONLY_PERMISSION_FIELDS:
        if getattr(overwrite, field, None) is not False:
            setattr(overwrite, field, False)
            changed = True

    return changed


async def ensure_dispatch_presence_channel_display_only(
    channel: discord.abc.GuildChannel,
) -> bool:
    guild = getattr(channel, "guild", None)

    if (
        guild is None
        or not hasattr(channel, "overwrites_for")
        or not hasattr(channel, "set_permissions")
    ):
        return False

    changed = False
    default_role = guild.default_role
    default_overwrite = channel.overwrites_for(default_role)

    if apply_display_only_permissions(
        default_overwrite,
        reveal_channel=True,
    ):
        await channel.set_permissions(
            default_role,
            overwrite=default_overwrite,
            reason="Keep companion presence channel display-only",
        )
        changed = True

    # @everyone 的拒絕通常就足夠，但既有 role/member overwrite 若明確允許
    # Send Messages，Discord 仍可能讓該身分聊天。只修正「已存在」的 overwrite，
    # 其餘權限（可見性、管理權等）原樣保留，不重建整張權限表。
    for target, existing_overwrite in list(getattr(channel, "overwrites", {}).items()):
        if target == default_role or target == getattr(guild, "me", None):
            continue

        if apply_display_only_permissions(existing_overwrite):
            await channel.set_permissions(
                target,
                overwrite=existing_overwrite,
                reason="Keep companion presence channel display-only",
            )
            changed = True

    return changed


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
                await ensure_dispatch_presence_channel_display_only(channel)

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
                f"[dispatch-presence] channel sync failed: {exc}",
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
