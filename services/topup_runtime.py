from __future__ import annotations

import asyncio
import traceback

import discord

import services.rewards as rewards
from services.topups import (
    calculate_topup_preview,
    get_pending_credit_topups,
    mark_topup_completed,
    mark_topup_processing,
    reset_topup_credit_error,
)
from services.wallet_service import adjust_wallet_balance, find_wallet_transaction, get_wallet_balance


async def _process_one_topup(bot: discord.Client, row: dict) -> None:
    topup_id = int(row["id"])
    if not mark_topup_processing(topup_id):
        return

    customer_id = int(str(row["customer_discord_id"]))
    amount = int(row["amount"] or 0)
    topup_no = str(row["topup_no"])
    operator_id = str(row.get("approved_by_discord_id") or "") or None
    operator_name = str(row.get("approved_by_display_name") or "").strip() or None

    try:
        data = rewards.get_customer_reward_data(customer_id)
        reward_key = f"topup:{topup_no}"
        reward_keys = data.setdefault("manual_purchase_keys", [])
        if not isinstance(reward_keys, list):
            reward_keys = []
            data["manual_purchase_keys"] = reward_keys

        before_total = int(data.get("total_spent", 0) or 0)
        if reward_key in reward_keys:
            # 已經套用過 VIP 累積；用現況回推本筆前總額，避免 worker 重啟重複累積。
            before_total = max(0, before_total - amount)

        preview = calculate_topup_preview(before_total, amount)

        principal_tx = find_wallet_transaction(
            customer_id=customer_id,
            order_no=topup_no,
            tx_type="topup",
        )
        if principal_tx is None:
            principal_tx = adjust_wallet_balance(
                customer_id=customer_id,
                amount=amount,
                tx_type="topup",
                operator_discord_id=operator_id,
                operator_display_name=operator_name,
                order_no=topup_no,
                note=f"儲值本金 {topup_no}",
            )

        bonus_amount = int(preview["rebate_amount"] or 0)
        bonus_tx = None
        if bonus_amount > 0:
            bonus_tx = find_wallet_transaction(
                customer_id=customer_id,
                order_no=topup_no,
                tx_type="topup_bonus",
            )
            if bonus_tx is None:
                bonus_tx = adjust_wallet_balance(
                    customer_id=customer_id,
                    amount=bonus_amount,
                    tx_type="topup_bonus",
                    operator_discord_id=operator_id,
                    operator_display_name=operator_name,
                    order_no=topup_no,
                    note=f"{preview['vip_level_after']} 儲值回饋 {preview['rebate_percent']}%",
                )

        if reward_key not in reward_keys:
            old_level = rewards.get_effective_member_level(data)
            data["total_spent"] = int(data.get("total_spent", 0) or 0) + amount
            reward_keys.append(reward_key)
            data["manual_purchase_keys"] = reward_keys[-500:]
            data["points"] = rewards.get_current_reward_points(data)
            rewards.sync_vip_level_to_cumulative_if_higher(data)

            guild = None
            guilds = list(getattr(bot, "guilds", []) or [])
            if guilds:
                guild = guilds[0]
            if guild is not None:
                member = await rewards.fetch_member_safely(guild, customer_id)
                await rewards.ensure_reward_member_benefits(guild, member, data)

            if rewards._SAVE_BOT_DATA is not None:
                rewards._SAVE_BOT_DATA()

            new_level = rewards.get_effective_member_level(data)
            if new_level.get("threshold", 0) < old_level.get("threshold", 0):
                raise RuntimeError("VIP 等級計算異常：儲值後等級不應下降。")

        mark_topup_completed(
            topup_id,
            preview=preview,
            wallet_transaction_id=int(principal_tx["id"]),
            bonus_transaction_id=int(bonus_tx["id"]) if bonus_tx else None,
        )

        user = bot.get_user(customer_id)
        if user is None:
            try:
                user = await bot.fetch_user(customer_id)
            except Exception:
                user = None
        if user is not None:
            try:
                balance = get_wallet_balance(customer_id)
                text = (
                    f"✅ 儲值完成｜`{topup_no}`\n"
                    f"儲值本金：**{amount:,}T**\n"
                    f"VIP 等級：**{preview['vip_level_after']}**\n"
                    f"儲值回饋：**{preview['rebate_percent']}%（+{bonus_amount:,}T）**\n"
                    f"本次實得：**{int(preview['credited_amount']):,}T**\n"
                    f"目前錢包餘額：**{balance:,}T**"
                )
                await user.send(text)
            except Exception:
                pass

    except Exception:
        reset_topup_credit_error(topup_id)
        print(f"[topup] credit failed id={topup_id}\n{traceback.format_exc()}", flush=True)


async def topup_credit_worker(bot: discord.Client) -> None:
    await bot.wait_until_ready()
    while not bot.is_closed():
        try:
            rows = get_pending_credit_topups(limit=20)
            for row in rows:
                await _process_one_topup(bot, row)
        except Exception:
            print(f"[topup] worker error\n{traceback.format_exc()}", flush=True)
        await asyncio.sleep(4)


def ensure_topup_credit_worker_started(bot: discord.Client) -> None:
    if getattr(bot, "_topup_credit_worker_started", False):
        return
    bot._topup_credit_worker_started = True
    bot.loop.create_task(topup_credit_worker(bot))
