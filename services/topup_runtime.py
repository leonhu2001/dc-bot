from __future__ import annotations

import asyncio
import sys
import traceback

import discord

import services.rewards as rewards
from core.time_utils import get_taipei_now_iso
from services.legacy_topup_bridge import install_legacy_wallet_add_bridge
from services.topups import (
    calculate_topup_preview,
    ensure_topup_tables,
    get_pending_credit_topups,
    mark_topup_completed,
    mark_topup_processing,
    reset_topup_credit_error,
)
from services.wallet_service import adjust_wallet_balance, find_wallet_transaction, get_wallet_balance


def install_wallet_vip_guard() -> None:
    """把 bot.py 已匯入的結單 VIP 函式包一層，防止錢包付款重複累積 VIP。"""
    target_module = None
    for module in list(sys.modules.values()):
        if module is None:
            continue
        if hasattr(module, "SELF_SERVICE_ORDER_SELECTIONS") and hasattr(module, "add_customer_reward_from_order"):
            target_module = module
            break

    if target_module is None or getattr(target_module, "_wallet_vip_guard_installed", False):
        return

    original = getattr(target_module, "add_customer_reward_from_order")

    async def guarded_add_customer_reward_from_order(
        guild,
        order_channel_id: int,
        customer_id: int,
        amount_text: str,
        notify_channel=None,
    ) -> str:
        order_data = getattr(target_module, "SELF_SERVICE_ORDER_SELECTIONS", {}).get(order_channel_id, {})
        payment_method = str(order_data.get("payment_method") or "").strip()

        if payment_method != "我的錢包":
            return await original(
                guild,
                order_channel_id,
                customer_id,
                amount_text,
                notify_channel=notify_channel,
            )

        if order_data.get("reward_counted"):
            return "此訂單已處理會員紀錄，未重複累積。"

        data = rewards.get_customer_reward_data(customer_id)
        data["order_count"] = int(data.get("order_count", 0) or 0) + 1
        data["last_order_at"] = get_taipei_now_iso()
        data["points"] = rewards.get_current_reward_points(data)

        order_data["reward_counted"] = True
        order_data["reward_amount"] = 0
        order_data["reward_excluded"] = True
        order_data["reward_excluded_reason"] = "錢包付款：儲值本金已於儲值時累積 VIP，避免重複計算"
        order_data["reward_counted_at"] = get_taipei_now_iso()

        selections = getattr(target_module, "SELF_SERVICE_ORDER_SELECTIONS", None)
        if isinstance(selections, dict):
            selections[order_channel_id] = order_data

        if rewards._SAVE_BOT_DATA is not None:
            rewards._SAVE_BOT_DATA()

        return (
            "會員紀錄已更新：完成訂單 +1；本單使用錢包付款，"
            "儲值本金已於儲值時累積 VIP，因此未再次增加累積消費。"
        )

    setattr(target_module, "add_customer_reward_from_order", guarded_add_customer_reward_from_order)
    target_module._wallet_vip_guard_installed = True
    print("[topup] wallet VIP double-count guard installed", flush=True)


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
            points_before = rewards.get_current_reward_points(data)

            data["total_spent"] = int(data.get("total_spent", 0) or 0) + amount
            reward_keys.append(reward_key)
            data["manual_purchase_keys"] = reward_keys[-500:]

            # 儲值本金只計 VIP，不額外產生消費點數。
            base_points_after = rewards.calculate_reward_points(int(data["total_spent"]))
            data["point_adjustment"] = int(points_before) - int(base_points_after)
            data["points"] = int(points_before)

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
    ensure_topup_tables()
    install_wallet_vip_guard()
    install_legacy_wallet_add_bridge(bot)
    if getattr(bot, "_topup_credit_worker_started", False):
        return
    bot._topup_credit_worker_started = True
    bot.loop.create_task(topup_credit_worker(bot))
