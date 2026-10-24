from __future__ import annotations

import discord
from discord.ext import commands

from services import quick_order_v2 as quick
from services.quick_order_v2_assets import public_order_panel_image_url


_INSTALLED = False

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


def panel_image_filename(channel_id: int) -> str | None:
    return _IMAGE_FILENAME_BY_CHANNEL_ID.get(int(channel_id))


def panel_image_url(channel_id: int) -> str | None:
    filename = panel_image_filename(channel_id)
    if not filename:
        return None
    return public_order_panel_image_url(filename)


def _looks_like_legacy_artwork_message(
    message: discord.Message,
    *,
    filename: str,
) -> bool:
    """Return True only for obsolete standalone image-only panel messages."""
    if message.components:
        return False
    if str(message.content or "").strip():
        return False

    expected = str(filename).lower()
    stem = expected[:-4] if expected.endswith(".png") else expected

    for attachment in message.attachments:
        name = str(getattr(attachment, "filename", "") or "").lower()
        if name == expected or (name.startswith(stem + "_") and name.endswith(".png")):
            return True

    for embed in message.embeds:
        image_url = str(getattr(getattr(embed, "image", None), "url", "") or "").lower()
        if expected in image_url or (stem and stem in image_url and ".png" in image_url):
            return True

    return False


async def cleanup_legacy_artwork_messages(
    channel: discord.TextChannel,
    *,
    bot_user_id: int | None,
    filename: str,
) -> int:
    """Delete obsolete image-only messages without touching the active panel."""
    removed = 0
    async for message in channel.history(limit=50):
        if bot_user_id is not None and message.author.id != bot_user_id:
            continue
        if not _looks_like_legacy_artwork_message(message, filename=filename):
            continue
        try:
            await message.delete()
            removed += 1
        except (discord.NotFound, discord.Forbidden, discord.HTTPException):
            continue
    return removed


async def refresh_quick_order_panel_images(bot: commands.Bot) -> None:
    """Compatibility refresh through the currently installed canonical panel owner."""
    await bot.wait_until_ready()
    for channel_id in _IMAGE_FILENAME_BY_CHANNEL_ID:
        try:
            await quick._ensure_panel(bot, channel_id)
        except Exception as exc:
            print(
                f"[quick-order-panel-image] refresh failed {channel_id}: "
                f"{type(exc).__name__}: {exc}",
                flush=True,
            )


def install_quick_order_v2_panel_images(bot: commands.Bot) -> None:
    """Legacy-compatible installer; runtime panel ownership lives elsewhere."""
    global _INSTALLED
    if _INSTALLED:
        return

    if not getattr(bot, "_quick_order_v2_panel_images_started", False):
        bot._quick_order_v2_panel_images_started = True
        bot.loop.create_task(refresh_quick_order_panel_images(bot))

    _INSTALLED = True
    print("[quick-order-panel-image] helper/repair layer installed", flush=True)


__all__ = [
    "cleanup_legacy_artwork_messages",
    "install_quick_order_v2_panel_images",
    "panel_image_filename",
    "panel_image_url",
    "refresh_quick_order_panel_images",
]
