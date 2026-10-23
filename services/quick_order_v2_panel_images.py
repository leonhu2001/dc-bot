from __future__ import annotations

import base64
import io
from pathlib import Path

import discord
from discord.ext import commands

from services import quick_order_v2 as quick
from services import quick_order_v2_production as production


_INSTALLED = False
_ORIGINAL_ENTRY_BUILDER = None
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


def _image_bytes(channel_id: int) -> tuple[str, bytes] | None:
    filename = _IMAGE_FILENAME_BY_CHANNEL_ID.get(int(channel_id))
    if not filename:
        return None

    png_path = _ASSET_DIR / filename
    if png_path.is_file():
        try:
            return filename, png_path.read_bytes()
        except OSError:
            pass

    fallback_path = _ASSET_DIR / f"{filename}.b64"
    if not fallback_path.is_file():
        return None

    try:
        raw = fallback_path.read_text(encoding="utf-8").strip()
        return filename, base64.b64decode(raw, validate=True)
    except (OSError, ValueError, base64.binascii.Error):
        return None


def _image_file(channel_id: int) -> discord.File | None:
    payload = _image_bytes(channel_id)
    if payload is None:
        return None
    filename, data = payload
    return discord.File(io.BytesIO(data), filename=filename)


def _install_entry_builder() -> None:
    global _ORIGINAL_ENTRY_BUILDER
    if _ORIGINAL_ENTRY_BUILDER is not None:
        return

    _ORIGINAL_ENTRY_BUILDER = production._clean_entry_embed
    original = _ORIGINAL_ENTRY_BUILDER

    def image_entry_embed(channel_id: int) -> discord.Embed:
        embed = original(channel_id)
        payload = _image_bytes(channel_id)
        if payload is not None:
            filename, _ = payload
            embed.set_image(url=f"attachment://{filename}")
        return embed

    production._clean_entry_embed = image_entry_embed
    quick.build_entry_embed = image_entry_embed


def _install_panel_sync() -> None:
    global _ORIGINAL_ENSURE_PANEL
    if _ORIGINAL_ENSURE_PANEL is not None:
        return

    _ORIGINAL_ENSURE_PANEL = production._clean_ensure_panel
    original = _ORIGINAL_ENSURE_PANEL

    async def image_ensure_panel(bot: commands.Bot, channel_id: int) -> None:
        if int(channel_id) not in _IMAGE_FILENAME_BY_CHANNEL_ID:
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
        view = quick._view_for_channel(channel_id)
        file = _image_file(channel_id)
        if file is None:
            await original(bot, channel_id)
            return

        target: discord.Message | None = None
        try:
            async for message in channel.history(limit=50):
                if bot.user is not None and message.author.id != bot.user.id:
                    continue
                if any(str(item.title or "") == str(embed.title or "") for item in message.embeds):
                    target = message
                    break
        except (discord.Forbidden, discord.HTTPException):
            pass

        try:
            if target is None:
                await channel.send(embed=embed, view=view, file=file)
            else:
                await target.edit(embed=embed, view=view, attachments=[file])
        except (discord.Forbidden, discord.HTTPException) as exc:
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
        await production._clean_ensure_panel(bot, channel_id)


def install_quick_order_v2_panel_images(bot: commands.Bot) -> None:
    global _INSTALLED
    if _INSTALLED:
        return

    _install_entry_builder()
    _install_panel_sync()

    if not getattr(bot, "_quick_order_v2_panel_images_started", False):
        bot._quick_order_v2_panel_images_started = True
        bot.loop.create_task(refresh_quick_order_panel_images(bot))

    _INSTALLED = True
    print("[quick-order-panel-image] game panel images installed", flush=True)


__all__ = [
    "install_quick_order_v2_panel_images",
    "refresh_quick_order_panel_images",
]
