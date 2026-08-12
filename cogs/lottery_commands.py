
from __future__ import annotations

import random
from typing import Iterable

import discord
from discord import app_commands
from discord.ext import commands

from core.permissions import is_customer_staff, is_manager_or_admin
from services.lottery import record_lottery_draw


GIVEAWAY_EMOJI = "🎉"


class LotteryCommands(commands.Cog):
    """全店免費反應抽獎。

    參加方式：
    - 管理 / 客服使用 /lottery panel 發送抽獎訊息
    - 顧客在訊息底下按 🎉
    - 每個 Discord 帳號同一個表情只能按一次，所以自然每人只算一次
    """

    lottery = app_commands.Group(
        name="lottery",
        description="魔丸全店反應抽獎",
    )

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    def is_lottery_admin(self, member: discord.Member) -> bool:
        return is_customer_staff(member) or is_manager_or_admin(member)

    async def _fetch_giveaway_message(
        self,
        interaction: discord.Interaction,
        message_id: str,
        channel: discord.TextChannel | discord.Thread | None = None,
    ) -> discord.Message | None:
        target_channel = channel or interaction.channel

        if not isinstance(target_channel, (discord.TextChannel, discord.Thread)):
            await interaction.followup.send("請在文字頻道使用，或指定抽獎訊息所在頻道。", ephemeral=True)
            return None

        try:
            snowflake = int(str(message_id).strip())
        except ValueError:
            await interaction.followup.send("訊息 ID 格式不正確。", ephemeral=True)
            return None

        try:
            return await target_channel.fetch_message(snowflake)
        except discord.NotFound:
            await interaction.followup.send("找不到這則抽獎訊息，請確認訊息 ID 和頻道是否正確。", ephemeral=True)
        except discord.Forbidden:
            await interaction.followup.send("Bot 沒有權限讀取這個頻道的訊息。", ephemeral=True)
        except discord.HTTPException as exc:
            await interaction.followup.send(f"讀取抽獎訊息失敗：{exc}", ephemeral=True)

        return None

    async def _collect_participants(self, message: discord.Message) -> list[discord.User | discord.Member]:
        participants: dict[int, discord.User | discord.Member] = {}

        for reaction in message.reactions:
            if str(reaction.emoji) != GIVEAWAY_EMOJI:
                continue

            async for user in reaction.users(limit=None):
                if user.bot:
                    continue

                participants[int(user.id)] = user

        return list(participants.values())

    def _build_panel_embed(
        self,
        *,
        prize: str,
        description: str | None = None,
    ) -> discord.Embed:
        embed = discord.Embed(
            title="🎁 魔丸全店抽獎活動",
            description=(
                f"**獎品：** {prize}\n\n"
                f"**參加方式：** 按下方 {GIVEAWAY_EMOJI} 表情即可參加\n"
                "**參加限制：** 每人限參加 1 次\n"
                "**消耗：** 不消耗點數、不消耗任何東西"
            ),
            color=discord.Color.gold(),
        )

        if description:
            embed.add_field(name="活動說明", value=description[:1024], inline=False)

        embed.set_footer(text="開獎時會從按下 🎉 的成員中隨機抽出得獎者。")
        return embed

    @lottery.command(
        name="panel",
        description="發送全店免費反應抽獎面板",
    )
    @app_commands.describe(
        prize="抽獎獎品，例如：免費陪玩 1 小時",
        description="活動說明，可不填",
    )
    async def giveaway_panel(
        self,
        interaction: discord.Interaction,
        prize: str,
        description: str | None = None,
    ):
        if not isinstance(interaction.user, discord.Member) or not self.is_lottery_admin(interaction.user):
            await interaction.response.send_message("只有客服、店長或管理員可以發送抽獎面板。", ephemeral=True)
            return

        if not isinstance(interaction.channel, (discord.TextChannel, discord.Thread)):
            await interaction.response.send_message("請在文字頻道使用這個指令。", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)

        embed = self._build_panel_embed(
            prize=str(prize).strip(),
            description=str(description or "").strip() or None,
        )

        message = await interaction.channel.send(
            content="@everyone 🎁 魔丸全店抽獎開始！按下 🎉 參加抽獎！",
            embed=embed,
            allowed_mentions=discord.AllowedMentions(everyone=True, roles=False, users=False),
        )
        await message.add_reaction(GIVEAWAY_EMOJI)

        await interaction.followup.send(
            f"已發送抽獎面板。\n訊息 ID：`{message.id}`\n開獎請用：`/lottery draw message_id:{message.id}`",
            ephemeral=True,
        )

    @lottery.command(
        name="status",
        description="查看某則抽獎訊息目前參加人數",
    )
    @app_commands.describe(
        message_id="抽獎面板訊息 ID",
        channel="抽獎訊息所在頻道，不填則使用目前頻道",
    )
    async def giveaway_status(
        self,
        interaction: discord.Interaction,
        message_id: str,
        channel: discord.TextChannel | None = None,
    ):
        if not isinstance(interaction.user, discord.Member) or not self.is_lottery_admin(interaction.user):
            await interaction.response.send_message("只有客服、店長或管理員可以查看抽獎狀態。", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)

        message = await self._fetch_giveaway_message(interaction, message_id, channel)

        if message is None:
            return

        participants = await self._collect_participants(message)
        preview = "\n".join(user.mention for user in participants[:25]) or "目前沒有人參加"

        if len(participants) > 25:
            preview += f"\n...另有 {len(participants) - 25} 人"

        embed = discord.Embed(
            title="🎉 抽獎參加狀態",
            description=f"目前參加人數：**{len(participants)} 人**",
            color=discord.Color.blurple(),
        )
        embed.add_field(name="參加名單預覽", value=preview[:1024], inline=False)
        embed.add_field(name="抽獎訊息", value=f"[點我查看]({message.jump_url})", inline=False)

        await interaction.followup.send(embed=embed, ephemeral=True)

    @lottery.command(
        name="draw",
        description="從抽獎訊息的 🎉 反應名單中開獎",
    )
    @app_commands.describe(
        message_id="抽獎面板訊息 ID",
        winners="得獎人數，預設 1",
        prize="本次開出的獎品名稱，可不填",
        channel="抽獎訊息所在頻道，不填則使用目前頻道",
    )
    async def giveaway_draw(
        self,
        interaction: discord.Interaction,
        message_id: str,
        winners: int = 1,
        prize: str | None = None,
        channel: discord.TextChannel | None = None,
    ):
        if not isinstance(interaction.user, discord.Member) or not self.is_lottery_admin(interaction.user):
            await interaction.response.send_message("只有客服、店長或管理員可以開獎。", ephemeral=True)
            return

        if winners <= 0:
            await interaction.response.send_message("得獎人數必須大於 0。", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=False)

        message = await self._fetch_giveaway_message(interaction, message_id, channel)

        if message is None:
            return

        participants = await self._collect_participants(message)

        if not participants:
            await interaction.followup.send("目前沒有人按 🎉 參加抽獎。", ephemeral=True)
            return

        picked_count = min(int(winners), len(participants))
        picked = random.sample(participants, picked_count)

        prize_text = str(prize or "抽獎獎品").strip() or "抽獎獎品"
        winner_mentions = "\n".join(f"{index}. {user.mention}" for index, user in enumerate(picked, start=1))

        for user in picked:
            try:
                record_lottery_draw("free-reaction", prize_text, int(user.id), int(interaction.user.id))
            except Exception as exc:
                print(f"保存免費反應抽獎結果失敗：{exc}")

        embed = discord.Embed(
            title="🎉 魔丸全店抽獎開獎",
            description=(
                f"**獎品：** {prize_text}\n"
                f"**參加人數：** {len(participants)} 人\n"
                f"**得獎人數：** {picked_count} 人\n\n"
                f"{winner_mentions}"
            ),
            color=discord.Color.green(),
        )
        embed.add_field(name="抽獎訊息", value=f"[點我查看]({message.jump_url})", inline=False)
        embed.set_footer(text="本次抽獎不消耗點數，每人依 🎉 反應限算一次。")

        await interaction.followup.send(
            content="@everyone 🎉 魔丸全店抽獎開獎啦！恭喜得獎者！",
            embed=embed,
            allowed_mentions=discord.AllowedMentions(everyone=True, roles=False, users=True),
        )


async def setup(bot: commands.Bot):
    await bot.add_cog(LotteryCommands(bot))
