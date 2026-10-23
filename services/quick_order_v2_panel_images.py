from __future__ import annotations

import discord
from discord.ext import commands

from services import quick_order_v2 as quick
from services import quick_order_v2_production as production
from services.quick_order_v2_assets import public_order_panel_image_url


_INSTALLED = False
_ORIGINAL_ENSURE_PANEL = None

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


async def _find_existing_panels(
    channel: discord.TextChannel,
    channel_id: int,
    bot_user_id: int | None,
) -> list[discord.Message]:
    result: list[discord.Message] = []
    async for message in channel.history(limit=50):
        if bot_user_id is not None and message.author.id != bot_user_id:
            continue
        if production._is_existing_entry_panel(message, channel_id):
            result.append(message)
    return result


def _looks_like_legacy_artwork_message(
    message: discord.Message,
    *,
    filename: str,
    channel_id: int,
) -> bool:
    """Return True only for obsolete image-only panel messages.

    Earlier image experiments could leave a standalone PNG message immediately
    above the real quick-order embed. Those messages should be removed once the
    artwork is rendered through embed.set_image(url=...). Never classify the
    actual entry panel itself as disposable.
    """
    if production._is_existing_entry_panel(message, channel_id):
        return False
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


async def _cleanup_legacy_artwork_messages(
    channel: discord.TextChannel,
    *,
    channel_id: int,
    bot_user_id: int | None,
    filename: str,
) -> int:
    removed = 0
    async for message in channel.history(limit=50):
        if bot_user_id is not None and message.author.id != bot_user_id:
            continue
        if not _looks_like_legacy_artwork_message(
            message,
            filename=filename,
            channel_id=channel_id,
        ):
            continue
        try:
            await message.delete()
            removed += 1
        except (discord.NotFound, discord.Forbidden, discord.HTTPException):
            continue
    return removed


def _install_panel_sync() -> None:
    global _ORIGINAL_ENSURE_PANEL
    if _ORIGINAL_ENSURE_PANEL is not None:
        return

    _ORIGINAL_ENSURE_PANEL = production._clean_ensure_panel
    original = _ORIGINAL_ENSURE_PANEL

    async def image_ensure_panel(bot: commands.Bot, channel_id: int) -> None:
        channel_id = int(channel_id)
        filename = _IMAGE_FILENAME_BY_CHANNEL_ID.get(channel_id)
        if not filename:
            await original(bot, channel_id)
            return

        image_url = public_order_panel_image_url(filename)
        if image_url is None:
            await original(bot, channel_id)
            print(
                f"[quick-order-panel-image] public PNG missing/invalid; kept text-only panel: "
                f"{channel_id} {filename}",
                flush=True,
            )
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

        bot_user_id = getattr(bot.user, "id", None)
        try:
            old_panels = await _find_existing_panels(
                channel,
                channel_id,
                bot_user_id,
            )
        except (discord.Forbidden, discord.HTTPException):
            old_panels = []

        # Remove image-only messages left by the earlier attachment experiments.
        # This creates no new notification and keeps the existing entry panel ID.
        try:
            removed = await _cleanup_legacy_artwork_messages(
                channel,
                channel_id=channel_id,
                bot_user_id=bot_user_id,
                filename=filename,
            )
            if removed:
                print(
                    f"[quick-order-panel-image] removed {removed} legacy artwork message(s): "
                    f"{channel_id}",
                    flush=True,
                )
        except (discord.Forbidden, discord.HTTPException):
            pass

        embed = production._clean_entry_embed(channel_id)
        embed.set_image(url=image_url)
        view = quick._view_for_channel(channel_id)
        target = old_panels[0] if old_panels else None

        try:
            if target is not None:
                # Edit the existing public panel in place so maintenance does not
                # create a new-message notification. attachments=[] also strips
                # attachment:// artwork from this same message if an old build
                # embedded the PNG as an attachment.
                await target.edit(
                    embed=embed,
                    view=view,
                    attachments=[],
                )
                print(
                    f"[quick-order-panel-image] public-URL panel edited in place: "
                    f"{channel_id} {filename}",
                    flush=True,
                )
                return

            # First-time setup only: no existing panel exists in this channel.
            await channel.send(embed=embed, view=view)
            print(
                f"[quick-order-panel-image] public-URL panel created: "
                f"{channel_id} {filename}",
                flush=True,
            )
        except (discord.Forbidden, discord.HTTPException, ValueError, TypeError) as exc:
            print(
                f"[quick-order-panel-image] sync failed {channel_id}: "
                f"{type(exc).__name__}: {exc}",
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

    # Install the price-list layer before refreshing the public panels so the
    # existing messages receive the current controls in the same in-place edit.
    from services.quick_order_v2_price_lists import install_quick_order_v2_price_lists

    install_quick_order_v2_price_lists(bot)

    if not getattr(bot, "_quick_order_v2_panel_images_started", False):
        bot._quick_order_v2_panel_images_started = True
        bot.loop.create_task(refresh_quick_order_panel_images(bot))

    _INSTALLED = True
    print("[quick-order-panel-image] public static-image layer installed", flush=True)


__all__ = [
    "install_quick_order_v2_panel_images",
    "refresh_quick_order_panel_images",
]
