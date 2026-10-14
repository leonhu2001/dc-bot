from __future__ import annotations

import asyncio
from types import SimpleNamespace

import services.rewards as rewards
from services.order_flow import build_payment_method_embed
from services.order_payment_policy import (
    is_zero_amount_order,
    requires_external_payment_review,
    requires_wallet_debit,
)


def test_zero_amount_payment_routing_skips_money_movement_but_positive_orders_do_not():
    assert is_zero_amount_order(0) is True
    assert is_zero_amount_order(1) is False

    assert requires_external_payment_review("轉帳", 0) is False
    assert requires_external_payment_review("街口", 0) is False
    assert requires_external_payment_review("轉帳", 1) is True
    assert requires_external_payment_review("街口", 1) is True

    assert requires_wallet_debit("我的錢包", 0) is False
    assert requires_wallet_debit("我的錢包", 1) is True


def test_payment_panel_displays_known_zero_amount_instead_of_staff_placeholder():
    zero_embed = build_payment_method_embed(
        customer_id=7000,
        category_label="三角洲",
        item="娛樂陪",
        quantity=1,
        amount=0,
    )
    unknown_embed = build_payment_method_embed(
        customer_id=7000,
        category_label="三角洲",
        item="娛樂陪",
        quantity=1,
        amount=None,
    )

    assert "訂單總價：0T" in str(zero_embed.description)
    assert "待客服填寫" not in str(zero_embed.description)
    assert "待客服填寫" in str(unknown_embed.description)


def test_zero_customer_pay_marks_reward_handling_complete_without_adding_spend_or_points():
    customer_id = 7001
    channel_id = 8001
    customer_rewards = {}
    order_data = {
        "customer_id": customer_id,
        "payment_method": "轉帳",
        "item": "娛樂陪〈端遊〉｜單陪",
    }
    orders = {channel_id: order_data}
    saves = []

    rewards.configure_reward_storage(customer_rewards)
    rewards.configure_reward_order_context(orders, lambda: saves.append(True))
    rewards.configure_rewards(
        member_levels=[{"name": "普通魔丸", "threshold": 0}],
        reward_point_divisor=100,
    )

    reward_data = rewards.get_customer_reward_data(customer_id)
    reward_data["total_spent"] = 2000
    reward_data["points"] = 20

    result = asyncio.run(
        rewards.add_customer_reward_from_order(
            guild=SimpleNamespace(),
            order_channel_id=channel_id,
            customer_id=customer_id,
            amount_text="0",
            notify_channel=None,
        )
    )

    assert "實付為 0T" in result
    assert reward_data["total_spent"] == 2000
    assert reward_data["order_count"] == 1
    assert reward_data["last_order_at"]
    assert rewards.get_current_reward_points(reward_data) == 20
    assert order_data["reward_counted"] is True
    assert order_data["reward_amount"] == 0
    assert order_data["reward_zero_amount"] is True
    assert order_data["reward_excluded"] is False
    assert saves


def test_zero_reward_marker_can_be_corrected_to_positive_amount_later():
    customer_id = 7002
    rewards.configure_reward_storage({})
    rewards.configure_rewards(
        member_levels=[{"name": "普通魔丸", "threshold": 0}],
        reward_point_divisor=100,
    )
    order_data = {
        "customer_id": customer_id,
        "amount": 0,
        "total_amount": 0,
        "reward_counted": True,
        "reward_amount": 0,
        "reward_excluded": False,
    }

    result = rewards.sync_reward_counted_order_amount(order_data, 500)

    assert result is not None
    assert result["delta"] == 500
    assert rewards.get_customer_reward_data(customer_id)["total_spent"] == 500
    assert order_data["reward_amount"] == 500
    assert "reward_zero_amount" not in order_data
