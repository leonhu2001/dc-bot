from __future__ import annotations

import discord
from discord.ext import commands

from services import quick_order_v2 as quick


_INSTALLED = False
_ORIGINAL_QUANTITY_CALLBACK = None
_ORIGINAL_DETAIL_CALLBACK = None
_ORIGINAL_ITEM_CALLBACK = None
_ORIGINAL_CATEGORY_CALLBACK = None

_QUICK_SELECT_IDS = {
    "self_service_order_category_select",
    "self_service_order_item_select",
    "self_service_order_detail_select",
    "self_service_order_quantity_select",
}
_QUANTITY_SELECTED_KEY = "quick_order_quantity_selected"
_LEGACY_RESELECT_FLAG = "legacy_four_selector_panel"


def _clear_defaults(select: discord.ui.Select) -> None:
    for option in getattr(select, "options", []) or []:
        option.default = False


def _select_value(select: discord.ui.Select, value: object) -> bool:
    selected = str(value or "").strip()
    matched = False
    for option in getattr(select, "options", []) or []:
        is_match = bool(selected) and str(getattr(option, "value", "")) == selected
        option.default = is_match
        matched = matched or is_match
    return matched


def apply_quick_order_select_display(view: discord.ui.View, data: dict) -> None:
    """Apply Quick Order select-display rules to an already-built canonical view."""
    category = str(data.get("category") or "")
    item_group = str(data.get("item_group") or "")
    detail_selected = bool(str(data.get("item_detail_value") or "").strip())
    quantity_selected = bool(data.get(_QUANTITY_SELECTED_KEY))
    classic_reselect = bool(data.get(_LEGACY_RESELECT_FLAG))

    if classic_reselect:
        from services.orders import ORDER_CATEGORY_LABELS

    for child in list(view.children):
        if not isinstance(child, discord.ui.Select):
            continue

        custom_id = str(getattr(child, "custom_id", "") or "")
        if custom_id not in _QUICK_SELECT_IDS:
            continue

        options = list(getattr(child, "options", []) or [])

        if classic_reselect and custom_id == "self_service_order_category_select":
            _select_value(child, category)
            if category:
                selected_label = str(ORDER_CATEGORY_LABELS.get(category, category))
                child.placeholder = f"已選：{selected_label}"[:150]
            else:
                child.placeholder = "請選擇類型"
            continue

        if classic_reselect and custom_id == "self_service_order_item_select":
            _select_value(child, item_group)
            child.placeholder = (
                f"已選：{item_group}"[:150]
                if item_group
                else "請選擇服務"
            )
            continue

        if custom_id == "self_service_order_detail_select":
            if len(options) > 1 and not detail_selected:
                _clear_defaults(child)
            child.placeholder = "請選擇方案" if category == "farm" else "請選擇規格"
            continue

        if custom_id == "self_service_order_quantity_select":
            if len(options) > 1 and not quantity_selected:
                _clear_defaults(child)
            child.placeholder = "請選擇時長 / 數量"
            continue

        _clear_defaults(child)
        if custom_id == "self_service_order_item_select":
            child.placeholder = "請選擇服務"
        elif custom_id == "self_service_order_category_select":
            child.placeholder = "請選擇類型"


def _install_selection_markers() -> None:
    """Track only choices that really came from a Discord interaction callback."""
    global _ORIGINAL_QUANTITY_CALLBACK
    global _ORIGINAL_DETAIL_CALLBACK
    global _ORIGINAL_ITEM_CALLBACK
    global _ORIGINAL_CATEGORY_CALLBACK

    from services import order_runtime as runtime

    if _ORIGINAL_QUANTITY_CALLBACK is None:
        _ORIGINAL_QUANTITY_CALLBACK = runtime.SelfServiceOrderQuantitySelect.callback
        original_quantity = _ORIGINAL_QUANTITY_CALLBACK

        async def quantity_callback(self, interaction: discord.Interaction):
            try:
                state = runtime._require_runtime_state()
                data = state.order_selections.get(self.channel_id, {})
                if (
                    isinstance(data, dict)
                    and data.get("quick_order_v2")
                    and state.can_operate_self_service_order(interaction.user, self.customer_id)
                    and self.values
                    and self.values[0] != "need_item"
                ):
                    data[_QUANTITY_SELECTED_KEY] = True
            except Exception:
                pass
            await original_quantity(self, interaction)

        runtime.SelfServiceOrderQuantitySelect.callback = quantity_callback

    if _ORIGINAL_DETAIL_CALLBACK is None:
        _ORIGINAL_DETAIL_CALLBACK = runtime.SelfServiceOrderDetailSelect.callback
        original_detail = _ORIGINAL_DETAIL_CALLBACK

        async def detail_callback(self, interaction: discord.Interaction):
            try:
                state = runtime._require_runtime_state()
                data = state.order_selections.get(self.channel_id, {})
                if (
                    isinstance(data, dict)
                    and data.get("quick_order_v2")
                    and state.can_operate_self_service_order(interaction.user, self.customer_id)
                    and self.values
                    and self.values[0] != "need_item"
                ):
                    data.pop(_QUANTITY_SELECTED_KEY, None)
            except Exception:
                pass
            await original_detail(self, interaction)

        runtime.SelfServiceOrderDetailSelect.callback = detail_callback

    if _ORIGINAL_ITEM_CALLBACK is None:
        _ORIGINAL_ITEM_CALLBACK = runtime.SelfServiceOrderItemSelect.callback
        original_item = _ORIGINAL_ITEM_CALLBACK

        async def item_callback(self, interaction: discord.Interaction):
            try:
                state = runtime._require_runtime_state()
                data = state.order_selections.get(self.channel_id, {})
                if isinstance(data, dict) and data.get("quick_order_v2"):
                    data.pop(_QUANTITY_SELECTED_KEY, None)
            except Exception:
                pass
            await original_item(self, interaction)

        runtime.SelfServiceOrderItemSelect.callback = item_callback

    if _ORIGINAL_CATEGORY_CALLBACK is None:
        _ORIGINAL_CATEGORY_CALLBACK = runtime.SelfServiceOrderCategorySelect.callback
        original_category = _ORIGINAL_CATEGORY_CALLBACK

        async def category_callback(self, interaction: discord.Interaction):
            try:
                state = runtime._require_runtime_state()
                data = state.order_selections.get(self.channel_id, {})
                if isinstance(data, dict) and data.get("quick_order_v2"):
                    data.pop(_QUANTITY_SELECTED_KEY, None)
            except Exception:
                pass
            await original_category(self, interaction)

        runtime.SelfServiceOrderCategorySelect.callback = category_callback


async def repair_existing_quick_order_selects(bot: commands.Bot) -> None:
    """Refresh already-open quick-order panels with the current Select display rules."""
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

    _install_selection_markers()

    _INSTALLED = True
    print("[quick-order-v2-select] interaction-aware select display installed", flush=True)


__all__ = [
    "apply_quick_order_select_display",
    "install_quick_order_v2_select_display",
    "repair_existing_quick_order_selects",
]
