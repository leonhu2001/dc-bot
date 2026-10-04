from __future__ import annotations

import discord


PROFILE_CHANNEL_IDS = (
    1538270157057691660,
    1538270089785245856,
)
SUPPORT_CHANNEL_ID = 1497622678138519572


def build_welcome_description(member_mention: str) -> str:
    return (
        f"🎉 **歡迎 {member_mention} 來到魔丸娛樂！**\n\n"
        "歡迎加入我們 ฅ՞•ﻌ•՞ฅ\n"
        "👤 想先挑選喜歡的陪玩／打手，可以逛逛個人牆\n"
        f"<#{PROFILE_CHANNEL_IDS[0]}> ・ <#{PROFILE_CHANNEL_IDS[1]}>\n\n"
        "🎫 想直接下單、詢問服務或需要協助\n"
        f"請前往 <#{SUPPORT_CHANNEL_ID}> 聯繫客服\n\n"
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
