"""Prevent duplicate self-service panels inside an existing order ticket.

A quick-order ticket already contains the active selector message. Staff using
the legacy order-control '派單' action must not send a second copy. Both
parallel confirm callbacks and later repeats serialize per channel and reuse
the original message.
"""
from __future__ import annotations

import asyncio
import discord

_PANEL_LOCKS: dict[int, asyncio.Lock] = {}


def _is_self_service_panel(message, *, bot_id: int | None) -> bool:
    if bot_id is not None and getattr(getattr(message, "author", None), "id", None) != bot_id:
        return False
    embeds = getattr(message, "embeds", ()) or ()
    title = str(getattr(embeds[0], "title", "") or "") if embeds else ""
    if title not in ("自助下單", "🛒 自助下單") and not title.startswith("快速下單｜"):
        return False
    components = getattr(message, "components", ()) or ()
    for row in components:
        for child in getattr(row, "children", ()) or ():
            if str(getattr(child, "custom_id", "") or "").startswith("self_service_order_"):
                return True
    # Early legacy panels also use the same title but may lack components.
    return title in ("自助下單", "🛒 自助下單")


async def ensure_single_self_service_panel(
    channel: discord.TextChannel,
    *,
    customer_id: int,
    embed: discord.Embed,
    view_factory,
) -> tuple[discord.Message, bool]:
    lock = _PANEL_LOCKS.setdefault(int(channel.id), asyncio.Lock())
    async with lock:
        bot_id = getattr(getattr(channel.guild, "me", None), "id", None)
        async for message in channel.history(limit=150):
            if _is_self_service_panel(message, bot_id=bot_id):
                return message, False
        if "quick_order_v2=1" in str(getattr(channel, "topic", "") or ""):
            # Every successfully opened quick ticket already sent its sole
            # selector. If it is absent/deleted/too old for history, fail
            # closed rather than silently creating a duplicate panel.
            raise ValueError("快速下單票口已有獨立面板紀錄，找不到原面板，請聯絡客服主管修復。")
        created = await channel.send(
            embed=embed,
            view=view_factory(customer_id=int(customer_id),channel_id=int(channel.id)),
            allowed_mentions=discord.AllowedMentions(users=False,roles=False,everyone=False),
        )
        return created, True


async def handle_legacy_order_control_dispatch(
    interaction: discord.Interaction, *, customer_id: int, view_factory,
) -> None:
    """Staff action: reuse the existing selector instead of posting a second.

    Creation is serialized per ticket, and all prompts remain ephemeral. This
    does not change any order status or duplicate a dispatch/order row.
    """
    channel=interaction.channel
    customer=(interaction.guild.get_member(customer_id)
              if interaction.guild is not None else None)
    mention=customer.mention if customer is not None else f"<@{customer_id}>"
    embed=discord.Embed(
        title="自助下單",
        description=(
            f"下單用戶：{mention}\n\n"
            "請下單用戶依序選擇訂單類別、訂單項目、指定選項與數量。\n"
            "畫面會即時顯示試算金額、可接職位與接單需求。\n"
            "送出後會先派單等待接單，人數滿後才會開放付款。"
        ),
        color=discord.Color.purple(),
    )
    await interaction.response.defer(ephemeral=True,thinking=True)
    try:
        panel,created=await ensure_single_self_service_panel(
            channel,customer_id=customer_id,embed=embed,view_factory=view_factory,
        )
    except ValueError as exc:
        await interaction.followup.send(str(exc), ephemeral=True)
        return
    except (discord.Forbidden,discord.HTTPException):
        await interaction.followup.send(
            "自助下單面板檢查失敗，請通知客服主管確認票口權限，不會重複發送。",
            ephemeral=True,
        )
        return
    await interaction.followup.send(
        (f"已開啟自助下單面板：{panel.jump_url}" if created
         else f"這張票口已有自助下單面板，請使用原本的：{panel.jump_url}"),
        ephemeral=True,
    )


__all__=["ensure_single_self_service_panel","_is_self_service_panel",
         "handle_legacy_order_control_dispatch"]
