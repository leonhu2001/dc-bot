from __future__ import annotations

import traceback

import discord

from views import member_portal


LEGACY_TOPUP_CHANNEL_ID = 1545133856305447003
_TOPUP_CUSTOM_ID = "mawan_member_portal_topup_v1"
_VIP_CUSTOM_ID = "mawan_member_portal_vip_v1"


class MemberPortalTopupButton(discord.ui.Button):
    def __init__(self) -> None:
        super().__init__(
            label="儲值中心",
            emoji="💳",
            style=discord.ButtonStyle.primary,
            custom_id=_TOPUP_CUSTOM_ID,
            row=1,
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        from views.topups import TopupAmountModal

        await interaction.response.send_modal(TopupAmountModal())


async def _vip_with_cumulative_spend(interaction: discord.Interaction) -> None:
    member = member_portal.get_member_summary(member_portal._member_id(interaction))
    vip_progress = member.get("vip_progress") or {}
    next_name = str(vip_progress.get("next_name") or "").strip()
    if next_name:
        progress_text = (
            f"下一級：**{next_name}**\n"
            f"尚差：**{int(vip_progress.get('remaining') or 0):,}T**"
        )
    else:
        progress_text = "已達最高 VIP 等級 👑"

    embed = discord.Embed(
        title="👑 點數 / VIP",
        color=discord.Color.gold(),
    )
    embed.add_field(
        name="目前等級",
        value=f"**{member.get('vip_name') or '普通魔丸'}**",
        inline=True,
    )
    embed.add_field(
        name="可用點數",
        value=f"**{int(member.get('points') or 0):,} 點**",
        inline=True,
    )
    embed.add_field(
        name="累積消費",
        value=f"**{int(member.get('total_spent') or 0):,}T**",
        inline=True,
    )
    embed.add_field(
        name="升級進度",
        value=progress_text,
        inline=False,
    )
    await interaction.response.send_message(
        embed=embed,
        view=member_portal._link_view(
            "查看 VIP 專區",
            f"{member_portal.MEMBER_PORTAL_URL}#vip",
        ),
        ephemeral=True,
    )


def _build_member_portal_embed_v2() -> discord.Embed:
    embed = member_portal.build_member_portal_embed()
    embed.description = (
        "查詢訂單、錢包、點數 / VIP、會員福利與儲值中心。\n"
        "查詢結果僅自己可見。"
    )
    return embed


def _patch_member_portal_view() -> None:
    if getattr(member_portal.MemberPortalView, "_mowan_20261026_patched", False):
        return

    original_init = member_portal.MemberPortalView.__init__

    def patched_init(self) -> None:
        original_init(self)

        if not any(
            str(getattr(item, "custom_id", "") or "") == _TOPUP_CUSTOM_ID
            for item in self.children
        ):
            self.add_item(MemberPortalTopupButton())

        for item in self.children:
            if str(getattr(item, "custom_id", "") or "") == _VIP_CUSTOM_ID:
                item.callback = _vip_with_cumulative_spend
                break

    member_portal.MemberPortalView.__init__ = patched_init
    member_portal.MemberPortalView._mowan_20261026_patched = True


async def _get_text_channel(bot: discord.Client, channel_id: int):
    channel = bot.get_channel(int(channel_id))
    if channel is None:
        try:
            channel = await bot.fetch_channel(int(channel_id))
        except Exception:
            return None
    if not isinstance(channel, discord.TextChannel):
        return None
    return channel


def _is_member_portal_message(message: discord.Message, bot_user_id: int) -> bool:
    if int(getattr(message.author, "id", 0) or 0) != int(bot_user_id):
        return False
    for embed in list(getattr(message, "embeds", []) or []):
        if str(getattr(embed, "title", "") or "") == "👤 我的專區":
            return True
        footer = getattr(embed, "footer", None)
        if str(getattr(footer, "text", "") or "") == member_portal.MEMBER_PORTAL_MARKER:
            return True
    return False


async def _sync_member_portal_panel(bot: discord.Client) -> None:
    await bot.wait_until_ready()
    bot_user = bot.user
    if bot_user is None:
        return

    channel = await _get_text_channel(bot, member_portal.MEMBER_PORTAL_CHANNEL_ID)
    if channel is None:
        print(
            f"[member-portal] channel not found: {member_portal.MEMBER_PORTAL_CHANNEL_ID}",
            flush=True,
        )
        return

    target = None
    try:
        async for message in channel.history(limit=100):
            if _is_member_portal_message(message, bot_user.id):
                target = message
                break
    except Exception:
        print(f"[member-portal] history scan failed\n{traceback.format_exc()}", flush=True)

    try:
        if target is None:
            target = await channel.send(
                embed=_build_member_portal_embed_v2(),
                view=member_portal.MemberPortalView(),
            )
            print(f"[member-portal] panel created message={target.id}", flush=True)
        else:
            await target.edit(
                embed=_build_member_portal_embed_v2(),
                view=member_portal.MemberPortalView(),
            )
            print(f"[member-portal] panel updated message={target.id}", flush=True)
    except Exception:
        print(f"[member-portal] panel sync failed\n{traceback.format_exc()}", flush=True)

    await _remove_legacy_topup_panel(bot, bot_user.id)


async def _remove_legacy_topup_panel(bot: discord.Client, bot_user_id: int) -> None:
    channel = await _get_text_channel(bot, LEGACY_TOPUP_CHANNEL_ID)
    if channel is None:
        return

    removed = 0
    try:
        async for message in channel.history(limit=100):
            if int(getattr(message.author, "id", 0) or 0) != int(bot_user_id):
                continue
            is_topup_panel = any(
                "儲值中心" in str(getattr(embed, "title", "") or "")
                for embed in list(getattr(message, "embeds", []) or [])
            )
            if not is_topup_panel:
                continue
            await message.delete()
            removed += 1
    except Exception:
        print(f"[member-portal] legacy topup cleanup failed\n{traceback.format_exc()}", flush=True)
        return

    if removed:
        print(f"[member-portal] removed legacy topup panels: {removed}", flush=True)


def install_member_portal_20261026(bot: discord.Client) -> None:
    _patch_member_portal_view()

    if not getattr(bot, "_member_portal_view_registered", False):
        bot.add_view(member_portal.MemberPortalView())
        bot._member_portal_view_registered = True

    if not getattr(bot, "_member_portal_20261026_sync_started", False):
        bot._member_portal_20261026_sync_started = True
        bot.loop.create_task(_sync_member_portal_panel(bot))


__all__ = ["install_member_portal_20261026"]
