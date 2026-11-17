"""Reconcile *display-only* Discord dispatch cards against paid WebOrders.

This never mutates order rows, payroll, payment status, Discord button views,
or message IDs. It only edits a known dispatch embed if its displayed state
disagrees with the durable active order.
"""
from __future__ import annotations

import asyncio
import discord

from services.dispatch_embed_presentation import (
    PAYMENT_FIELD, STATUS_FIELD, display_payment, display_status,
    unify_dispatch_embed,
)


def _recent_paid_orders(*, limit: int = 40) -> list[dict]:
    from sqlalchemy import select
    from shared.db import SessionLocal
    from shared.models import WebOrder

    session = SessionLocal()
    try:
        orders = session.scalars(
            select(WebOrder)
            .where(WebOrder.status == "active")
            .where(WebOrder.dispatch_message_id.is_not(None))
            .where(WebOrder.dispatch_channel_id.is_not(None))
            .order_by(WebOrder.id.desc())
            .limit(max(1, min(int(limit), 80)))
        ).all()
        return [{
            "id": int(order.id),
            "dispatch_channel_id": order.dispatch_channel_id,
            "dispatch_message_id": order.dispatch_message_id,
            "payment_method": getattr(order, "payment_method", None),
            "amount": (
                getattr(order, "customer_pay_amount", None)
                if getattr(order, "customer_pay_amount", None) is not None
                else getattr(order, "amount", None)
            ),
        } for order in orders]
    finally:
        session.close()


def _positive_int(value: object) -> int | None:
    try:
        result = int(value)
    except (ValueError, TypeError):
        return None
    return result if result > 0 else None


def _has_wrong_paid_status(embed: discord.Embed, *, zero_amount: bool) -> bool:
    fields = [(str(f.name), str(f.value)) for f in embed.fields]
    expected_phase, _color = display_status("active")
    expected_payment = display_payment(
        "active", zero_amount=zero_amount, paid_confirmed=True
    )
    return (
        len([value for name, value in fields if name == STATUS_FIELD]) != 1
        or len([value for name, value in fields if name == PAYMENT_FIELD]) != 1
        or any(name in {"狀態", "目前階段"} for name, _value in fields)
        or any(name == STATUS_FIELD and value != expected_phase for name, value in fields)
        or any(name == PAYMENT_FIELD and value != expected_payment for name, value in fields)
    )


async def reconcile_recent_paid_dispatch_embeds(
    bot: discord.Client, guild_id: int, *, limit: int = 40,
) -> int:
    guild = bot.get_guild(int(guild_id))
    if guild is None:
        return 0
    repaired = 0
    for row in _recent_paid_orders(limit=limit):
        channel_id = _positive_int(row["dispatch_channel_id"])
        message_id = _positive_int(row["dispatch_message_id"])
        if not channel_id or not message_id:
            continue
        channel = guild.get_channel(channel_id)
        if channel is None or not hasattr(channel, "fetch_message"):
            continue
        try:
            msg = await channel.fetch_message(message_id)
            if not msg.embeds:
                continue
            original = msg.embeds[0]
            # Only original dispatch cards, never unrelated channel notices.
            if str(original.title or "") not in {
                "魔丸娛樂｜接單面板", "網站訂單｜等待接單",
            }:
                continue
            zero_amount = row["amount"] is not None and int(row["amount"]) == 0
            if not _has_wrong_paid_status(original, zero_amount=zero_amount):
                continue
            corrected = original.copy()
            method = str(row["payment_method"] or "").strip()
            if method and method not in {"待付款", "未紀錄"}:
                for index, field in enumerate(corrected.fields):
                    if str(field.name) == "付款方式" and str(field.value) in {
                        "待付款", "未紀錄", "等待付款",
                    }:
                        corrected.set_field_at(
                            index, name="付款方式", value=method, inline=field.inline
                        )
            unify_dispatch_embed(
                corrected, status="active",
                zero_amount=zero_amount, paid_confirmed=True,
            )
            # Preserve the view and route: only update the existing Embed.
            await msg.edit(embed=corrected, allowed_mentions=discord.AllowedMentions.none())
            repaired += 1
        except (discord.NotFound, discord.Forbidden, discord.HTTPException) as exc:
            print(
                f"[dispatch-embed] cannot update WEB-{row['id']}: {type(exc).__name__}",
                flush=True,
            )
        except (ValueError, TypeError) as exc:
            print(f"[dispatch-embed] invalid WEB-{row['id']}: {exc}", flush=True)
    return repaired


async def paid_dispatch_embed_reconcile_worker(
    bot: discord.Client, guild_id: int,
) -> None:
    await bot.wait_until_ready()
    while not bot.is_closed():
        try:
            repaired = await reconcile_recent_paid_dispatch_embeds(bot, guild_id)
            if repaired:
                print(f"[dispatch-embed] corrected {repaired} paid cards", flush=True)
        except Exception as exc:
            print(
                f"[dispatch-embed] read-only reconciliation failed: "
                f"{type(exc).__name__}: {exc}", flush=True,
            )
        await asyncio.sleep(600)
