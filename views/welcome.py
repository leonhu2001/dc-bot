from __future__ import annotations

import re

import discord


PROFILE_CHANNEL_IDS = (
    1538270157057691660,
    1538270089785245856,
)
SUPPORT_CHANNEL_ID = 1497622678138519572


def build_welcome_description(member_mention: str) -> str:
    return (
        f"🎉 **歡迎 {member_mention} 來到魔丸娛樂！**\n\n"
        "歡迎加入我們 ฅ՞•ﻌ•՞ฅ\n\n"
        "👤 **挑選陪玩／打手**\n"
        f"<#{PROFILE_CHANNEL_IDS[0]}> ・ <#{PROFILE_CHANNEL_IDS[1]}>\n"
        "先看看大家的個人牆\n\n"
        "🎟️ **下單／客服**\n"
        f"<#{SUPPORT_CHANNEL_ID}>\n"
        "直接下單、詢問服務或尋求協助\n\n"
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
