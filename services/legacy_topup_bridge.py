from __future__ import annotations

import sys
import traceback

import discord

import services.rewards as rewards
from services.topups import calculate_topup_preview, create_topup_order, mark_topup_completed


def install_legacy_wallet_add_bridge(bot: discord.Client) -> None:
    target_module = None
    for module in list(sys.modules.values()):
        if module is None:
            continue
        if hasattr(module, "adjust_customer_wallet_balance") and hasattr(module, "CUSTOMER_REWARDS"):
            target_module = module
            break

    if target_module is None or getattr(target_module, "_legacy_wallet_add_bridge_installed", False):
        return

    original_adjust = getattr(target_module, "adjust_customer_wallet_balance")

    def bridged_adjust_customer_wallet_balance(**kwargs):
        tx_type = str(kwargs.get("tx_type") or "adjustment").strip()
        if tx_type != "topup":
            return original_adjust(**kwargs)

        customer_id = int(str(kwargs.get("customer_id")))
        amount = int(kwargs.get("amount") or 0)
        operator = kwargs.get("operator")
        note = str(kwargs.get("note") or "客服儲值").strip()

        guild = None
        guilds = list(getattr(bot, "guilds", []) or [])
        if guilds:
            guild = guilds[0]
        member = guild.get_member(customer_id) if guild is not None else None
        display_name = (
            getattr(member, "display_name", None)
            or str(customer_id)
        )

        order = create_topup_order(
            customer_discord_id=customer_id,
            customer_display_name=display_name,
            amount=amount,
            source="discord_staff",
            payment_method="staff_confirmed",
        )
        topup_no = str(order["topup_no"])

        data = rewards.get_customer_reward_data(customer_id)
        before_total = int(data.get("total_spent", 0) or 0)
        points_before = rewards.get_current_reward_points(data)
        preview = calculate_topup_preview(before_total, amount)

        principal_kwargs = dict(kwargs)
        principal_kwargs["order_no"] = topup_no
        principal_kwargs["note"] = note
        principal_tx = original_adjust(**principal_kwargs)

        bonus_amount = int(preview["rebate_amount"] or 0)
        bonus_tx = None
        if bonus_amount > 0:
            bonus_tx = original_adjust(
                customer_id=customer_id,
                amount=bonus_amount,
                tx_type="topup_bonus",
                operator=operator,
                order_no=topup_no,
                note=f"{preview['vip_level_after']} 儲值回饋 {preview['rebate_percent']}%",
            )

        reward_key = f"topup:{topup_no}"
        reward_keys = data.setdefault("manual_purchase_keys", [])
        if not isinstance(reward_keys, list):
            reward_keys = []

        data["total_spent"] = before_total + amount
        if reward_key not in reward_keys:
            reward_keys.append(reward_key)
        data["manual_purchase_keys"] = reward_keys[-500:]

        # 儲值只推進 VIP，不額外產生消費點數。
        base_points_after = rewards.calculate_reward_points(int(data["total_spent"]))
        data["point_adjustment"] = int(points_before) - int(base_points_after)
        data["points"] = int(points_before)
        rewards.sync_vip_level_to_cumulative_if_higher(data)

        if rewards._SAVE_BOT_DATA is not None:
            rewards._SAVE_BOT_DATA()

        mark_topup_completed(
            int(order["id"]),
            preview=preview,
            wallet_transaction_id=int(principal_tx["id"]),
            bonus_transaction_id=int(bonus_tx["id"]) if bonus_tx else None,
        )

        if guild is not None and member is not None:
            try:
                bot.loop.create_task(
                    rewards.ensure_reward_member_benefits(guild, member, data)
                )
            except Exception:
                print(f"[topup] legacy VIP role sync failed\n{traceback.format_exc()}", flush=True)

        return principal_tx

    setattr(target_module, "adjust_customer_wallet_balance", bridged_adjust_customer_wallet_balance)
    target_module._legacy_wallet_add_bridge_installed = True
    print("[topup] legacy /wallet_add bridge installed", flush=True)
