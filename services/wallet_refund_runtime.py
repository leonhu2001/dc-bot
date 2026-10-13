from __future__ import annotations

import traceback

import discord

import services.rewards as rewards
from core.vip_levels import has_active_vip_progress_reset
from services.vip_monthly_benefits import sync_current_month_vip_benefits
from services.wallet_refunds import (
    list_pending_wallet_refunds,
    mark_wallet_refund_completed,
    mark_wallet_refund_failed,
    mark_wallet_refund_processing,
    reset_wallet_refund_for_retry,
)
from services.wallet_service import (
    adjust_wallet_balance,
    find_wallet_transaction,
    get_wallet_balance_breakdown,
)


def _apply_refund_to_member_data(data: dict, amount: int) -> dict:
    """Reverse refunded top-up principal from VIP progress without changing points."""
    amount = max(0, int(amount or 0))
    total_before = max(0, int(data.get("total_spent", 0) or 0))
    total_after = max(0, total_before - amount)
    points_before = int(rewards.get_current_reward_points(data))
    old_level = rewards.get_effective_member_level(data)
    old_index = rewards.get_effective_member_level_index(data)

    data["total_spent"] = total_after

    if has_active_vip_progress_reset(data):
        base_total = int(data.get("vip_progress_base_total_spent", total_before) or 0)
        stored_index = int(data.get("vip_level_index", old_index) or 0)
        current_level = rewards.get_member_level_by_index(stored_index)
        virtual_total = max(
            0,
            int(current_level.get("threshold", 0) or 0)
            + (total_after - base_total),
        )
        recalculated_index = rewards.get_member_level_index_by_total_spent(virtual_total)

        if recalculated_index < stored_index:
            data["vip_level_index"] = recalculated_index
            data["vip_progress_base_total_spent"] = total_after
        else:
            data["vip_level_index"] = stored_index
        data["vip_progress_reset_active"] = True
    else:
        data["vip_level_index"] = rewards.get_member_level_index_by_total_spent(total_after)
        data["vip_progress_base_total_spent"] = None
        data["vip_progress_reset_active"] = False

    # Top-up principal never grants points, so refunding it must not remove points.
    base_points_after = rewards.calculate_reward_points(total_after)
    data["point_adjustment"] = points_before - int(base_points_after)
    data["points"] = points_before

    new_level = rewards.get_effective_member_level(data)
    return {
        "total_before": total_before,
        "total_after": total_after,
        "points_before": points_before,
        "points_after": int(rewards.get_current_reward_points(data)),
        "old_level": str(old_level.get("name") or "普通魔丸"),
        "new_level": str(new_level.get("name") or "普通魔丸"),
    }


def _saved_refund_result(data: dict, refund_id: int) -> dict | None:
    logs = data.get("point_adjustment_logs")
    if not isinstance(logs, list):
        return None
    for raw in reversed(logs):
        if not isinstance(raw, dict):
            continue
        if str(raw.get("source") or "") != "wallet_refund":
            continue
        try:
            log_refund_id = int(raw.get("refund_id"))
        except (TypeError, ValueError):
            continue
        if log_refund_id != int(refund_id):
            continue
        return {
            "total_before": int(raw.get("total_before") or 0),
            "total_after": int(raw.get("total_after") or 0),
            "points_before": int(raw.get("points_before") or 0),
            "points_after": int(raw.get("points_after") or 0),
            "old_level": str(raw.get("old_level") or "普通魔丸"),
            "new_level": str(raw.get("new_level") or "普通魔丸"),
        }
    return None


def _apply_refund_to_member_once(data: dict, *, refund_id: int, amount: int) -> dict:
    """Persist idempotency in fields already serialized by the rewards store."""
    refund_key = f"wallet_refund:{int(refund_id)}"
    keys = data.setdefault("manual_purchase_keys", [])
    if not isinstance(keys, list):
        keys = []
        data["manual_purchase_keys"] = keys

    if refund_key in keys:
        saved = _saved_refund_result(data, refund_id)
        if saved is not None:
            return saved
        current_level = rewards.get_effective_member_level(data)
        current_total = max(0, int(data.get("total_spent", 0) or 0))
        current_points = int(rewards.get_current_reward_points(data))
        return {
            "total_before": current_total + max(0, int(amount or 0)),
            "total_after": current_total,
            "points_before": current_points,
            "points_after": current_points,
            "old_level": str(current_level.get("name") or "普通魔丸"),
            "new_level": str(current_level.get("name") or "普通魔丸"),
        }

    result = _apply_refund_to_member_data(data, amount)
    keys.append(refund_key)
    data["manual_purchase_keys"] = keys[-500:]

    logs = data.setdefault("point_adjustment_logs", [])
    if not isinstance(logs, list):
        logs = []
        data["point_adjustment_logs"] = logs
    logs.append(
        {
            "source": "wallet_refund",
            "refund_id": int(refund_id),
            "amount": max(0, int(amount or 0)),
            **result,
        }
    )
    data["point_adjustment_logs"] = logs[-500:]
    return result


async def _sync_refund_member_state(
    bot: discord.Client,
    customer_id: int,
    data: dict,
) -> None:
    guilds = list(getattr(bot, "guilds", []) or [])
    guild = guilds[0] if guilds else None
    if guild is not None:
        try:
            member = await rewards.fetch_member_safely(guild, customer_id)
            if member is not None:
                await rewards.ensure_reward_member_benefits(guild, member, data)
        except Exception:
            print(
                f"[wallet-refund] VIP role sync failed user={customer_id}\n"
                f"{traceback.format_exc()}",
                flush=True,
            )

    if rewards._SAVE_BOT_DATA is not None:
        rewards._SAVE_BOT_DATA()

    try:
        sync_current_month_vip_benefits()
    except Exception:
        print(
            f"[wallet-refund] monthly benefit sync failed user={customer_id}\n"
            f"{traceback.format_exc()}",
            flush=True,
        )


async def process_pending_wallet_refunds(bot: discord.Client) -> None:
    for row in list_pending_wallet_refunds(limit=20):
        refund_id = int(row["id"])
        if not mark_wallet_refund_processing(refund_id):
            continue

        customer_id = int(str(row["customer_discord_id"]))
        amount = int(row["amount"] or 0)
        operator_id = str(row.get("requested_by_discord_id") or "") or None
        operator_name = str(row.get("requested_by_display_name") or "").strip() or None
        refund_reference = f"WALLET-REFUND-{refund_id}"
        refund_tx = None
        wallet_debit_amount = 0
        bonus_offset_applied = 0

        try:
            refund_tx = find_wallet_transaction(
                customer_id=customer_id,
                order_no=refund_reference,
                tx_type="refund",
            )

            if refund_tx is None:
                breakdown = get_wallet_balance_breakdown(customer_id)
                principal = int(breakdown.get("principal_balance") or 0)
                refundable = int(breakdown.get("refundable_balance") or 0)
                bonus_offset_applied = int(breakdown.get("refund_offset_balance") or 0)
                if amount <= 0 or amount > refundable:
                    raise ValueError(
                        f"退款額度不足：申請實退 {amount:,}T，目前最多可實退 {refundable:,}T。"
                    )

                # 一般點單會先花贈額。若贈額已先被使用、但還沒有足夠本金消費去沖抵，
                # 退款時要連同這段抵扣一起從錢包本金移除，現金只退 request.amount。
                wallet_debit_amount = amount + bonus_offset_applied
                if wallet_debit_amount > principal:
                    raise ValueError(
                        f"退款本金不足：需扣除 {wallet_debit_amount:,}T，本金僅剩 {principal:,}T。"
                    )

                refund_tx = adjust_wallet_balance(
                    customer_id=customer_id,
                    amount=-wallet_debit_amount,
                    tx_type="refund",
                    operator_discord_id=operator_id,
                    operator_display_name=operator_name,
                    order_no=refund_reference,
                    note=(
                        f"儲值退款實退 {amount:,}T"
                        + (
                            f"｜已使用贈額抵扣 {bonus_offset_applied:,}T"
                            if bonus_offset_applied > 0
                            else ""
                        )
                        + (f"｜{row.get('note')}" if str(row.get("note") or "").strip() else "")
                    ),
                )
            else:
                wallet_debit_amount = abs(int(refund_tx.get("amount") or 0))
                bonus_offset_applied = max(0, wallet_debit_amount - amount)

            bonus_reference = f"{refund_reference}:BONUS"
            bonus_tx = find_wallet_transaction(
                customer_id=customer_id,
                order_no=bonus_reference,
                tx_type="bonus_reversal",
            )
            if bonus_tx is not None:
                bonus_revoked = abs(int(bonus_tx.get("amount") or 0))
            else:
                current_bonus = int(
                    get_wallet_balance_breakdown(customer_id).get("bonus_balance") or 0
                )
                bonus_revoked = current_bonus
                if current_bonus > 0:
                    bonus_tx = adjust_wallet_balance(
                        customer_id=customer_id,
                        amount=-current_bonus,
                        tx_type="bonus_reversal",
                        operator_discord_id=operator_id,
                        operator_display_name=operator_name,
                        order_no=bonus_reference,
                        note="退款時撤銷尚未使用的 VIP／活動贈額",
                    )

            data = rewards.get_customer_reward_data(customer_id)
            member_result = _apply_refund_to_member_once(
                data,
                refund_id=refund_id,
                amount=amount,
            )
            await _sync_refund_member_state(bot, customer_id, data)

            mark_wallet_refund_completed(
                refund_id,
                wallet_transaction_id=int(refund_tx["id"]),
                wallet_debit_amount=wallet_debit_amount,
                bonus_offset_applied=bonus_offset_applied,
                bonus_reversal_transaction_id=(
                    int(bonus_tx["id"]) if bonus_tx is not None else None
                ),
                bonus_revoked_amount=bonus_revoked,
                vip_total_before=int(member_result["total_before"]),
                vip_total_after=int(member_result["total_after"]),
                vip_level_before=str(member_result["old_level"]),
                vip_level_after=str(member_result["new_level"]),
            )

            user = bot.get_user(customer_id)
            if user is None:
                try:
                    user = await bot.fetch_user(customer_id)
                except Exception:
                    user = None
            if user is not None:
                try:
                    message = (
                        f"✅ 儲值退款已完成｜實退 **{amount:,}T**\n"
                        f"VIP：**{member_result['old_level']} → {member_result['new_level']}**"
                    )
                    if bonus_offset_applied > 0:
                        message += (
                            f"\n已使用贈額抵扣：**{bonus_offset_applied:,}T**"
                            "（避免贈額先消費後再全額退本金）"
                        )
                    if bonus_revoked > 0:
                        message += f"\n已撤銷未使用贈額：**{bonus_revoked:,}T**"
                    await user.send(message)
                except Exception:
                    pass

        except Exception as exc:
            committed_refund = refund_tx or find_wallet_transaction(
                customer_id=customer_id,
                order_no=refund_reference,
                tx_type="refund",
            )
            if committed_refund is None:
                mark_wallet_refund_failed(refund_id, exc)
            else:
                reset_wallet_refund_for_retry(refund_id, exc)
            print(
                f"[wallet-refund] failed id={refund_id}\n{traceback.format_exc()}",
                flush=True,
            )
