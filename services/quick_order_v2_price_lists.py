from __future__ import annotations

import hashlib
from pathlib import Path

import discord
from discord.ext import commands

from services import quick_order_v2 as quick
from services import quick_order_v2_production as production


_INSTALLED = False
_ORIGINAL_VIEW_FOR_CHANNEL = None
_ORIGINAL_DELTA_CALLBACK = None
_ORIGINAL_ENTRY_EMBED = None

_ASSET_DIR = Path(__file__).resolve().parents[1] / "assets" / "order_panels"
_DELTA_COVER_BY_CATEGORY = {
    "delta_desktop_fun": "delta_fun_panel.png",
}

_PRICE_LIST_LABEL_BY_CHANNEL_ID = {
    int(quick.QUICK_ORDER_V2_CHANNELS["delta"]): "三角洲行動",
    int(quick.QUICK_ORDER_V2_CHANNELS["valorant"]): "特戰英豪",
    int(quick.QUICK_ORDER_V2_CHANNELS["lol"]): "英雄聯盟",
    int(quick.QUICK_ORDER_V2_CHANNELS["apex"]): "APEX",
    int(quick.QUICK_ORDER_V2_CHANNELS["steam"]): "STEAM",
}

# Temporary copy. The store-specific text can be replaced here later without
# touching the ordering flow or panel layout.
_PRICE_LIST_TEXT_BY_CHANNEL_ID = {
    channel_id: "價目表內容整理中，稍後更新。"
    for channel_id in _PRICE_LIST_LABEL_BY_CHANNEL_ID
}


def _delta_cover_asset(category: str) -> tuple[Path, str] | None:
    filename = _DELTA_COVER_BY_CATEGORY.get(str(category))
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


class QuickPriceListButton(discord.ui.Button):
    def __init__(self, channel_id: int):
        self.source_channel_id = int(channel_id)
        super().__init__(
            label="查看價目表",
            emoji="📋",
            style=discord.ButtonStyle.secondary,
            row=1,
            custom_id=f"quick_order_v2_price_list_{self.source_channel_id}",
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        label = _PRICE_LIST_LABEL_BY_CHANNEL_ID.get(
            self.source_channel_id,
            "遊戲",
        )
        text = _PRICE_LIST_TEXT_BY_CHANNEL_ID.get(
            self.source_channel_id,
            "價目表內容整理中，稍後更新。",
        )
        embed = discord.Embed(
            title=f"📋 {label}｜價目表",
            description=text,
            color=discord.Color.blurple(),
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)


def _install_entry_copy() -> None:
    """Keep Delta's public copy as compact as the other game panels."""
    global _ORIGINAL_ENTRY_EMBED
    if _ORIGINAL_ENTRY_EMBED is not None:
        return

    _ORIGINAL_ENTRY_EMBED = production._clean_entry_embed
    original = _ORIGINAL_ENTRY_EMBED

    def compact_entry_embed(channel_id: int) -> discord.Embed:
        embed = original(channel_id)
        if int(channel_id) == int(quick.QUICK_ORDER_V2_CHANNELS["delta"]):
            embed.description = "請選擇你要的服務。"
        return embed

    production._clean_entry_embed = compact_entry_embed
    quick.build_entry_embed = compact_entry_embed


def _install_view_factory() -> None:
    global _ORIGINAL_VIEW_FOR_CHANNEL
    if _ORIGINAL_VIEW_FOR_CHANNEL is not None:
        return

    _ORIGINAL_VIEW_FOR_CHANNEL = quick._view_for_channel
    original = _ORIGINAL_VIEW_FOR_CHANNEL

    def price_view_for_channel(channel_id: int) -> discord.ui.View:
        view = original(channel_id)
        if int(channel_id) in _PRICE_LIST_LABEL_BY_CHANNEL_ID:
            view.add_item(QuickPriceListButton(int(channel_id)))
        return view

    quick._view_for_channel = price_view_for_channel


async def _delta_category_callback(
    self: quick.QuickDeltaCategoryButton,
    interaction: discord.Interaction,
) -> None:
    if not quick._options(self.category):
        await interaction.response.send_message(
            "這個分類目前沒有可下單服務。",
            ephemeral=True,
        )
        return

    embed = discord.Embed(
        title=f"{self.category_emoji} 三角洲行動｜{self.category_label}",
        description="請選擇服務。",
        color=discord.Color.green(),
    )
    view = discord.ui.View(timeout=180)
    view.add_item(
        quick.QuickServiceSelect(
            category=self.category,
            source_channel_id=quick.QUICK_ORDER_V2_CHANNELS["delta"],
            persistent=False,
        )
    )

    asset = _delta_cover_asset(self.category)
    if asset is None:
        print(
            f"[quick-order-price] delta cover missing category={self.category} "
            f"expected={_DELTA_COVER_BY_CATEGORY.get(str(self.category))}",
            flush=True,
        )
        await interaction.response.send_message(
            embed=embed,
            view=view,
            ephemeral=True,
        )
        return

    path, attachment_name = asset
    embed.set_image(url=f"attachment://{attachment_name}")
    try:
        await interaction.response.send_message(
            embed=embed,
            view=view,
            ephemeral=True,
            file=discord.File(path, filename=attachment_name),
        )
    except (discord.HTTPException, OSError, ValueError, TypeError) as exc:
        print(
            f"[quick-order-price] delta cover failed category={self.category}: "
            f"{type(exc).__name__}: {exc}",
            flush=True,
        )
        if not interaction.response.is_done():
            await interaction.response.send_message(
                embed=discord.Embed(
                    title=f"{self.category_emoji} 三角洲行動｜{self.category_label}",
                    description="請選擇服務。",
                    color=discord.Color.green(),
                ),
                view=view,
                ephemeral=True,
            )


def _install_delta_cover_callback() -> None:
    global _ORIGINAL_DELTA_CALLBACK
    if _ORIGINAL_DELTA_CALLBACK is not None:
        return

    _ORIGINAL_DELTA_CALLBACK = quick.QuickDeltaCategoryButton.callback

    # Make this callback authoritative no matter which display layer installs
    # first. production.install_quick_order_v2_production() assigns the class
    # callback from production._clean_delta_callback, so replace both references.
    production._clean_delta_callback = _delta_category_callback
    quick.QuickDeltaCategoryButton.callback = _delta_category_callback


async def _refresh_delta_panel(bot: commands.Bot) -> None:
    await bot.wait_until_ready()
    try:
        # Existing public panels are edited in place. No delete/re-send means
        # routine copy or button changes do not generate a new-message alert.
        await quick._ensure_panel(
            bot,
            int(quick.QUICK_ORDER_V2_CHANNELS["delta"]),
        )
    except Exception as exc:
        print(
            f"[quick-order-price] delta panel refresh failed: "
            f"{type(exc).__name__}: {exc}",
            flush=True,
        )


def install_quick_order_v2_price_lists(bot: commands.Bot) -> None:
    global _INSTALLED
    if _INSTALLED:
        return

    _install_entry_copy()
    _install_view_factory()
    _install_delta_cover_callback()

    # quick_order_v2 registered its persistent views before this display layer was
    # installed. Re-register the five customer-facing game views so the new price
    # buttons also survive bot restarts. Existing custom_ids are intentionally the
    # same; discord.py updates the dispatch mapping to these current view objects.
    for channel_id in _PRICE_LIST_LABEL_BY_CHANNEL_ID:
        bot.add_view(quick._view_for_channel(channel_id))

    if not getattr(bot, "_quick_order_v2_price_panel_refresh_started", False):
        bot._quick_order_v2_price_panel_refresh_started = True
        bot.loop.create_task(_refresh_delta_panel(bot))

    _INSTALLED = True
    print("[quick-order-price] price buttons and delta covers installed", flush=True)


__all__ = [
    "QuickPriceListButton",
    "install_quick_order_v2_price_lists",
]
