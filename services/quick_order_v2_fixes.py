from __future__ import annotations

import unicodedata

import discord
from discord.ext import commands

from services import orders
from services import quick_order_v2 as quick


_INSTALLED = False
_ORIGINAL_DETAILS_RESOLVER = None

_X_EQUIVALENTS = str.maketrans({
    "×": "x",
    "✕": "x",
    "✖": "x",
    "⨯": "x",
    "Ｘ": "X",
    "ｘ": "x",
})

_FARM_3X3_GROUP_LABEL = "賽季3x3"
_FARM_3X3_RULE_ORDER = (
    "farm_season_3x3_normal",
    "farm_season_3x3_dc_loss",
    "farm_season_3x3_dc_skin",
    "farm_season_3x3_dc_skin_loss",
    "farm_season_3x3_contract",
)
_FARM_3X3_RULE_KEYS = frozenset(_FARM_3X3_RULE_ORDER)


def _normalized_label(value) -> str:
    """Normalize storefront labels for Discord display."""
    text = unicodedata.normalize("NFKC", str(value or "")).translate(_X_EQUIVALENTS)
    cleaned: list[str] = []
    for char in text:
        category = unicodedata.category(char)
        if category.startswith("C") or category.startswith("M"):
            if char.isspace():
                cleaned.append(" ")
            continue
        cleaned.append(char)
    return " ".join("".join(cleaned).strip().split())


def _normalized_key(value) -> str:
    """Return a semantic key for storefront group identity."""
    text = _normalized_label(value).casefold()
    return "".join(char for char in text if char.isalnum())


def _display_group_label(value) -> str:
    text = _normalized_label(value)
    if _normalized_key(text) == _normalized_key(_FARM_3X3_GROUP_LABEL):
        return _FARM_3X3_GROUP_LABEL
    return text


def _farm_3x3_details() -> list[dict]:
    """Return the five canonical built-in 3x3 schemes in the store-defined order.

    These are variants of one service, not independent second-level groups. Manager
    catalog_group_label overrides must never split them apart in Discord quick order.
    Price/rule data is still resolved later through each detail's rule_key.
    """
    by_rule_key: dict[str, dict] = {}
    for group in orders.SELF_SERVICE_ORDER_CATALOG.get("farm", []):
        if _normalized_key(group.get("label")) != _normalized_key(_FARM_3X3_GROUP_LABEL):
            continue
        for detail in group.get("details", []):
            rule_key = str(detail.get("rule_key") or "")
            if rule_key not in _FARM_3X3_RULE_KEYS:
                continue

            item = dict(detail)
            rule = orders.ORDER_RULES.get(rule_key)
            manager_group_label = (
                str(getattr(rule, "catalog_group_label", "") or "").strip()
                if rule is not None
                else ""
            )
            if manager_group_label and rule is not None:
                item["label"] = str(
                    getattr(rule, "label", "")
                    or item.get("label")
                    or ""
                )
            item["item"] = str(
                getattr(rule, "label", "")
                or item.get("label")
                or ""
            )
            by_rule_key[rule_key] = item
        break

    return [
        by_rule_key[rule_key]
        for rule_key in _FARM_3X3_RULE_ORDER
        if rule_key in by_rule_key
    ]


def _canonical_details(category: str | None, group_label: str | None) -> list[dict]:
    """Resolve a visible Discord service group to its selectable details."""
    if _ORIGINAL_DETAILS_RESOLVER is None:
        return []
    if category is None or group_label is None:
        return []

    category_text = str(category)
    target_key = _normalized_key(group_label)
    if not target_key:
        return []

    # 3x3 is a fixed built-in five-scheme service. Do not let per-rule manager
    # catalog_group_label overrides split three variants away from this selector.
    if category_text == "farm" and target_key == _normalized_key(_FARM_3X3_GROUP_LABEL):
        return _farm_3x3_details()

    candidates: list[str] = []
    seen_raw: set[str] = set()

    for value in orders.ORDER_ITEM_GROUPS_BY_CATEGORY.get(category_text, []):
        text = str(value or "").strip()
        if not text or _normalized_key(text) != target_key or text in seen_raw:
            continue
        seen_raw.add(text)
        candidates.append(text)

    raw_group = str(group_label or "").strip()
    if raw_group and _normalized_key(raw_group) == target_key and raw_group not in seen_raw:
        candidates.insert(0, raw_group)

    result: list[dict] = []
    seen_details: set[str] = set()
    for candidate in candidates:
        for detail in _ORIGINAL_DETAILS_RESOLVER(category_text, candidate):
            detail_key = str(
                detail.get("rule_key")
                or detail.get("value")
                or detail.get("label")
                or ""
            )
            if not detail_key or detail_key in seen_details:
                continue
            seen_details.add(detail_key)
            result.append(dict(detail))
    return result


def _live_groups(category: str) -> list[str]:
    """Return only real, selectable storefront groups for the public quick entry."""
    category_text = str(category)
    if category_text == str(quick.VIP_TIMER_CATEGORY):
        quick.refresh_vip_timer_self_service_catalog()

    result: list[str] = []
    seen: set[str] = set()
    farm_3x3_added = False

    for value in orders.ORDER_ITEM_GROUPS_BY_CATEGORY.get(category_text, []):
        details = _canonical_details(category_text, value)
        if not details:
            continue

        # Any effective group made exclusively from the built-in 3x3 variants is
        # one service. This collapses stale/manager-split groups into 賽季3x3 while
        # keeping unrelated custom farm services untouched.
        detail_rule_keys = {
            str(detail.get("rule_key") or "")
            for detail in details
            if str(detail.get("rule_key") or "")
        }
        if (
            category_text == "farm"
            and detail_rule_keys
            and detail_rule_keys.issubset(_FARM_3X3_RULE_KEYS)
        ):
            if not farm_3x3_added:
                result.append(_FARM_3X3_GROUP_LABEL)
                seen.add(_normalized_key(_FARM_3X3_GROUP_LABEL))
                farm_3x3_added = True
            continue

        text = _display_group_label(value)
        key = _normalized_key(text)
        if not text or not key or key in seen:
            continue

        seen.add(key)
        result.append(text)

    # Defensive fallback: the raw catalog is authoritative for the built-in 3x3
    # service even if every effective group label was overridden in manager data.
    if category_text == "farm" and not farm_3x3_added and _farm_3x3_details():
        result.insert(0, _FARM_3X3_GROUP_LABEL)

    return result


def _install_canonical_group_resolver() -> None:
    global _ORIGINAL_DETAILS_RESOLVER
    if _ORIGINAL_DETAILS_RESOLVER is not None:
        return

    _ORIGINAL_DETAILS_RESOLVER = orders.get_order_item_details_for_group
    orders.get_order_item_details_for_group = _canonical_details

    # These modules imported the resolver directly, so update their local aliases
    # too. This is Discord-runtime only; the separate web process keeps its own UI.
    from services import order_runtime
    from services import self_service_selection_state as selection_state

    order_runtime.get_order_item_details_for_group = _canonical_details
    selection_state.get_order_item_details_for_group = _canonical_details


def _disable_legacy_ticket_patch() -> None:
    """Keep the old core ticket wrapper from stacking under production policy.

    setup_commands installs fixes before quick_order_v2. Marking the legacy patch as
    already handled means install_quick_order_v2 still registers persistent views and
    panel tasks, while production remains the sole owner of Quick Order ticket UI.
    """
    if (
        getattr(quick, "_ORIGINAL_VIEW_INIT", None) is None
        and getattr(quick, "_ORIGINAL_PANEL_BUILDER", None) is None
    ):
        quick._PATCH_INSTALLED = True


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

    # Public entry and ticket detail lookup use one resolver. Built-in 3x3 is
    # explicitly kept as one service with five schemes.
    _install_canonical_group_resolver()
    quick._groups = _live_groups

    # Production owns the only active Quick Order ticket UI wrapper. Disable the
    # old core wrapper before install_quick_order_v2 runs immediately after us.
    _disable_legacy_ticket_patch()

    # Discord supports up to five buttons per action row; keep all four Delta
    # entry buttons on the same row instead of forcing the fourth onto row 2.
    quick.QuickDeltaEntryView.__init__ = _delta_entry_init

    _INSTALLED = True
    print("[quick-order-v2-fix] fixes installed", flush=True)


__all__ = ["install_quick_order_v2_fixes", "repair_existing_quick_order_v2_tickets"]