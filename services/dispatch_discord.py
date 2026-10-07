from __future__ import annotations

import json
from typing import Any

import discord
from sqlalchemy import text

from services.dispatch_display import (
    acceptance_lock_display,
    build_service_display,
    dispatch_status_display,
)
from shared.db import SessionLocal
from shared.models import WebOrder
from shared.order_acceptance import (
    ACCEPTED_PENDING_PAY,
    WAITING_ACCEPTANCE,
    get_acceptance_state,
)


def _json_dict(value: Any) -> dict:
    if isinstance(value, dict):
        return dict(value)
    try:
        parsed = json.loads(str(value or ""))
    except Exception:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _to_int(value: Any, default: int | None = None) -> int | None:
    try:
        if value is None or value == "":
            return default
        return int(value)
    except (TypeError, ValueError):
        return default


def _load_ids(value: Any) -> list[str]:
    try:
        parsed = json.loads(str(value or "[]"))
    except Exception:
        return []
    if not isinstance(parsed, list):
        return []
    return [str(item) for item in parsed if str(item).strip()]


def _status_color(status: str, *, locked: bool) -> discord.Color:
    if locked:
        return discord.Color.gold()
    if status == WAITING_ACCEPTANCE:
        return discord.Color.blue()
    if status == ACCEPTED_PENDING_PAY:
        return discord.Color.gold()
    if status == "active":
        return discord.Color.green()
    if status == "stored":
        return discord.Color.orange()
    if status in {"closed", "cancelled"}:
        return discord.Color.dark_grey()
    return discord.Color.blurple()


def _financial_snapshot(order: WebOrder, price_snapshot: dict) -> dict:
    data = dict(price_snapshot)
    data.setdefault("original_amount", _to_int(order.original_amount, 0) or 0)
    data.setdefault("service_original_amount", data.get("original_amount", 0))
    data.setdefault("manual_discount_amount", _to_int(order.manual_discount_amount, 0) or 0)
    data.setdefault("cash_coupon_amount", _to_int(order.cash_coupon_amount, 0) or 0)
    data.setdefault("fixed_discount_amount", data.get("cash_coupon_amount", 0))
    data.setdefault("payout_base_amount", _to_int(order.payout_base_amount, 0) or 0)
    data.setdefault(
        "customer_pay_amount",
        _to_int(order.customer_pay_amount, _to_int(order.amount, 0) or 0) or 0,
    )

    absorbed = _to_int(order.store_absorbed_amount, 0) or 0
    fixed = _to_int(data.get("cash_coupon_amount"), 0) or 0
    data.setdefault("point_discount_coupon_amount", max(0, absorbed - fixed))
    return data


def _receiver_text(guild: discord.Guild, state) -> str:
    values: list[str] = []
    for claim in getattr(state, "claims", ()):
        user_id = _to_int(getattr(claim, "staff_discord_id", None))
        member = guild.get_member(user_id) if user_id is not None else None
        value = (
            member.mention
            if member is not None
            else str(getattr(claim, "staff_display_name", None) or "").strip()
        )
        if value and value not in values:
            values.append(value)
    return "、".join(values) or "尚未接單"


async def refresh_unified_dispatch_message(
    guild: discord.Guild,
    order_id: int,
) -> bool:
    """Render the canonical Discord dispatch panel from persisted order state.

    Both Discord button claims and Web lobby claims ultimately change the same
    acceptance tables. Re-rendering from those tables keeps presentation equal
    regardless of which surface performed the action.
    """
    db = SessionLocal()
    try:
        order = db.get(WebOrder, int(order_id))
        if order is None:
            return False

        meta = db.execute(
            text("""
                SELECT
                    created_at,
                    order_rule_key,
                    required_staff_count,
                    min_protector_count,
                    specified_staff_ids_json,
                    rule_snapshot_json,
                    price_snapshot_json
                FROM order_acceptance_meta
                WHERE order_id = :order_id
                LIMIT 1
            """),
            {"order_id": int(order_id)},
        ).mappings().first()

        if meta is None:
            return False

        dispatch_message_id = _to_int(order.dispatch_message_id)
        dispatch_channel_id = _to_int(order.dispatch_channel_id)
        ticket_channel_id = _to_int(order.ticket_channel_id)
        customer_id = _to_int(order.customer_discord_id)

        order_data = {
            "category": str(order.category or "未紀錄"),
            "item": str(order.item or "未紀錄"),
            "quantity": _to_int(order.quantity, 1) or 1,
            "payment_method": str(order.payment_method or "待付款"),
            "customer_display_name": str(order.customer_display_name or "未知顧客"),
            "note": str(order.note or "").strip(),
            "rule_snapshot_json": order.rule_snapshot_json or meta["rule_snapshot_json"],
            "price_snapshot_json": order.price_snapshot_json or meta["price_snapshot_json"],
            "order_rule_key": str(order.order_rule_key or meta["order_rule_key"] or ""),
        }
    finally:
        db.close()

    if dispatch_message_id is None or dispatch_channel_id is None or ticket_channel_id is None:
        return False

    dispatch_channel = guild.get_channel(dispatch_channel_id)
    ticket_channel = guild.get_channel(ticket_channel_id)
    if not isinstance(dispatch_channel, discord.TextChannel):
        return False
    if not isinstance(ticket_channel, discord.TextChannel):
        return False

    try:
        message = await dispatch_channel.fetch_message(dispatch_message_id)
    except (discord.NotFound, discord.Forbidden, discord.HTTPException):
        return False

    state = get_acceptance_state(int(order_id))
    lock = acceptance_lock_display(meta["created_at"], state.status)
    status_label, status_detail = dispatch_status_display(
        status=state.status,
        locked=bool(lock["locked"]),
        current_staff_count=int(state.accepted_count or 0),
        required_staff_count=int(state.required_staff_count or 0),
    )

    price_snapshot = _json_dict(order_data["price_snapshot_json"])
    rule_snapshot = _json_dict(order_data["rule_snapshot_json"])
    service = build_service_display(
        quantity=order_data["quantity"],
        rule_key=order_data["order_rule_key"],
        rule_snapshot=rule_snapshot,
        price_snapshot=price_snapshot,
    )

    embed = discord.Embed(
        title="魔丸娛樂｜接單面板",
        description="Discord 與 Web 接單共用同一份訂單狀態；服務內容在接單前後皆保持顯示。",
        color=_status_color(str(state.status or ""), locked=bool(lock["locked"])),
    )
    status_value = status_label
    if status_detail:
        status_value += f"\n{status_detail}"
    embed.add_field(name="狀態", value=status_value[:1024], inline=False)
    embed.add_field(name="顧客", value=order_data["customer_display_name"][:1024], inline=True)
    embed.add_field(name="票口", value=ticket_channel.mention, inline=True)
    embed.add_field(
        name="訂單",
        value=f"{order_data['category']}｜{order_data['item']}"[:1024],
        inline=False,
    )
    embed.add_field(name="服務內容", value=service["purchased_text"], inline=True)
    embed.add_field(name="實際服務", value=service["total_text"], inline=True)
    embed.add_field(name="付款方式", value=order_data["payment_method"][:1024], inline=True)

    if service["bonus_text"]:
        embed.add_field(
            name="服務加贈／福利",
            value=str(service["bonus_text"])[:1024],
            inline=False,
        )

    specified_ids = _load_ids(meta["specified_staff_ids_json"])
    if specified_ids:
        embed.add_field(
            name="指定人員",
            value="、".join(f"<@{worker_id}>" for worker_id in specified_ids)[:1024],
            inline=False,
        )

    embed.add_field(
        name="接單進度",
        value=f"{state.accepted_count}/{state.required_staff_count} 人",
        inline=True,
    )
    embed.add_field(
        name="目前接單",
        value=_receiver_text(guild, state)[:1024],
        inline=False,
    )

    if order_data["note"]:
        embed.add_field(name="訂單備註", value=order_data["note"][:1024], inline=False)

    financial_data = _financial_snapshot(order=order, price_snapshot=price_snapshot)
    try:
        from services.self_service_runtime import add_self_service_financial_breakdown_fields

        add_self_service_financial_breakdown_fields(
            embed,
            financial_data,
            final_label=("顧客實付" if state.status == "active" else "顧客應付"),
        )
    except Exception as exc:
        print(
            f"[dispatch-display] financial fields skipped order={order_id}: "
            f"{type(exc).__name__}: {exc}",
            flush=True,
        )

    embed.set_footer(text=f"魔丸娛樂｜WEB-{int(order_id)}｜接單系統")

    # The backend still validates every click. Disabling the shared button here
    # simply makes the one-minute whole-order lock visible and prevents noise.
    view_locked = bool(lock["locked"]) or state.status != WAITING_ACCEPTANCE
    try:
        from services.order_runtime import DispatchClaimView

        view = DispatchClaimView(
            customer_id=int(customer_id or 0),
            category_label=order_data["category"],
            item=order_data["item"],
            quantity=order_data["quantity"],
            payment_method=order_data["payment_method"],
            source_channel_id=ticket_channel_id,
            companion_preference=(
                "指定陪玩/打手"
                if specified_ids
                else "不指定陪玩/打手"
            ),
            locked=view_locked,
            status=str(state.status or WAITING_ACCEPTANCE),
        )
    except Exception as exc:
        print(
            f"[dispatch-display] view build failed order={order_id}: "
            f"{type(exc).__name__}: {exc}",
            flush=True,
        )
        return False

    try:
        await message.edit(
            embed=embed,
            view=view,
            allowed_mentions=discord.AllowedMentions(
                users=True,
                roles=False,
                everyone=False,
            ),
        )
    except (discord.NotFound, discord.Forbidden, discord.HTTPException) as exc:
        print(
            f"[dispatch-display] message edit failed order={order_id}: "
            f"{type(exc).__name__}: {exc}",
            flush=True,
        )
        return False

    return True
