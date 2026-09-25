from core.vip_levels import BASE_MEMBER_LEVELS
import services.rewards as rewards


def setup_function():
    rewards.configure_rewards(
        member_levels=BASE_MEMBER_LEVELS,
        reward_point_divisor=100,
    )
    rewards.configure_reward_storage({})


def test_amount_correction_reduces_total_points_and_vip_level():
    data = rewards.get_customer_reward_data(1001)
    data.update(
        {
            "total_spent": 12500,
            "point_adjustment": 3,
            "points": 128,
            "vip_level_index": 3,
            "vip_progress_base_total_spent": None,
            "vip_progress_reset_active": False,
        }
    )

    result = rewards.correct_customer_reward_amount(
        1001,
        old_amount=1500,
        new_amount=500,
    )

    assert result["delta"] == -1000
    assert result["old_total_spent"] == 12500
    assert result["new_total_spent"] == 11500
    assert result["old_points"] == 128
    assert result["new_points"] == 118
    assert result["old_level"] == "白金魔丸"
    assert result["new_level"] == "金級魔丸"
    assert data["vip_level_index"] == 2
    assert data["point_adjustment"] == 3


def test_amount_correction_can_upgrade_when_corrected_upward():
    data = rewards.get_customer_reward_data(1002)
    data.update(
        {
            "total_spent": 5900,
            "vip_level_index": 1,
            "vip_progress_base_total_spent": None,
            "vip_progress_reset_active": False,
        }
    )

    result = rewards.correct_customer_reward_amount(
        1002,
        old_amount=400,
        new_amount=600,
    )

    assert result["new_total_spent"] == 6100
    assert result["new_points"] == 61
    assert result["new_level"] == "金級魔丸"
    assert data["vip_level_index"] == 2


def test_amount_correction_preserves_active_vip_reset_state():
    data = rewards.get_customer_reward_data(1003)
    data.update(
        {
            "total_spent": 12500,
            "vip_level_index": 1,
            "vip_progress_base_total_spent": 12000,
            "vip_progress_reset_active": True,
        }
    )

    result = rewards.correct_customer_reward_amount(
        1003,
        old_amount=1500,
        new_amount=500,
    )

    assert result["reset_preserved"] is True
    assert result["new_total_spent"] == 11500
    assert data["vip_level_index"] == 1
    assert data["vip_progress_base_total_spent"] == 12000
    assert data["vip_progress_reset_active"] is True
