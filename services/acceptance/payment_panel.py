from __future__ import annotations

from typing import Any

import discord

from core.database import remember_order_data, save_bot_data
from core.time_utils import get_taipei_now_iso
from services.logging_service import send_order_log
from services.order_flow import build_payment_method_embed
from services.orders import _to_int


def acceptance_staff_display_text(
    guild: discord.Guild | None,
    state,
) -> str | None:
    """Return accepted staff as Discord mentions with saved-name fallback."""
    values: list[str] = []

    for claim in getattr(state, "claims", ()):
        user_id = _to_int(getattr(claim, "staff_discord_id", None))
        member = (
            guild.get_member(user_id)
            if guild is not None and user_id is not None
            else None
        )

        if member is not None:
            display_value = member.mention
        else:
            display_value = str(
                getattr(claim, "staff_display_name", None)
                or ""
            ).strip()

        if display_value and display_value not in values:
            values.append(display_value)

    return "、".join(values) or None


def _normalize_selected_payment_method(data: dict) -> str | None:
    selected = str(data.get("payment_method") or "").strip()

    if selected == "待付款":
        data.pop("payment_method", None)
        return None

    return selected or None


def _payment_view(
    payment_method_view_type,
    *,
    customer_id: int,
    channel_id: int,
    selected_method: str | None = None,
    submitted: bool = False,
):
    kwargs: dict[str, Any] = {
        "customer_id": customer_id,
        "channel_id": channel_id,
    }

    if selected_method:
        kwargs["selected_method"] = selected_method

    if submitted:
        kwargs["submitted"] = True

    return payment_method_view_type(**kwargs)


def build_acceptance_payment_surface(
    *,
    payment_method_view_type,
    customer_id: int,
    channel_id: int,
    category_label: str,
    item: str,
    quantity: int,
    companion_preference,
    amount: int,
    receiver_text: str | None,
    selected_method: str | None = None,
    submitted: bool = False,
    payment_status_note: str | None = None,
) -> tuple[discord.Embed, discord.ui.View]:
    payment_embed = build_payment_method_embed(
        customer_id=customer_id,
        category_label=category_label,
        item=item,
        quantity=quantity,
        payment_method=selected_method,
        companion_preference=companion_preference,
        amount=amount,
        receiver_text=receiver_text,
        submitted=submitted,
    )

    if payment_status_note:
        payment_embed.add_field(
            name="付款狀態",
            value=payment_status_note,
            inline=False,
        )

    payment_view = _payment_view(
        payment_method_view_type,
        customer_id=customer_id,
        channel_id=channel_id,
        selected_method=selected_method,
        submitted=submitted,
    )

    return payment_embed, payment_view


async def ensure_acceptance_payment_panel(
    *,
    guild: discord.Guild,
    ticket_channel: discord.TextChannel,
    data: dict,
    payment_method_view_type,
    customer_id: int,
    category_label: str,
    item: str,
    quantity: int,
    companion_preference,
    amount: int,
    state,
    reuse_existing: bool = False,
    log_title: str | None = None,
    log_source: str | None = None,
) -> tuple[discord.Message | None, str]:
    """Create or restore the one canonical payment panel for an accepted order.

    Normal acceptance flow uses ``reuse_existing=False`` and will not duplicate
    a recorded panel. Repair flow uses ``reuse_existing=True`` so the recorded
    message is refreshed when it still exists, otherwise a new one is sent.
    """
    channel_id = int(ticket_channel.id)
    selected_method = _normalize_selected_payment_method(data)
    receiver_text = acceptance_staff_display_text(guild, state)

    if receiver_text:
        data["accepted_staff_display_text"] = receiver_text
    else:
        data.pop("accepted_staff_display_text", None)

    existing_message_id = _to_int(data.get("payment_message_id"))

    if existing_message_id is not None and not reuse_existing:
        return None, "existing"

    payment_embed, payment_view = build_acceptance_payment_surface(
        payment_method_view_type=payment_method_view_type,
        customer_id=customer_id,
        channel_id=channel_id,
        category_label=category_label,
        item=item,
        quantity=quantity,
        companion_preference=companion_preference,
        amount=amount,
        receiver_text=receiver_text,
        selected_method=selected_method,
    )

    content = f"<@{customer_id}> 接單人數已滿，請選擇付款方式。"
    payment_message: discord.Message | None = None
    action = "sent"

    if reuse_existing and existing_message_id is not None:
        existing_channel_id = (
            _to_int(data.get("payment_channel_id"), channel_id)
            or channel_id
        )
        existing_channel = guild.get_channel(existing_channel_id)

        if isinstance(existing_channel, discord.TextChannel):
            try:
                existing_message = await existing_channel.fetch_message(
                    existing_message_id
                )
                await existing_message.edit(
                    content=content,
                    embed=payment_embed,
                    view=payment_view,
                    allowed_mentions=discord.AllowedMentions(
                        users=True,
                        roles=False,
                        everyone=False,
                    ),
                )
                payment_message = existing_message
                action = "restored"
            except (
                discord.NotFound,
                discord.Forbidden,
                discord.HTTPException,
            ):
                payment_message = None

    if payment_message is None:
        payment_message = await ticket_channel.send(
            content=content,
            embed=payment_embed,
            view=payment_view,
            allowed_mentions=discord.AllowedMentions(
                users=True,
                roles=False,
                everyone=False,
            ),
        )
        action = "sent"

    data["payment_channel_id"] = int(payment_message.channel.id)
    data["payment_message_id"] = int(payment_message.id)
    data["accepted_pending_pay_at"] = (
        data.get("accepted_pending_pay_at")
        or get_taipei_now_iso()
    )

    remember_order_data(channel_id, data)
    save_bot_data()

    if log_title:
        fields = [
            ("顧客", f"<@{customer_id}>", True),
            ("訂單", f"{category_label}｜{item} x{quantity}", False),
            (
                "接單進度",
                f"{getattr(state, 'accepted_count', 0)}/{getattr(state, 'required_staff_count', 1)}",
                True,
            ),
            ("票口", ticket_channel.mention, False),
        ]

        if log_source:
            fields.append(("來源", log_source, True))

        try:
            await send_order_log(
                guild,
                title=log_title,
                fields=fields,
                color=discord.Color.gold(),
            )
        except Exception:
            if reuse_existing:
                pass
            else:
                raise

    return payment_message, action


async def invalidate_acceptance_payment_panel(
    *,
    guild: discord.Guild,
    ticket_channel: discord.TextChannel,
    data: dict,
    payment_method_view_type,
    customer_id: int,
    category_label: str,
    item: str,
    quantity: int,
    companion_preference,
    amount: int,
    state,
) -> bool:
    """Disable a stale payment panel when acceptance falls below requirement."""
    old_message_id = _to_int(data.get("payment_message_id"))
    old_channel_id = (
        _to_int(data.get("payment_channel_id"), ticket_channel.id)
        or ticket_channel.id
    )

    if old_message_id is not None:
        old_channel = guild.get_channel(old_channel_id)

        if isinstance(old_channel, discord.TextChannel):
            try:
                old_message = await old_channel.fetch_message(old_message_id)
                receiver_text = acceptance_staff_display_text(guild, state)
                disabled_embed, disabled_view = build_acceptance_payment_surface(
                    payment_method_view_type=payment_method_view_type,
                    customer_id=customer_id,
                    channel_id=ticket_channel.id,
                    category_label=category_label,
                    item=item,
                    quantity=quantity,
                    companion_preference=companion_preference,
                    amount=amount,
                    receiver_text=receiver_text,
                    selected_method="等待接單人數補滿",
                    submitted=True,
                    payment_status_note=(
                        "接單人數目前不足，這個付款面板已失效。"
                        "人數再次補滿時會重新開付款面板。"
                    ),
                )
                await old_message.edit(
                    embed=disabled_embed,
                    view=disabled_view,
                    allowed_mentions=discord.AllowedMentions(
                        users=True,
                        roles=False,
                        everyone=False,
                    ),
                )
            except (
                discord.NotFound,
                discord.Forbidden,
                discord.HTTPException,
            ):
                pass

    changed = any(
        key in data
        for key in (
            "payment_message_id",
            "payment_channel_id",
            "accepted_pending_pay_at",
        )
    )

    data.pop("payment_message_id", None)
    data.pop("payment_channel_id", None)
    data.pop("accepted_pending_pay_at", None)

    if changed:
        remember_order_data(ticket_channel.id, data)
        save_bot_data()

    return changed
