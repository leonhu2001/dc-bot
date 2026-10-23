from __future__ import annotations

import hashlib
from pathlib import Path

import discord
from discord.ext import commands

from services import quick_order_v2 as quick
from services import quick_order_v2_production as production


_INSTALLED = False
_ORIGINAL_ENSURE_PANEL = None

_WEB_STATIC_DIR = (
    Path(__file__).resolve().parents[1]
    / "web"
    / "app"
    / "static"
    / "order_panels"
)
_PUBLIC_BASE_URL = "https://mowanentertainment.com/static/order_panels"
_IMAGE_FILENAME_BY_KEY = {
    "apex": "apex_panel.png",
    "lol": "lol_panel.png",
    "steam": "steam_panel.png",
    "valorant": "valorant_panel.png",
}
_IMAGE_FILENAME_BY_CHANNEL_ID = {
    int(quick.QUICK_ORDER_V2_CHANNELS[key]): filename
    for key, filename in _IMAGE_FILENAME_BY_KEY.items()
}


def _image_url(channel_id: int) -> str | None:
    """Return a public static URL for a valid deployed PNG.

    The file is served by the existing FastAPI /static mount. A content hash is
    appended as a query string so Discord does not keep an old cached image when
    the local artwork is replaced later.
    """
    filename = _IMAGE_FILENAME_BY_CHANNEL_ID.get(int(channel_id))
    if not filename:
        return None

    path = _WEB_STATIC_DIR / filename
    if not path.is_file():
        return None

    try:
        data = path.read_bytes()
    except OSError:
        return None

    if not data.startswith(b"\x89PNG\r\n\x1a\n"):
        return None

    digest = hashlib.sha256(data).hexdigest()[:12]
    return f"{_PUBLIC_BASE_URL}/{filename}?v={digest}"


async def _find_existing_panel_message(
    channel: discord.TextChannel,
    channel_id: int,
    bot_user_id: int | None,
) -> discord.Message | None:
    async for message in channel.history(limit=50):
        if bot_user_id is not None and message.author.id != bot_user_id:
            continue
        if production._is_existing_entry_panel(message, channel_id):
            return message
    return None


def _install_panel_sync() -> None:
    global _ORIGINAL_ENSURE_PANEL
    if _ORIGINAL_ENSURE_PANEL is not None:
        return

    _ORIGINAL_ENSURE_PANEL = production._clean_ensure_panel
    original = _ORIGINAL_ENSURE_PANEL

    async def image_ensure_panel(bot: commands.Bot, channel_id: int) -> None:
        channel_id = int(channel_id)
        if channel_id not in _IMAGE_FILENAME_BY_CHANNEL_ID:
            await original(bot, channel_id)
            return

        channel = bot.get_channel(channel_id)
        if not isinstance(channel, discord.TextChannel):
            try:
                fetched = await bot.fetch_channel(channel_id)
                channel = fetched if isinstance(fetched, discord.TextChannel) else None
            except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                channel = None

        if not isinstance(channel, discord.TextChannel):
            print(f"[quick-order-panel-image] channel not found: {channel_id}", flush=True)
            return

        embed = production._clean_entry_embed(channel_id)
        image_url = _image_url(channel_id)
        if image_url:
            # External image URL keeps the artwork inside the Discord embed. No
            # message attachment is used, so it cannot render as a separate block.
            embed.set_image(url=image_url)

        view = quick._view_for_channel(channel_id)

        target: discord.Message | None = None
        try:
            target = await _find_existing_panel_message(
                channel,
                channel_id,
                getattr(bot.user, "id", None),
            )
        except (discord.Forbidden, discord.HTTPException):
            target = None

        try:
            if target is None:
                await channel.send(embed=embed, view=view)
            else:
                # Explicitly clear the old Discord attachment from the previous
                # rollout, then keep only the normal embed + its external image.
                await target.edit(
                    embed=embed,
                    view=view,
                    attachments=[],
                )
        except (discord.Forbidden, discord.HTTPException, OSError, ValueError, TypeError) as exc:
            print(
                f"[quick-order-panel-image] sync failed {channel_id}: "
                f"{type(exc).__name__}: {exc}",
                flush=True,
            )
            return

        if image_url:
            print(
                f"[quick-order-panel-image] embedded image ready: {channel_id} {image_url}",
                flush=True,
            )
        else:
            print(
                f"[quick-order-panel-image] PNG missing; kept text-only panel: {channel_id}",
                flush=True,
            )

    production._clean_ensure_panel = image_ensure_panel
    quick._ensure_panel = image_ensure_panel


async def refresh_quick_order_panel_images(bot: commands.Bot) -> None:
    await bot.wait_until_ready()
    for channel_id in _IMAGE_FILENAME_BY_CHANNEL_ID:
        try:
            await production._clean_ensure_panel(bot, channel_id)
        except Exception as exc:
            # One broken channel must not prevent the remaining game panels from
            # being refreshed.
            print(
                f"[quick-order-panel-image] refresh failed {channel_id}: "
                f"{type(exc).__name__}: {exc}",
                flush=True,
            )


def install_quick_order_v2_panel_images(bot: commands.Bot) -> None:
    global _INSTALLED
    if _INSTALLED:
        return

    _install_panel_sync()

    if not getattr(bot, "_quick_order_v2_panel_images_started", False):
        bot._quick_order_v2_panel_images_started = True
        bot.loop.create_task(refresh_quick_order_panel_images(bot))

    _INSTALLED = True
    print("[quick-order-panel-image] embed-image layer installed", flush=True)


__all__ = [
    "install_quick_order_v2_panel_images",
    "refresh_quick_order_panel_images",
]
