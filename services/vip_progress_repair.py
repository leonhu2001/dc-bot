from __future__ import annotations

from typing import Any

import services.rewards as rewards
from core.vip_levels import get_topup_rebate_percent, has_active_vip_progress_reset


def _to_int(value: Any, default: int | None = None) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _max_member_level_index() -> int:
    # 以既有公開函式取得最高階級 index，避免依賴 rewards 私有常數。
    return rewards.get_member_level_index_by_total_spent(10**18)


def has_active_downgrade_reset(data: dict) -> bool:
    """相容舊呼叫名稱；實際判斷統一使用核心 VIP reset 規則。"""
    return has_active_vip_progress_reset(data)


def repair_vip_progress_data(data: dict) -> tuple[bool, dict, dict]:
    """修復歷史上卡在舊 VIP 階級的資料。

    舊版邏輯只要 vip_level_index 低於累積金額推導出的階級，且
    vip_progress_base_total_spent 為空，就會誤判成不能升級。

    真正被降級的會員一定會有 vip_downgrade_logs 與重置基準，
    這類資料完全保留原規則；其餘沒有降級紀錄的資料則應依正常
    有效累積金額自動升級。
    """
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

    # 沒有真正 reset 證據時，base_total 是舊版正常升級留下的髒資料。
    if data.get("vip_progress_base_total_spent") is not None:
        data["vip_progress_base_total_spent"] = None
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
) -> dict[str, Any]:
    """依會員真正有效 VIP 狀態計算儲值後等級與返利。

    若會員處於降級後重新累積區間，這裡會保留重置基準，
    不會因歷史 total_spent 很高就提前取得高階返利。
    """
    amount = max(0, int(amount or 0))
    before_total = max(0, int(data.get("total_spent", 0) or 0))

    before_level = rewards.get_effective_member_level(data)

    simulated = dict(data)
    simulated["total_spent"] = before_total + amount

    after_level = rewards.get_effective_member_level(simulated)
    rebate_percent = get_topup_rebate_percent(
        str(after_level.get("name") or "普通魔丸")
    )
    rebate_amount = amount * int(rebate_percent) // 100

    return {
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
