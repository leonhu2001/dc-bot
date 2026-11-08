from __future__ import annotations

import json

from services.orders import _to_int
from services.rewards import (
    sync_reward_counted_order_amount,
    reverse_cancelled_order_rewards,
    get_customer_reward_data,
    fetch_member_safely,
    ensure_reward_member_benefits,
)

async def process_cancel_aware_amount_event(
    event: dict, *,
    apply_wallet_adjustment,
    order_selections,
    remember_order,
    save_data,
    mark_done,
    mark_failed,
    guild,
) -> None:
    _apply_web_order_wallet_amount_adjustment = apply_wallet_adjustment
    SELF_SERVICE_ORDER_SELECTIONS = order_selections
    remember_order_data = remember_order
    save_bot_data = save_data
    _web_sync_mark_event_done = mark_done
    _web_sync_mark_event_failed = mark_failed
    event_id = int(event["event_id"])
    retry_count = int(event.get("retry_count") or 0)

    try:
        payload = {}
        try:
            payload = json.loads(event.get("payload_json") or "{}")
        except Exception:
            payload = {}

        # Wallet reconciliation must run even if the Discord-side order state
        # has already been cleaned up. The event reference makes this idempotent.
        _apply_web_order_wallet_amount_adjustment(
            event,
            payload,
        )

        ticket_channel_id = _to_int(event.get("ticket_channel_id"), None)
        new_amount = max(0, int(event.get("amount") or 0))
        order_status = str(event.get("status") or "").strip().lower()

        # Website-only orders may be edited before the Discord ticket/state exists.
        # Their latest amount will be read when the bot seeds the order later.
        if ticket_channel_id is None:
            _web_sync_mark_event_done(event_id)
            print(
                f"[amount-sync] event_id={event_id} skipped: no ticket channel yet",
                flush=True,
            )
            return

        order_data = SELF_SERVICE_ORDER_SELECTIONS.get(int(ticket_channel_id))

        if not isinstance(order_data, dict):
            _web_sync_mark_event_done(event_id)
            print(
                f"[amount-sync] event_id={event_id} skipped: "
                f"bot order state not found ticket={ticket_channel_id}",
                flush=True,
            )
            return

        old_order_amount = max(0, int(order_data.get("amount") or 0))
        if order_status in {"cancelled", "canceled"}:
            reward_result = reverse_cancelled_order_rewards(order_data)
            order_data["status"] = "cancelled"
            order_data["closed"] = True
        else:
            reward_result = sync_reward_counted_order_amount(
                order_data,
                new_amount,
            )

        # Persist order and VIP state before acknowledging the event.
        remember_order_data(int(ticket_channel_id), order_data)
        save_bot_data()

        if (
            reward_result
            and not reward_result.get("reset_preserved")
            and reward_result.get("old_level") != reward_result.get("new_level")
        ):
            guild = guild

            if guild is not None:
                member = await fetch_member_safely(
                    guild,
                    int(reward_result["customer_id"]),
                )
                await ensure_reward_member_benefits(
                    guild,
                    member,
                    get_customer_reward_data(
                        int(reward_result["customer_id"])
                    ),
                )

        _web_sync_mark_event_done(event_id)

        if reward_result:
            print(
                "[amount-sync] "
                f"event_id={event_id} ticket={ticket_channel_id} "
                f"amount {reward_result['old_amount']}->{reward_result['new_amount']} "
                f"vip_total {reward_result['old_total_spent']}->{reward_result['new_total_spent']} "
                f"points {reward_result['old_points']}->{reward_result['new_points']} "
                f"level {reward_result['old_level']}->{reward_result['new_level']}",
                flush=True,
            )
        else:
            print(
                "[amount-sync] "
                f"event_id={event_id} ticket={ticket_channel_id} "
                f"order amount {old_order_amount}->{new_amount}; "
                f"status={order_status or 'unknown'} "
                "reward not previously counted",
                flush=True,
            )

    except Exception as exc:
        _web_sync_mark_event_failed(
            event_id,
            str(exc),
            retry_count,
        )
        print(
            f"[amount-sync] event_id={event_id} failed: {type(exc).__name__}: {exc}",
            flush=True,
        )



async def repair_existing_cancelled_web_vip_rewards(
    *, order_selections, remember_order, save_data, guild, load_refs,
) -> int:
    SELF_SERVICE_ORDER_SELECTIONS = order_selections
    remember_order_data = remember_order
    save_bot_data = save_data
    _web_sync_load_cancelled_order_refs = load_refs
    """Repair already-cancelled paid orders that older sync events missed.

    Only apply to a matching ticket with a recorded reward, and persist the
    per-order reversal marker to prevent double deductions after restart.
    Never estimate VIP spend from Web order price alone.
    """
    repaired = 0
    for row in _web_sync_load_cancelled_order_refs():
        ticket_id = _to_int(row.get("ticket_channel_id"), None)
        if ticket_id is None:
            continue
        data = SELF_SERVICE_ORDER_SELECTIONS.get(ticket_id)
        if not isinstance(data, dict) or not data.get("reward_counted"):
            continue
        if data.get("reward_cancel_reconciled"):
            continue
        order_customer = _to_int(row.get("customer_discord_id"), None)
        saved_customer = _to_int(data.get("customer_id"), None)
        if order_customer is None or order_customer != saved_customer:
            print(
                f"[vip-cancel-repair] customer mismatch "
                f"order_id={row.get('order_id')} ticket={ticket_id}",
                flush=True,
            )
            continue
        try:
            summary = reverse_cancelled_order_rewards(data)
            data["status"] = "cancelled"
            data["closed"] = True
            remember_order_data(ticket_id, data)
            save_bot_data()
            if summary:
                repaired += 1
                print(
                    f"[vip-cancel-repair] order_id={row.get('order_id')} "
                    f"ticket={ticket_id} customer={saved_customer} "
                    f"vip -{summary['old_amount']}T, "
                    f"wallet_points_spend -{summary['reversed_wallet_spend']}T",
                    flush=True,
                )
                if (
                    not summary.get("reset_preserved")
                    and summary.get("old_level") != summary.get("new_level")
                ):
                    guild = guild
                    if guild:
                        member = await fetch_member_safely(guild, saved_customer)
                        await ensure_reward_member_benefits(
                            guild, member, get_customer_reward_data(saved_customer)
                        )
        except Exception as exc:
            print(
                f"[vip-cancel-repair] failed order_id={row.get('order_id')} "
                f"ticket={ticket_id}: {type(exc).__name__}: {exc}",
                flush=True,
            )
    return repaired


