from __future__ import annotations

from typing import Any, Callable

import re

import discord

_MEMBER_LEVELS: list[dict[str, Any]] = [
    {"name": "普通魔丸", "threshold": 0},
]
_REWARD_POINT_DIVISOR: int = 100
_CUSTOMER_REWARDS: dict[int, dict[str, Any]] = {}
_ORDER_SELECTIONS: dict[int, dict[str, Any]] = {}
_SAVE_BOT_DATA: Callable[[], None] | None = None
_SILVER_MEMBER_ROLE_ID: int | None = None
_PLATINUM_PRIVATE_CATEGORY_ID: int | None = None
_PLATINUM_CHAT_ROLE_IDS: list[int] = []


def configure_reward_benefits(
    *,
    silver_member_role_id: int | None = None,
    platinum_private_category_id: int | None = None,
    platinum_chat_role_ids: list[int] | None = None,
) -> None:
    """設定會員福利需要的身分組 / 類別 ID。"""
    global _SILVER_MEMBER_ROLE_ID, _PLATINUM_PRIVATE_CATEGORY_ID, _PLATINUM_CHAT_ROLE_IDS
    _SILVER_MEMBER_ROLE_ID = silver_member_role_id
    _PLATINUM_PRIVATE_CATEGORY_ID = platinum_private_category_id
    _PLATINUM_CHAT_ROLE_IDS = list(platinum_chat_role_ids or [])


def configure_reward_storage(customer_rewards: dict[int, dict[str, Any]]) -> None:
    """設定顧客會員資料來源。

    資料本體仍由 bot.py / database 層保存，這裡只保存 reference，
    讓會員服務能沿用同一份 CUSTOMER_REWARDS。
    """
    global _CUSTOMER_REWARDS
    _CUSTOMER_REWARDS = customer_rewards




def configure_reward_order_context(
    order_selections: dict[int, dict[str, Any]],
    save_bot_data_func: Callable[[], None],
) -> None:
    """設定訂單資料與保存函式，供結單累積會員消費使用。"""
    global _ORDER_SELECTIONS, _SAVE_BOT_DATA
    _ORDER_SELECTIONS = order_selections
    _SAVE_BOT_DATA = save_bot_data_func

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

async def fetch_member_safely(guild: discord.Guild, user_id: int) -> discord.Member | None:
    member = guild.get_member(user_id)
    if member is not None:
        return member
    try:
        return await guild.fetch_member(user_id)
    except (discord.NotFound, discord.Forbidden, discord.HTTPException):
        return None


async def ensure_reward_member_benefits(guild: discord.Guild, member: discord.Member | None, data: dict) -> list[str]:
    if member is None:
        return []

    notices = []
    level = get_effective_member_level(data)
    level_threshold = int(level.get("threshold", 0) or 0)

    if _SILVER_MEMBER_ROLE_ID is not None:
        silver_role = guild.get_role(_SILVER_MEMBER_ROLE_ID)
    else:
        silver_role = None

    if level_threshold >= 2500:
        if silver_role is not None and silver_role not in member.roles:
            try:
                await member.add_roles(silver_role, reason="累積消費達銀級魔丸門檻")
                notices.append("已給予銀級魔丸身分組")
            except discord.Forbidden:
                notices.append("銀級魔丸身分組給予失敗：Bot 權限不足或身分組位置不夠高")
            except discord.HTTPException:
                notices.append("銀級魔丸身分組給予失敗：Discord API 錯誤")
    else:
        if silver_role is not None and silver_role in member.roles:
            try:
                await member.remove_roles(silver_role, reason="VIP 維持條件未達，降至普通魔丸")
                notices.append("已收回銀級魔丸身分組")
            except discord.Forbidden:
                notices.append("銀級魔丸身分組收回失敗：Bot 權限不足或身分組位置不夠高")
            except discord.HTTPException:
                notices.append("銀級魔丸身分組收回失敗：Discord API 錯誤")

    if level_threshold >= 13000:
        existing_channel_id = _to_int(data.get("platinum_channel_id"))
        if existing_channel_id is not None and guild.get_channel(existing_channel_id) is not None:
            return notices

        category = guild.get_channel(_PLATINUM_PRIVATE_CATEGORY_ID) if _PLATINUM_PRIVATE_CATEGORY_ID is not None else None
        if not isinstance(category, discord.CategoryChannel):
            notices.append("白金專屬頻道建立失敗：找不到指定類別")
            return notices

        overwrites = {
            guild.default_role: discord.PermissionOverwrite(
                view_channel=False,
                send_messages=False,
                read_message_history=False,
            ),
            member: discord.PermissionOverwrite(
                view_channel=True,
                send_messages=True,
                read_message_history=True,
                attach_files=True,
            ),
        }

        if guild.me is not None:
            overwrites[guild.me] = discord.PermissionOverwrite(
                view_channel=True,
                send_messages=True,
                manage_channels=True,
                read_message_history=True,
                attach_files=True,
            )

        for role_id in _PLATINUM_CHAT_ROLE_IDS:
            role = guild.get_role(role_id)
            if role is not None:
                overwrites[role] = discord.PermissionOverwrite(
                    view_channel=True,
                    send_messages=True,
                    read_message_history=True,
                    attach_files=True,
                )

        clean_name = "".join(c if c.isalnum() else "-" for c in member.display_name.lower())[:40]
        channel_name = f"白金魔丸-{clean_name}-{member.id}"[:90]

        try:
            channel = await guild.create_text_channel(
                name=channel_name,
                category=category,
                overwrites=overwrites,
                topic=f"platinum_customer_id={member.id}",
                reason="累積消費達白金魔丸門檻，自動建立專屬聊天頻道"
            )
            data["platinum_channel_id"] = channel.id
            notices.append(f"已建立白金專屬聊天頻道：{channel.mention}")

            await channel.send(
                f"{member.mention} 已達白金魔丸會員，這裡是你的專屬聊天頻道。",
                allowed_mentions=discord.AllowedMentions(users=True, roles=False, everyone=False)
            )
        except discord.Forbidden:
            notices.append("白金專屬頻道建立失敗：Bot 權限不足")
        except discord.HTTPException:
            notices.append("白金專屬頻道建立失敗：Discord API 錯誤")

    return notices


def parse_receipt_amount(amount_text: str) -> int | None:
    """從收據金額欄位擷取金額。
    支援：1275、NT$1,275、1275T、750+595。
    若有加號，會把所有數字相加；否則取第一組數字。
    """
    normalized = amount_text.replace(",", "").strip()
    numbers = [int(value) for value in re.findall(r"\d+", normalized)]

    if not numbers:
        return None

    if "+" in normalized and len(numbers) >= 2:
        return sum(numbers)

    return numbers[0]


async def add_customer_reward_from_order(
    guild: discord.Guild,
    order_channel_id: int,
    customer_id: int,
    amount_text: str,
    notify_channel: discord.abc.Messageable | None = None,
) -> str:
    order_data = _ORDER_SELECTIONS.get(order_channel_id, {})

    if order_data.get("reward_counted"):
        return "此訂單已累積過會員消費，未重複累積。"

    amount = parse_receipt_amount(amount_text)
    if amount is None or amount <= 0:
        return "會員消費未累積：收據金額欄位沒有可辨識的數字。"

    data = get_customer_reward_data(customer_id)
    old_total_spent = int(data.get("total_spent", 0) or 0)
    old_level = get_effective_member_level(data)
    data["total_spent"] = old_total_spent + amount
    data["order_count"] = int(data.get("order_count", 0) or 0) + 1

    from core.time_utils import get_taipei_now_iso

    data["last_order_at"] = get_taipei_now_iso()
    data["points"] = get_current_reward_points(data)
    sync_vip_level_to_cumulative_if_higher(data)

    order_data["reward_counted"] = True
    order_data["reward_amount"] = amount
    order_data["reward_counted_at"] = get_taipei_now_iso()
    _ORDER_SELECTIONS[order_channel_id] = order_data

    member = await fetch_member_safely(guild, customer_id)
    benefit_notices = await ensure_reward_member_benefits(guild, member, data)

    level = get_effective_member_level(data)
    if level["threshold"] > old_level["threshold"]:
        upgrade_notice = f"恭喜 <@{customer_id}> 升級為 **{level['name']}**！目前累積消費：{format_t_amount(int(data['total_spent']))}"
        benefit_notices.insert(0, upgrade_notice)
        if notify_channel is not None:
            try:
                await notify_channel.send(
                    upgrade_notice,
                    allowed_mentions=discord.AllowedMentions(users=True, roles=False, everyone=False)
                )
            except discord.HTTPException:
                pass

    if _SAVE_BOT_DATA is not None:
        _SAVE_BOT_DATA()

    result = (
        f"會員累積已更新：+{format_t_amount(amount)}，"
        f"目前累積 {format_t_amount(int(data['total_spent']))}，"
        f"完成訂單 {int(data['order_count'])} 單，"
        f"等級：{level['name']}。"
    )

    if benefit_notices:
        result += "\n" + "\n".join(f"- {notice}" for notice in benefit_notices)

    return result

