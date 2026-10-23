from __future__ import annotations

import discord
from discord.ext import commands

from services import quick_order_v2 as quick


_INSTALLED = False
_ORIGINAL_VIEW_INIT = None

_QUICK_SELECT_IDS = {
    "self_service_order_category_select",
    "self_service_order_item_select",
    "self_service_order_detail_select",
    "self_service_order_quantity_select",
}


def _reset_quick_order_select_display(view: discord.ui.View, data: dict) -> None:
    """Do not render customer-choice selects with a pre-selected Discord option.

    The order draft may already contain a value used for pricing/state, but a Discord
    SelectOption(default=True) visually looks as if the customer actively chose it.
    That is especially confusing on newly created quick-order tickets because no
    interaction callback has fired yet. Quick-order tickets therefore keep the
    current value in the embed/state while the select itself always starts from a
    neutral prompt.
    """
    category = str(data.get("category") or "")

    for child in list(view.children):
        if not isinstance(child, discord.ui.Select):
            continue

        custom_id = str(getattr(child, "custom_id", "") or "")
        if custom_id not in _QUICK_SELECT_IDS:
            continue

        for option in getattr(child, "options", []) or []:
            option.default = False

        if custom_id == "self_service_order_detail_select":
            child.placeholder = "請選擇方案" if category == "farm" else "請選擇規格"
        elif custom_id == "self_service_order_quantity_select":
            child.placeholder = "請選擇時長 / 數量"
        elif custom_id == "self_service_order_item_select":
            child.placeholder = "請選擇服務"
        elif custom_id == "self_service_order_category_select":
            child.placeholder = "請選擇類型"


def _install_quick_order_view_patch() -> None:
    global _ORIGINAL_VIEW_INIT
    if _ORIGINAL_VIEW_INIT is not None:
        return

    from services import self_service_ui_runtime as ui

    _ORIGINAL_VIEW_INIT = ui.SelfServiceOrderView.__init__
    original = _ORIGINAL_VIEW_INIT

    def quick_order_view_init(
        self,
        customer_id: int,
        channel_id: int,
        selected_category: str | None = None,
    ):
        original(self, customer_id, channel_id, selected_category)

        data = ui.SELF_SERVICE_ORDER_SELECTIONS.get(channel_id, {})
        if not isinstance(data, dict) or not data.get("quick_order_v2"):
            return

        _reset_quick_order_select_display(self, data)

    ui.SelfServiceOrderView.__init__ = quick_order_view_init


async def repair_existing_quick_order_selects(bot: commands.Bot) -> None:
    """Refresh already-open quick-order panels so stale default checks disappear."""
    await bot.wait_until_ready()

    from services import self_service_ui_runtime as ui

    category_id = int(getattr(quick, "CUSTOMER_CATEGORY_ID", 0) or 0)
    category = bot.get_channel(category_id)
    if not isinstance(category, discord.CategoryChannel):
        return

    refreshed = 0
    bot_user_id = getattr(bot.user, "id", None)

    for channel in list(category.text_channels):
        if "quick_order_v2=1" not in str(channel.topic or ""):
            continue

        data = ui.SELF_SERVICE_ORDER_SELECTIONS.get(channel.id, {})
        if not isinstance(data, dict) or not data.get("quick_order_v2"):
            continue

        customer_id = int(data.get("customer_id") or 0)
        if customer_id <= 0:
            continue

        try:
            async for message in channel.history(limit=25, oldest_first=True):
                if bot_user_id is not None and message.author.id != bot_user_id:
                    continue

                has_order_select = any(
                    str(getattr(component, "custom_id", "") or "") in _QUICK_SELECT_IDS
                    for row in message.components
                    for component in getattr(row, "children", [])
                )
                if not has_order_select:
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
                refreshed += 1
                break
        except (ValueError, TypeError, discord.Forbidden, discord.HTTPException) as exc:
            print(
                f"[quick-order-v2-select] refresh failed channel={channel.id}: "
                f"{type(exc).__name__}: {exc}",
                flush=True,
            )

    if refreshed:
        print(
            f"[quick-order-v2-select] refreshed {refreshed} quick-order panel(s)",
            flush=True,
        )


def install_quick_order_v2_select_display(bot: commands.Bot) -> None:
    global _INSTALLED
    if _INSTALLED:
        return

    _install_quick_order_view_patch()

    if not getattr(bot, "_quick_order_v2_select_repair_started", False):
        bot._quick_order_v2_select_repair_started = True
        bot.loop.create_task(repair_existing_quick_order_selects(bot))

    _INSTALLED = True
    print("[quick-order-v2-select] neutral select display installed", flush=True)


__all__ = [
    "install_quick_order_v2_select_display",
    "repair_existing_quick_order_selects",
]
