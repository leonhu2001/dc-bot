from __future__ import annotations

import asyncio
import re
from collections.abc import Awaitable, Callable

import discord

from core.database import (
    delete_vip_voice_room_record,
    get_vip_voice_room_by_owner,
    list_vip_voice_rooms,
    upsert_vip_voice_room,
)


_CONFIGURED = False
_HIDDEN_VIP_USER_IDS: list[int] = []
VIP_VOICE_LOBBY_ROLE_IDS: list[int] = []
VIP_VOICE_LOBBY_CATEGORY_ID = 0
VIP_VOICE_CREATE_CHANNEL_NAME = ""
TEMP_VIP_VOICE_CHANNEL_IDS: set[int]
TEMP_VOICE_CONTROL_PANELS: dict
bot = None
fetch_member_safely: Callable
VoiceRoomControlView: Callable
delete_voice_control_panel: Callable[..., Awaitable]
sync_voice_control_panel_state_from_channel: Callable
sync_vip_whitelist_permissions: Callable[..., Awaitable]


def configure_vip_voice_runtime(
    *,
    bot_instance,
    hidden_vip_user_ids: list[int],
    vip_voice_role_ids: list[int],
    vip_voice_category_id: int,
    vip_voice_create_channel_name: str,
    temp_vip_channel_ids: set[int],
    temp_voice_control_panels: dict,
    fetch_member: Callable,
    control_view_factory: Callable,
    delete_control_panel: Callable[..., Awaitable],
    sync_control_panel_state: Callable,
    sync_whitelist_permissions: Callable[..., Awaitable],
) -> None:
    """Bind Discord/runtime collaborators for persistent VIP voice rooms."""
    global _CONFIGURED, _HIDDEN_VIP_USER_IDS
    global VIP_VOICE_LOBBY_ROLE_IDS, VIP_VOICE_LOBBY_CATEGORY_ID
    global VIP_VOICE_CREATE_CHANNEL_NAME, TEMP_VIP_VOICE_CHANNEL_IDS
    global TEMP_VOICE_CONTROL_PANELS, bot, fetch_member_safely
    global VoiceRoomControlView, delete_voice_control_panel
    global sync_voice_control_panel_state_from_channel, sync_vip_whitelist_permissions

    bot = bot_instance
    _HIDDEN_VIP_USER_IDS = [int(value) for value in hidden_vip_user_ids]
    VIP_VOICE_LOBBY_ROLE_IDS = [int(value) for value in vip_voice_role_ids]
    VIP_VOICE_LOBBY_CATEGORY_ID = int(vip_voice_category_id)
    VIP_VOICE_CREATE_CHANNEL_NAME = str(vip_voice_create_channel_name)
    TEMP_VIP_VOICE_CHANNEL_IDS = temp_vip_channel_ids
    TEMP_VOICE_CONTROL_PANELS = temp_voice_control_panels
    fetch_member_safely = fetch_member
    VoiceRoomControlView = control_view_factory
    delete_voice_control_panel = delete_control_panel
    sync_voice_control_panel_state_from_channel = sync_control_panel_state
    sync_vip_whitelist_permissions = sync_whitelist_permissions
    _CONFIGURED = True


def set_vip_voice_hidden_user_ids(user_ids: list[int]) -> None:
    global _HIDDEN_VIP_USER_IDS
    _HIDDEN_VIP_USER_IDS = [int(value) for value in user_ids]


def member_has_vip_voice_role(member: discord.Member | None) -> bool:
    if member is None:
        return False

    # 隱藏 VIP 不需要公開 VIP role，但在語音房生命週期中等同有效 VIP。
    if int(member.id) in {int(user_id) for user_id in _HIDDEN_VIP_USER_IDS}:
        return True

    vip_role_ids = {int(role_id) for role_id in VIP_VOICE_LOBBY_ROLE_IDS}
    return any(int(role.id) in vip_role_ids for role in getattr(member, "roles", []))


async def delete_vip_voice_room_for_owner(
    guild: discord.Guild,
    owner_id: int,
    *,
    reason: str,
    verify_vip_inactive: bool = False,
    verify_delay_seconds: float = 0,
) -> bool:
    row = get_vip_voice_room_by_owner(int(owner_id))
    if not row:
        return False

    channel_id = int(row.get("channel_id") or 0)

    # VIP 失效刪房一定做最後一次 Discord 即時驗證。
    # 任何暫時性的 member_update / 身分組同步事件都不能直接刪永久房。
    if verify_vip_inactive:
        if verify_delay_seconds > 0:
            await asyncio.sleep(float(verify_delay_seconds))

        latest_member = await fetch_member_safely(guild, int(owner_id))

        if latest_member is None:
            print(
                f"[vip-voice] skip delete: unable to verify member "
                f"owner={owner_id} channel={channel_id} reason={reason}"
            )
            return False

        if member_has_vip_voice_role(latest_member):
            print(
                f"[vip-voice] skip delete: VIP still active "
                f"owner={owner_id} channel={channel_id} reason={reason}"
            )
            return False

    channel = guild.get_channel(channel_id) if channel_id else None

    print(
        f"[vip-voice] deleting room "
        f"owner={owner_id} channel={channel_id} reason={reason}"
    )

    if isinstance(channel, discord.VoiceChannel):
        try:
            await channel.delete(reason=reason)
        except discord.NotFound:
            pass
        except discord.Forbidden:
            print(f"Bot 權限不足，無法刪除 VIP 語音房：{channel_id}")
            return False
        except discord.HTTPException as e:
            print(f"刪除 VIP 語音房失敗：{channel_id}：{e}")
            return False

    TEMP_VIP_VOICE_CHANNEL_IDS.discard(channel_id)
    await delete_voice_control_panel(guild, channel_id)
    delete_vip_voice_room_record(owner_id=int(owner_id), channel_id=channel_id)
    return True


async def restore_persistent_vip_voice_rooms(guild: discord.Guild) -> int:
    # 先接管更新前已存在、但還沒寫入資料庫的 VIP 房。
    known_channel_ids = {
        int(row.get("channel_id") or 0)
        for row in list_vip_voice_rooms()
        if int(row.get("channel_id") or 0)
    }
    vip_category = guild.get_channel(VIP_VOICE_LOBBY_CATEGORY_ID)

    if isinstance(vip_category, discord.CategoryChannel):
        for channel in vip_category.voice_channels:
            if channel.id in known_channel_ids or channel.name == VIP_VOICE_CREATE_CHANNEL_NAME:
                continue

            owner_id = 0
            panel_message_id = 0

            try:
                async for message in channel.history(limit=100):
                    if bot.user is not None and message.author.id != bot.user.id:
                        continue
                    if not message.embeds:
                        continue

                    embed = message.embeds[0]
                    if str(embed.title or "") != "專屬語音房":
                        continue

                    match = re.search(r"<@!?(\d+)>", str(embed.description or ""))
                    if match is None:
                        continue

                    owner_id = int(match.group(1))
                    panel_message_id = int(message.id)
                    break
            except (discord.Forbidden, discord.HTTPException):
                continue

            owner = await fetch_member_safely(guild, owner_id) if owner_id else None
            if owner is None or not member_has_vip_voice_role(owner):
                continue

            upsert_vip_voice_room(owner_id, channel.id, panel_message_id or None)
            known_channel_ids.add(channel.id)

    restored = 0

    for row in list_vip_voice_rooms():
        owner_id = int(row.get("owner_id") or 0)
        channel_id = int(row.get("channel_id") or 0)
        panel_message_id = int(row.get("panel_message_id") or 0)

        if not owner_id or not channel_id:
            delete_vip_voice_room_record(owner_id=owner_id or None, channel_id=channel_id or None)
            continue

        channel = guild.get_channel(channel_id)
        owner = await fetch_member_safely(guild, owner_id)

        if not isinstance(channel, discord.VoiceChannel):
            delete_vip_voice_room_record(owner_id=owner_id, channel_id=channel_id)
            continue

        # 成員資料暫時抓不到時不要誤刪永久房；真的離開伺服器會由 on_member_remove 清理。
        if owner is None:
            continue

        if not member_has_vip_voice_role(owner):
            await delete_vip_voice_room_for_owner(
                guild,
                owner_id,
                reason="VIP membership is no longer active",
                verify_vip_inactive=True,
            )
            continue

        TEMP_VIP_VOICE_CHANNEL_IDS.add(channel_id)
        TEMP_VOICE_CONTROL_PANELS[channel_id] = {
            "owner_id": owner_id,
            "panel_channel_id": channel_id,
            "panel_message_id": panel_message_id or None,
            "room_type": "vip",
            "locked": False,
            "hidden": False,
        }
        sync_voice_control_panel_state_from_channel(channel)

        try:
            await sync_vip_whitelist_permissions(
                channel,
                owner_id,
            )
        except discord.Forbidden:
            print(
                f"Bot 權限不足，無法恢復 VIP 白名單權限："
                f"owner={owner_id} channel={channel_id}"
            )
        except discord.HTTPException as exc:
            print(
                f"恢復 VIP 白名單權限失敗："
                f"owner={owner_id} channel={channel_id}: {exc}"
            )

        if panel_message_id:
            control_view = VoiceRoomControlView(
                voice_channel_id=channel_id,
                owner_id=owner_id,
                room_type="vip",
            )

            try:
                bot.add_view(
                    control_view,
                    message_id=panel_message_id,
                )
            except ValueError:
                pass

            # Persistent view registration only restores callbacks; it does not
            # change the buttons already rendered on an old Discord message.
            # Edit the existing panel so pre-existing VIP rooms immediately get
            # newly-added controls such as the whitelist button after deploy.
            try:
                panel_message = await channel.fetch_message(panel_message_id)
                await panel_message.edit(
                    view=control_view,
                    allowed_mentions=discord.AllowedMentions(
                        users=True,
                        roles=False,
                        everyone=False,
                    ),
                )
            except discord.NotFound:
                pass
            except discord.Forbidden:
                print(
                    f"Bot 權限不足，無法更新既有 VIP Panel："
                    f"owner={owner_id} channel={channel_id}"
                )
            except discord.HTTPException as exc:
                print(
                    f"更新既有 VIP Panel 失敗："
                    f"owner={owner_id} channel={channel_id}: {exc}"
                )

        restored += 1

    return restored
