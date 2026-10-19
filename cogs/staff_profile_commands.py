from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands

from core.permissions import has_role, is_customer_staff
from views.staff_profiles import (
    CustomerFavoritesView,
    PublicStaffProfileBrowseView,
    StaffProfilePanelView,
    build_customer_favorites_embed,
    build_staff_profile_embed,
    find_profile_card_image_url,
    get_staff_profile,
    list_customer_favorites,
    save_staff_profile_panel_message,
    upsert_staff_profile,
)


async def _fetch_staff_profile_panel_target(
    guild: discord.Guild,
    profile: dict,
):
    channel_id_text = str(
        profile.get("forum_thread_id")
        or profile.get("forum_channel_id")
        or ""
    ).strip()
    message_id_text = str(profile.get("panel_message_id") or "").strip()

    if not channel_id_text or not message_id_text:
        return None, None, "這位成員還沒有記錄個人牆 panel 位置，請先在個人牆貼文內使用 /staff_profile_panel。"

    try:
        channel_id = int(channel_id_text)
        message_id = int(message_id_text)
    except (TypeError, ValueError):
        return None, None, "個人牆 panel 位置資料格式錯誤，請重新使用 /staff_profile_panel 生成一次。"

    channel = None

    try:
        get_thread = getattr(guild, "get_thread", None)
        if callable(get_thread):
            channel = get_thread(channel_id)

        if channel is None:
            channel = guild.get_channel(channel_id)

        if channel is None:
            channel = await guild.fetch_channel(channel_id)
    except (discord.NotFound, discord.Forbidden, discord.HTTPException):
        channel = None

    if channel is None or not hasattr(channel, "fetch_message"):
        return None, None, "找不到原本的個人牆頻道或貼文，請確認貼文是否還存在。"

    try:
        message = await channel.fetch_message(message_id)
    except discord.NotFound:
        return channel, None, "找不到原本的個人牆 panel 訊息，請重新使用 /staff_profile_panel 生成一次。"
    except discord.Forbidden:
        return channel, None, "Bot 沒有權限讀取或編輯原本的個人牆 panel。"
    except discord.HTTPException as exc:
        return channel, None, f"讀取個人牆 panel 失敗：{exc}"

    return channel, message, None


class StaffProfileCommands(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    def require_customer_staff_or_manager(
        self,
        interaction: discord.Interaction,
    ) -> bool:
        manager_role_id = int(getattr(self.bot, "manager_role_id_value", 0) or 0)
        return (
            isinstance(interaction.user, discord.Member)
            and (
                is_customer_staff(interaction.user)
                or has_role(interaction.user, manager_role_id)
                or interaction.user.guild_permissions.administrator
            )
        )

    @app_commands.command(
        name="my_favorites",
        description="查看你收藏的成員",
    )
    async def my_favorites(self, interaction: discord.Interaction):
        customer_id = str(interaction.user.id)
        favorites = list_customer_favorites(customer_id, limit=25)
        embed = build_customer_favorites_embed(customer_id, favorites)

        if favorites:
            await interaction.response.send_message(
                embed=embed,
                view=CustomerFavoritesView(customer_id, favorites),
                ephemeral=True,
            )
        else:
            await interaction.response.send_message(
                embed=embed,
                ephemeral=True,
            )

    @app_commands.command(
        name="browse_staff_profiles",
        description="瀏覽公開成員個人牆",
    )
    @app_commands.describe(keyword="可搜尋名稱、遊戲、服務或階級，可不填")
    async def browse_staff_profiles(
        self,
        interaction: discord.Interaction,
        keyword: str | None = None,
    ):
        keyword_text = str(keyword or "").strip()[:60]
        view = PublicStaffProfileBrowseView(
            interaction.user.id,
            keyword=keyword_text,
            page=0,
            page_size=10,
        )

        if view.children:
            await interaction.response.send_message(
                embed=view.build_embed(),
                view=view,
                ephemeral=True,
                allowed_mentions=discord.AllowedMentions(
                    users=False,
                    roles=False,
                    everyone=False,
                ),
            )
        else:
            await interaction.response.send_message(
                embed=view.build_embed(),
                ephemeral=True,
                allowed_mentions=discord.AllowedMentions(
                    users=False,
                    roles=False,
                    everyone=False,
                ),
            )

    @app_commands.command(
        name="staff_profile_panel",
        description="客服在成員個人牆貼文內生成或更新成員 panel",
    )
    @app_commands.describe(
        member="這個個人牆對應的成員",
        role_title="階級，例如：護航、女護、頂護",
        games="主要遊戲，例如：三角洲",
        services="服務類型，例如：護航 / 技術陪",
        bio="個人特色，例如：穩定、報點清楚、耐心",
        profile_type="類型，例如：打手、陪玩、主播",
        display_name="顯示名稱，可不填，預設使用 Discord 暱稱",
    )
    @app_commands.default_permissions(manage_messages=True)
    async def staff_profile_panel(
        self,
        interaction: discord.Interaction,
        member: discord.Member,
        role_title: str,
        games: str,
        services: str,
        bio: str,
        profile_type: str = "打手",
        display_name: str | None = None,
    ):
        if not self.require_customer_staff_or_manager(interaction):
            await interaction.response.send_message(
                "只有客服、店長或管理員可以建立個人牆 panel。",
                ephemeral=True,
            )
            return

        channel = interaction.channel
        if channel is None or not hasattr(channel, "send"):
            await interaction.response.send_message(
                "請在成員個人牆貼文或文字頻道內使用此指令。",
                ephemeral=True,
            )
            return

        await interaction.response.defer(ephemeral=True)

        parent_id = None
        if isinstance(channel, discord.Thread):
            parent_id = getattr(channel.parent, "id", None)

        image_url = await find_profile_card_image_url(channel)
        profile = upsert_staff_profile(
            staff_id=member.id,
            display_name=display_name or member.display_name,
            profile_type=profile_type,
            role_title=role_title,
            main_games=games,
            service_tags=services,
            bio=bio,
            card_image_url=image_url,
            forum_thread_id=getattr(channel, "id", None),
            forum_channel_id=parent_id or getattr(channel, "id", None),
            is_public=True,
        )

        old_message_id = 0
        try:
            old_message_id = int(str(profile.get("panel_message_id") or "0"))
        except (TypeError, ValueError):
            old_message_id = 0

        view = StaffProfilePanelView(member.id)
        embed = build_staff_profile_embed(profile)
        panel_message = None
        action_text = "已生成"

        if old_message_id and hasattr(channel, "fetch_message"):
            try:
                panel_message = await channel.fetch_message(old_message_id)
                await panel_message.edit(
                    embed=embed,
                    view=view,
                    allowed_mentions=discord.AllowedMentions(
                        users=False,
                        roles=False,
                        everyone=False,
                    ),
                )
                action_text = "已更新"
            except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                panel_message = None

        if panel_message is None:
            panel_message = await channel.send(
                embed=embed,
                view=view,
                allowed_mentions=discord.AllowedMentions(
                    users=False,
                    roles=False,
                    everyone=False,
                ),
            )
            action_text = "已生成"

        save_staff_profile_panel_message(
            staff_id=member.id,
            panel_message_id=panel_message.id,
            forum_thread_id=getattr(channel, "id", None),
            forum_channel_id=parent_id or getattr(channel, "id", None),
        )

        try:
            self.bot.add_view(
                StaffProfilePanelView(member.id),
                message_id=panel_message.id,
            )
        except ValueError:
            pass

        image_note = (
            "已抓到貼文圖片作為名片圖。"
            if image_url
            else "沒有抓到圖片；panel 仍已建立，可之後重新執行指令更新。"
        )
        await interaction.followup.send(
            f"{action_text} {member.mention} 的個人牆 panel。\n{image_note}",
            ephemeral=True,
            allowed_mentions=discord.AllowedMentions(
                users=False,
                roles=False,
                everyone=False,
            ),
        )

    @app_commands.command(
        name="refresh_staff_profile_panel",
        description="將後台個人牆資料同步到 Discord panel",
    )
    @app_commands.describe(member="要同步個人牆 panel 的成員")
    @app_commands.default_permissions(manage_messages=True)
    async def refresh_staff_profile_panel(
        self,
        interaction: discord.Interaction,
        member: discord.Member,
    ):
        if not self.require_customer_staff_or_manager(interaction):
            await interaction.response.send_message(
                "只有客服、店長或管理員可以同步個人牆 panel。",
                ephemeral=True,
            )
            return

        if interaction.guild is None:
            await interaction.response.send_message(
                "這個指令只能在伺服器內使用。",
                ephemeral=True,
            )
            return

        await interaction.response.defer(ephemeral=True)

        profile = get_staff_profile(member.id)
        if profile is None:
            await interaction.followup.send(
                "找不到這位成員的個人牆資料，請先建立 /staff_profile_panel。",
                ephemeral=True,
            )
            return

        channel, panel_message, error_message = (
            await _fetch_staff_profile_panel_target(
                interaction.guild,
                profile,
            )
        )

        if error_message:
            await interaction.followup.send(error_message, ephemeral=True)
            return

        view = StaffProfilePanelView(member.id)
        embed = build_staff_profile_embed(profile)

        try:
            await panel_message.edit(
                embed=embed,
                view=view,
                allowed_mentions=discord.AllowedMentions(
                    users=False,
                    roles=False,
                    everyone=False,
                ),
            )
        except discord.Forbidden:
            await interaction.followup.send(
                "Bot 沒有權限編輯這則個人牆 panel。",
                ephemeral=True,
            )
            return
        except discord.HTTPException as exc:
            await interaction.followup.send(
                f"同步個人牆 panel 失敗：{exc}",
                ephemeral=True,
            )
            return

        parent_id = None
        if isinstance(channel, discord.Thread):
            parent_id = getattr(channel.parent, "id", None)

        save_staff_profile_panel_message(
            staff_id=member.id,
            panel_message_id=panel_message.id,
            forum_thread_id=getattr(channel, "id", None),
            forum_channel_id=parent_id or getattr(channel, "id", None),
        )

        try:
            self.bot.add_view(
                StaffProfilePanelView(member.id),
                message_id=panel_message.id,
            )
        except ValueError:
            pass

        await interaction.followup.send(
            f"已同步 {member.mention} 的個人牆 panel。\n"
            "後台資料已更新到 Discord 訊息；收藏、指定下單、查看評價按鈕也已重新掛上。",
            ephemeral=True,
            allowed_mentions=discord.AllowedMentions(
                users=False,
                roles=False,
                everyone=False,
            ),
        )


async def setup(bot: commands.Bot):
    await bot.add_cog(StaffProfileCommands(bot))
    guild_id = int(getattr(bot, "guild_id_value", 0) or 0)
    if guild_id:
        bot.tree.copy_global_to(guild=discord.Object(id=guild_id))
