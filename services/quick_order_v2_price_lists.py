from __future__ import annotations

import discord
from discord.ext import commands

from services import quick_order_v2 as quick
from services import quick_order_v2_production as production
from services.quick_order_v2_assets import public_order_panel_image_url


_INSTALLED = False
_ORIGINAL_VIEW_FOR_CHANNEL = None
_ORIGINAL_DELTA_CALLBACK = None
_ORIGINAL_ENTRY_EMBED = None

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

_PRICE_LIST_IMAGE_BY_CHANNEL_ID = {
    int(quick.QUICK_ORDER_V2_CHANNELS["lol"]): "pricelists/lol_pricelist.png",
    int(quick.QUICK_ORDER_V2_CHANNELS["valorant"]): "pricelists/valorant_pricelist.png",
}

_APEX_PRICE_LIST_TEXT = """**娛樂陪**
NG｜每人 **300T / H**
積分｜每人 **350T / H**

**鑽石陪**
NG｜每人 **400T / H**
積分｜每人 **450T / H**

**大師陪**
NG｜每人 **500T / H**
積分｜每人 **550T / H**

**頂獵陪**
NG｜每人 **600T / H**
積分｜每人 **650T / H**

🎁 **娛樂陪累積福利**
累積 10 小時 → 送 1 小時券

👤 **指定打手／陪玩**
每人 +100T
⚠️ 兩單（2H）以上免指定費"""

# Temporary copy for games whose image price list has not been supplied yet.
_PRICE_LIST_TEXT_BY_CHANNEL_ID = {
    channel_id: "價目表內容整理中，稍後更新。"
    for channel_id in _PRICE_LIST_LABEL_BY_CHANNEL_ID
}
_PRICE_LIST_TEXT_BY_CHANNEL_ID[int(quick.QUICK_ORDER_V2_CHANNELS["apex"])] = (
    _APEX_PRICE_LIST_TEXT
)


def _delta_cover_url(category: str) -> str | None:
    filename = _DELTA_COVER_BY_CATEGORY.get(str(category))
    if not filename:
        return None
    return public_order_panel_image_url(filename)


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
        embed = discord.Embed(
            title=f"📋 {label}｜價目表",
            color=discord.Color.blurple(),
        )

        image_path = _PRICE_LIST_IMAGE_BY_CHANNEL_ID.get(self.source_channel_id)
        image_url = public_order_panel_image_url(image_path) if image_path else None
        if image_url is not None:
            embed.description = "點擊圖片可放大查看。"
            embed.set_image(url=image_url)
        else:
            embed.description = _PRICE_LIST_TEXT_BY_CHANNEL_ID.get(
                self.source_channel_id,
                "價目表內容整理中，稍後更新。",
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

    image_url = _delta_cover_url(self.category)
    if image_url is not None:
        embed.set_image(url=image_url)
    elif self.category in _DELTA_COVER_BY_CATEGORY:
        print(
            f"[quick-order-price] delta cover missing/invalid category={self.category} "
            f"expected={_DELTA_COVER_BY_CATEGORY.get(str(self.category))}",
            flush=True,
        )

    await interaction.response.send_message(
        embed=embed,
        view=view,
        ephemeral=True,
    )


def _install_delta_cover_callback() -> None:
    global _ORIGINAL_DELTA_CALLBACK
    if _ORIGINAL_DELTA_CALLBACK is not None:
        return

    _ORIGINAL_DELTA_CALLBACK = quick.QuickDeltaCategoryButton.callback
    production._clean_delta_callback = _delta_category_callback
    quick.QuickDeltaCategoryButton.callback = _delta_category_callback


async def _refresh_delta_panel(bot: commands.Bot) -> None:
    await bot.wait_until_ready()
    try:
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

    for channel_id in _PRICE_LIST_LABEL_BY_CHANNEL_ID:
        bot.add_view(quick._view_for_channel(channel_id))

    if not getattr(bot, "_quick_order_v2_price_panel_refresh_started", False):
        bot._quick_order_v2_price_panel_refresh_started = True
        bot.loop.create_task(_refresh_delta_panel(bot))

    _INSTALLED = True
    print("[quick-order-price] price buttons and public delta covers installed", flush=True)


__all__ = [
    "QuickPriceListButton",
    "install_quick_order_v2_price_lists",
]
