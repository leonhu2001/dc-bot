from __future__ import annotations

from typing import Any

import services.rewards as rewards
from core.vip_levels import (
    VIP_TOPUP_REBATE_POLICY_CURRENT,
    get_topup_rebate_percent,
    has_active_vip_progress_reset,
)


def _to_int(value: Any, default: int | None = None) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _max_member_level_index() -> int:
    return rewards.get_member_level_index_by_total_spent(10**18)


def has_active_downgrade_reset(data: dict) -> bool:
    return has_active_vip_progress_reset(data)


def repair_vip_progress_data(data: dict) -> tuple[bool, dict, dict]:
    total_spent = max(0, int(data.get("total_spent", 0) or 0))
    cumulative_index = rewards.get_member_level_index_by_total_spent(total_spent)

    stored_index = _to_int(data.get("vip_level_index"))
    if stored_index is None:
        stored_index = cumulative_index
        data["vip_level_index"] = stored_index
        old_level = rewards.get_member_level_by_index(stored_index)
        return True, old_level, old_level

    stored_index = max(0, min(stored_index, _max_member_level_index()))
    old_level = rewards.get_member_level_by_index(stored_index)

    if has_active_downgrade_reset(data):
        return False, old_level, rewards.get_effective_member_level(data)

    changed = False

    if data.get("vip_progress_base_total_spent") is not None:
        data["vip_progress_base_total_spent"] = None
        changed = True

    if data.get("vip_progress_reset_active") is not False:
        data["vip_progress_reset_active"] = False
        changed = True

    if cumulative_index > stored_index:
        data["vip_level_index"] = cumulative_index
        changed = True

    new_level = rewards.get_member_level_by_index(
        int(data.get("vip_level_index", stored_index) or 0)
    )
    return changed, old_level, new_level


def calculate_member_topup_preview(
    data: dict,
    amount: int,
    *,
    policy_version: str | None = None,
) -> dict[str, Any]:
    """依會員真正有效 VIP 狀態及該儲值單版本計算返利。"""
    amount = max(0, int(amount or 0))
    before_total = max(0, int(data.get("total_spent", 0) or 0))
    policy = str(policy_version or VIP_TOPUP_REBATE_POLICY_CURRENT)

    before_level = rewards.get_effective_member_level(data)

    simulated = dict(data)
    simulated["total_spent"] = before_total + amount

    after_level = rewards.get_effective_member_level(simulated)
    rebate_percent = get_topup_rebate_percent(
        str(after_level.get("name") or "普通魔丸"),
        policy_version=policy,
    )
    rebate_amount = amount * int(rebate_percent) // 100

    return {
        "policy_version": policy,
        "vip_total_before": before_total,
        "vip_total_after": before_total + amount,
        "vip_level_before": str(before_level.get("name") or "普通魔丸"),
        "vip_level_after": str(after_level.get("name") or "普通魔丸"),
        "rebate_percent": int(rebate_percent),
        "rebate_amount": int(rebate_amount),
        "credited_amount": int(amount + rebate_amount),
    }


def repair_all_legacy_vip_progress() -> list[dict[str, Any]]:
    repaired: list[dict[str, Any]] = []

    for user_id, data in rewards.iter_customer_reward_items():
        if not isinstance(data, dict):
            continue

        changed, old_level, new_level = repair_vip_progress_data(data)
        if not changed:
            continue

        repaired.append(
            {
                "user_id": int(user_id),
                "old_level": str(old_level.get("name") or "普通魔丸"),
                "new_level": str(new_level.get("name") or "普通魔丸"),
                "total_spent": int(data.get("total_spent", 0) or 0),
            }
        )

    return repaired
