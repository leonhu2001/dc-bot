from __future__ import annotations

import re
import unicodedata

import discord

from services import quick_order_v2 as quick


_PRICE_LIST_LABEL_BY_CHANNEL_ID = {
    int(quick.QUICK_ORDER_V2_CHANNELS["delta"]): "三角洲行動",
    int(quick.QUICK_ORDER_V2_CHANNELS["valorant"]): "VALORANT",
    int(quick.QUICK_ORDER_V2_CHANNELS["lol"]): "英雄聯盟",
    int(quick.QUICK_ORDER_V2_CHANNELS["apex"]): "APEX",
    int(quick.QUICK_ORDER_V2_CHANNELS["steam"]): "STEAM",
}


def _display_width(value: str) -> int:
    return sum(
        2 if unicodedata.east_asian_width(char) in {"W", "F"} else 1
        for char in str(value)
    )


def _aligned_code_block(rows: tuple[tuple[str, str], ...]) -> str:
    """Render two-column Discord price rows with CJK-aware spacing."""
    if not rows:
        return "```text\n```"
    label_width = max(_display_width(label) for label, _ in rows)
    lines = []
    for label, value in rows:
        padding = " " * (label_width - _display_width(label) + 4)
        lines.append(f"{label}{padding}{value}")
    return "```text\n" + "\n".join(lines) + "\n```"


DELTA_PRICE_LIST_CATEGORIES = (
    ("desktop", "端遊", "🖥️"),
    ("mobile", "手遊", "📱"),
    ("farm", "代肝代解", "🛠️"),
    ("fun", "趣味單", "🎉"),
)

DELTA_MOBILE_PRICE_LISTS = {
    "trial": {
        "label": "體驗單",
        "text": f"""**體驗單**
{_aligned_code_block((("777W", "400T"), ("1688W", "800T")))}""",
    },
    "guarantee": {
        "label": "保底單",
        "text": f"""**累積保底**
{_aligned_code_block((("1500W", "600T"), ("4200W", "2000T"), ("110M", "4000T"), ("300M", "10000T")))}""",
    },
    "big_red": {
        "label": "大紅單",
        "text": f"""**累積帶出**
{_aligned_code_block((("1 大紅", "1000T"), ("5 大紅", "4000T"), ("10 大紅", "7000T")))}
📌 **大紅定義**
價值 **100萬以上** 的紅色物資即計為大紅。""",
    },
    "babel": {
        "label": "絕巴保底單",
        "text": f"""**絕巴保底方案**
{_aligned_code_block((("基礎方案", "600T"), ("進階方案", "3000T"), ("最強方案", "5000T"), ("三幻神挑戰", "5000T")))}
**基礎方案**
2 個沙色保險 ＋ 800W 保底

**進階方案**
累積 10 個沙色保險 ＋ 6000W 保底

**最強方案**
累積 20 個沙色保險 ＋ 100M 保底

**三幻神挑戰**
三幻神任一出現即完成
⚠️ **不出不結單**""",
    },
    "entertainment": {
        "label": "娛樂陪",
        "text": f"""**娛樂陪**
{_aligned_code_block((("單陪", "320T / H"), ("雙陪", "600T / H")))}
🎁 **娛樂陪累積回饋**
{_aligned_code_block((("計時", "累積 10 小時 → 贈送 1 小時券"),))}

📌 **指定陪玩**
{_aligned_code_block((("指定打手／陪玩", "每人 +100T"),))}
⚠️ **2H 或 2局以上免指定費**""",
    },
    "sweet": {
        "label": "甜蜜單",
        "text": f"""**甜蜜單**
{_aligned_code_block((("單陪", "520T / H"), ("雙陪", "1314T / H")))}
📌 **指定陪玩**
{_aligned_code_block((("指定打手／陪玩", "每人 +100T"),))}
⚠️ **2H 或 2局以上免指定費**""",
    },
    "teaching": {
        "label": "教學單",
        "text": f"""**1對1教學**
{_aligned_code_block((("每人", "500T / H"),))}
📌 **指定人員**
{_aligned_code_block((("指定打手／教學人員", "每人 +100T"),))}
⚠️ **2H 或 2局以上免指定費**""",
    },
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
{_aligned_code_block((("NG", "每人 300T / H"), ("積分", "每人 250T / 局")))}

{_rank_heading(interaction, "Ascendant", "超凡陪")}
{_aligned_code_block((("NG", "每人 330T / H"), ("積分", "每人 290T / 局")))}

{_rank_heading(interaction, "Immortal", "神話陪")}
{_aligned_code_block((("NG", "每人 350T / H"), ("積分", "每人 330T / 局")))}

{_rank_heading(interaction, "Radiant", "輻能陪")}
{_aligned_code_block((("NG", "每人 380T / H"), ("積分", "每人 370T / 局")))}

🎁 **娛樂陪累積回饋**
{_aligned_code_block((("計局", "累積 15 局 → 贈送 1 局券"), ("計時", "累積 10 小時 → 贈送 1 小時券")))}

📌 **指定陪玩**
{_aligned_code_block((("指定打手／陪玩", "每人 +100T"),))}
⚠️ **2H 或 2局以上免指定費**"""


def _apex_price_list(interaction: discord.Interaction) -> str:
    return f"""**娛樂陪**
{_aligned_code_block((("NG", "每人 300T / H"), ("積分", "每人 350T / H")))}

{_rank_heading(interaction, "Diamond", "鑽石陪")}
{_aligned_code_block((("NG", "每人 400T / H"), ("積分", "每人 450T / H")))}

{_rank_heading(interaction, "Master~1", "大師陪")}
{_aligned_code_block((("NG", "每人 480T / H"), ("積分", "每人 530T / H")))}

{_rank_heading(interaction, "Predator", "頂獵陪")}
{_aligned_code_block((("NG", "每人 580T / H"), ("積分", "每人 630T / H")))}

🎁 **娛樂陪累積回饋**
{_aligned_code_block((("計時", "累積 10 小時 → 贈送 1 小時券"),))}

📌 **指定陪玩**
{_aligned_code_block((("指定打手／陪玩", "每人 +100T"),))}
⚠️ **2H 以上免指定費**"""


def _lol_price_list(interaction: discord.Interaction) -> str:
    return f"""**娛樂陪**
{_aligned_code_block((("ARAM", "每人 300T / H"), ("NG", "每人 300T / H"), ("積分", "每人 250T / 局")))}

{_rank_heading(interaction, "Master", "大師陪")}
{_aligned_code_block((("NG", "每人 340T / H"), ("積分", "每人 300T / 局")))}

{_rank_heading(interaction, "Grandmaster", "宗師陪")}
{_aligned_code_block((("NG", "每人 360T / H"), ("積分", "每人 300T / 局")))}

{_rank_heading(interaction, "Challenger", "菁英陪")}
{_aligned_code_block((("NG", "每人 400T / H"), ("積分", "每人 400T / 局")))}

🎁 **娛樂陪累積回饋**
{_aligned_code_block((("計局", "累積 15 局 → 贈送 1 局券"), ("計時", "累積 10 小時 → 贈送 1 小時券")))}

📌 **指定陪玩**
{_aligned_code_block((("指定打手／陪玩", "每人 +100T"),))}
⚠️ **2H 或 2局以上免指定費**"""


def _steam_price_list(_: discord.Interaction) -> str:
    return f"""**娛樂陪**
{_aligned_code_block((("一般陪玩", "每人 320T / H"),))}

📌 **指定陪玩**
{_aligned_code_block((("指定打手／陪玩", "每人 +100T"),))}
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


def _delta_category_label(value: str) -> str:
    for key, label, _ in DELTA_PRICE_LIST_CATEGORIES:
        if key == value:
            return label
    return "三角洲行動"


def _delta_root_embed() -> discord.Embed:
    return discord.Embed(
        title="📋 三角洲行動・價目表",
        description="請先選擇價目表分類。",
        color=discord.Color.blurple(),
    )


def _delta_category_embed(category: str) -> discord.Embed:
    label = _delta_category_label(category)
    description = (
        "請選擇要查看的單子。"
        if category == "mobile"
        else "此分類價目表內容整理中。"
    )
    return discord.Embed(
        title=f"📋 三角洲行動・{label}價目",
        description=description,
        color=discord.Color.blurple(),
    )


def _delta_mobile_embed(plan_key: str) -> discord.Embed:
    plan = DELTA_MOBILE_PRICE_LISTS[plan_key]
    return discord.Embed(
        title=f"📋 三角洲行動・手遊・{plan['label']}",
        description=str(plan["text"]),
        color=discord.Color.blurple(),
    )


class DeltaPriceListCategorySelect(discord.ui.Select):
    def __init__(self, selected: str | None = None):
        super().__init__(
            placeholder="請選擇價目表分類",
            min_values=1,
            max_values=1,
            row=0,
            custom_id="quick_order_v2_delta_price_list_category",
            options=[
                discord.SelectOption(
                    label=label,
                    value=value,
                    emoji=emoji,
                    default=value == selected,
                )
                for value, label, emoji in DELTA_PRICE_LIST_CATEGORIES
            ],
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        category = str(self.values[0])
        await interaction.response.edit_message(
            embed=_delta_category_embed(category),
            view=DeltaPriceListView(category=category),
        )


class DeltaMobilePriceListSelect(discord.ui.Select):
    def __init__(self, selected: str | None = None):
        super().__init__(
            placeholder="請選擇手遊單子",
            min_values=1,
            max_values=1,
            row=1,
            custom_id="quick_order_v2_delta_mobile_price_list",
            options=[
                discord.SelectOption(
                    label=str(plan["label"]),
                    value=key,
                    default=key == selected,
                )
                for key, plan in DELTA_MOBILE_PRICE_LISTS.items()
            ],
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        plan_key = str(self.values[0])
        await interaction.response.edit_message(
            embed=_delta_mobile_embed(plan_key),
            view=DeltaPriceListView(category="mobile", mobile_plan=plan_key),
        )


class DeltaPriceListView(discord.ui.View):
    def __init__(
        self,
        category: str | None = None,
        mobile_plan: str | None = None,
    ):
        super().__init__(timeout=180)
        self.add_item(DeltaPriceListCategorySelect(selected=category))
        if category == "mobile":
            self.add_item(DeltaMobilePriceListSelect(selected=mobile_plan))


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
        if self.source_channel_id == int(quick.QUICK_ORDER_V2_CHANNELS["delta"]):
            await interaction.response.send_message(
                embed=_delta_root_embed(),
                view=DeltaPriceListView(),
                ephemeral=True,
            )
            return

        label = _PRICE_LIST_LABEL_BY_CHANNEL_ID.get(
            self.source_channel_id,
            "遊戲",
        )
        embed = discord.Embed(
            title=f"📋 {label}・陪玩價目",
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
    "DELTA_MOBILE_PRICE_LISTS",
    "DELTA_PRICE_LIST_CATEGORIES",
    "DeltaPriceListView",
    "QuickPriceListButton",
    "add_price_list_control",
    "has_price_list",
]
