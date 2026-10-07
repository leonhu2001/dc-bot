import asyncio
from pathlib import Path

from services import rewards
from web.app.routers.dispatch_state import _dispatch_alert_keys_for_user


def test_wallet_order_does_not_double_count_topup_vip_progress():
    customer_rewards = {}
    orders = {
        12345: {
            "customer_id": 9001,
            "payment_method": "我的錢包",
            "amount": 600,
            "total_amount": 600,
        }
    }
    save_calls = []

    rewards.configure_reward_storage(customer_rewards)
    rewards.configure_reward_order_context(
        orders,
        lambda: save_calls.append(True),
    )

    data = rewards.get_customer_reward_data(9001)
    data["total_spent"] = 2000
    data["order_count"] = 0
    data["point_adjustment"] = -20
    data["points"] = rewards.get_current_reward_points(data)

    result = asyncio.run(
        rewards.add_customer_reward_from_order(
            guild=None,
            order_channel_id=12345,
            customer_id=9001,
            amount_text="600",
        )
    )

    assert data["total_spent"] == 2000
    assert data["order_count"] == 1
    assert orders[12345]["reward_counted"] is True
    assert orders[12345]["reward_excluded"] is True
    assert orders[12345]["reward_amount"] == 0
    assert "未再次增加累積消費" in result
    assert save_calls

    # Re-running the close path must remain idempotent.
    asyncio.run(
        rewards.add_customer_reward_from_order(
            guild=None,
            order_channel_id=12345,
            customer_id=9001,
            amount_text="600",
        )
    )
    assert data["total_spent"] == 2000
    assert data["order_count"] == 1


def test_wallet_reward_exclusion_survives_later_amount_correction():
    customer_rewards = {}
    rewards.configure_reward_storage(customer_rewards)
    data = rewards.get_customer_reward_data(9002)
    data["total_spent"] = 2000

    order_data = {
        "customer_id": 9002,
        "payment_method": "我的錢包",
        "amount": 600,
        "total_amount": 600,
        "reward_counted": True,
        "reward_excluded": True,
        "reward_amount": 0,
    }

    result = rewards.sync_reward_counted_order_amount(order_data, 800)

    assert result is None
    assert data["total_spent"] == 2000
    assert order_data["amount"] == 800
    assert order_data["total_amount"] == 800
    assert order_data["reward_amount"] == 0


def _snapshot(rule):
    return {
        "keys": ["MO-1"],
        "_alert_rules": {"MO-1": rule},
    }


def test_fully_specified_order_only_alerts_specified_staff():
    snapshot = _snapshot(
        {
            "required_staff_count": 1,
            "specified_staff_ids": ["111"],
            "active_claim_staff_ids": [],
        }
    )

    assert _dispatch_alert_keys_for_user(snapshot, {"id": "111"}) == ["MO-1"]
    assert _dispatch_alert_keys_for_user(snapshot, {"id": "222"}) == []


def test_partially_specified_multi_staff_order_alerts_for_open_general_slot():
    snapshot = _snapshot(
        {
            "required_staff_count": 3,
            "specified_staff_ids": ["111"],
            "active_claim_staff_ids": [],
        }
    )

    assert _dispatch_alert_keys_for_user(snapshot, {"id": "222"}) == ["MO-1"]


def test_non_specified_alert_stops_when_unrestricted_slots_are_filled():
    snapshot = _snapshot(
        {
            "required_staff_count": 2,
            "specified_staff_ids": ["111"],
            "active_claim_staff_ids": ["222"],
        }
    )

    assert _dispatch_alert_keys_for_user(snapshot, {"id": "333"}) == []
    assert _dispatch_alert_keys_for_user(snapshot, {"id": "111"}) == ["MO-1"]


def test_unrestricted_order_alerts_every_dispatch_viewer():
    snapshot = _snapshot(
        {
            "required_staff_count": 2,
            "specified_staff_ids": [],
            "active_claim_staff_ids": [],
        }
    )

    assert _dispatch_alert_keys_for_user(snapshot, {"id": "333"}) == ["MO-1"]


def test_dispatch_frontend_uses_user_specific_alert_keys():
    source = Path("web/app/static/js/dispatch_alerts.js").read_text(encoding="utf-8")

    assert "knownAlertKeys" in source
    assert "data.alert_keys || data.keys || []" in source
    assert "newAlertKeys" in source
    assert "refreshAfterNewOrder(0, newAlertKeys)" in source


def test_legacy_wallet_vip_runtime_monkey_patch_is_removed():
    source = Path("services/topup_runtime.py").read_text(encoding="utf-8")

    assert "install_wallet_vip_guard" not in source
    assert "_wallet_vip_guard_installed" not in source
