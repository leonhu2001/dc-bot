from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands

from views.panels import MainPanelView
from views.voice import (
    get_or_create_play_voice_lobby,
    get_or_create_vip_voice_lobby,
    get_or_create_public_voice_lobby,
)


class SetupCommands(commands.Cog):
    setup = app_commands.Group(name="setup", description="面板與語音入口設定")

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @setup.command(
        name="panel",
        description="建立魔丸娛樂客服面板",
    )
    @app_commands.checks.has_permissions(administrator=True)
    @app_commands.default_permissions(manage_messages=True)
    async def setup_panel(self, interaction: discord.Interaction):
        embed = discord.Embed(
            title="魔丸娛樂客服中心",
            description="歡迎來到魔丸娛樂，點擊下方按鈕聯絡客服",
            color=discord.Color.purple(),
        )

        if not isinstance(interaction.channel, discord.TextChannel):
            await interaction.response.send_message("請在文字頻道使用這個指令。", ephemeral=True)
            return

        await interaction.channel.send(embed=embed, view=MainPanelView())
        await interaction.response.send_message("客服面板已建立。", ephemeral=True)

    @setup.command(
        name="complaint_panel",
        description="建立客訴表單面板",
    )
    @app_commands.checks.has_permissions(administrator=True)
    @app_commands.default_permissions(manage_messages=True)
    async def setup_complaint_panel(self, interaction: discord.Interaction):
        await interaction.response.send_message(
            "客訴功能已整合到「/setup panel」建立的客服中心主面板，不需要另外建立客訴面板。",
            ephemeral=True,
        )


    @setup.command(
        name="feedback_panel",
        description="建立顧客意見箱面板",
    )
    @app_commands.checks.has_permissions(administrator=True)
    @app_commands.default_permissions(manage_messages=True)
    async def setup_feedback_panel(self, interaction: discord.Interaction):
        await interaction.response.send_message(
            "顧客意見功能已整合到「/setup panel」建立的客服中心主面板，不需要另外建立顧客意見箱面板。",
            ephemeral=True,
        )


    @setup.command(
        name="play_voice",
        description="建立陪玩語音入口頻道",
    )
    @app_commands.checks.has_permissions(administrator=True)
    @app_commands.default_permissions(manage_messages=True)
    async def setup_play_voice(self, interaction: discord.Interaction):
        guild = interaction.guild
        if guild is None:
            await interaction.response.send_message("這個功能只能在伺服器內使用。", ephemeral=True)
            return

        lobby_channel = await get_or_create_play_voice_lobby(guild)
        if lobby_channel is None:
            await interaction.response.send_message("建立失敗，請確認 PLAY_VOICE_CATEGORY_ID 是否正確。", ephemeral=True)
            return

        await interaction.response.send_message(f"陪玩語音入口已建立 / 確認存在：{lobby_channel.mention}", ephemeral=True)

    @setup.command(
        name="vip_voice",
        description="建立 VIP 語音入口頻道",
    )
    @app_commands.checks.has_permissions(administrator=True)
    @app_commands.default_permissions(manage_messages=True)
    async def setup_vip_voice(self, interaction: discord.Interaction):
        guild = interaction.guild
        if guild is None:
            await interaction.response.send_message("這個功能只能在伺服器內使用。", ephemeral=True)
            return

        lobby_channel = await get_or_create_vip_voice_lobby(guild)
        if lobby_channel is None:
            await interaction.response.send_message("建立失敗，請確認 PLAY_VOICE_CATEGORY_ID 是否正確。", ephemeral=True)
            return

        await interaction.response.send_message(f"VIP 語音入口已建立 / 確認存在：{lobby_channel.mention}", ephemeral=True)

    @setup.command(
        name="public_voice",
        description="建立公共語音入口頻道",
    )
    @app_commands.checks.has_permissions(administrator=True)
    @app_commands.default_permissions(manage_messages=True)
    async def setup_public_voice(self, interaction: discord.Interaction):
        guild = interaction.guild
        if guild is None:
            await interaction.response.send_message("這個功能只能在伺服器內使用。", ephemeral=True)
            return

        lobby_channel = await get_or_create_public_voice_lobby(guild)
        if lobby_channel is None:
            await interaction.response.send_message("建立失敗，請確認 PLAY_VOICE_CATEGORY_ID 是否正確。", ephemeral=True)
            return

        await interaction.response.send_message(f"公共語音入口已建立 / 確認存在：{lobby_channel.mention}", ephemeral=True)

    async def cog_app_command_error(
        self,
        interaction: discord.Interaction,
        error: app_commands.AppCommandError,
    ):
        if interaction.response.is_done():
            send = interaction.followup.send
        else:
            send = interaction.response.send_message

        if isinstance(error, app_commands.MissingPermissions):
            await send("你需要管理員權限才能使用這個指令。", ephemeral=True)
        elif isinstance(error, discord.Forbidden):
            await send(
                "Bot 權限不足。請確認 Bot 有檢視頻道、傳送訊息、嵌入連結、管理頻道、管理身分組等必要權限。",
                ephemeral=True,
            )
        else:
            await send(f"發生錯誤：{error}", ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(SetupCommands(bot))
