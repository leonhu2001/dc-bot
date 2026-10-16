from __future__ import annotations

import discord

from services.orders import _to_int


def _ticket_overwrite_has_values(overwrite: discord.PermissionOverwrite) -> bool:
    values = getattr(overwrite, "_values", None)
    if isinstance(values, dict):
        return bool(values)

    return any(
        getattr(overwrite, attr, None) is not None
        for attr in (
            "view_channel",
            "send_messages",
            "read_message_history",
            "attach_files",
            "embed_links",
        )
    )


async def grant_order_ticket_access(
    guild: discord.Guild,
    ticket_channel_id: int,
    member: discord.Member,
) -> bool:
    """接單成功後給接單者票口可見 / 文字互動權限。"""
    channel = guild.get_channel(int(ticket_channel_id))
    if not isinstance(channel, discord.TextChannel):
        return False

    overwrite = channel.overwrites_for(member)
    overwrite.view_channel = True
    overwrite.send_messages = True
    overwrite.read_message_history = True
    overwrite.attach_files = True
    overwrite.embed_links = True

    try:
        await channel.set_permissions(
            member,
            overwrite=overwrite,
            reason="Grant accepted staff ticket access",
        )
        return True
    except discord.Forbidden:
        print(
            f"[ticket-access] Bot 權限不足，無法開放票口 "
            f"channel={ticket_channel_id} member={member.id}"
        )
    except discord.HTTPException as exc:
        print(
            f"[ticket-access] 開放票口失敗 "
            f"channel={ticket_channel_id} member={member.id}: {exc}"
        )

    return False


async def revoke_order_ticket_access(
    guild: discord.Guild,
    ticket_channel_id: int,
    member: discord.Member,
) -> bool:
    """取消接單後只清掉接單流程寫入的票口權限，恢復角色繼承。"""
    channel = guild.get_channel(int(ticket_channel_id))
    if not isinstance(channel, discord.TextChannel):
        return False

    overwrite = channel.overwrites_for(member)
    overwrite.view_channel = None
    overwrite.send_messages = None
    overwrite.read_message_history = None
    overwrite.attach_files = None
    overwrite.embed_links = None

    try:
        await channel.set_permissions(
            member,
            overwrite=overwrite if _ticket_overwrite_has_values(overwrite) else None,
            reason="Revoke unclaimed staff ticket access",
        )
        return True
    except discord.Forbidden:
        print(
            f"[ticket-access] Bot 權限不足，無法收回票口 "
            f"channel={ticket_channel_id} member={member.id}"
        )
    except discord.HTTPException as exc:
        print(
            f"[ticket-access] 收回票口失敗 "
            f"channel={ticket_channel_id} member={member.id}: {exc}"
        )

    return False


async def sync_acceptance_ticket_access_from_state(
    guild: discord.Guild,
    ticket_channel_id: int,
    state,
) -> None:
    """刷新接單狀態時，確保所有目前接單者都能看到票口。"""
    for claim in getattr(state, "claims", ()):
        user_id = _to_int(getattr(claim, "staff_discord_id", None))
        if user_id is None:
            continue

        member = guild.get_member(user_id)
        if member is None:
            try:
                fetched = await guild.fetch_member(user_id)
                member = fetched if isinstance(fetched, discord.Member) else None
            except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                member = None

        if member is not None:
            await grant_order_ticket_access(
                guild,
                int(ticket_channel_id),
                member,
            )
