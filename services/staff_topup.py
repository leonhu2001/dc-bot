from __future__ import annotations

import traceback
from typing import Any

import discord

import services.rewards as rewards
from services.topups import create_topup_order, mark_topup_completed
from services.vip_progress_repair import calculate_member_topup_preview, repair_vip_progress_data
from services.wallet_service import adjust_wallet_balance


def _operator_identity(operator: Any) -> tuple[str | int | None, str | None]:
    operator_id = getattr(operator, "id", None)
    operator_name = (
        getattr(operator, "display_name", None)
        or getattr(operator, "name", None)
        or (str(operator_id) if operator_id is not None else None)
    )
    return operator_id, str(operator_name).strip() if operator_name else None


def _resolve_customer_context(
    bot: discord.Client,
    customer_id: int,
    customer_display_name: str | None,
) -> tuple[discord.Guild | None, Any, str]:
    guilds = list(getattr(bot, "guilds", []) or [])
    guild = guilds[0] if guilds else None
    member = guild.get_member(customer_id) if guild is not None else None
    display_name = (
        str(customer_display_name or "").strip()
        or getattr(member, "display_name", None)
        or str(customer_id)
    )
    return guild, member, str(display_name)


def credit_staff_topup(
    bot: discord.Client,
    *,
    customer_id: int,
    amount: int,
    operator: Any,
    note: str | None = None,
    customer_display_name: str | None = None,
) -> dict:
    """Credit one staff-confirmed topup through the canonical topup/wallet services.

    This preserves the legacy /wallet_add business behavior without requiring a
    monkey-patched wallet function: create a completed topup order, credit the
    principal and VIP rebate, advance cumulative VIP spend, preserve the
    customer's existing point balance, and schedule Discord VIP-role sync.
    """

    customer_id = int(str(customer_id))
    amount = int(amount or 0)
    note_text = str(note or "客服儲值").strip() or "客服儲值"
    guild, member, display_name = _resolve_customer_context(
        bot,
        customer_id,
        customer_display_name,
    )
    operator_id, operator_name = _operator_identity(operator)

    order = create_topup_order(
        customer_discord_id=customer_id,
        customer_display_name=display_name,
        amount=amount,
        source="discord_staff",
        payment_method="staff_confirmed",
    )
    topup_no = str(order["topup_no"])

    data = rewards.get_customer_reward_data(customer_id)
    repair_vip_progress_data(data)
    before_total = int(data.get("total_spent", 0) or 0)
    points_before = rewards.get_current_reward_points(data)
    preview = calculate_member_topup_preview(data, amount)

    principal_tx = adjust_wallet_balance(
        customer_id=customer_id,
        amount=amount,
        tx_type="topup",
        operator_discord_id=operator_id,
        operator_display_name=operator_name,
        order_no=topup_no,
        note=note_text,
    )

    bonus_amount = int(preview["rebate_amount"] or 0)
    bonus_tx = None
    if bonus_amount > 0:
        bonus_tx = adjust_wallet_balance(
            customer_id=customer_id,
            amount=bonus_amount,
            tx_type="topup_bonus",
            operator_discord_id=operator_id,
            operator_display_name=operator_name,
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
    repair_vip_progress_data(data)

    # 儲值單顯示以實際完成後的有效等級為準。
    actual_level = rewards.get_effective_member_level(data)
    completed_preview = dict(preview)
    completed_preview["vip_level_after"] = str(
        actual_level.get("name")
        or completed_preview["vip_level_after"]
    )
    completed_preview["vip_total_after"] = int(data["total_spent"])

    if rewards._SAVE_BOT_DATA is not None:
        rewards._SAVE_BOT_DATA()

    mark_topup_completed(
        int(order["id"]),
        preview=completed_preview,
        wallet_transaction_id=int(principal_tx["id"]),
        bonus_transaction_id=int(bonus_tx["id"]) if bonus_tx else None,
    )

    if guild is not None and member is not None:
        try:
            bot.loop.create_task(
                rewards.ensure_reward_member_benefits(guild, member, data)
            )
        except Exception:
            print(
                f"[topup] staff VIP role sync failed\n{traceback.format_exc()}",
                flush=True,
            )

    return principal_tx
