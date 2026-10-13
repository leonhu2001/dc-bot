from __future__ import annotations

from core.vip_levels import BASE_MEMBER_LEVELS
import services.rewards as rewards
from services.wallet_refund_runtime import _apply_refund_to_member_data
from services.wallet_refunds import (
    create_wallet_refund_request,
    list_pending_wallet_refunds,
)
from services.wallet_service import adjust_wallet_balance


def setup_module():
    rewards.configure_rewards(member_levels=BASE_MEMBER_LEVELS, reward_point_divisor=100)


def test_refund_request_cannot_exceed_paid_principal(tmp_path):
    db = tmp_path / "bot.db"
    adjust_wallet_balance(customer_id="1", amount=1000, tx_type="topup", db_file=db)
    adjust_wallet_balance(customer_id="1", amount=30, tx_type="topup_bonus", db_file=db)

    request = create_wallet_refund_request(
        customer_discord_id="1",
        amount=1000,
        requested_by_discord_id="9",
        requested_by_display_name="Admin",
        db_file=db,
    )
    assert request["amount"] == 1000
    assert request["status"] == "pending"
    assert len(list_pending_wallet_refunds(db_file=db)) == 1


def test_refund_reduces_vip_total_but_keeps_points_unchanged():
    data = {
        "total_spent": 26000,
        "vip_level_index": 4,
        "vip_progress_base_total_spent": None,
        "vip_progress_reset_active": False,
        "point_adjustment": -200,
    }
    points_before = rewards.get_current_reward_points(data)

    result = _apply_refund_to_member_data(data, 2000)

    assert result["total_before"] == 26000
    assert result["total_after"] == 24000
    assert result["old_level"] == "鑽石魔丸"
    assert result["new_level"] == "白金魔丸"
    assert rewards.get_current_reward_points(data) == points_before


def test_refund_can_downgrade_inside_reset_progress():
    data = {
        "total_spent": 31000,
        "vip_level_index": 3,
        "vip_progress_base_total_spent": 31000,
        "vip_progress_reset_active": True,
        "vip_downgrade_logs": [
            {
                "old_level": "鑽石魔丸",
                "new_level": "白金魔丸",
                "progress_reset_total_spent": 31000,
            }
        ],
        "point_adjustment": -250,
    }

    result = _apply_refund_to_member_data(data, 1000)

    assert result["old_level"] == "白金魔丸"
    assert result["new_level"] == "金級魔丸"
    assert data["vip_progress_reset_active"] is True
    assert data["vip_progress_base_total_spent"] == 30000
