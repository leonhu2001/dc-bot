from __future__ import annotations

import unicodedata

import discord
from discord.ext import commands

from services import orders
from services import quick_order_v2 as quick


_INSTALLED = False
_ORIGINAL_CREATE_TICKET = None


def _normalized_label(value) -> str:
    text = unicodedata.normalize("NFKC", str(value or "")).strip()
    return " ".join(text.split())


def _live_groups(category: str) -> list[str]:
    """Read the live storefront catalog instead of the startup-time group snapshot.

    VIP timer groups are generated dynamically, and runtime catalog extensions may
    add or replace groups after services.orders first built its compatibility maps.
    Reading SELF_SERVICE_ORDER_CATALOG here keeps the quick-order entry aligned with
    what the ticket UI actually uses.
    """
    if str(category) == str(quick.VIP_TIMER_CATEGORY):
        quick.refresh_vip_timer_self_service_catalog()

    result: list[str] = []
    seen: set[str] = set()
    for group in orders.SELF_SERVICE_ORDER_CATALOG.get(str(category), []):
        if not isinstance(group, dict):
            continue
        text = _normalized_label(group.get("label"))
        key = text.casefold()
        if not text or key in seen:
            continue
        seen.add(key)
        result.append(text)
    return result


def _delta_entry_init(self) -> None:
    discord.ui.View.__init__(self, timeout=None)
    for emoji, label, category, style in quick._DELTA_BUTTONS:
        self.add_item(
            quick.QuickDeltaCategoryButton(
                emoji=emoji,
                label=label,
                category=category,
                style=style,
                row=0,
            )
        )


async def _attach_order_control_view(channel: discord.TextChannel) -> bool:
    """Restore the same customer-service operation row used by legacy order tickets."""
    try:
        from services import self_service_runtime as runtime

        state = runtime._require_runtime_state()
        view_type = state.order_control_view_type
        if view_type is None:
            return False
    except Exception as exc:
        print(
            f"[quick-order-v2-fix] cannot resolve order control view: "
            f"{type(exc).__name__}: {exc}",
            flush=True,
        )
        return False

    try:
        async for message in channel.history(limit=12, oldest_first=True):
            if "新版快速下單票口已建立" not in str(message.content or ""):
                continue
            await message.edit(view=view_type())
            return True
    except (discord.Forbidden, discord.HTTPException) as exc:
        print(
            f"[quick-order-v2-fix] restore control row failed "
            f"channel={channel.id}: {type(exc).__name__}: {exc}",
            flush=True,
        )
    return False


def _install_create_ticket_wrapper() -> None:
    global _ORIGINAL_CREATE_TICKET
    if _ORIGINAL_CREATE_TICKET is not None:
        return

    _ORIGINAL_CREATE_TICKET = quick._create_ticket
    original = _ORIGINAL_CREATE_TICKET

    async def create_ticket_with_control_row(
        interaction: discord.Interaction,
        *,
        category: str,
        item_group: str,
        source_channel_id: int,
    ) -> discord.TextChannel | None:
        ticket = await original(
            interaction,
            category=category,
            item_group=item_group,
            source_channel_id=source_channel_id,
        )
        if isinstance(ticket, discord.TextChannel):
            await _attach_order_control_view(ticket)
        return ticket

    quick._create_ticket = create_ticket_with_control_row


async def repair_existing_quick_order_v2_tickets(bot: commands.Bot) -> None:
    await bot.wait_until_ready()
    category_id = int(getattr(quick, "CUSTOMER_CATEGORY_ID", 0) or 0)
    category = bot.get_channel(category_id)
    if not isinstance(category, discord.CategoryChannel):
        return

    repaired = 0
    for channel in list(category.text_channels):
        if "quick_order_v2=1" not in str(channel.topic or ""):
            continue
        if await _attach_order_control_view(channel):
            repaired += 1

    if repaired:
        print(
            f"[quick-order-v2-fix] restored customer-service control row "
            f"for {repaired} quick-order ticket(s)",
            flush=True,
        )


def install_quick_order_v2_fixes(bot: commands.Bot) -> None:
    global _INSTALLED
    if _INSTALLED:
        return

    # 1. Live catalog fixes both stale VIP start-game options and duplicate groups.
    quick._groups = _live_groups

    # 2. Discord supports up to five buttons per action row; keep all four Delta
    # entry buttons on the same row instead of forcing the fourth onto row 2.
    quick.QuickDeltaEntryView.__init__ = _delta_entry_init

    # 3. Quick tickets bypassed the legacy create_private_channel helper, so the
    # customer-service OrderControlView was never attached. Put the real view back.
    _install_create_ticket_wrapper()

    if not getattr(bot, "_quick_order_v2_control_repair_started", False):
        bot._quick_order_v2_control_repair_started = True
        bot.loop.create_task(repair_existing_quick_order_v2_tickets(bot))

    _INSTALLED = True
    print("[quick-order-v2-fix] fixes installed", flush=True)


__all__ = ["install_quick_order_v2_fixes", "repair_existing_quick_order_v2_tickets"]
