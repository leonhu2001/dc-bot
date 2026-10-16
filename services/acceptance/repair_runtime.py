from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

import discord
from sqlalchemy import select

from core.database import remember_order_data, save_bot_data
from core.time_utils import get_taipei_now_iso
from shared.db import SessionLocal
from shared.models import WebOrder
from shared.order_acceptance import ACCEPTED_PENDING_PAY, get_acceptance_state
from shared.order_state import WAITING_ACCEPTANCE, transition_order_state
from services.logging_service import send_order_log
from services.order_flow import build_payment_method_embed
from services.orders import _to_int


@dataclass(frozen=True)
class AcceptanceRepairDeps:
    order_selections: dict[int, dict]
    payment_method_view_type: type
    refresh_acceptance_dispatch: Callable[..., Any]
    sync_ticket_access_from_state: Callable[..., Any]
    acceptance_staff_display_text: Callable[..., str | None]


_DEPS: AcceptanceRepairDeps | None = None


def configure_acceptance_repair_runtime(
    *,
    order_selections: dict[int, dict],
    payment_method_view_type: type,
    refresh_acceptance_dispatch: Callable[..., Any],
    sync_ticket_access_from_state: Callable[..., Any],
    acceptance_staff_display_text: Callable[..., str | None],
) -> None:
    global _DEPS
    _DEPS = AcceptanceRepairDeps(
        order_selections=order_selections,
        payment_method_view_type=payment_method_view_type,
        refresh_acceptance_dispatch=refresh_acceptance_dispatch,
        sync_ticket_access_from_state=sync_ticket_access_from_state,
        acceptance_staff_display_text=acceptance_staff_display_text,
    )


def _require_deps() -> AcceptanceRepairDeps:
    if _DEPS is None:
        raise RuntimeError("acceptance repair runtime not configured")
    return _DEPS


def _list_repair_order_ids(statuses: tuple[str, ...], *, limit: int) -> list[int]:
    db = SessionLocal()
    try:
        rows = db.execute(
            select(WebOrder.id)
            .where(WebOrder.status.in_(statuses))
            .order_by(WebOrder.id.desc())
            .limit(max(0, int(limit)))
        ).all()
        return [int(row[0]) for row in rows]
    finally:
        db.close()


async def repair_pending_acceptance_dispatch_panels_once(
    guild: discord.Guild,
    *,
    limit: int = 100,
) -> int:
    deps = _require_deps()
    repaired = 0

    for order_id in _list_repair_order_ids(
        ("waiting_acceptance", "accepted_pending_pay"),
        limit=limit,
    ):
        try:
            await deps.refresh_acceptance_dispatch(guild, order_id)
            repaired += 1
        except Exception as exc:
            print(
                f"[acceptance-sync] startup reconcile failed "
                f"order_id={order_id}: {type(exc).__name__}: {exc}",
                flush=True,
            )

    return repaired


async def restore_acceptance_payment_panel_for_order(
    guild: discord.Guild,
    order_id: int,
    *,
    reason: str = "manual",
) -> tuple[bool, str]:
    deps = _require_deps()
    db = SessionLocal()
    try:
        order = db.get(WebOrder, int(order_id))
        if order is None:
            return False, f"找不到 WEB-{order_id}。"

        current_status = str(order.status or "").lower()
        state = None
        state_status = current_status
        accepted_count = None
        required_count = None

        try:
            state = get_acceptance_state(int(order_id))
            state_status = str(
                getattr(state, "status", current_status) or current_status
            ).lower()
            accepted_count = getattr(state, "accepted_count", None)
            required_count = getattr(state, "required_staff_count", None)
        except Exception:
            state = None

        if (
            state_status != ACCEPTED_PENDING_PAY
            and current_status != ACCEPTED_PENDING_PAY
        ):
            return (
                False,
                f"WEB-{order_id} 目前不是等待付款狀態，"
                f"status={current_status}，acceptance_status={state_status}。",
            )

        ticket_channel_id = _to_int(order.ticket_channel_id)
        if ticket_channel_id is None:
            return False, f"WEB-{order_id} 沒有 ticket_channel_id。"

        ticket_channel = guild.get_channel(ticket_channel_id)
        if not isinstance(ticket_channel, discord.TextChannel):
            return False, f"WEB-{order_id} 找不到票口頻道：{ticket_channel_id}。"

        customer_id = _to_int(order.customer_discord_id)
        if customer_id is None:
            return False, f"WEB-{order_id} 沒有 customer_discord_id。"

        amount = (
            _to_int(getattr(order, "customer_pay_amount", None), 0)
            or _to_int(order.amount, 0)
            or _to_int(getattr(order, "total_amount", None), 0)
            or 0
        )
        quantity = _to_int(order.quantity, 1) or 1
        category_label = str(order.category or "訂單")
        item = str(order.item or "未紀錄")

        data = deps.order_selections.setdefault(ticket_channel_id, {})
        data["status"] = ACCEPTED_PENDING_PAY
        data["customer_id"] = customer_id
        data["category"] = data.get("category") or category_label
        data["category_label"] = data.get("category_label") or category_label
        data["item"] = data.get("item") or item
        data["quantity"] = _to_int(data.get("quantity"), quantity) or quantity
        data["amount"] = _to_int(data.get("amount"), amount) or amount
        data["total_amount"] = _to_int(data.get("total_amount"), amount) or amount

        dispatch_channel_id = _to_int(getattr(order, "dispatch_channel_id", None))
        dispatch_message_id = _to_int(getattr(order, "dispatch_message_id", None))
        if dispatch_channel_id is not None:
            data["dispatch_channel_id"] = dispatch_channel_id
        if dispatch_message_id is not None:
            data["dispatch_message_id"] = dispatch_message_id

        if str(data.get("payment_method") or "") == "待付款":
            data.pop("payment_method", None)

        selected_payment_method = str(data.get("payment_method") or "").strip() or None
        accepted_staff_display_text = (
            deps.acceptance_staff_display_text(guild, state)
            if state is not None
            else str(data.get("accepted_staff_display_text") or "").strip() or None
        )
        if accepted_staff_display_text:
            data["accepted_staff_display_text"] = accepted_staff_display_text

        payment_embed = build_payment_method_embed(
            customer_id=customer_id,
            category_label=str(data.get("category_label") or category_label),
            item=str(data.get("item") or item),
            quantity=_to_int(data.get("quantity"), quantity) or quantity,
            payment_method=selected_payment_method,
            companion_preference=data.get("companion_preference"),
            amount=_to_int(data.get("amount"), amount) or amount,
            receiver_text=accepted_staff_display_text,
        )
        payment_view = deps.payment_method_view_type(
            customer_id=customer_id,
            channel_id=ticket_channel_id,
            selected_method=selected_payment_method,
        )

        existing_message_id = _to_int(data.get("payment_message_id"))
        existing_channel_id = (
            _to_int(data.get("payment_channel_id"), ticket_channel_id)
            or ticket_channel_id
        )
        existing_channel = guild.get_channel(existing_channel_id)
        existing_message = None

        if (
            isinstance(existing_channel, discord.TextChannel)
            and existing_message_id is not None
        ):
            try:
                existing_message = await existing_channel.fetch_message(
                    existing_message_id
                )
            except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                existing_message = None

        content = f"<@{customer_id}> 接單人數已滿，請選擇付款方式。"
        if existing_message is not None:
            try:
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
                data["payment_channel_id"] = existing_message.channel.id
                data["payment_message_id"] = existing_message.id
                action = "已重新掛回付款 panel"
            except discord.HTTPException:
                existing_message = None

        if existing_message is None:
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
            data["payment_channel_id"] = ticket_channel.id
            data["payment_message_id"] = payment_message.id
            action = "已補送新的付款 panel"

        data["accepted_pending_pay_at"] = (
            data.get("accepted_pending_pay_at") or get_taipei_now_iso()
        )
        remember_order_data(ticket_channel_id, data)
        save_bot_data()

        if current_status != ACCEPTED_PENDING_PAY:
            transition_order_state(
                order_id=int(order_id),
                target_status=ACCEPTED_PENDING_PAY,
                source="payment_panel_repair",
                reason=f"付款 panel 修復：{reason}",
                expected_statuses={
                    WAITING_ACCEPTANCE,
                    ACCEPTED_PENDING_PAY,
                },
            )

        progress_text = ""
        if accepted_count is not None and required_count is not None:
            progress_text = f"｜接單進度 {accepted_count}/{required_count}"

        try:
            await send_order_log(
                guild,
                title="付款 panel 已修復",
                fields=[
                    ("訂單", f"WEB-{order_id}", True),
                    ("顧客", f"<@{customer_id}>", True),
                    ("狀態", f"{action}{progress_text}", False),
                    ("票口", ticket_channel.mention, False),
                    ("來源", reason, True),
                ],
                color=discord.Color.gold(),
            )
        except Exception:
            pass

        return True, f"WEB-{order_id} {action}。"
    finally:
        db.close()


async def repair_pending_acceptance_payment_panels_once(
    guild: discord.Guild,
    *,
    reason: str = "startup",
    limit: int = 30,
) -> int:
    repaired = 0

    for order_id in _list_repair_order_ids(
        ("accepted_pending_pay", "waiting_acceptance"),
        limit=limit,
    ):
        try:
            ok, message = await restore_acceptance_payment_panel_for_order(
                guild,
                order_id,
                reason=reason,
            )
            if ok:
                repaired += 1
                print(f"[acceptance-repair] {message}", flush=True)
        except Exception as exc:
            print(
                f"[acceptance-repair] failed order_id={order_id}: "
                f"{type(exc).__name__}: {exc}",
                flush=True,
            )

    return repaired


async def repair_pending_acceptance_ticket_access_once(
    guild: discord.Guild,
    *,
    limit: int = 100,
) -> int:
    deps = _require_deps()
    db = SessionLocal()
    try:
        rows = db.execute(
            select(WebOrder.id, WebOrder.ticket_channel_id)
            .where(WebOrder.status.in_(("waiting_acceptance", "accepted_pending_pay")))
            .where(WebOrder.ticket_channel_id.is_not(None))
            .order_by(WebOrder.id.desc())
            .limit(max(0, int(limit)))
        ).all()
    finally:
        db.close()

    restored = 0
    for order_id, raw_ticket_channel_id in rows:
        ticket_channel_id = _to_int(raw_ticket_channel_id)
        if ticket_channel_id is None:
            continue

        try:
            state = get_acceptance_state(int(order_id))
            accepted_count = int(getattr(state, "accepted_count", 0) or 0)
            if accepted_count <= 0:
                continue

            await deps.sync_ticket_access_from_state(
                guild,
                ticket_channel_id,
                state,
            )
            restored += accepted_count
        except Exception as exc:
            print(
                f"[ticket-access] startup repair failed "
                f"order_id={order_id}: {type(exc).__name__}: {exc}",
                flush=True,
            )

    return restored
