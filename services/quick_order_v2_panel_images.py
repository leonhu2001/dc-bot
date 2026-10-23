from __future__ import annotations

import hashlib
import io
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


def _image_payload(channel_id: int) -> tuple[str, bytes] | None:
    """Load the real PNG deployed beside the bot.

    Do not fall back to the old base64 placeholders. If the PNG is missing we keep
    the normal text-only panel instead of publishing a broken attachment image.
    """
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
    stem = Path(filename).stem
    attachment_name = f"{stem}_{digest}.png"
    return attachment_name, data


def _image_file(channel_id: int) -> tuple[str, discord.File] | None:
    payload = _image_payload(channel_id)
    if payload is None:
        return None
    filename, data = payload
    return filename, discord.File(io.BytesIO(data), filename=filename)


def _find_existing_panel_message(
    channel: discord.TextChannel,
    channel_id: int,
    bot_user_id: int | None,
):
    async def finder() -> discord.Message | None:
        async for message in channel.history(limit=50):
            if bot_user_id is not None and message.author.id != bot_user_id:
                continue
            if production._is_existing_entry_panel(message, channel_id):
                return message
        return None

    return finder()


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

        payload = _image_file(channel_id)
        if payload is None:
            # Missing local asset must never create an attachment:// blank box.
            await original(bot, channel_id)
            print(
                f"[quick-order-panel-image] PNG missing; kept text-only panel: {channel_id}",
                flush=True,
            )
            return

        attachment_name, file = payload

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
        embed.set_image(url=f"attachment://{attachment_name}")
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
            # Discord attachment replacement on an existing embed can leave a stale
            # attachment:// URL. Keep a panel only when it already owns this exact
            # content-addressed attachment; otherwise send the replacement first and
            # delete the old panel afterwards.
            if target is not None and any(
                attachment.filename == attachment_name
                for attachment in target.attachments
            ):
                await target.edit(embed=embed, view=view)
                return

            replacement = await channel.send(embed=embed, view=view, file=file)
            if target is not None and target.id != replacement.id:
                try:
                    await target.delete()
                except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                    pass
        except (discord.Forbidden, discord.HTTPException, OSError, ValueError, TypeError) as exc:
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
            # One broken channel must not prevent the remaining three panels from
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
    print("[quick-order-panel-image] real PNG panel images installed", flush=True)


__all__ = [
    "install_quick_order_v2_panel_images",
    "refresh_quick_order_panel_images",
]
