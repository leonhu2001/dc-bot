from __future__ import annotations

import re

import discord

from services import quick_order_v2 as quick


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
    """Resolve a server custom emoji by the shortcode the owner uses in Discord."""
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
⚠️ **2H 或 2局以上免指定費**"""


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


def has_price_list(channel_id: int) -> bool:
    return int(channel_id) in _PRICE_LIST_LABEL_BY_CHANNEL_ID


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


def add_price_list_control(view: discord.ui.View, channel_id: int) -> discord.ui.View:
    """Decorate a canonical public quick-order view without patching its factory."""
    if has_price_list(channel_id):
        view.add_item(QuickPriceListButton(int(channel_id)))
    return view


__all__ = [
    "QuickPriceListButton",
    "add_price_list_control",
    "has_price_list",
]
