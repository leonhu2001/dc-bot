from __future__ import annotations

import re

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
    int(quick.QUICK_ORDER_V2_CHANNELS["valorant"]): "VALORANT",
    int(quick.QUICK_ORDER_V2_CHANNELS["lol"]): "英雄聯盟",
    int(quick.QUICK_ORDER_V2_CHANNELS["apex"]): "APEX",
    int(quick.QUICK_ORDER_V2_CHANNELS["steam"]): "STEAM",
}


def _normalise_emoji_name(value: str) -> str:
    return re.sub(r"[^a-z0-9]", "", str(value or "").casefold())


def _guild_emoji(interaction: discord.Interaction, token: str) -> str:
    """Resolve a server custom emoji by the shortcode the owner uses in Discord.

    Discord's client can display duplicate emoji shortcodes with a ``~1`` suffix,
    while the API may expose either a distinct suffixed name or duplicate base
    names. Try the full normalized name first, then treat ``~N`` as the Nth
    duplicate of the base name. Missing emojis simply fall back to text labels.
    """
    guild = interaction.guild
    if guild is None:
        return ""

    raw = str(token or "").strip().strip(":")
    if not raw:
        return ""

    full_key = _normalise_emoji_name(raw)
    exact = [emoji for emoji in guild.emojis if _normalise_emoji_name(emoji.name) == full_key]
    if exact:
        return str(exact[0])

    duplicate_index: int | None = None
    base = raw
    if "~" in raw:
        candidate, suffix = raw.rsplit("~", 1)
        if suffix.isdigit():
            base = candidate
            duplicate_index = int(suffix)

    base_key = _normalise_emoji_name(base)
    matches = [emoji for emoji in guild.emojis if _normalise_emoji_name(emoji.name) == base_key]
    if not matches:
        return ""

    if duplicate_index is not None and duplicate_index < len(matches):
        return str(matches[duplicate_index])
    return str(matches[0])


def _rank_heading(interaction: discord.Interaction, emoji_token: str, label: str) -> str:
    emoji = _guild_emoji(interaction, emoji_token)
    return f"{emoji} **{label}**" if emoji else f"**{label}**"


def _valorant_price_list(interaction: discord.Interaction) -> str:
    return f"""**娛樂陪**
NG｜每人 **300T / H**
積分｜每人 **250T / 局**

{_rank_heading(interaction, "Ascendant", "超凡陪")}
NG｜每人 **330T / H**
積分｜每人 **290T / 局**

{_rank_heading(interaction, "Immortal", "神話陪")}
NG｜每人 **350T / H**
積分｜每人 **330T / 局**

{_rank_heading(interaction, "Radiant", "輻能陪")}
NG｜每人 **380T / H**
積分｜每人 **370T / 局**

🎁 **娛樂陪累積回饋**
計局｜累積 **15 局** → 贈送 **1 局券**
計時｜累積 **10 小時** → 贈送 **1 小時券**

📌 **指定陪玩**
指定打手／陪玩｜每人 **+100T**
單筆消費滿 **500T** 免指定費"""


def _apex_price_list(interaction: discord.Interaction) -> str:
    return f"""**娛樂陪**
NG｜每人 **300T / H**
積分｜每人 **350T / H**

{_rank_heading(interaction, "Diamond", "鑽石陪")}
NG｜每人 **400T / H**
積分｜每人 **450T / H**

{_rank_heading(interaction, "Master~1", "大師陪")}
NG｜每人 **480T / H**
積分｜每人 **530T / H**

{_rank_heading(interaction, "Predator", "頂獵陪")}
NG｜每人 **580T / H**
積分｜每人 **630T / H**

🎁 **娛樂陪累積回饋**
累積 **10 小時** → 贈送 **1 小時券**

📌 **指定陪玩**
指定打手／陪玩｜每人 **+100T**
⚠️ **2H 以上免指定費**"""


def _lol_price_list(interaction: discord.Interaction) -> str:
    return f"""**娛樂陪**
ARAM｜每人 **300T / H**
NG｜每人 **300T / H**
積分｜每人 **250T / 局**

{_rank_heading(interaction, "Master", "大師陪")}
NG｜每人 **340T / H**
積分｜每人 **300T / 局**

{_rank_heading(interaction, "Grandmaster", "宗師陪")}
NG｜每人 **360T / H**
積分｜每人 **300T / 局**

{_rank_heading(interaction, "Challenger", "菁英陪")}
NG｜每人 **400T / H**
積分｜每人 **400T / 局**

🎁 **娛樂陪累積回饋**
計局｜累積 **15 局** → 贈送 **1 局券**
計時｜累積 **10 小時** → 贈送 **1 小時券**

📌 **指定陪玩**
指定打手／陪玩｜每人 **+100T**
⚠️ **2H 或 2局以上免指定費**"""


def _steam_price_list(_: discord.Interaction) -> str:
    return """**娛樂陪**
每人 **320T / H**

📌 **指定陪玩**
指定打手／陪玩｜每人 **+100T**
⚠️ **2H 以上免指定費**"""


def _price_list_text(interaction: discord.Interaction, channel_id: int) -> str:
    if int(channel_id) == int(quick.QUICK_ORDER_V2_CHANNELS["valorant"]):
        return _valorant_price_list(interaction)
    if int(channel_id) == int(quick.QUICK_ORDER_V2_CHANNELS["lol"]):
        return _lol_price_list(interaction)
    if int(channel_id) == int(quick.QUICK_ORDER_V2_CHANNELS["apex"]):
        return _apex_price_list(interaction)
    if int(channel_id) == int(quick.QUICK_ORDER_V2_CHANNELS["steam"]):
        return _steam_price_list(interaction)
    return "價目表內容整理中，稍後更新。"


def _delta_cover_url(category: str) -> str | None:
    filename = _DELTA_COVER_BY_CATEGORY.get(str(category))
    if not filename:
        return None
    return public_order_panel_image_url(filename)


def _live_vip_timer_eligibility(customer_id: int | str, *, check_open_order: bool = True) -> None:
    """Resolve the shared VIP gate at interaction time instead of a stale import."""
    from services import vip_timer_self_service as self_service

    return self_service.assert_vip_timer_self_service_eligible(
        customer_id,
        check_open_order=check_open_order,
    )


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
            title=f"📋 {label}｜陪玩價目",
            description=_price_list_text(interaction, self.source_channel_id),
            color=discord.Color.blurple(),
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)


def _install_entry_copy() -> None:
    """Keep Delta compact and keep the VIP public gate copy authoritative."""
    global _ORIGINAL_ENTRY_EMBED
    if _ORIGINAL_ENTRY_EMBED is not None:
        return

    _ORIGINAL_ENTRY_EMBED = production._clean_entry_embed
    original = _ORIGINAL_ENTRY_EMBED

    def compact_entry_embed(channel_id: int) -> discord.Embed:
        embed = original(channel_id)
        if int(channel_id) == int(quick.QUICK_ORDER_V2_CHANNELS["delta"]):
            embed.description = "請選擇你要的服務。"
        elif int(channel_id) == int(quick.QUICK_ORDER_V2_CHANNELS["vip_timer"]):
            embed.description = str(embed.description or "").replace(
                "金級會員以上限定。",
                "白金級會員以上限定。",
            )
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


async def _refresh_policy_panels(bot: commands.Bot) -> None:
    await bot.wait_until_ready()
    for key in ("delta", "vip_timer"):
        channel_id = int(quick.QUICK_ORDER_V2_CHANNELS[key])
        try:
            await quick._ensure_panel(bot, channel_id)
        except Exception as exc:
            print(
                f"[quick-order-price] panel refresh failed {channel_id}: "
                f"{type(exc).__name__}: {exc}",
                flush=True,
            )


def install_quick_order_v2_price_lists(bot: commands.Bot) -> None:
    global _INSTALLED
    if _INSTALLED:
        return

    # quick_order_v2 imported the eligibility function early. Route it through a
    # live lookup so the Platinum gate installed by vip_timer_policy_v5 is used.
    quick.assert_vip_timer_self_service_eligible = _live_vip_timer_eligibility
    _install_entry_copy()
    _install_view_factory()
    _install_delta_cover_callback()

    for channel_id in _PRICE_LIST_LABEL_BY_CHANNEL_ID:
        bot.add_view(quick._view_for_channel(channel_id))

    if not getattr(bot, "_quick_order_v2_price_panel_refresh_started", False):
        bot._quick_order_v2_price_panel_refresh_started = True
        bot.loop.create_task(_refresh_policy_panels(bot))

    _INSTALLED = True
    print("[quick-order-price] text price lists and policy panel copy installed", flush=True)


__all__ = [
    "QuickPriceListButton",
    "install_quick_order_v2_price_lists",
]
