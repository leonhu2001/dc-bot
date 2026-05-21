from __future__ import annotations

from typing import Any

import discord

_MEMBER_LEVELS: list[dict[str, Any]] = [
    {"name": "普通魔丸", "threshold": 0},
]
_REWARD_POINT_DIVISOR: int = 100
_CUSTOMER_REWARDS: dict[int, dict[str, Any]] = {}


def configure_reward_storage(customer_rewards: dict[int, dict[str, Any]]) -> None:
    """設定顧客會員資料來源。

    資料本體仍由 bot.py / database 層保存，這裡只保存 reference，
    讓會員服務能沿用同一份 CUSTOMER_REWARDS。
    """
    global _CUSTOMER_REWARDS
    _CUSTOMER_REWARDS = customer_rewards


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


def get_customer_reward_data(user_id: int) -> dict:
    data = _CUSTOMER_REWARDS.setdefault(
        user_id,
        {
            "total_spent": 0,
            "order_count": 0,
            "last_order_at": None,
            "points": 0,
            "point_adjustment": 0,
            "point_adjustment_logs": [],
            "platinum_channel_id": None,
            "manual_purchase_keys": [],
            "vip_level_index": None,
            "vip_progress_base_total_spent": None,
            "vip_last_downgrade_check_month": None,
            "vip_downgrade_logs": [],
        }
    )
    data.setdefault("total_spent", 0)
    data.setdefault("order_count", 0)
    data.setdefault("last_order_at", None)
    data.setdefault("points", 0)
    data.setdefault("point_adjustment", 0)
    data.setdefault("point_adjustment_logs", [])
    data.setdefault("platinum_channel_id", None)
    data.setdefault("manual_purchase_keys", [])
    data.setdefault("notes", [])
    data.setdefault("vip_level_index", None)
    data.setdefault("vip_progress_base_total_spent", None)
    data.setdefault("vip_last_downgrade_check_month", None)
    data.setdefault("vip_downgrade_logs", [])
    if not isinstance(data["manual_purchase_keys"], list):
        data["manual_purchase_keys"] = []
    if not isinstance(data["point_adjustment_logs"], list):
        data["point_adjustment_logs"] = []
    if not isinstance(data["notes"], list):
        data["notes"] = []
    if not isinstance(data["vip_downgrade_logs"], list):
        data["vip_downgrade_logs"] = []
    return data

def build_member_info_embed(member: discord.abc.User, data: dict, show_points: bool = True) -> discord.Embed:
    total_spent = int(data.get("total_spent", 0) or 0)
    order_count = int(data.get("order_count", 0) or 0)
    points = get_current_reward_points(data)
    level = get_effective_member_level(data)
    next_level, next_level_gap = get_next_member_level_for_data(data)

    embed = discord.Embed(
        title="你的會員資料" if show_points else "顧客會員資料",
        color=discord.Color.purple()
    )
    embed.add_field(name="顧客", value=member.mention, inline=False)
    embed.add_field(name="累積消費", value=format_t_amount(total_spent), inline=True)
    if show_points:
        embed.add_field(name="目前點數", value=f"{points:,} 點", inline=True)
    embed.add_field(name="完成訂單", value=f"{order_count:,} 單", inline=True)
    embed.add_field(name="會員等級", value=level["name"], inline=True)

    if next_level is None:
        embed.add_field(name="距離下一級還差", value="已達最高等級", inline=False)
    else:
        embed.add_field(
            name="距離下一級還差",
            value=f"{format_t_amount(next_level_gap)}（下一級：{next_level['name']}）",
            inline=False
        )

    return embed


def get_customer_notes(user_id: int) -> list[dict]:
    data = get_customer_reward_data(user_id)
    notes = data.setdefault("notes", [])
    if not isinstance(notes, list):
        data["notes"] = []
        notes = data["notes"]
    return notes


def format_customer_notes_for_staff(user_id: int, limit: int = 8) -> str:
    notes = get_customer_notes(user_id)
    if not notes:
        return "無備註"

    lines = []
    for index, note in enumerate(notes[:limit], start=1):
        tag = "🚫 黑名單" if note.get("is_blacklist") else "📝 備註"
        created_at = note.get("created_at") or "未紀錄時間"
        operator_id = note.get("operator_id")
        operator_text = f"<@{operator_id}>" if operator_id else "未紀錄"
        content = str(note.get("content") or "未填寫")
        lines.append(f"{index}. {tag}｜{content}\n　建立：{created_at}｜人員：{operator_text}")

    if len(notes) > limit:
        lines.append(f"…還有 {len(notes) - limit} 筆")

    return "\n".join(lines)


def format_customer_notes_for_ticket(user_id: int) -> str:
    notes = get_customer_notes(user_id)
    if not notes:
        return ""

    blacklist_notes = [n for n in notes if n.get("is_blacklist")]
    normal_notes = [n for n in notes if not n.get("is_blacklist")]
    picked = blacklist_notes[:3] + normal_notes[:3]

    lines = ["\n\n⚠️ 客服注意：此顧客有備註紀錄"]
    if blacklist_notes:
        lines.append("🚫 含黑名單 / 高風險備註")

    for index, note in enumerate(picked[:5], start=1):
        tag = "黑名單" if note.get("is_blacklist") else "備註"
        lines.append(f"{index}. [{tag}] {note.get('content') or '未填寫'}")

    return "\n".join(lines)

