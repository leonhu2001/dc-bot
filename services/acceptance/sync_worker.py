from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from typing import Any, Awaitable, Callable

import discord

from core.time_utils import utc_now_naive


@dataclass(frozen=True)
class AcceptanceSyncWorkerDeps:
    bot: Any
    guild_id: int
    refresh_acceptance_dispatch: Callable[[discord.Guild, int], Awaitable[Any]]
    refresh_existing_web_sync_dispatch: Callable[[dict[str, Any]], Awaitable[Any]]
    grant_ticket_access: Callable[[discord.Guild, int, discord.Member], Awaitable[bool]]
    revoke_ticket_access: Callable[[discord.Guild, int, discord.Member], Awaitable[bool]]
    to_int: Callable[..., Any]


_DEPS: AcceptanceSyncWorkerDeps | None = None


def configure_acceptance_sync_worker(
    *,
    bot_instance: Any,
    guild_id: int,
    refresh_acceptance_dispatch: Callable[[discord.Guild, int], Awaitable[Any]],
    refresh_existing_web_sync_dispatch: Callable[[dict[str, Any]], Awaitable[Any]],
    grant_ticket_access: Callable[[discord.Guild, int, discord.Member], Awaitable[bool]],
    revoke_ticket_access: Callable[[discord.Guild, int, discord.Member], Awaitable[bool]],
    to_int: Callable[..., Any],
) -> None:
    global _DEPS
    _DEPS = AcceptanceSyncWorkerDeps(
        bot=bot_instance,
        guild_id=int(guild_id),
        refresh_acceptance_dispatch=refresh_acceptance_dispatch,
        refresh_existing_web_sync_dispatch=refresh_existing_web_sync_dispatch,
        grant_ticket_access=grant_ticket_access,
        revoke_ticket_access=revoke_ticket_access,
        to_int=to_int,
    )


def _require_deps() -> AcceptanceSyncWorkerDeps:
    if _DEPS is None:
        raise RuntimeError("acceptance sync worker is not configured")
    return _DEPS


async def process_acceptance_sync_events_once() -> None:
    from sqlalchemy import select, update

    from shared.db import SessionLocal
    from shared.models import SyncEvent, SyncEventStatus, SyncEventType, WebOrder

    deps = _require_deps()
    guild = deps.bot.get_guild(deps.guild_id)

    if guild is None:
        return

    async def _resolve_member(worker_id: int | None):
        if worker_id is None:
            return None

        member = guild.get_member(worker_id)
        if member is not None:
            return member

        try:
            fetched_member = await guild.fetch_member(worker_id)
            return (
                fetched_member
                if isinstance(fetched_member, discord.Member)
                else None
            )
        except (
            discord.NotFound,
            discord.Forbidden,
            discord.HTTPException,
        ):
            return None

    db = SessionLocal()

    try:
        events = list(
            db.scalars(
                select(SyncEvent)
                .where(SyncEvent.status == SyncEventStatus.PENDING.value)
                .where(SyncEvent.event_type.in_([
                    SyncEventType.ORDER_CLAIMED.value,
                    SyncEventType.ORDER_UNCLAIMED.value,
                ]))
                .order_by(SyncEvent.created_at.asc())
                .limit(10)
            ).all()
        )

        for event in events:
            try:
                payload = json.loads(event.payload_json or "{}")
            except Exception:
                payload = {}

            is_prepay_acceptance = bool(payload.get("prepay_acceptance"))
            is_admin_worker_change = payload.get("reason") in {
                "admin_added_worker",
                "admin_removed_worker",
            }

            claimed = db.execute(
                update(SyncEvent)
                .where(SyncEvent.id == int(event.id))
                .where(SyncEvent.status == SyncEventStatus.PENDING.value)
                .values(
                    status=SyncEventStatus.PROCESSING.value,
                    retry_count=int(event.retry_count or 0) + 1,
                    processed_at=utc_now_naive(),
                )
            )
            db.commit()

            if claimed.rowcount != 1:
                continue

            if not is_prepay_acceptance and not is_admin_worker_change:
                event.status = SyncEventStatus.DONE.value
                event.error_message = None
                event.processed_at = utc_now_naive()
                db.commit()
                continue

            try:
                order = db.get(WebOrder, int(event.order_id))
                ticket_channel_id = (
                    deps.to_int(order.ticket_channel_id)
                    if order is not None
                    else None
                )

                if is_prepay_acceptance:
                    await deps.refresh_acceptance_dispatch(
                        guild,
                        int(event.order_id),
                    )
                elif is_admin_worker_change:
                    if order is None:
                        raise RuntimeError(
                            f"web order not found: {event.order_id}"
                        )

                    await deps.refresh_existing_web_sync_dispatch(
                        {
                            "order_id": int(event.order_id),
                            "dispatch_channel_id": order.dispatch_channel_id,
                            "dispatch_message_id": order.dispatch_message_id,
                        }
                    )

                worker_id = deps.to_int(payload.get("worker_discord_id"))

                if worker_id is not None and ticket_channel_id is not None:
                    member = await _resolve_member(worker_id)

                    if member is not None:
                        if event.event_type == SyncEventType.ORDER_CLAIMED.value:
                            await deps.grant_ticket_access(
                                guild,
                                ticket_channel_id,
                                member,
                            )
                        elif event.event_type == SyncEventType.ORDER_UNCLAIMED.value:
                            await deps.revoke_ticket_access(
                                guild,
                                ticket_channel_id,
                                member,
                            )

                event.status = SyncEventStatus.DONE.value
                event.error_message = None
                event.processed_at = utc_now_naive()
                db.commit()
            except Exception as exc:
                event.status = SyncEventStatus.FAILED.value
                event.error_message = f"{type(exc).__name__}: {exc}"
                event.processed_at = utc_now_naive()
                db.commit()
                print(
                    f"[acceptance-sync] 處理網站接單事件失敗 event_id={event.id}: {exc}"
                )
    finally:
        db.close()


async def acceptance_sync_event_worker() -> None:
    deps = _require_deps()
    await deps.bot.wait_until_ready()
    print("[acceptance-sync] worker loop running", flush=True)

    while not deps.bot.is_closed():
        try:
            await process_acceptance_sync_events_once()
        except Exception as exc:
            print(f"[acceptance-sync] 背景同步失敗：{exc}")

        await asyncio.sleep(5)
