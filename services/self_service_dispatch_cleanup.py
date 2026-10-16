from __future__ import annotations

from collections.abc import Callable
from typing import Any

import discord


_FAILED_DISPATCH_RUNTIME_KEYS = (
    "provisional_dispatch_message_id",
    "provisional_dispatch_channel_id",
    "dispatch_message_id",
    "dispatch_channel_id",
    "web_order_id",
    "status",
    "waiting_acceptance_created_at",
    "accepted_staff_display_text",
    "payment_message_id",
    "payment_channel_id",
    "payment_finalizing",
    "payment_finalized_at",
    "payment_finalized_by",
    "rule_version",
    "rule_snapshot_json",
    "price_snapshot_json",
    "web_order_note",
)

_ROLLBACK_RUNTIME_KEYS = (
    "dispatch_rollback_pending",
    "dispatch_rollback_warnings",
    "rollback_dispatch_message_id",
    "rollback_dispatch_channel_id",
    "rollback_web_order_id",
)


async def cleanup_failed_self_service_dispatch(
    interaction: discord.Interaction,
    *,
    channel_id: int,
    data: dict,
    order_claims: dict,
    default_dispatch_channel_id: int,
    remember_order: Callable[[int, dict], Any],
    save_data: Callable[[], Any],
    delete_claim_row: Callable[..., Any] | None = None,
) -> list[str]:
    """Roll back a failed pre-claim self-service dispatch while preserving its draft.

    The dispatch message id is persisted immediately after the provisional
    Discord message is created. Failed cleanup keeps a dedicated recovery
    pointer instead of discarding the only identifiers that can safely retry
    the cleanup. Normal runtime links are still removed so payment/acceptance
    code cannot mistake a rollback-pending draft for a valid order.
    """
    warnings: list[str] = []
    guild = interaction.guild

    def to_int(value, default=None):
        try:
            if value is None or value == "":
                return default
            return int(value)
        except (TypeError, ValueError):
            return default

    dispatch_message_id = (
        to_int(data.get("rollback_dispatch_message_id"))
        or to_int(data.get("provisional_dispatch_message_id"))
        or to_int(data.get("dispatch_message_id"))
    )
    dispatch_channel_id = (
        to_int(data.get("rollback_dispatch_channel_id"))
        or to_int(data.get("provisional_dispatch_channel_id"))
        or to_int(data.get("dispatch_channel_id"))
        or int(default_dispatch_channel_id)
    )
    web_order_id = (
        to_int(data.get("rollback_web_order_id"))
        or to_int(data.get("web_order_id"))
    )
    vip_monthly_benefit_id = to_int(data.get("vip_monthly_benefit_id"))

    if delete_claim_row is None:
        from core.database import delete_claim_row_from_db

        delete_claim_row = delete_claim_row_from_db

    # Use only this attempt's provisional dispatch message id to identify the
    # canonical WebOrder. Passing ticket_channel_id here would make the shared
    # helper use an OR lookup and could target an unrelated stale order from the
    # same ticket if the current upsert never completed.
    if dispatch_message_id is not None:
        try:
            from shared.web_order_sync import delete_web_order_by_ticket_channel

            delete_web_order_by_ticket_channel(
                dispatch_message_id=dispatch_message_id,
            )

            # The shared delete helper releases VIP monthly cash benefits only
            # when a ticket id is supplied. Release by channel separately, but
            # only when this draft actually selected a monthly cash benefit.
            if vip_monthly_benefit_id is not None:
                from services.vip_monthly_benefits import (
                    release_cash_benefits_for_channel,
                )

                release_cash_benefits_for_channel(channel_id)
        except Exception as exc:
            warnings.append(f"網站訂單回滾失敗：{type(exc).__name__}")
            print(
                f"[self-service-dispatch] failed web rollback channel_id={channel_id}: "
                f"{type(exc).__name__}: {exc}",
                flush=True,
            )

        order_claims.pop(dispatch_message_id, None)
        try:
            delete_claim_row(
                message_id=dispatch_message_id,
                source_channel_id=channel_id,
            )
        except Exception as exc:
            warnings.append(f"接單暫存清理失敗：{type(exc).__name__}")
            print(
                f"[self-service-dispatch] failed claim rollback channel_id={channel_id}: "
                f"{type(exc).__name__}: {exc}",
                flush=True,
            )

    if guild is not None and dispatch_message_id is not None:
        dispatch_channel = guild.get_channel(dispatch_channel_id)
        if not isinstance(dispatch_channel, discord.TextChannel):
            try:
                fetched = await guild.fetch_channel(dispatch_channel_id)
                dispatch_channel = fetched if isinstance(fetched, discord.TextChannel) else None
            except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                dispatch_channel = None

        if isinstance(dispatch_channel, discord.TextChannel):
            try:
                message = await dispatch_channel.fetch_message(dispatch_message_id)
                await message.delete()
            except discord.NotFound:
                pass
            except (discord.Forbidden, discord.HTTPException) as exc:
                warnings.append(f"暫存派單訊息刪除失敗：{type(exc).__name__}")
        else:
            warnings.append("找不到派單頻道，暫存派單訊息可能需要人工確認")

    # Whether cleanup completed or needs another attempt, never leave the draft
    # looking like a live order to payment/acceptance code.
    for key in _FAILED_DISPATCH_RUNTIME_KEYS:
        data.pop(key, None)

    data.pop("payment_method", None)
    data["closed"] = False

    if warnings and dispatch_message_id is not None:
        data["dispatch_rollback_pending"] = True
        data["dispatch_rollback_warnings"] = list(warnings)
        data["rollback_dispatch_message_id"] = int(dispatch_message_id)
        data["rollback_dispatch_channel_id"] = int(dispatch_channel_id)
        if web_order_id is not None:
            data["rollback_web_order_id"] = int(web_order_id)
    else:
        for key in _ROLLBACK_RUNTIME_KEYS:
            data.pop(key, None)

    remember_order(int(channel_id), data)
    save_data()
    return warnings
