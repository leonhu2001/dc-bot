from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

import discord
from sqlalchemy import select

from shared.db import SessionLocal
from shared.models import WebOrder
from shared.order_acceptance import ACCEPTED_PENDING_PAY, get_acceptance_state
from shared.order_state import WAITING_ACCEPTANCE, transition_order_state
from services.acceptance.payment_panel import ensure_acceptance_payment_panel
from services.orders import _to_int


@dataclass(frozen=True)
class AcceptanceRepairDeps:
    order_selections: dict[int, dict]
    payment_method_view_type: type
    refresh_acceptance_dispatch: Callable[..., Any]
    sync_ticket_access_from_state: Callable[..., Any]


_DEPS: AcceptanceRepairDeps | None = None


def configure_acceptance_repair_runtime(
    *,
    order_selections: dict[int, dict],
    payment_method_view_type: type,
    refresh_acceptance_dispatch: Callable[..., Any],
    sync_ticket_access_from_state: Callable[..., Any],
) -> None:
    global _DEPS
    _DEPS = AcceptanceRepairDeps(
        order_selections=order_selections,
        payment_method_view_type=payment_method_view_type,
        refresh_acceptance_dispatch=refresh_acceptance_dispatch,
        sync_ticket_access_from_state=sync_ticket_access_from_state,
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
        (WAITING_ACCEPTANCE, ACCEPTED_PENDING_PAY),
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

        try:
            state = get_acceptance_state(int(order_id))
            state_status = str(
                getattr(state, "status", current_status) or current_status
            ).lower()
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

        payment_message, action = await ensure_acceptance_payment_panel(
            guild=guild,
            ticket_channel=ticket_channel,
            data=data,
            payment_method_view_type=deps.payment_method_view_type,
            customer_id=customer_id,
            category_label=str(data.get("category_label") or category_label),
            item=str(data.get("item") or item),
            quantity=_to_int(data.get("quantity"), quantity) or quantity,
            companion_preference=data.get("companion_preference"),
            amount=_to_int(data.get("amount"), amount) or amount,
            state=state,
            reuse_existing=True,
            log_title="付款 panel 已修復",
            log_source=reason,
        )

        if payment_message is None:
            return False, f"WEB-{order_id} 付款 panel 修復失敗。"

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

        action_text = (
            "已重新掛回付款 panel"
            if action == "restored"
            else "已補送新的付款 panel"
        )
        return True, f"WEB-{order_id} {action_text}。"
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
        (ACCEPTED_PENDING_PAY, WAITING_ACCEPTANCE),
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
            .where(WebOrder.status.in_((WAITING_ACCEPTANCE, ACCEPTED_PENDING_PAY)))
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
