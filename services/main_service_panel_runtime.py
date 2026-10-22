from __future__ import annotations

import discord
from discord.ext import commands

from views.panels import MainPanelView, build_main_panel_embed


MAIN_SERVICE_CHANNEL_ID = 1497622678138519572


async def sync_main_service_panel(bot: commands.Bot) -> None:
    """Update the existing service-lobby panel in place after order entry moved out."""
    await bot.wait_until_ready()

    channel = bot.get_channel(MAIN_SERVICE_CHANNEL_ID)
    if not isinstance(channel, discord.TextChannel):
        try:
            fetched = await bot.fetch_channel(MAIN_SERVICE_CHANNEL_ID)
            channel = fetched if isinstance(fetched, discord.TextChannel) else None
        except (discord.NotFound, discord.Forbidden, discord.HTTPException):
            channel = None

    if not isinstance(channel, discord.TextChannel):
        print(
            f"[main-service-panel] channel not found: {MAIN_SERVICE_CHANNEL_ID}",
            flush=True,
        )
        return

    target: discord.Message | None = None
    try:
        async for message in channel.history(limit=100):
            if bot.user is not None and message.author.id != bot.user.id:
                continue
            titles = {str(embed.title or "") for embed in message.embeds}
            if titles.intersection({
                "魔丸娛樂客服中心",
                "魔丸娛樂｜服務大廳",
                "魔丸娛樂｜客服中心",
            }):
                target = message
                break
    except (discord.Forbidden, discord.HTTPException) as exc:
        print(
            f"[main-service-panel] scan failed: {type(exc).__name__}: {exc}",
            flush=True,
        )
        return

    if target is None:
        print(
            "[main-service-panel] existing panel not found; skipped creating a duplicate",
            flush=True,
        )
        return

    try:
        await target.edit(embed=build_main_panel_embed(), view=MainPanelView())
        print("[main-service-panel] support-only panel synced", flush=True)
    except (discord.Forbidden, discord.HTTPException) as exc:
        print(
            f"[main-service-panel] update failed: {type(exc).__name__}: {exc}",
            flush=True,
        )


def install_main_service_panel_sync(bot: commands.Bot) -> None:
    if getattr(bot, "_main_service_panel_sync_started", False):
        return
    bot._main_service_panel_sync_started = True
    bot.loop.create_task(sync_main_service_panel(bot))


__all__ = [
    "MAIN_SERVICE_CHANNEL_ID",
    "install_main_service_panel_sync",
    "sync_main_service_panel",
]
