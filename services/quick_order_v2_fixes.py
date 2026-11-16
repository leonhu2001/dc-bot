from __future__ import annotations

import discord
from discord.ext import commands

from services import orders
from services import quick_order_v2 as quick


_INSTALLED = False

# Compatibility-only aliases. Catalog logic lives in services.orders and is
# shared by the Bot and Web; no production module attribute is rebound.
_FARM_3X3_GROUP_LABEL = orders._FARM_3X3_GROUP_LABEL
_FARM_3X3_RULE_ORDER = orders._FARM_3X3_RULE_ORDER
_FARM_3X3_RULE_KEYS = orders._FARM_3X3_RULE_KEYS
_normalized_label = orders._normalized_group_label
_normalized_key = orders._normalized_group_key
_display_group_label = orders._display_group_label
_farm_3x3_details = orders._farm_3x3_details
_canonical_details = orders.get_order_item_details_for_group


def _live_groups(category: str) -> list[str]:
    if str(category) == str(quick.VIP_TIMER_CATEGORY):
        quick.refresh_vip_timer_self_service_catalog()
    return orders.get_live_order_item_groups(category)


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
            content = str(message.content or "")
            if not any(
                marker in content
                for marker in (
                    "新版快速下單票口已建立",
                    "已選服務：",
                    "請完成下方選項。",
                )
            ):
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


async def _refresh_existing_farm_3x3_panel(channel: discord.TextChannel) -> bool:
    """Replace stale two-option 3x3 components on already-open quick tickets."""
    try:
        from services import self_service_ui_runtime as ui

        data = ui.SELF_SERVICE_ORDER_SELECTIONS.get(channel.id, {})
        if not isinstance(data, dict) or not data.get("quick_order_v2"):
            return False
        if str(data.get("category") or "") != "farm":
            return False
        if _normalized_key(data.get("item_group")) != _normalized_key(_FARM_3X3_GROUP_LABEL):
            return False

        customer_id = int(data.get("customer_id") or 0)
        if customer_id <= 0:
            return False

        bot_user_id = getattr(getattr(channel.guild, "me", None), "id", None)
        async for message in channel.history(limit=25, oldest_first=True):
            if bot_user_id is not None and message.author.id != bot_user_id:
                continue

            has_detail_select = any(
                getattr(component, "custom_id", None) == "self_service_order_detail_select"
                for row in message.components
                for component in getattr(row, "children", [])
            )
            if not has_detail_select:
                continue

            await message.edit(
                embed=ui.build_self_service_panel_embed(customer_id, data, channel.guild),
                view=ui.SelfServiceOrderView(
                    customer_id=customer_id,
                    channel_id=channel.id,
                    selected_category=data.get("category"),
                ),
                allowed_mentions=discord.AllowedMentions(
                    users=True,
                    roles=False,
                    everyone=False,
                ),
            )
            return True
    except (ValueError, TypeError, discord.Forbidden, discord.HTTPException) as exc:
        print(
            f"[quick-order-v2-fix] refresh 3x3 panel failed channel={channel.id}: "
            f"{type(exc).__name__}: {exc}",
            flush=True,
        )
    return False


async def repair_existing_quick_order_v2_tickets(bot: commands.Bot) -> None:
    await bot.wait_until_ready()
    category_id = int(getattr(quick, "CUSTOMER_CATEGORY_ID", 0) or 0)
    category = bot.get_channel(category_id)
    if not isinstance(category, discord.CategoryChannel):
        return

    control_repaired = 0
    farm_panels_refreshed = 0
    for channel in list(category.text_channels):
        if "quick_order_v2=1" not in str(channel.topic or ""):
            continue
        if await _attach_order_control_view(channel):
            control_repaired += 1
        if await _refresh_existing_farm_3x3_panel(channel):
            farm_panels_refreshed += 1

    if control_repaired:
        print(
            f"[quick-order-v2-fix] restored customer-service control row "
            f"for {control_repaired} quick-order ticket(s)",
            flush=True,
        )
    if farm_panels_refreshed:
        print(
            f"[quick-order-v2-fix] refreshed {farm_panels_refreshed} existing 3x3 panel(s)",
            flush=True,
        )


def install_quick_order_v2_fixes(bot: commands.Bot) -> None:
    global _INSTALLED
    if _INSTALLED:
        return

    # Group and detail resolvers are native functions in services.orders.
    # Preserve this installer as a harmless compatibility entrypoint for the
    # existing startup sequence and explicit historical-ticket repair helpers.
    # Never replace orders/order_runtime/selection_state callables here.

    _INSTALLED = True
    print("[quick-order-v2-fix] fixes installed", flush=True)


__all__ = ["install_quick_order_v2_fixes", "repair_existing_quick_order_v2_tickets"]