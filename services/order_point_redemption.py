from __future__ import annotations

from typing import Any, Callable

import discord

from services.point_benefit_catalog import (
    adapt_point_benefit_for_rule,
    calculate_service_bonus_point_cost,
    get_point_benefit_item,
    is_service_bonus_allowed_for_rule,
    uses_dynamic_service_point_cost,
)


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


def _resolve_order_rule(data: dict):
    """Resolve the current authoritative rule without trusting order money fields."""

    try:
        from services.order_rules import ORDER_RULES, get_rule
        from services.orders import ORDER_RULE_KEY_BY_LABEL
    except Exception:
        return None

    rule_key = str(data.get("order_rule_key") or "").strip()
    if rule_key:
        try:
            return get_rule(rule_key)
        except Exception:
            pass

    item_text = str(data.get("item") or "").strip()
    alias_key = ORDER_RULE_KEY_BY_LABEL.get(item_text)
    if alias_key:
        try:
            rule = get_rule(alias_key)
            data["order_rule_key"] = rule.key
            return rule
        except Exception:
            pass

    for rule in ORDER_RULES.values():
        if str(getattr(rule, "label", "") or "") == item_text:
            data["order_rule_key"] = rule.key
            return rule

    return None


def _is_dynamic_game_rule_hint(data: dict) -> bool:
    rule_key = str(data.get("order_rule_key") or "").strip().lower()
    return rule_key.startswith(("lol_", "valorant_", "apex_"))


def _get_pending_order_point_benefit_info(data: dict) -> dict | None:
    # zYao 3C3B website finance point safety v1
    if data.get("website_finance_settled"):
        return None

    benefit_key = str(
        data.get("point_benefit_key")
        or data.get("selected_point_benefit_key")
        or ""
    ).strip()

    if not benefit_key:
        return None

    injected_item = get_order_point_item(benefit_key)
    catalog_item = get_point_benefit_item(benefit_key)
    item = catalog_item or injected_item or {}
    rule = _resolve_order_rule(data)

    # LoL / VALORANT / APEX service rewards are never allowed to trust the
    # persisted point_benefit_cost. Recalculate from the live rule unit price and
    # actual companion count immediately before both precheck and deduction.
    if rule is not None and uses_dynamic_service_point_cost(rule, item):
        if not is_service_bonus_allowed_for_rule(
            rule,
            item,
            player_count=data.get("player_count"),
        ):
            raise ValueError("這張點數加時／加局福利與目前陪玩人數或商品類型不一致，請重新選擇。")

        benefit_cost = calculate_service_bonus_point_cost(
            rule=rule,
            benefit=item,
            player_count=data.get("player_count"),
        )
        adapted = adapt_point_benefit_for_rule(rule, item)
        benefit_name = str(adapted.get("name") or item.get("name") or benefit_key)

        if benefit_cost <= 0:
            raise ValueError("無法依正式商品規則重新計算點數成本，請重新選擇點數福利。")

        # Keep the order snapshot useful for audit/UI, but it is output from the
        # authoritative calculation rather than an input to the deduction.
        data["point_benefit_cost"] = int(benefit_cost)
        data["point_benefit_name"] = benefit_name
        return {
            "key": benefit_key,
            "name": benefit_name,
            "cost": int(benefit_cost),
        }

    # If the order explicitly identifies one of the dynamic game rule families,
    # failure to resolve that rule must fail closed instead of falling back to a
    # tamperable/stale stored cost.
    if (
        _is_dynamic_game_rule_hint(data)
        and str(item.get("kind") or "") == "service_bonus"
        and rule is None
    ):
        raise ValueError("找不到正式商品規則，無法安全計算點數成本；請重新選擇商品後再付款。")

    benefit_name = str(
        data.get("point_benefit_name")
        or item.get("name")
        or benefit_key
    )

    # Non-dynamic products keep their historical snapshot behavior for backward
    # compatibility. Only the three rule-priced game catalogs use mandatory live
    # recalculation above.
    benefit_cost = _to_int(
        data.get("point_benefit_cost"),
        _to_int(item.get("cost"), 0) if item else 0,
    ) or 0

    if benefit_cost <= 0:
        return None

    return {
        "key": benefit_key,
        "name": benefit_name,
        "cost": int(benefit_cost),
    }


def precheck_order_point_benefit_for_payment(data: dict, customer_id: int) -> None:
    info = _get_pending_order_point_benefit_info(data)

    if info is None:
        return

    if data.get("point_benefit_redeemed"):
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
