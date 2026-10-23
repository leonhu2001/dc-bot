from __future__ import annotations

import hashlib
from pathlib import Path

import discord
from discord.ext import commands

from services import quick_order_v2 as quick
from services import quick_order_v2_production as production


_INSTALLED = False
_ORIGINAL_ENSURE_PANEL = None

_ASSET_DIR = Path(__file__).resolve().parents[1] / "assets" / "order_panels"
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


def _image_asset(channel_id: int) -> tuple[Path, str] | None:
    filename = _IMAGE_FILENAME_BY_CHANNEL_ID.get(int(channel_id))
    if not filename:
        return None

    path = _ASSET_DIR / filename
    if not path.is_file():
        return None

    try:
        data = path.read_bytes()
    except OSError:
        return None

    if not data.startswith(b"\x89PNG\r\n\x1a\n"):
        return None

    digest = hashlib.sha256(data).hexdigest()[:12]
    attachment_name = f"{Path(filename).stem}_{digest}.png"
    return path, attachment_name


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

        asset = _image_asset(channel_id)
        if asset is None:
            await original(bot, channel_id)
            print(
                f"[quick-order-panel-image] PNG missing/invalid; kept text-only panel: {channel_id}",
                flush=True,
            )
            return

        path, attachment_name = asset
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

        try:
            old_panels = await _find_existing_panels(
                channel,
                channel_id,
                getattr(bot.user, "id", None),
            )
        except (discord.Forbidden, discord.HTTPException):
            old_panels = []

        embed = production._clean_entry_embed(channel_id)
        embed.set_image(url=f"attachment://{attachment_name}")
        view = quick._view_for_channel(channel_id)

        try:
            replacement = await channel.send(
                embed=embed,
                view=view,
                file=discord.File(path, filename=attachment_name),
            )
        except (discord.Forbidden, discord.HTTPException, OSError, ValueError, TypeError) as exc:
            print(
                f"[quick-order-panel-image] send failed {channel_id}: "
                f"{type(exc).__name__}: {exc}",
                flush=True,
            )
            return

        for message in old_panels:
            if message.id == replacement.id:
                continue
            try:
                await message.delete()
            except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                pass

        print(
            f"[quick-order-panel-image] embedded PNG panel replaced: "
            f"{channel_id} {attachment_name}",
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

    # The price-list button layer wraps quick._view_for_channel. Install it before
    # the four image panels are refreshed so every newly rebuilt panel already has
    # the extra button. It also owns the Delta category-cover callback.
    from services.quick_order_v2_price_lists import install_quick_order_v2_price_lists

    install_quick_order_v2_price_lists(bot)

    if not getattr(bot, "_quick_order_v2_panel_images_started", False):
        bot._quick_order_v2_panel_images_started = True
        bot.loop.create_task(refresh_quick_order_panel_images(bot))

    _INSTALLED = True
    print("[quick-order-panel-image] embedded-attachment layer installed", flush=True)


__all__ = [
    "install_quick_order_v2_panel_images",
    "refresh_quick_order_panel_images",
]
