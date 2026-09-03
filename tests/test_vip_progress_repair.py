from core.vip_levels import BASE_MEMBER_LEVELS
import services.rewards as rewards
from services.vip_progress_repair import (
    has_active_downgrade_reset,
    repair_vip_progress_data,
)


def setup_module():
    rewards.configure_rewards(member_levels=BASE_MEMBER_LEVELS, reward_point_divisor=100)


def test_stuck_silver_promotes_to_gold_without_downgrade_record():
    data = {
        "total_spent": 6000,
        "vip_level_index": 1,
        "vip_progress_base_total_spent": None,
        "vip_downgrade_logs": [],
    }

    changed, old_level, new_level = repair_vip_progress_data(data)

    assert changed is True
    assert old_level["name"] == "銀級魔丸"
    assert new_level["name"] == "金級魔丸"
    assert data["vip_level_index"] == 2
    assert data["vip_progress_base_total_spent"] is None


def test_stale_upgrade_base_without_downgrade_record_is_cleared():
    data = {
        "total_spent": 12000,
        "vip_level_index": 2,
        "vip_progress_base_total_spent": 6000,
        "vip_downgrade_logs": [],
    }

    changed, old_level, new_level = repair_vip_progress_data(data)

    assert changed is True
    assert old_level["name"] == "金級魔丸"
    assert new_level["name"] == "白金魔丸"
    assert data["vip_level_index"] == 3
    assert data["vip_progress_base_total_spent"] is None


def test_real_downgrade_reset_is_preserved():
    data = {
        "total_spent": 12000,
        "vip_level_index": 1,
        "vip_progress_base_total_spent": 12000,
        "vip_downgrade_logs": [
            {
                "old_level": "金級魔丸",
                "new_level": "銀級魔丸",
                "progress_reset_total_spent": 12000,
            }
        ],
    }

    assert has_active_downgrade_reset(data) is True

    changed, old_level, new_level = repair_vip_progress_data(data)

    assert changed is False
    assert old_level["name"] == "銀級魔丸"
    assert new_level["name"] == "銀級魔丸"
    assert data["vip_level_index"] == 1
    assert data["vip_progress_base_total_spent"] == 12000
