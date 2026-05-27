from __future__ import annotations

from typing import Any, Callable
from datetime import datetime, timezone, timedelta
from pathlib import Path
import sqlite3

import hashlib
import re

import discord

from core.time_utils import get_taipei_now, get_taipei_now_iso
from core.database import init_database, _db_columns, _json_load_maybe

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
_REWARD_DB_FILE: Path | None = None
VIP_PROGRESS_EXCLUDED_ITEMS = {"幣號"}

# ========= VIP display / reward exclusions =========

NO_VIP_REWARD_ITEMS = {
    
    "代洗哈夫幣",
    "純綠代肝哈夫幣",
}

VIP_LEVEL_BENEFITS = {
    "普通魔丸": "尚未解鎖 VIP 福利。",
    "銀級魔丸": (
        "累積消費 2,000T⤴️\n"
        "・專屬 VIP 身分組，可自行創建 VIP 語音頻道\n"
        "・基礎單 97 折，體驗單除外"
    ),
    "金級魔丸": (
        "累積消費 6,000T⤴️\n"
        "・享有銀級所有福利\n"
        "・基礎單 96 折，體驗單除外"
    ),
    "白金魔丸": (
        "累積消費 12,000T⤴️\n"
        "・享有金級所有福利\n"
        "・基礎單 95.5 折，體驗單除外\n"
        "・可建立 VIP 專屬文字頻道\n"
        "・升級當月贈送 9 折優惠券 1 張，低消 500，限 30 天內使用"
    ),
    "鑽石魔丸": (
        "累積消費 25,000T⤴️\n"
        "・享有白金所有福利\n"
        "・基礎單 95 折，體驗單除外\n"
        "・優先安排熟悉打手"
    ),
    "星耀魔丸": (
        "累積消費 50,000T⤴️\n"
        "・享有鑽石所有福利\n"
        "・每月 1 小時免指定費\n"
        "・優先排單"
    ),
    "頂級魔丸": (
        "累積消費 88,888T⤴️\n"
        "・享有星耀所有福利\n"
        "・基礎單 9 折，體驗單除外\n"
        "・每月 3 小時免指定費\n"
        "・每月一次免費「機密航天保底1000w」\n"
        "・最高優先排單\n"
        "・專屬客服優先處理"
    ),
}



def recalculate_web_payout_after_close(order_no=None, web_order_id=None):
    """Discord 結單後同步重算 web dashboard 分潤。"""
    try:
        from shared.db import SessionLocal
        from shared.models import WebOrder
        from web.app.services.order_service import recalculate_order_payouts

        db = SessionLocal()

        try:
            order = None

            if web_order_id:
                try:
                    order = db.get(WebOrder, int(web_order_id))
                except Exception:
                    order = None

            if order is None and order_no:
                order = (
                    db.query(WebOrder)
                    .filter(WebOrder.bot_order_no == str(order_no))
                    .first()
                )

            if order is None:
                print(f"[rewards] web payout skipped: order not found order_no={order_no} web_order_id={web_order_id}")
                return

            order.status = "closed"
            recalculate_order_payouts(db, order.id)
            db.commit()

            print(f"[rewards] web payout recalculated WEB-{order.id} order_no={order.bot_order_no}")

        finally:
            db.close()

    except Exception as exc:
        print(f"[rewards] web payout recalculate failed: {exc}")


def get_member_level_benefits_text(level_name: str) -> str:
    return VIP_LEVEL_BENEFITS.get(str(level_name or "普通魔丸"), "尚未設定此等級福利。")


# ========= end VIP display / reward exclusions =========



def configure_reward_database(db_file: str | Path | None) -> None:
    """設定會員服務需要查詢的 SQLite 資料庫。"""
    global _REWARD_DB_FILE
    _REWARD_DB_FILE = Path(db_file) if db_file is not None else None

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


def iter_customer_reward_items():
    """Return a snapshot of customer reward data items for reports/cogs."""
    return list(_CUSTOMER_REWARDS.items())

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
    embed.add_field(
        name="目前福利",
        value=get_member_level_benefits_text(str(level.get("name") or "普通魔丸")),
        inline=False,
    )

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

    if level_threshold >= 2000:
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

    # 白金以上不再自動建立 VIP 專屬文字頻道。
    # 文字頻道若要建立，改由客服手動處理。

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

    item_name = str(order_data.get("item") or "").strip()
    if item_name in NO_VIP_REWARD_ITEMS:
        order_data["reward_counted"] = True
        order_data["reward_excluded"] = True
        order_data["reward_excluded_reason"] = "此項目不累積 VIP 點數"
        order_data["reward_counted_at"] = get_taipei_now_iso()
        _ORDER_SELECTIONS[order_channel_id] = order_data

        if _SAVE_BOT_DATA is not None:
            _SAVE_BOT_DATA()

        return f"會員消費未累積：{item_name} 不累積 VIP 點數。"

    amount = parse_receipt_amount(amount_text)
    if amount is None or amount <= 0:
        return "會員消費未累積：收據金額欄位沒有可辨識的數字。"

    item = str(order_data.get("item") or "").strip()
    if item in VIP_PROGRESS_EXCLUDED_ITEMS:
        order_data["reward_counted"] = True
        order_data["reward_excluded"] = True
        order_data["reward_excluded_reason"] = f"{item} 不累積 VIP 進度"
        order_data["reward_amount"] = 0
        order_data["reward_counted_at"] = get_taipei_now_iso()
        _ORDER_SELECTIONS[order_channel_id] = order_data

        if _SAVE_BOT_DATA is not None:
            _SAVE_BOT_DATA()

        return f"會員消費未累積：{item} 不累積 VIP 進度。"

    data = get_customer_reward_data(customer_id)
    old_total_spent = int(data.get("total_spent", 0) or 0)
    old_level = get_effective_member_level(data)
    data["total_spent"] = old_total_spent + amount
    data["order_count"] = int(data.get("order_count", 0) or 0) + 1

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

def parse_manual_purchase_date(date_text: str) -> tuple[str, str] | tuple[None, None]:
    """支援 20260512、2026/05/12、2026-05-12，回傳 ISO 與顯示文字。"""
    text = date_text.strip()

    for fmt in ("%Y%m%d", "%Y/%m/%d", "%Y-%m-%d"):
        try:
            dt = datetime.strptime(text, fmt)
            taipei_tz = timezone(timedelta(hours=8))
            dt = dt.replace(tzinfo=taipei_tz)
            return dt.isoformat(timespec="seconds"), dt.strftime("%Y/%m/%d")
        except ValueError:
            pass

    return None, None


def build_manual_purchase_key(customer_id: int, amount: int, date_iso: str, note: str | None = None) -> str:
    clean_note = (note or "").strip()
    return f"manual:{customer_id}:{amount}:{date_iso}:{clean_note}"


async def add_manual_purchase(
    guild: discord.Guild,
    customer_id: int,
    amount: int,
    date_text: str,
    operator_id: int,
    note: str | None = None,
) -> tuple[bool, str]:
    if amount <= 0:
        return False, "金額必須大於 0。"

    date_iso, display_date = parse_manual_purchase_date(date_text)
    if date_iso is None or display_date is None:
        return False, "日期格式錯誤，請用 20260512、2026/05/12 或 2026-05-12。"

    data = get_customer_reward_data(customer_id)
    old_level = get_effective_member_level(data)
    manual_keys = data.setdefault("manual_purchase_keys", [])
    purchase_key = build_manual_purchase_key(customer_id, amount, date_iso, note)

    if purchase_key in manual_keys:
        return False, f"已跳過重複補登：<@{customer_id}> {format_t_amount(amount)} {display_date}。"

    data["total_spent"] = int(data.get("total_spent", 0) or 0) + amount
    data["order_count"] = int(data.get("order_count", 0) or 0) + 1
    data["points"] = get_current_reward_points(data)

    old_last = data.get("last_order_at")
    if not old_last or str(date_iso) > str(old_last):
        data["last_order_at"] = date_iso

    manual_keys.append(purchase_key)
    data["last_manual_added_at"] = get_taipei_now_iso()
    data["last_manual_added_by"] = operator_id
    sync_vip_level_to_cumulative_if_higher(data)
    _CUSTOMER_REWARDS[customer_id] = data

    # 補登也寫入 orders，讓 /stats_today、/stats_month、VIP 維持消費都查得到。
    # 使用 deterministic negative channel_id，避免重複補登與 Discord 真實頻道 ID 撞到。
    manual_hash = int(hashlib.sha1(purchase_key.encode("utf-8")).hexdigest()[:14], 16)
    manual_channel_id = -manual_hash
    _ORDER_SELECTIONS[manual_channel_id] = {
        "customer_id": customer_id,
        "order_no": f"MANUAL{date_iso[:10].replace('-', '')}{str(customer_id)[-4:]}",
        "category": "manual_purchase",
        "item": (note or "手動補登"),
        "quantity": 1,
        "payment_method": "補登",
        "amount": amount,
        "total_amount": amount,
        "status": "closed",
        "closed": True,
        "created_at": date_iso,
        "closed_at": date_iso,
        "note": note or "手動補登",
        "reward_counted": True,
        "reward_amount": amount,
        "reward_counted_at": date_iso,
    }

    member = await fetch_member_safely(guild, customer_id)
    benefit_notices = await ensure_reward_member_benefits(guild, member, data)

    if _SAVE_BOT_DATA is not None:
        _SAVE_BOT_DATA()

    level = get_effective_member_level(data)
    if level["threshold"] > old_level["threshold"]:
        benefit_notices.insert(0, f"恭喜 <@{customer_id}> 升級為 **{level['name']}**！目前累積消費：{format_t_amount(int(data['total_spent']))}")

    msg = (
        f"已補登 <@{customer_id}>：+{format_t_amount(amount)}，日期 {display_date}。"
        f"目前累積 {format_t_amount(int(data['total_spent']))}，"
        f"完成訂單 {int(data['order_count'])} 單，等級：{level['name']}。"
    )
    if benefit_notices:
        msg += "\n" + "\n".join(f"- {notice}" for notice in benefit_notices)
    return True, msg

async def adjust_customer_points(
    customer_id: int,
    delta_points: int,
    operator_id: int,
    reason: str | None = None,
) -> tuple[bool, str]:
    if delta_points == 0:
        return False, "調整點數不能是 0。"

    data = get_customer_reward_data(customer_id)
    before_points = get_current_reward_points(data)

    if before_points + delta_points < 0:
        return False, f"扣點失敗：<@{customer_id}> 目前只有 {before_points:,} 點，不足扣除 {abs(delta_points):,} 點。"

    data["point_adjustment"] = int(data.get("point_adjustment", 0) or 0) + delta_points
    after_points = get_current_reward_points(data)
    data["points"] = after_points

    logs = data.setdefault("point_adjustment_logs", [])
    logs.append({
        "delta": delta_points,
        "before": before_points,
        "after": after_points,
        "operator_id": operator_id,
        "reason": (reason or "").strip(),
        "created_at": get_taipei_now_iso(),
    })
    # 避免 JSON 檔越來越肥，先保留最近 100 筆點數調整紀錄。
    if len(logs) > 100:
        data["point_adjustment_logs"] = logs[-100:]

    _CUSTOMER_REWARDS[customer_id] = data
    if _SAVE_BOT_DATA is not None:
        _SAVE_BOT_DATA()

    action = "增加" if delta_points > 0 else "扣除"
    reason_text = f"，原因：{reason}" if reason else ""
    return True, (
        f"已為 <@{customer_id}> {action} {abs(delta_points):,} 點{reason_text}。\n"
        f"調整前：{before_points:,} 點\n"
        f"調整後：{after_points:,} 點"
    )


def _normalize_reward_datetime_text(value: str | None) -> str | None:
    if not value:
        return None

    text = str(value).strip()

    if not text:
        return None

    # SQLite datetime('now') 會產生空白格式；ISO 格式則含 T。
    text = text.replace(" ", "T", 1) if " " in text and "T" not in text else text

    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return str(value)

    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone(timedelta(hours=8)))

    return dt.isoformat(timespec="seconds")


def get_previous_calendar_month_range(now: datetime | None = None) -> tuple[datetime, datetime, str]:
    """取得上一個完整月份區間，以及本次檢查月份 key。"""
    now = now or get_taipei_now()
    first_this_month = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    last_prev_month = first_this_month - timedelta(seconds=1)
    first_prev_month = last_prev_month.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    month_key = first_this_month.strftime("%Y-%m")
    return first_prev_month, first_this_month, month_key


def get_customer_closed_spend_between(customer_id: int, start_dt: datetime, end_dt: datetime) -> int:
    """直接從 SQLite orders 查會員維持消費，避免只看 Bot 記憶體漏算補登資料。"""
    init_database()

    db_file = _REWARD_DB_FILE or Path("bot.db")
    start_text = start_dt.isoformat(timespec="seconds")
    end_text = end_dt.isoformat(timespec="seconds")

    try:
        with sqlite3.connect(db_file) as conn:
            conn.row_factory = sqlite3.Row
            cur = conn.cursor()
            cols = _db_columns(cur, "orders")

            if {"customer_id", "amount", "status", "closed_at"}.issubset(cols):
                row = cur.execute(
                    """
                    SELECT COALESCE(SUM(amount), 0) AS total
                    FROM orders
                    WHERE customer_id=?
                      AND status='closed'
                      AND closed_at >= ?
                      AND closed_at < ?
                    """,
                    (int(customer_id), start_text, end_text),
                ).fetchone()
                return int(row["total"] or 0)

            # 舊 data 欄位資料庫 fallback。
            total = 0
            if "data" in cols:
                for row in cur.execute("SELECT data FROM orders").fetchall():
                    data = _json_load_maybe(row["data"], {})
                    if not isinstance(data, dict):
                        continue
                    if _to_int(data.get("customer_id")) != int(customer_id):
                        continue
                    if str(data.get("status", "")).lower() != "closed" and not data.get("closed"):
                        continue
                    closed_text = _normalize_reward_datetime_text(
                        data.get("closed_at") or data.get("reward_counted_at")
                    )
                    if closed_text is None or not (start_text <= closed_text < end_text):
                        continue
                    total += _to_int(data.get("amount") or data.get("reward_amount"), 0) or 0
            return total
    except sqlite3.Error as e:
        print(f"查詢會員維持消費失敗：{e}")
        return 0



async def run_vip_downgrade_check(
    guild: discord.Guild | None,
    *,
    force: bool = False,
    maintain_min_monthly_spend: int = 500,
    first_check_month: str = "2026-06",
    send_log_func: Callable[..., Any] | None = None,
) -> tuple[int, list[str]]:
    """檢查並執行 VIP 自動降階。

    這個函式保留原本邏輯，只把主流程搬到 rewards service：
    - 低於第一個檢查月份時不處理。
    - 每位會員每個檢查月份只檢查一次，除非 force=True。
    - 未達月消費門檻時降一階，並重置下一級進度基準。
    - 套用會員福利並保存資料。
    """
    if guild is None:
        return 0, ["找不到伺服器，無法檢查 VIP 降階。"]

    start_dt, end_dt, check_month_key = get_previous_calendar_month_range()

    if check_month_key < first_check_month:
        return 0, [
            f"VIP 降階尚未啟用。第一次檢查月份為 {first_check_month}，"
            f"本次 {check_month_key} 不檢查，避免 2026/04 未營運資料造成誤降階。"
        ]

    changed_count = 0
    messages: list[str] = []

    for user_id, data in list(_CUSTOMER_REWARDS.items()):
        if not isinstance(data, dict):
            continue

        current_index = get_effective_member_level_index(data)
        if current_index <= 0:
            data["vip_last_downgrade_check_month"] = check_month_key
            _CUSTOMER_REWARDS[user_id] = data
            continue

        if not force and data.get("vip_last_downgrade_check_month") == check_month_key:
            continue

        monthly_spend = get_customer_closed_spend_between(int(user_id), start_dt, end_dt)
        data["vip_last_downgrade_check_month"] = check_month_key

        if monthly_spend >= int(maintain_min_monthly_spend or 0):
            _CUSTOMER_REWARDS[user_id] = data
            continue

        old_level = get_member_level_by_index(current_index)
        new_index = max(0, current_index - 1)
        new_level = get_member_level_by_index(new_index)
        data["vip_level_index"] = new_index
        data["vip_progress_base_total_spent"] = int(data.get("total_spent", 0) or 0)

        log = {
            "checked_month": check_month_key,
            "previous_month_start": start_dt.isoformat(timespec="seconds"),
            "previous_month_end": end_dt.isoformat(timespec="seconds"),
            "previous_month_spend": monthly_spend,
            "required_spend": int(maintain_min_monthly_spend or 0),
            "old_level": old_level["name"],
            "new_level": new_level["name"],
            "progress_reset_total_spent": data["vip_progress_base_total_spent"],
            "created_at": get_taipei_now_iso(),
        }
        logs = data.setdefault("vip_downgrade_logs", [])
        if isinstance(logs, list):
            logs.append(log)
            data["vip_downgrade_logs"] = logs[-24:]
        else:
            data["vip_downgrade_logs"] = [log]

        member = await fetch_member_safely(guild, int(user_id))
        benefit_notices = await ensure_reward_member_benefits(guild, member, data)
        _CUSTOMER_REWARDS[user_id] = data
        changed_count += 1

        message = (
            f"<@{user_id}>：{old_level['name']} → {new_level['name']}｜"
            f"上月消費 {format_t_amount(monthly_spend)}，未達 {format_t_amount(int(maintain_min_monthly_spend or 0))}"
        )
        if benefit_notices:
            message += "｜" + "、".join(benefit_notices)
        messages.append(message)

    if _SAVE_BOT_DATA is not None:
        _SAVE_BOT_DATA()

    if changed_count and send_log_func is not None:
        await send_log_func(
            guild,
            title="VIP 會員自動降階",
            description=(
                f"檢查月份：{check_month_key}\n"
                f"統計區間：{start_dt.strftime('%Y/%m/%d')} ～ {end_dt.strftime('%Y/%m/%d')}\n"
                f"維持條件：上月消費滿 {format_t_amount(int(maintain_min_monthly_spend or 0))}\n\n"
                + "\n".join(messages[:20])
            ),
            color=discord.Color.orange(),
        )

    return changed_count, messages
