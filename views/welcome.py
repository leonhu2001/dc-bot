from __future__ import annotations

import re

import discord


PROFILE_CHANNEL_IDS = (
    1538270157057691660,
    1538270089785245856,
)
SUPPORT_CHANNEL_ID = 1497622678138519572
PRICE_LIST_CHANNEL_ID = 1569412217269395597
GAME_ORDER_CHANNELS = (
    ("🔺 三角洲", 1562940108246753331),
    ("🎯 特戰英豪", 1562940127976890509),
    ("⚔️ 英雄聯盟", 1562940161313087498),
    ("🕹️ Steam 遊戲", 1562940249171042415),
    ("🏹 APEX", 1562940146632888450),
)


def build_welcome_description(member_mention: str) -> str:
    game_links = "\n".join(
        f"{label}：<#{channel_id}>"
        for label, channel_id in GAME_ORDER_CHANNELS
    )
    return (
        f"🎉 **歡迎 {member_mention} 來到魔丸娛樂！**\n\n"
        "歡迎加入我們 ฅ՞•ﻌ•՞ฅ\n\n"
        "👤 **挑選陪玩／打手**\n"
        f"<#{PROFILE_CHANNEL_IDS[0]}> ・ <#{PROFILE_CHANNEL_IDS[1]}>\n"
        "先看看大家的個人牆，找到喜歡的陪玩！\n\n"
        "📖 **下單前先看價目表**\n"
        f"<#{PRICE_LIST_CHANNEL_ID}>\n\n"
        "🎮 **各遊戲下單區**\n"
        f"{game_links}\n\n"
        "🔔 **需要真人客服？**\n"
        f"前往 <#{SUPPORT_CHANNEL_ID}>，按 **🔔 呼叫客服** "
        "即可建立／開啟私人客服票口。\n"
        "🕒 客服服務時間：**AM 10:00－隔日 AM 2:00**\n\n"
        "**祝你在魔丸玩得開心 🖤**"
    )


def build_welcome_embed(
    member_mention: str,
    *,
    avatar_url: str | None = None,
) -> discord.Embed:
    embed = discord.Embed(
        description=build_welcome_description(member_mention),
        color=discord.Color.green(),
    )
    if avatar_url:
        embed.set_thumbnail(url=avatar_url)
    return embed



def extract_welcome_member_mention(description: str | None) -> str | None:
    if not description or "來到魔丸娛樂" not in description:
        return None

    match = re.search(r"<@!?\d+>", description)
    return match.group(0) if match else None
