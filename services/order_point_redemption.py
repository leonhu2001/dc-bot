from __future__ import annotations

from typing import Any, Callable

import discord

from services.order_point_redemption_policy import get_pending_point_benefit_info


CUSTOMER_REWARDS: dict
_to_int: Callable[..., int]
get_current_reward_points: Callable[..., int]
get_customer_reward_data: Callable[..., Any]
get_order_point_item: Callable[..., Any]
get_taipei_now_iso: Callable[..., str]
remember_order_data: Callable[..., Any]
save_bot_data: Callable[..., Any]
send_order_log: Callable[..., Any]


def configure_order_point_redemption(
    *,
    customer_rewards: dict,
    to_int: Callable[..., int],
    current_reward_points: Callable[..., int],
    customer_reward_data: Callable[..., Any],
    order_point_item: Callable[..., Any],
    taipei_now_iso: Callable[..., str],
    remember_data: Callable[..., Any],
    save_data: Callable[..., Any],
    order_log_sender: Callable[..., Any],
) -> None:
    global CUSTOMER_REWARDS
    global _to_int
    global get_current_reward_points
    global get_customer_reward_data
    global get_order_point_item
    global get_taipei_now_iso
    global remember_order_data
    global save_bot_data
    global send_order_log

    CUSTOMER_REWARDS = customer_rewards
    _to_int = to_int
    get_current_reward_points = current_reward_points
    get_customer_reward_data = customer_reward_data
    get_order_point_item = order_point_item
    get_taipei_now_iso = taipei_now_iso
    remember_order_data = remember_data
    save_bot_data = save_data
    send_order_log = order_log_sender


def _get_pending_order_point_benefit_info(data: dict) -> dict | None:
    return get_pending_point_benefit_info(
        data,
        point_item_lookup=get_order_point_item,
        to_int=_to_int,
    )


def precheck_order_point_benefit_for_payment(data: dict, customer_id: int) -> None:
    info = _get_pending_order_point_benefit_info(data)
    if info is None or data.get("point_benefit_redeemed"):
        return

    reward_data = get_customer_reward_data(int(customer_id))
    before_points = int(get_current_reward_points(reward_data))
    if before_points < int(info["cost"]):
        raise ValueError(
            f"點數不足，無法使用「{info['name']}」。"
            f"需要 {info['cost']} 點，目前只有 {before_points} 點。"
        )


async def redeem_order_point_benefit_on_payment(
    *,
    interaction: discord.Interaction,
    data: dict,
    customer_id: int,
    channel_id: int,
) -> str | None:
    info = _get_pending_order_point_benefit_info(data)
    if info is None:
        return None

    if data.get("point_benefit_redeemed"):
        before_points = _to_int(data.get("point_benefit_before_points"), 0) or 0
        after_points = _to_int(data.get("point_benefit_after_points"), 0) or 0
        return f"點數福利已扣點：{info['cost']} 點｜{info['name']}（{before_points} → {after_points}）"

    reward_data = get_customer_reward_data(int(customer_id))
    before_points = int(get_current_reward_points(reward_data))
    if before_points < int(info["cost"]):
        raise ValueError(
            f"點數不足，無法使用「{info['name']}」。"
            f"需要 {info['cost']} 點，目前只有 {before_points} 點。"
        )

    logs = reward_data.setdefault("point_adjustment_logs", [])
    if not isinstance(logs, list):
        logs = []
        reward_data["point_adjustment_logs"] = logs

    reward_data["point_adjustment"] = int(reward_data.get("point_adjustment", 0) or 0) - int(info["cost"])
    after_points = int(get_current_reward_points(reward_data))
    reward_data["points"] = after_points
    logs.append(
        {
            "created_at": get_taipei_now_iso(),
            "delta": -int(info["cost"]),
            "before_points": before_points,
            "after_points": after_points,
            "reason": f"訂單點數福利：{info['name']}",
            "source": "order_point_benefit",
            "order_channel_id": int(channel_id),
            "order_no": data.get("order_no") or data.get("receipt_id"),
            "benefit_key": info["key"],
            "benefit_name": info["name"],
            "operator_id": int(getattr(interaction.user, "id", 0) or 0),
        }
    )

    CUSTOMER_REWARDS[int(customer_id)] = reward_data
    data["point_benefit_redeemed"] = True
    data["point_benefit_redeemed_at"] = get_taipei_now_iso()
    data["point_benefit_before_points"] = before_points
    data["point_benefit_after_points"] = after_points
    data["point_benefit_redeemed_by"] = int(getattr(interaction.user, "id", 0) or 0)

    remember_order_data(channel_id, data)
    save_bot_data()

    try:
        await send_order_log(
            interaction.guild,
            title="訂單點數福利已扣點",
            fields=[
                ("顧客", f"<@{customer_id}>", True),
                ("福利", f"{info['cost']} 點｜{info['name']}", True),
                ("點數", f"{before_points} → {after_points}", True),
                ("訂單", str(data.get("order_no") or data.get("receipt_id") or channel_id), False),
            ],
            color=discord.Color.gold(),
        )
    except Exception as exc:
        print(f"[points] 訂單點數福利扣點日誌失敗 channel_id={channel_id}: {exc}")

    return f"點數福利已扣 {info['cost']} 點：{info['name']}（{before_points} → {after_points}）"
