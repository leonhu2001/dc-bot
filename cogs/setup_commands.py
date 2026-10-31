from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands

from core.vip_levels import build_topup_rebate_public_summary
from services.topup_runtime import ensure_topup_credit_worker_started
from services.payment_review_runtime import ensure_payment_review_worker_started
from services.vip_timer_self_service import install_vip_timer_self_service
from services.quick_order_v2 import install_quick_order_v2
from services.quick_order_v2_fixes import install_quick_order_v2_fixes
from services.quick_order_v2_production import install_quick_order_v2_production
from services.quick_order_v2_select_display import install_quick_order_v2_select_display
from services.custom_order_quick_entry import install_custom_order_quick_entry
from services.discord_vip_channel_access import install_discord_vip_channel_access
from services.order_ticket_name_restore_runtime import install_order_ticket_name_restore
from views.market import install_market_discord
from views.member_portal import (
    MEMBER_PORTAL_CHANNEL_ID,
    MEMBER_PORTAL_MARKER,
    MemberPortalView,
    build_member_portal_embed,
)
from views.panels import MainPanelView, build_main_panel_embed
from views.topups import TopupPanelView
from views.staff_management import (
    StaffManagementPanelView,
    validate_staff_panel_commands,
)
from views.voice import (
    get_or_create_play_voice_lobby,
    get_or_create_vip_voice_lobby,
    get_or_create_public_voice_lobby,
)


class SetupCommands(commands.Cog):
    setup = app_commands.Group(name="setup", description="面板與語音入口設定")

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        install_vip_timer_self_service()
        install_quick_order_v2_fixes(bot)
        install_quick_order_v2_production(bot)
        install_quick_order_v2(bot)
        install_quick_order_v2_select_display(bot)
        install_custom_order_quick_entry(bot)
        install_discord_vip_channel_access()
        install_order_ticket_name_restore(bot)
        install_market_discord(bot)

        if not getattr(
            bot,
            "_staff_management_panel_view_registered",
            False,
        ):
            bot.add_view(
                StaffManagementPanelView()
            )
            bot._staff_management_panel_view_registered = True

        ensure_topup_credit_worker_started(bot)
        ensure_payment_review_worker_started(bot)
        if not getattr(bot, "_topup_panel_view_registered", False):
            bot.add_view(TopupPanelView())
            bot._topup_panel_view_registered = True

        if not getattr(bot, "_member_portal_view_registered", False):
            bot.add_view(MemberPortalView())
            bot._member_portal_view_registered = True

        if not getattr(bot, "_member_portal_sync_task_started", False):
            bot._member_portal_sync_task_started = True
            bot.loop.create_task(self._sync_member_portal_panel())

    async def _sync_member_portal_panel(self) -> None:
        """Refresh the existing member portal in place after every bot restart."""
        await self.bot.wait_until_ready()

        channel = self.bot.get_channel(MEMBER_PORTAL_CHANNEL_ID)
        if not isinstance(channel, discord.TextChannel):
            try:
                fetched = await self.bot.fetch_channel(MEMBER_PORTAL_CHANNEL_ID)
            except (discord.NotFound, discord.Forbidden, discord.HTTPException) as exc:
                print(
                    f"[member-portal] channel lookup failed: {type(exc).__name__}: {exc}",
                    flush=True,
                )
                return
            channel = fetched if isinstance(fetched, discord.TextChannel) else None

        if channel is None or self.bot.user is None:
            return

        target_message: discord.Message | None = None
        try:
            async for message in channel.history(limit=100, oldest_first=False):
                if message.author.id != self.bot.user.id or not message.embeds:
                    continue
                embed = message.embeds[0]
                footer_text = str(getattr(embed.footer, "text", "") or "")
                if embed.title == "👤 我的專區" or footer_text == MEMBER_PORTAL_MARKER:
                    target_message = message
                    break
        except (discord.Forbidden, discord.HTTPException) as exc:
            print(
                f"[member-portal] history scan failed: {type(exc).__name__}: {exc}",
                flush=True,
            )
            return

        try:
            if target_message is None:
                target_message = await channel.send(
                    embed=build_member_portal_embed(),
                    view=MemberPortalView(),
                )
                action = "created"
            else:
                await target_message.edit(
                    embed=build_member_portal_embed(),
                    view=MemberPortalView(),
                )
                action = "refreshed"
        except (discord.Forbidden, discord.HTTPException) as exc:
            print(
                f"[member-portal] panel sync failed: {type(exc).__name__}: {exc}",
                flush=True,
            )
            return

        print(
            f"[member-portal] panel {action}: channel={channel.id} message={target_message.id}",
            flush=True,
        )

    @setup.command(
        name="panel",
        description="建立魔丸娛樂客服面板",
    )
    @app_commands.checks.has_permissions(administrator=True)
    @app_commands.default_permissions(manage_messages=True)
    async def setup_panel(self, interaction: discord.Interaction):
        if not isinstance(interaction.channel, discord.TextChannel):
            await interaction.response.send_message("請在文字頻道使用這個指令。", ephemeral=True)
            return

        await interaction.channel.send(embed=build_main_panel_embed(), view=MainPanelView())
        await interaction.response.send_message("客服面板已建立。", ephemeral=True)

    @setup.command(
        name="staff_panel",
        description="建立客服專用管理中心 Panel",
    )
    @app_commands.checks.has_permissions(administrator=True)
    @app_commands.default_permissions(manage_messages=True)
    async def setup_staff_panel(
        self,
        interaction: discord.Interaction,
    ):
        if not isinstance(
            interaction.channel,
            discord.TextChannel,
        ):
            await interaction.response.send_message(
                "請在文字頻道使用這個指令。", ephemeral=True
            )
            return

        missing = validate_staff_panel_commands(
            self.bot,
            interaction.guild_id,
        )

        if missing:
            await interaction.response.send_message(
                "客服管理中心目前缺少對應功能：\n"
                + "\n".join(
                    f"- `{item}`"
                    for item in missing
                )
                + "\n請先重新啟動並同步 Bot 指令。",
                ephemeral=True,
            )
            return

        embed = discord.Embed(
            title="🧭 魔丸娛樂｜客服管理中心",
            description=(
                "客服日常操作集中入口。\n\n"
                "📦 **訂單管理**｜搜尋與查看訂單\n"
                "💤 **存單管理**｜查看與管理目前存單\n"
                "👤 **顧客管理**｜會員資料與顧客備註\n"
                "💰 **會員 / 錢包**｜會員資料與錢包流水\n"
                "📊 **營運查詢**｜今日、本月與消費排行\n"
                "🛠️ **系統工具**｜資料健康檢查\n\n"
                "所有操作結果僅操作人員本人可見。"
            ),
            color=discord.Color.purple(),
        )

        await interaction.channel.send(
            embed=embed,
            view=StaffManagementPanelView(),
        )

        await interaction.response.send_message(
            "客服管理中心 Panel 已建立。",
            ephemeral=True,
        )

    @setup.command(
        name="topup_panel",
        description="建立或更新魔丸娛樂儲值中心面板",
    )
    @app_commands.describe(
        message_id="要原地更新的 Panel 訊息 ID；不填則建立新 Panel",
    )
    @app_commands.checks.has_permissions(administrator=True)
    @app_commands.default_permissions(manage_messages=True)
    async def setup_topup_panel(
        self,
        interaction: discord.Interaction,
        message_id: str | None = None,
    ):
        if not isinstance(interaction.channel, discord.TextChannel):
            await interaction.response.send_message("請在文字頻道使用這個指令。", ephemeral=True)
            return

        embed = discord.Embed(
            title="💰 魔丸娛樂｜儲值中心",
            description=(
                "可於此處進行魔丸錢包儲值。\n"
                "付款完成並經客服確認後，系統會自動入帳並同步 VIP 進度。\n\n"
                "**VIP 儲值回饋**\n"
                f"{build_topup_rebate_public_summary()}\n"
                "本次儲值若達成新 VIP 等級，當筆即套用新等級返利。"
            ),
            color=discord.Color.gold(),
        )
        view = TopupPanelView()

        if message_id:
            raw_message_id = str(message_id).strip()
            if not raw_message_id.isdigit():
                await interaction.response.send_message(
                    "訊息 ID 格式不正確，請貼上純數字訊息 ID。",
                    ephemeral=True,
                )
                return

            target_message_id = int(raw_message_id)
            try:
                target_message = await interaction.channel.fetch_message(target_message_id)
            except discord.NotFound:
                await interaction.response.send_message(
                    "找不到這則訊息，請確認是在該 Panel 所在的頻道執行指令。",
                    ephemeral=True,
                )
                return
            except discord.Forbidden:
                await interaction.response.send_message(
                    "Bot 沒有讀取或編輯這個頻道訊息的權限。",
                    ephemeral=True,
                )
                return
            except discord.HTTPException as exc:
                await interaction.response.send_message(
                    f"讀取 Panel 失敗：{exc}",
                    ephemeral=True,
                )
                return

            bot_user = self.bot.user
            if bot_user is None or target_message.author.id != bot_user.id:
                await interaction.response.send_message(
                    "只能更新由目前 Bot 自己發送的 Panel 訊息。",
                    ephemeral=True,
                )
                return

            try:
                await target_message.edit(embed=embed, view=view)
            except discord.Forbidden:
                await interaction.response.send_message(
                    "Bot 沒有編輯這則 Panel 的權限。",
                    ephemeral=True,
                )
                return
            except discord.HTTPException as exc:
                await interaction.response.send_message(
                    f"更新 Panel 失敗：{exc}",
                    ephemeral=True,
                )
                return

            await interaction.response.send_message(
                f"儲值中心 Panel `{target_message_id}` 已原地更新。",
                ephemeral=True,
            )
            return

        await interaction.channel.send(embed=embed, view=view)
        await interaction.response.send_message("儲值中心面板已建立。", ephemeral=True)

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
