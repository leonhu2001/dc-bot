from __future__ import annotations

from typing import Any

_MEMBER_LEVELS: list[dict[str, Any]] = [
    {"name": "普通魔丸", "threshold": 0},
]
_REWARD_POINT_DIVISOR: int = 100


def configure_rewards(*, member_levels: list[dict] | None = None, reward_point_divisor: int = 100) -> None:
    """設定會員等級與點數換算。

    只保存設定，不保存顧客資料；顧客資料仍由 bot.py / database 層管理。
    """
    global _MEMBER_LEVELS, _REWARD_POINT_DIVISOR
    _MEMBER_LEVELS = list(member_levels or [{"name": "普通魔丸", "threshold": 0}])
    _REWARD_POINT_DIVISOR = int(reward_point_divisor or 100)


def _to_int(value, default: int | None = None) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def get_member_level(total_spent: int) -> dict:
    current = _MEMBER_LEVELS[0]
    for level in _MEMBER_LEVELS:
        if total_spent >= level["threshold"]:
            current = level
        else:
            break
    return current


def get_next_member_level(total_spent: int) -> dict | None:
    for level in _MEMBER_LEVELS:
        if total_spent < level["threshold"]:
            return level
    return None


def get_member_level_index_by_total_spent(total_spent: int) -> int:
    index = 0
    for i, level in enumerate(_MEMBER_LEVELS):
        if total_spent >= int(level["threshold"]):
            index = i
        else:
            break
    return index


def get_member_level_by_index(index: int) -> dict:
    safe_index = max(0, min(int(index), len(_MEMBER_LEVELS) - 1))
    return _MEMBER_LEVELS[safe_index]


def get_effective_member_level_index(data: dict) -> int:
    total_spent = int(data.get("total_spent", 0) or 0)
    cumulative_index = get_member_level_index_by_total_spent(total_spent)
    stored_index = _to_int(data.get("vip_level_index"))

    if stored_index is None:
        return cumulative_index

    stored_index = max(0, min(int(stored_index), len(_MEMBER_LEVELS) - 1))

    # 若顧客曾被降階，不能再用歷史累積總額直接判斷下一級，
    # 要從降階後的新基準重新累積。
    base_total = _to_int(data.get("vip_progress_base_total_spent"))
    if stored_index < cumulative_index:
        if base_total is None:
            return stored_index

        earned_after_reset = max(0, total_spent - base_total)
        virtual_total = int(_MEMBER_LEVELS[stored_index]["threshold"]) + earned_after_reset
        progressed_index = get_member_level_index_by_total_spent(virtual_total)
        return max(stored_index, min(progressed_index, len(_MEMBER_LEVELS) - 1))

    return stored_index


def get_effective_member_level(data: dict) -> dict:
    return get_member_level_by_index(get_effective_member_level_index(data))


def get_next_member_level_for_data(data: dict) -> tuple[dict | None, int]:
    total_spent = int(data.get("total_spent", 0) or 0)
    current_index = get_effective_member_level_index(data)

    if current_index >= len(_MEMBER_LEVELS) - 1:
        return None, 0

    next_level = get_member_level_by_index(current_index + 1)
    current_level = get_member_level_by_index(current_index)
    stored_index = _to_int(data.get("vip_level_index"))
    base_total = _to_int(data.get("vip_progress_base_total_spent"))
    cumulative_index = get_member_level_index_by_total_spent(total_spent)

    # 降階後從該等級的 0 開始重新累積。
    if stored_index is not None and stored_index < cumulative_index:
        if base_total is None:
            earned_after_reset = 0
        else:
            earned_after_reset = max(0, total_spent - base_total)
        needed_between_levels = int(next_level["threshold"]) - int(current_level["threshold"])
        return next_level, max(0, needed_between_levels - earned_after_reset)

    return next_level, max(0, int(next_level["threshold"]) - total_spent)


def sync_vip_level_to_cumulative_if_higher(data: dict) -> tuple[dict, dict]:
    old_level = get_effective_member_level(data)
    current_stored_index = _to_int(data.get("vip_level_index"))

    if current_stored_index is None:
        data["vip_level_index"] = get_member_level_index_by_total_spent(int(data.get("total_spent", 0) or 0))
    else:
        effective_index = get_effective_member_level_index(data)
        if effective_index > current_stored_index:
            data["vip_level_index"] = effective_index
            data["vip_progress_base_total_spent"] = int(data.get("total_spent", 0) or 0)

    new_level = get_effective_member_level(data)
    return old_level, new_level


def format_t_amount(amount: int) -> str:
    return f"{amount:,}T"


def calculate_reward_points(total_spent: int) -> int:
    return total_spent // _REWARD_POINT_DIVISOR


def get_current_reward_points(data: dict) -> int:
    total_spent = int(data.get("total_spent", 0) or 0)
    base_points = calculate_reward_points(total_spent)
    adjustment = int(data.get("point_adjustment", 0) or 0)
    return max(0, base_points + adjustment)
