from __future__ import annotations

from dataclasses import replace
import re

import discord
from discord.ext import commands

from core.config import config_int
from services.orders import (
    ORDER_CATEGORY_LABELS,
    get_order_item_detail_for_selection,
    get_order_item_group_label,
)
from services.ticket_identity import build_ticket_channel_name


CUSTOMER_CATEGORY_ID = config_int("CUSTOMER_CATEGORY_ID", 1483895536938651809)
_SIMPLIFIED_NAME_RE = re.compile(r"^[🟢🟡🟠⚫🔴⚪][・┃]客服中心$")
_ORIGINAL_QUICK_CREATE_TICKET = None

_GAME_LABELS = {
    "delta_desktop_basic": "三角洲端遊",
    "delta_mobile_basic": "三角洲手遊",
    "delta_desktop_fun": "三角洲趣味",
    "farm": "三角洲代肝",
    "basic": "三角洲",
    "fun": "三角洲趣味",
    "general": "通用",
    "steam": "STEAM",
    "valorant": "特戰英豪",
    "lol": "英雄聯盟",
    "apex": "APEX",
    "custom": "自訂",
    "vip_timer": "VIP計時",
}


def _topic_customer_id(channel: discord.TextChannel) -> int | None:
    for part in str(channel.topic or "").split(";"):
        if "=" not in part:
            continue
        key, value = part.split("=", 1)
        if key.strip() != "order_customer_id":
            continue
        try:
            return int(value.strip())
        except (TypeError, ValueError):
            return None
    return None


def _is_quick_order_ticket(channel: discord.TextChannel, data: dict) -> bool:
    return bool(data.get("quick_order_v2")) or "quick_order_v2=1" in str(channel.topic or "")


def _status_from_simplified_name(name: str) -> str:
    text = str(name or "")
    if text.startswith("🟠"):
        return "stored"
    if text.startswith("⚫"):
        return "closed"
    if text.startswith("🔴"):
        return "cancelled"
    return "active"


def _legacy_prefix(status: str) -> str:
    normalized = str(status or "").strip().lower()
    if normalized == "stored":
        return "存單"
    if normalized == "closed":
        return "已結單"
    if normalized in {"cancelled", "canceled"}:
        return "已取消"
    return "下單"


def _requested_status(prefix: str, data: dict) -> str:
    requested = str(prefix or "").strip()
    if requested.startswith("存單"):
        return "stored"
    if requested.startswith("已結單"):
        return "closed"
    if requested.startswith("已取消"):
        return "cancelled"

    current = str(data.get("status") or "").strip().lower()
    if current in {"stored", "closed", "cancelled", "canceled"}:
        return current
    return "active"


def _merge_claim_fallback(channel_id: int, data: dict) -> dict:
    merged = dict(data or {})
    try:
        from services import order_storage_runtime as storage

        claims = getattr(storage, "ORDER_CLAIMS", {})
        for claim in claims.values():
            if not isinstance(claim, dict):
                continue
            try:
                source_channel_id = int(claim.get("source_channel_id") or 0)
            except (TypeError, ValueError):
                continue
            if source_channel_id != int(channel_id):
                continue
            for key in (
                "customer_id",
                "category",
                "category_label",
                "item_group",
                "item_detail_value",
                "item",
                "quantity",
                "payment_method",
                "status",
            ):
                if not merged.get(key) and claim.get(key) is not None:
                    merged[key] = claim.get(key)
            break
    except Exception:
        pass
    return merged


def _game_label(data: dict) -> str:
    category = str(data.get("category") or "").strip()
    if category in _GAME_LABELS:
        return _GAME_LABELS[category]

    raw = str(
        data.get("category_label")
        or ORDER_CATEGORY_LABELS.get(category, "")
        or category
        or "訂單"
    ).strip()
    lower = raw.casefold()

    if "三角洲" in raw:
        if "手遊" in raw:
            return "三角洲手遊"
        if "趣味" in raw:
            return "三角洲趣味"
        if "代肝" in raw or "代解" in raw:
            return "三角洲代肝"
        if "端遊" in raw:
            return "三角洲端遊"
        return "三角洲"
    if "特戰" in raw or "valorant" in lower:
        return "特戰英豪"
    if "英雄聯盟" in raw or lower == "lol" or "lol" in lower:
        return "英雄聯盟"
    if "apex" in lower:
        return "APEX"
    if "steam" in lower:
        return "STEAM"
    if "vip" in lower and "計時" in raw:
        return "VIP計時"
    return raw or "訂單"


def _play_labels(data: dict) -> list[str]:
    category = str(data.get("category") or "").strip() or None
    group = str(data.get("item_group") or "").strip()
    item = str(data.get("item") or "").strip()
    detail_value = str(data.get("item_detail_value") or "").strip() or None

    if not group and item:
        try:
            group = str(get_order_item_group_label(item) or "").strip()
        except Exception:
            group = ""

    detail_label = ""
    if category and group and detail_value:
        try:
            detail = get_order_item_detail_for_selection(category, group, detail_value)
            detail_label = str((detail or {}).get("label") or "").strip()
        except Exception:
            detail_label = ""

    if not detail_label and item and item != group:
        detail_label = item

    result: list[str] = []
    seen: set[str] = set()
    for value in (group, detail_label):
        text = str(value or "").strip()
        key = text.casefold()
        if not text or key in seen:
            continue
        seen.add(key)
        result.append(text)
    return result


def _order_prefix(data: dict, status: str = "active") -> str:
    parts = [_legacy_prefix(status), _game_label(data), *_play_labels(data)]
    return "-".join(str(part).strip() for part in parts if str(part).strip())


def _stored_prefix(data: dict) -> str:
    return _order_prefix(data, "stored")


async def _rename_quick_ticket_from_data(
    channel: discord.TextChannel,
    data: dict,
    *,
    status: str = "active",
    member: discord.Member | None = None,
) -> None:
    if not _is_quick_order_ticket(channel, data):
        return

    customer_id = _topic_customer_id(channel) or int(data.get("customer_id") or 0) or None
    if member is None and customer_id:
        member = channel.guild.get_member(customer_id)
        if member is None:
            try:
                member = await channel.guild.fetch_member(customer_id)
            except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                member = None

    display_name = None
    if member is None:
        display_name = str(data.get("customer_display_name") or customer_id or "客人").strip()

    new_name = build_ticket_channel_name(
        _order_prefix(data, status),
        member,
        display_name=display_name,
    )
    if channel.name == new_name:
        return

    try:
        await channel.edit(
            name=new_name,
            reason="Keep quick-order ticket game and service visible",
        )
    except (discord.Forbidden, discord.HTTPException) as exc:
        print(
            f"[order-ticket-name] quick rename failed channel={channel.id}: "
            f"{type(exc).__name__}: {exc}",
            flush=True,
        )


def _install_quick_create_ticket_patch() -> bool:
    global _ORIGINAL_QUICK_CREATE_TICKET
    if _ORIGINAL_QUICK_CREATE_TICKET is not None:
        return True

    try:
        from services import quick_order_v2 as quick
        from services import self_service_ui_runtime as ui

        original = quick._create_ticket
        _ORIGINAL_QUICK_CREATE_TICKET = original

        async def informative_quick_create_ticket(
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
                data = ui.SELF_SERVICE_ORDER_SELECTIONS.get(ticket.id, {})
                if isinstance(data, dict):
                    await _rename_quick_ticket_from_data(
                        ticket,
                        data,
                        status="active",
                        member=interaction.user if isinstance(interaction.user, discord.Member) else None,
                    )
            return ticket

        quick._create_ticket = informative_quick_create_ticket
        return True
    except Exception as exc:
        print(
            f"[order-ticket-name] cannot install quick-create wrapper: "
            f"{type(exc).__name__}: {exc}",
            flush=True,
        )
        return False


def _install_store_renamer_patch() -> bool:
    """Keep game + service/detail in every quick-order rename and stored order."""
    try:
        from services import order_payment_runtime, order_runtime

        state = getattr(order_runtime, "_RUNTIME_STATE", None)
        if state is None:
            return False

        existing_wrapper = getattr(order_runtime, "_rich_store_ticket_renamer", None)
        if getattr(order_runtime, "_rich_store_ticket_renamer_installed", False):
            if callable(existing_wrapper):
                # Payment finalization owns a separate runtime callback. Keep it
                # on the same context-aware renamer so a raw item such as 單陪
                # cannot overwrite the rich quick-ticket name after payment.
                order_payment_runtime.rename_ticket_channel = existing_wrapper
            return True

        original = state.ticket_channel_renamer

        async def rich_ticket_channel_renamer(
            channel,
            prefix: str,
            member=None,
            *,
            display_name: str | None = None,
        ) -> None:
            effective_prefix = str(prefix or "")
            if isinstance(channel, discord.TextChannel):
                data = state.order_selections.get(channel.id, {})
                if not isinstance(data, dict):
                    data = {}
                data = _merge_claim_fallback(channel.id, data)

                if _is_quick_order_ticket(channel, data):
                    effective_prefix = _order_prefix(
                        data,
                        _requested_status(effective_prefix, data),
                    )
                elif effective_prefix.startswith("存單"):
                    effective_prefix = _stored_prefix(data)

            await original(
                channel,
                effective_prefix,
                member=member,
                display_name=display_name,
            )

        order_runtime._RUNTIME_STATE = replace(
            state,
            ticket_channel_renamer=rich_ticket_channel_renamer,
        )
        order_runtime._rich_store_ticket_renamer = rich_ticket_channel_renamer
        order_runtime._rich_store_ticket_renamer_installed = True
        # order_payment_runtime is configured independently from order_runtime.
        # Without this assignment, payment completion renames the ticket again
        # from its raw item label and can erase the game/service prefix.
        order_payment_runtime.rename_ticket_channel = rich_ticket_channel_renamer
        return True
    except Exception as exc:
        print(
            f"[order-ticket-name] cannot install stored-name wrapper: "
            f"{type(exc).__name__}: {exc}",
            flush=True,
        )
        return False


async def restore_unintentionally_simplified_order_ticket_names(
    bot: commands.Bot,
) -> None:
    """Repair simplified names, enrich quick tickets, and preserve stored-ticket detail."""
    await bot.wait_until_ready()
    _install_store_renamer_patch()
    _install_quick_create_ticket_patch()

    category = bot.get_channel(CUSTOMER_CATEGORY_ID)
    if not isinstance(category, discord.CategoryChannel):
        try:
            fetched = await bot.fetch_channel(CUSTOMER_CATEGORY_ID)
            category = fetched if isinstance(fetched, discord.CategoryChannel) else None
        except (discord.NotFound, discord.Forbidden, discord.HTTPException):
            category = None

    if not isinstance(category, discord.CategoryChannel):
        return

    try:
        from services import self_service_ui_runtime as ui
        selections = ui.SELF_SERVICE_ORDER_SELECTIONS
    except Exception:
        selections = {}

    restored = 0
    for channel in list(category.text_channels):
        customer_id = _topic_customer_id(channel)
        if customer_id is None:
            continue

        data = selections.get(channel.id, {}) if isinstance(selections, dict) else {}
        if not isinstance(data, dict):
            data = {}
        data = _merge_claim_fallback(channel.id, data)

        status = str(data.get("status") or "").strip().lower()
        simplified = bool(_SIMPLIFIED_NAME_RE.fullmatch(str(channel.name or "")))
        if not status and simplified:
            status = _status_from_simplified_name(channel.name)

        is_quick = _is_quick_order_ticket(channel, data)
        is_stored = status == "stored" or str(channel.name or "").startswith("存單-")
        if is_quick:
            prefix = _order_prefix(data, status or "active")
        elif is_stored:
            prefix = _stored_prefix(data)
        elif simplified:
            prefix = _legacy_prefix(status)
        else:
            continue

        member = channel.guild.get_member(customer_id)
        if member is None:
            try:
                member = await channel.guild.fetch_member(customer_id)
            except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                member = None

        display_name = None
        if member is None:
            display_name = str(data.get("customer_display_name") or "").strip() or str(customer_id)

        new_name = build_ticket_channel_name(
            prefix,
            member,
            display_name=display_name,
        )
        if channel.name == new_name:
            continue

        try:
            await channel.edit(
                name=new_name,
                reason="Restore informative order ticket naming",
            )
            restored += 1
        except (discord.Forbidden, discord.HTTPException) as exc:
            print(
                f"[order-ticket-name-restore] rename failed channel={channel.id}: "
                f"{type(exc).__name__}: {exc}",
                flush=True,
            )

    if restored:
        print(
            f"[order-ticket-name-restore] restored {restored} order ticket channel(s)",
            flush=True,
        )


def install_order_ticket_name_restore(bot: commands.Bot) -> None:
    _install_store_renamer_patch()
    _install_quick_create_ticket_patch()
    if getattr(bot, "_order_ticket_name_restore_started", False):
        return
    bot._order_ticket_name_restore_started = True
    bot.loop.create_task(restore_unintentionally_simplified_order_ticket_names(bot))


__all__ = [
    "install_order_ticket_name_restore",
    "restore_unintentionally_simplified_order_ticket_names",
]
