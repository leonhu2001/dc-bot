from __future__ import annotations

import unicodedata

import discord
from discord.ext import commands

from services import orders
from services import quick_order_v2 as quick


_INSTALLED = False
_ORIGINAL_CREATE_TICKET = None
_ORIGINAL_DETAILS_RESOLVER = None


def _normalized_label(value) -> str:
    """Normalize storefront labels for Discord grouping/deduplication.

    Manager-edited catalog labels can pick up invisible Unicode format/control
    characters (zero-width space/joiner, BOM, word joiner, etc.) through copy/paste.
    Discord renders those labels identically, while Python string equality treats
    them as different groups. Strip invisible formatting characters and normalize
    whitespace before comparing or displaying the label.
    """
    text = unicodedata.normalize("NFKC", str(value or ""))
    cleaned: list[str] = []
    for char in text:
        category = unicodedata.category(char)
        if category == "Cf":
            continue
        if category == "Cc":
            if char.isspace():
                cleaned.append(" ")
            continue
        cleaned.append(char)
    return " ".join("".join(cleaned).strip().split())


def _normalized_key(value) -> str:
    return _normalized_label(value).casefold()


def _live_groups(category: str) -> list[str]:
    """Return one visible option for each effective storefront group."""
    if str(category) == str(quick.VIP_TIMER_CATEGORY):
        quick.refresh_vip_timer_self_service_catalog()

    result: list[str] = []
    seen: set[str] = set()
    for value in orders.ORDER_ITEM_GROUPS_BY_CATEGORY.get(str(category), []):
        text = _normalized_label(value)
        key = _normalized_key(text)
        if not text or key in seen:
            continue
        seen.add(key)
        result.append(text)
    return result


def _canonical_details(category: str | None, group_label: str | None) -> list[dict]:
    """Merge every raw spelling of one visible group into one detail list.

    The public select intentionally collapses visually-equivalent labels into one
    option. Detail lookup must do the opposite internally: inspect every distinct
    raw group string whose normalized key matches, then merge their products. This
    keeps all 3x3 variants even when one manager override contains an invisible
    Unicode character.
    """
    if _ORIGINAL_DETAILS_RESOLVER is None:
        return []
    if category is None or group_label is None:
        return []

    target_key = _normalized_key(group_label)
    candidates: list[str] = []
    seen_raw: set[str] = set()

    for value in orders.ORDER_ITEM_GROUPS_BY_CATEGORY.get(str(category), []):
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
        for detail in _ORIGINAL_DETAILS_RESOLVER(category, candidate):
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

    # 1. Public entry and ticket detail lookup use the same canonical visible label.
    # The entry shows one option; detail lookup merges all raw Unicode variants.
    _install_canonical_group_resolver()
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
