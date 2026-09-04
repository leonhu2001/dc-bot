from core.vip_levels import BASE_MEMBER_LEVELS
import services.rewards as rewards
from services.vip_progress_repair import (
    has_active_downgrade_reset,
    repair_vip_progress_data,
)


def setup_module():
    rewards.configure_rewards(member_levels=BASE_MEMBER_LEVELS, reward_point_divisor=100)


def test_stuck_silver_promotes_to_gold_without_reset_baseline():
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


def test_reset_baseline_without_log_is_preserved_for_legacy_data():
    data = {
        "total_spent": 8880,
        "vip_level_index": 1,
        "vip_progress_base_total_spent": 5180,
        "vip_downgrade_logs": [],
    }

    assert has_active_downgrade_reset(data) is True

    changed, old_level, new_level = repair_vip_progress_data(data)

    assert changed is False
    assert old_level["name"] == "銀級魔丸"
    assert new_level["name"] == "銀級魔丸"
    assert data["vip_level_index"] == 1
    assert data["vip_progress_base_total_spent"] == 5180


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


def test_core_normal_progress_auto_upgrades_without_reset_baseline():
    data = {
        "total_spent": 6000,
        "vip_level_index": 1,
        "vip_progress_base_total_spent": None,
    }

    assert rewards.get_effective_member_level(data)["name"] == "金級魔丸"

    old_level, new_level = rewards.sync_vip_level_to_cumulative_if_higher(data)

    assert old_level["name"] == "金級魔丸"
    assert new_level["name"] == "金級魔丸"
    assert data["vip_level_index"] == 2
    assert data["vip_progress_base_total_spent"] is None


def test_downgrade_reset_requires_new_spend_then_clears_after_reupgrade():
    data = {
        "total_spent": 8880,
        "vip_level_index": 1,
        "vip_progress_base_total_spent": 5180,
    }

    assert rewards.get_effective_member_level(data)["name"] == "銀級魔丸"

    next_level, remaining = rewards.get_next_member_level_for_data(data)
    assert next_level["name"] == "金級魔丸"
    assert remaining == 300

    data["total_spent"] = 9180

    assert rewards.get_effective_member_level(data)["name"] == "金級魔丸"

    rewards.sync_vip_level_to_cumulative_if_higher(data)

    assert data["vip_level_index"] == 2
    assert data["vip_progress_base_total_spent"] is None
