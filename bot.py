import os
from dotenv import load_dotenv

load_dotenv()
import os
import json
import re
import random
import shutil
import sqlite3
import io
import asyncio
from datetime import datetime, timezone, timedelta
from pathlib import Path

from core.time_utils import (
    get_taipei_now,
    get_taipei_now_iso,
    get_taipei_now_text,
    parse_datetime_safe,
    _parse_datetime_safe,
)

from core.config import (
    _config_int,
    _config_int_list,
    _config_str,
    _config_str_list,
)

from core.database import (
    configure_database,
    init_database,
    configure_data_access,
    _db_table_exists,
    _db_columns,
    _db_add_column_if_missing,
    _json_load_maybe,
    _json_default,
    _serialize_orders,
    _serialize_claims,
    _serialize_customer_rewards,
    _serialize_order_counters,
    _deserialize_claim_data,
    _deserialize_customer_data,
    load_bot_data_from_json,
    load_bot_data_from_sqlite,
    load_bot_data,
    save_bot_data,
    delete_order_row_from_db,
    delete_claim_row_from_db,
    remember_order_data,
    remember_claim_data,
    run_daily_backup_once,
    generate_order_receipt_id,
)

from services.rewards import (
    configure_rewards,
    configure_reward_storage,
    configure_reward_order_context,
    configure_reward_benefits,
    get_member_level,
    get_next_member_level,
    get_member_level_index_by_total_spent,
    get_member_level_by_index,
    get_effective_member_level_index,
    get_effective_member_level,
    get_next_member_level_for_data,
    sync_vip_level_to_cumulative_if_higher,
    format_t_amount,
    calculate_reward_points,
    get_current_reward_points,
    get_customer_reward_data,
    build_member_info_embed,
    get_customer_notes,
    format_customer_notes_for_staff,
    format_customer_notes_for_ticket,
    fetch_member_safely,
    ensure_reward_member_benefits,
    parse_receipt_amount,
    parse_manual_purchase_date,
    add_customer_reward_from_order,
    add_manual_purchase,
    adjust_customer_points,
    configure_reward_database,
    get_previous_calendar_month_range,
    get_customer_closed_spend_between,
)

from services.orders import (
    _to_int,
    ORDER_CATEGORY_LABELS,
    ORDER_ITEMS_BY_CATEGORY,
    ORDER_ITEM_TO_CATEGORY,
    SPECIAL_COMPANION_ITEMS,
    QUANTITY_SELECT_ITEMS,
    QUANTITY_OPTIONS,
)

import discord
from discord.ext import commands
from discord import app_commands
from dotenv import load_dotenv

from core.permissions import (
    configure_permissions,
    has_role,
    is_customer_staff,
    is_exam_staff,
    is_complaint_staff,
    is_manager_or_admin,
    can_operate_self_service_order,
)


# ========= 讀取 .env =========

env_path = Path(__file__).parent / ".env"
load_dotenv(dotenv_path=env_path)

TOKEN = os.getenv("DISCORD_TOKEN")

if TOKEN is None:
    raise RuntimeError("讀不到 DISCORD_TOKEN，請確認 .env 檔案在 bot.py 同一個資料夾")


# ========= 固定 ID =========

GUILD_ID = 1129474191226306672

# 類別 ID
CUSTOMER_CATEGORY_ID = 1483895536938651809
EXAM_CATEGORY_ID = 1483873316702781471
PLAY_VOICE_CATEGORY_ID = 1482016208638447699

# 陪玩語音入口頻道名稱
PLAY_VOICE_CREATE_CHANNEL_NAME = "➕┃點我創建陪玩頻道"
OLD_PLAY_VOICE_CREATE_CHANNEL_NAMES = ["🎮┃陪玩點我創建頻道"]

# VIP 語音入口頻道名稱
VIP_VOICE_CREATE_CHANNEL_NAME = "➕┃點我創建VIP頻道"
OLD_VIP_VOICE_CREATE_CHANNEL_NAMES = ["👑┃𝙑𝙄𝙋專用點我創建頻道"]

# 公共語音入口頻道名稱
PUBLIC_VOICE_CREATE_CHANNEL_NAME = "➕┃點我創建公共頻道"

# VIP 語音入口可見 / 可進入身分組 ID
VIP_VOICE_LOBBY_ROLE_ID = 1482080566760177706

# 身分組 ID
CUSTOMER_ROLE_ID = 1482084782031638548
EXAMINER_ROLE_ID = 1497427024644411543
MANAGER_ROLE_ID = 1131128849443328030
RECRUIT_APPLICANT_ROLE_ID = 1498829171042943057  # 入職票口開啟期間身分組

# 會員制度 ID / 設定
SILVER_MEMBER_ROLE_ID = 1482080566760177706
PLATINUM_PRIVATE_CATEGORY_ID = 1483871504419520654
PLATINUM_CHAT_ROLE_IDS = [
    1503706721883783218,
    1503701170504339458,
]
REWARD_POINT_DIVISOR = 100
MEMBER_LEVELS = [
    {"name": "普通魔丸", "threshold": 0},
    {"name": "銀級魔丸", "threshold": 2500},
    {"name": "金級魔丸", "threshold": 7000},
    {"name": "白金魔丸", "threshold": 13000},
    {"name": "鑽石魔丸", "threshold": 30000},
    {"name": "頂級魔丸", "threshold": 77777},
]

# 訂單日誌 / 備份設定
ORDER_LOG_CATEGORY_ID = 1483895536938651809
ORDER_LOG_CHANNEL_NAME = "🤖┃機器人日誌"
LOTTERY_ANNOUNCE_CHANNEL_ID = 1482079302739693739
BACKUP_KEEP_DAYS = 30
ORDER_ID_PREFIX = "MO"

# 接單身分組 ID
COMPANION_RECEIVER_ROLE_ID = 1503706721883783218  # 陪玩接單
BOOSTER_RECEIVER_ROLE_ID = 1503701170504339458    # 打手接單

# 收據頻道 ID
RECEIPT_CHANNEL_ID = 1497623878619627682

# 考核通知頻道 ID
EXAM_NOTICE_CHANNEL_ID = 1482083066531942563

# 客訴面板頻道 ID
COMPLAINT_PANEL_CHANNEL_ID = 1497653883948765344

# 顧客意見箱面板頻道 ID
FEEDBACK_PANEL_CHANNEL_ID = 1504345505633927178

# 客訴送出頻道 ID
COMPLAINT_RECEIVE_CHANNEL_ID = 1502040302649872394

# 派單頻道 ID
DISPATCH_CHANNEL_ID = 1483868763446186036

# 評價頻道 ID
REVIEW_CHANNEL_ID = 1482998033091268691

# 歡迎頻道 ID
WELCOME_CHANNEL_ID = 1482080953353375752

# 新成員自動給予身分組 ID
NEW_MEMBER_ROLE_ID = 1483872591457550494

# 陪玩語音入口 / 陪玩語音房可見與可進入身分組 ID
# 目前只開放：陪玩接單、打手接單、客服
PLAY_VOICE_ALLOWED_ROLE_IDS = [
    1503706721883783218,
    1503701170504339458,
    1482084782031638548,
]

# 語音房按「隱藏」後，仍可看見房間的身分組 ID
VOICE_ROOM_HIDDEN_VISIBLE_ROLE_IDS = [
    1503706721883783218,
    1503701170504339458,
    1482084782031638548,
]

# 暫存由機器人建立的陪玩語音房 ID
TEMP_PLAY_VOICE_CHANNEL_IDS = set()

# 暫存由機器人建立的 VIP 語音房 ID
TEMP_VIP_VOICE_CHANNEL_IDS = set()

# 暫存由機器人建立的公共語音房 ID
TEMP_PUBLIC_VOICE_CHANNEL_IDS = set()

# 暫存語音房控制面板資料
# voice_channel_id -> {owner_id, panel_channel_id, room_type, locked, hidden}
TEMP_VOICE_CONTROL_PANELS = {}


# ========= 外部設定檔覆蓋 =========
# config.json 讀取邏輯已搬到 core/config.py。
# 這裡只保留「把設定套用到預設值」的區塊，降低 bot.py 負擔。


# 伺服器 / 類別
GUILD_ID = _config_int("GUILD_ID", GUILD_ID)
CUSTOMER_CATEGORY_ID = _config_int("CUSTOMER_CATEGORY_ID", CUSTOMER_CATEGORY_ID)
EXAM_CATEGORY_ID = _config_int("EXAM_CATEGORY_ID", EXAM_CATEGORY_ID)
PLAY_VOICE_CATEGORY_ID = _config_int("PLAY_VOICE_CATEGORY_ID", PLAY_VOICE_CATEGORY_ID)
PLATINUM_PRIVATE_CATEGORY_ID = _config_int("PLATINUM_PRIVATE_CATEGORY_ID", PLATINUM_PRIVATE_CATEGORY_ID)
ORDER_LOG_CATEGORY_ID = _config_int("ORDER_LOG_CATEGORY_ID", ORDER_LOG_CATEGORY_ID)

# 頻道
LOTTERY_ANNOUNCE_CHANNEL_ID = _config_int("LOTTERY_ANNOUNCE_CHANNEL_ID", LOTTERY_ANNOUNCE_CHANNEL_ID)
RECEIPT_CHANNEL_ID = _config_int("RECEIPT_CHANNEL_ID", RECEIPT_CHANNEL_ID)
EXAM_NOTICE_CHANNEL_ID = _config_int("EXAM_NOTICE_CHANNEL_ID", EXAM_NOTICE_CHANNEL_ID)
COMPLAINT_PANEL_CHANNEL_ID = _config_int("COMPLAINT_PANEL_CHANNEL_ID", COMPLAINT_PANEL_CHANNEL_ID)
FEEDBACK_PANEL_CHANNEL_ID = _config_int("FEEDBACK_PANEL_CHANNEL_ID", FEEDBACK_PANEL_CHANNEL_ID)
COMPLAINT_RECEIVE_CHANNEL_ID = _config_int("COMPLAINT_RECEIVE_CHANNEL_ID", COMPLAINT_RECEIVE_CHANNEL_ID)
DISPATCH_CHANNEL_ID = _config_int("DISPATCH_CHANNEL_ID", DISPATCH_CHANNEL_ID)
REVIEW_CHANNEL_ID = _config_int("REVIEW_CHANNEL_ID", REVIEW_CHANNEL_ID)
WELCOME_CHANNEL_ID = _config_int("WELCOME_CHANNEL_ID", WELCOME_CHANNEL_ID)

# 身分組
VIP_VOICE_LOBBY_ROLE_ID = _config_int("VIP_VOICE_LOBBY_ROLE_ID", VIP_VOICE_LOBBY_ROLE_ID)
CUSTOMER_ROLE_ID = _config_int("CUSTOMER_ROLE_ID", CUSTOMER_ROLE_ID)
EXAMINER_ROLE_ID = _config_int("EXAMINER_ROLE_ID", EXAMINER_ROLE_ID)
MANAGER_ROLE_ID = _config_int("MANAGER_ROLE_ID", MANAGER_ROLE_ID)
RECRUIT_APPLICANT_ROLE_ID = _config_int("RECRUIT_APPLICANT_ROLE_ID", RECRUIT_APPLICANT_ROLE_ID)
SILVER_MEMBER_ROLE_ID = _config_int("SILVER_MEMBER_ROLE_ID", SILVER_MEMBER_ROLE_ID)
COMPANION_RECEIVER_ROLE_ID = _config_int("COMPANION_RECEIVER_ROLE_ID", COMPANION_RECEIVER_ROLE_ID)
BOOSTER_RECEIVER_ROLE_ID = _config_int("BOOSTER_RECEIVER_ROLE_ID", BOOSTER_RECEIVER_ROLE_ID)
NEW_MEMBER_ROLE_ID = _config_int("NEW_MEMBER_ROLE_ID", NEW_MEMBER_ROLE_ID)
PLATINUM_CHAT_ROLE_IDS = _config_int_list("PLATINUM_CHAT_ROLE_IDS", PLATINUM_CHAT_ROLE_IDS)
PLAY_VOICE_ALLOWED_ROLE_IDS = _config_int_list("PLAY_VOICE_ALLOWED_ROLE_IDS", PLAY_VOICE_ALLOWED_ROLE_IDS)
VOICE_ROOM_HIDDEN_VISIBLE_ROLE_IDS = _config_int_list("VOICE_ROOM_HIDDEN_VISIBLE_ROLE_IDS", VOICE_ROOM_HIDDEN_VISIBLE_ROLE_IDS)

# 名稱 / 其他設定
PLAY_VOICE_CREATE_CHANNEL_NAME = _config_str("PLAY_VOICE_CREATE_CHANNEL_NAME", PLAY_VOICE_CREATE_CHANNEL_NAME)
OLD_PLAY_VOICE_CREATE_CHANNEL_NAMES = _config_str_list("OLD_PLAY_VOICE_CREATE_CHANNEL_NAMES", OLD_PLAY_VOICE_CREATE_CHANNEL_NAMES)
VIP_VOICE_CREATE_CHANNEL_NAME = _config_str("VIP_VOICE_CREATE_CHANNEL_NAME", VIP_VOICE_CREATE_CHANNEL_NAME)
OLD_VIP_VOICE_CREATE_CHANNEL_NAMES = _config_str_list("OLD_VIP_VOICE_CREATE_CHANNEL_NAMES", OLD_VIP_VOICE_CREATE_CHANNEL_NAMES)
PUBLIC_VOICE_CREATE_CHANNEL_NAME = _config_str("PUBLIC_VOICE_CREATE_CHANNEL_NAME", PUBLIC_VOICE_CREATE_CHANNEL_NAME)
ORDER_LOG_CHANNEL_NAME = _config_str("ORDER_LOG_CHANNEL_NAME", ORDER_LOG_CHANNEL_NAME)
ORDER_ID_PREFIX = _config_str("ORDER_ID_PREFIX", ORDER_ID_PREFIX)
BACKUP_KEEP_DAYS = _config_int("BACKUP_KEEP_DAYS", BACKUP_KEEP_DAYS)
REWARD_POINT_DIVISOR = _config_int("REWARD_POINT_DIVISOR", REWARD_POINT_DIVISOR)

configure_rewards(
    member_levels=MEMBER_LEVELS,
    reward_point_divisor=REWARD_POINT_DIVISOR,
)

configure_reward_benefits(
    silver_member_role_id=SILVER_MEMBER_ROLE_ID,
    platinum_private_category_id=PLATINUM_PRIVATE_CATEGORY_ID,
    platinum_chat_role_ids=PLATINUM_CHAT_ROLE_IDS,
)

configure_permissions(
    customer_role_id=CUSTOMER_ROLE_ID,
    examiner_role_id=EXAMINER_ROLE_ID,
    manager_role_id=MANAGER_ROLE_ID,
)


# ========= Bot 設定 =========

intents = discord.Intents.default()
intents.guilds = True
intents.members = True
intents.voice_states = True
intents.message_content = True

bot = commands.Bot(command_prefix="!", intents=intents)


# ========= 工具函式 =========

def safe_channel_name(prefix: str, member: discord.Member) -> str:
    name = member.name.lower()
    clean = "".join(c if c.isalnum() else "-" for c in name)
    return f"{prefix}-{clean}-{member.id}"[:90]


def is_agree_answer(text: str) -> bool:
    answer = text.strip().lower()

    agree_words = {
        "是",
        "有",
        "已詳閱",
        "已詳讀",
        "已閱讀",
        "我已詳閱",
        "我已詳讀",
        "我已閱讀",
        "同意",
        "yes",
        "y",
        "ok",
        "okay",
    }

    return answer in agree_words



def get_recruit_info_from_channel(channel: discord.TextChannel) -> tuple[str, str]:
    if not channel.topic:
        return "未紀錄暱稱", "未紀錄職位"

    data = {}

    for part in channel.topic.split(";"):
        if "=" in part:
            key, value = part.split("=", 1)
            data[key.strip()] = value.strip()

    nickname = data.get("recruit_nickname", "未紀錄暱稱")
    position = data.get("recruit_position", "未紀錄職位")

    return nickname, position


def get_recruit_member_id_from_channel(channel: discord.TextChannel) -> int | None:
    """從入職票口 topic 讀取申請人 ID。"""
    if not channel.topic:
        return None

    data = {}

    for part in channel.topic.split(";"):
        if "=" in part:
            key, value = part.split("=", 1)
            data[key.strip()] = value.strip()

    recruit_member_id = data.get("recruit_member_id")

    if recruit_member_id is None:
        return None

    try:
        return int(recruit_member_id)
    except ValueError:
        return None


async def remove_recruit_applicant_role(guild: discord.Guild | None, channel: discord.abc.GuildChannel | None):
    """入職票口關閉時收回申請人暫時身分組。"""
    if guild is None or not isinstance(channel, discord.TextChannel):
        return

    recruit_member_id = get_recruit_member_id_from_channel(channel)

    if recruit_member_id is None:
        return

    member = guild.get_member(recruit_member_id)
    role = guild.get_role(RECRUIT_APPLICANT_ROLE_ID)

    if member is None or role is None:
        return

    if role not in member.roles:
        return

    try:
        await member.remove_roles(role, reason="Recruit ticket closed")
    except discord.Forbidden:
        print("Bot 權限不足，無法收回入職申請暫時身分組。請確認 Bot 身分組位置高於該身分組。")
    except discord.HTTPException as e:
        print(f"收回入職申請暫時身分組失敗：{e}")


def get_order_customer_id_from_channel(channel: discord.TextChannel) -> int | None:
    """
    優先從頻道 topic 讀取點單顧客 ID。
    若是舊票口沒有 topic，會嘗試從頻道名稱最後一段讀取 ID。
    頻道名稱格式通常會是：下單-名字-使用者ID
    """
    if channel.topic:
        data = {}

        for part in channel.topic.split(";"):
            if "=" in part:
                key, value = part.split("=", 1)
                data[key.strip()] = value.strip()

        customer_id = data.get("order_customer_id")

        if customer_id is not None:
            try:
                return int(customer_id)
            except ValueError:
                pass

    try:
        possible_id = channel.name.rsplit("-", 1)[-1]
        return int(possible_id)
    except ValueError:
        return None


def rating_to_stars(rating_text: str) -> tuple[int | None, str | None]:
    try:
        rating = int(rating_text.strip())
    except ValueError:
        return None, None

    if rating < 1 or rating > 5:
        return None, None

    stars = "⭐" * rating
    return rating, stars


def is_anonymous_answer(text: str) -> bool:
    answer = text.strip().lower()
    return answer in {"是", "匿名", "要", "yes", "y", "true", "1"}


def is_review_media_attachment(attachment: discord.Attachment) -> bool:
    if attachment.content_type:
        return (
            attachment.content_type.startswith("image/")
            or attachment.content_type.startswith("video/")
        )

    media_exts = (
        ".png", ".jpg", ".jpeg", ".gif", ".webp",
        ".mp4", ".mov", ".webm", ".mkv", ".avi", ".m4v"
    )
    return attachment.filename.lower().endswith(media_exts)


def chunk_list(items: list, size: int):
    for i in range(0, len(items), size):
        yield items[i:i + size]


def safe_voice_channel_name(member: discord.Member) -> str:
    display_name = member.display_name.strip() or member.name
    # Discord 語音頻道名稱最多 100 字，這裡留一點安全長度
    return f"🎮┃{display_name}的陪玩頻道"[:95]


def safe_vip_voice_channel_name(member: discord.Member) -> str:
    display_name = member.display_name.strip() or member.name
    # Discord 語音頻道名稱最多 100 字，這裡留一點安全長度
    return f"👑┃{display_name}的𝙑𝙄𝙋頻道"[:95]


def safe_public_voice_channel_name(member: discord.Member) -> str:
    display_name = member.display_name.strip() or member.name
    # Discord 語音頻道名稱最多 100 字，這裡留一點安全長度
    return f"➕┃{display_name}的公共房間"[:95]


def get_play_voice_allowed_roles(guild: discord.Guild) -> list[discord.Role]:
    return [
        role
        for role_id in PLAY_VOICE_ALLOWED_ROLE_IDS
        if (role := guild.get_role(role_id)) is not None
    ]


def get_voice_room_hidden_visible_roles(guild: discord.Guild) -> list[discord.Role]:
    return [
        role
        for role_id in VOICE_ROOM_HIDDEN_VISIBLE_ROLE_IDS
        if (role := guild.get_role(role_id)) is not None
    ]


def build_play_voice_overwrites(guild: discord.Guild) -> dict:
    overwrites = {
        guild.default_role: discord.PermissionOverwrite(
            view_channel=False,
            connect=False
        ),
        guild.me: discord.PermissionOverwrite(
            view_channel=True,
            connect=True,
            speak=True,
            move_members=True,
            manage_channels=True
        ),
    }

    for role in get_play_voice_allowed_roles(guild):
        overwrites[role] = discord.PermissionOverwrite(
            view_channel=True,
            connect=True,
            speak=True,
            stream=True,
            use_voice_activation=True
        )

    return overwrites


def build_vip_lobby_overwrites(guild: discord.Guild) -> dict:
    vip_role = guild.get_role(VIP_VOICE_LOBBY_ROLE_ID)

    overwrites = {
        guild.default_role: discord.PermissionOverwrite(
            view_channel=False,
            connect=False
        ),
        guild.me: discord.PermissionOverwrite(
            view_channel=True,
            connect=True,
            speak=True,
            move_members=True,
            manage_channels=True
        ),
    }

    if vip_role is not None:
        overwrites[vip_role] = discord.PermissionOverwrite(
            view_channel=True,
            connect=True,
            speak=True,
            stream=True,
            use_voice_activation=True
        )

    return overwrites


def build_vip_room_overwrites(guild: discord.Guild, member: discord.Member) -> dict:
    overwrites = {
        guild.default_role: discord.PermissionOverwrite(
            view_channel=False,
            connect=False
        ),
        guild.me: discord.PermissionOverwrite(
            view_channel=True,
            connect=True,
            speak=True,
            move_members=True,
            manage_channels=True
        ),
        member: discord.PermissionOverwrite(
            view_channel=True,
            connect=True,
            speak=True,
            stream=True,
            use_voice_activation=True
        ),
    }

    for role in get_play_voice_allowed_roles(guild):
        overwrites[role] = discord.PermissionOverwrite(
            view_channel=True,
            connect=True,
            speak=True,
            stream=True,
            use_voice_activation=True
        )

    return overwrites


def build_public_voice_overwrites(guild: discord.Guild) -> dict:
    return {
        guild.default_role: discord.PermissionOverwrite(
            view_channel=True,
            connect=True,
            speak=True,
            stream=True,
            use_voice_activation=True
        ),
        guild.me: discord.PermissionOverwrite(
            view_channel=True,
            connect=True,
            speak=True,
            move_members=True,
            manage_channels=True
        ),
    }


async def get_or_create_play_voice_lobby(guild: discord.Guild) -> discord.VoiceChannel | None:
    category = guild.get_channel(PLAY_VOICE_CATEGORY_ID)

    if category is None or not isinstance(category, discord.CategoryChannel):
        print("找不到陪玩語音類別，請確認 PLAY_VOICE_CATEGORY_ID 是否正確。")
        return None

    for channel in category.voice_channels:
        if channel.name == PLAY_VOICE_CREATE_CHANNEL_NAME:
            await channel.edit(overwrites=build_play_voice_overwrites(guild), reason="Update play voice lobby permissions")
            return channel

        if channel.name in OLD_PLAY_VOICE_CREATE_CHANNEL_NAMES:
            await channel.edit(
                name=PLAY_VOICE_CREATE_CHANNEL_NAME,
                overwrites=build_play_voice_overwrites(guild),
                reason="Rename old play voice lobby"
            )
            return channel

    return await guild.create_voice_channel(
        name=PLAY_VOICE_CREATE_CHANNEL_NAME,
        category=category,
        overwrites=build_play_voice_overwrites(guild),
        reason="Create play voice lobby"
    )


async def get_or_create_vip_voice_lobby(guild: discord.Guild) -> discord.VoiceChannel | None:
    category = guild.get_channel(PLAY_VOICE_CATEGORY_ID)

    if category is None or not isinstance(category, discord.CategoryChannel):
        print("找不到 VIP 語音類別，請確認 PLAY_VOICE_CATEGORY_ID 是否正確。")
        return None

    for channel in category.voice_channels:
        if channel.name == VIP_VOICE_CREATE_CHANNEL_NAME:
            await channel.edit(overwrites=build_vip_lobby_overwrites(guild), reason="Update VIP voice lobby permissions")
            return channel

        if channel.name in OLD_VIP_VOICE_CREATE_CHANNEL_NAMES:
            await channel.edit(
                name=VIP_VOICE_CREATE_CHANNEL_NAME,
                overwrites=build_vip_lobby_overwrites(guild),
                reason="Rename old VIP voice lobby"
            )
            return channel

    return await guild.create_voice_channel(
        name=VIP_VOICE_CREATE_CHANNEL_NAME,
        category=category,
        overwrites=build_vip_lobby_overwrites(guild),
        reason="Create VIP voice lobby"
    )


async def get_or_create_public_voice_lobby(guild: discord.Guild) -> discord.VoiceChannel | None:
    category = guild.get_channel(PLAY_VOICE_CATEGORY_ID)

    if category is None or not isinstance(category, discord.CategoryChannel):
        print("找不到公共語音類別，請確認 PLAY_VOICE_CATEGORY_ID 是否正確。")
        return None

    for channel in category.voice_channels:
        if channel.name == PUBLIC_VOICE_CREATE_CHANNEL_NAME:
            await channel.edit(overwrites=build_public_voice_overwrites(guild), reason="Update public voice lobby permissions")
            return channel

    return await guild.create_voice_channel(
        name=PUBLIC_VOICE_CREATE_CHANNEL_NAME,
        category=category,
        overwrites=build_public_voice_overwrites(guild),
        reason="Create public voice lobby"
    )


def build_creator_voice_overwrite() -> discord.PermissionOverwrite:
    return discord.PermissionOverwrite(
        view_channel=True,
        connect=True,
        speak=True,
        stream=True,
        use_voice_activation=True,
        move_members=True,
    )


def build_voice_control_panel_overwrites(
    guild: discord.Guild,
    member: discord.Member
) -> dict:
    return {
        guild.default_role: discord.PermissionOverwrite(
            view_channel=False,
            send_messages=False,
            read_message_history=False,
        ),
        guild.me: discord.PermissionOverwrite(
            view_channel=True,
            send_messages=True,
            manage_channels=True,
            read_message_history=True,
        ),
        member: discord.PermissionOverwrite(
            view_channel=True,
            send_messages=True,
            read_message_history=True,
        ),
    }


def safe_voice_control_panel_name(member: discord.Member) -> str:
    display_name = member.display_name.strip() or member.name
    clean = "".join(c if c.isalnum() else "-" for c in display_name.lower())
    return f"遙控器-{clean}-{member.id}"[:90]


async def delete_voice_control_panel(guild: discord.Guild, voice_channel_id: int):
    # 控制面板現在直接發在語音房聊天室。
    # 語音房被刪除時，聊天室內容會一起消失，所以這裡只需要清掉暫存資料。
    TEMP_VOICE_CONTROL_PANELS.pop(voice_channel_id, None)


def get_room_targets_for_control(
    guild: discord.Guild,
    room_type: str
) -> list[discord.abc.Snowflake]:
    if room_type == "public":
        return [guild.default_role]

    return get_play_voice_allowed_roles(guild)


async def apply_voice_lock_state(
    voice_channel: discord.VoiceChannel,
    owner: discord.Member,
    room_type: str,
    locked: bool,
):
    overwrites = dict(voice_channel.overwrites)

    for target in get_room_targets_for_control(voice_channel.guild, room_type):
        overwrite = overwrites.get(target, discord.PermissionOverwrite())
        overwrite.connect = not locked
        overwrites[target] = overwrite

    owner_overwrite = overwrites.get(owner, discord.PermissionOverwrite())
    owner_overwrite.view_channel = True
    owner_overwrite.connect = True
    owner_overwrite.speak = True
    owner_overwrite.stream = True
    owner_overwrite.use_voice_activation = True
    overwrites[owner] = owner_overwrite

    bot_member = voice_channel.guild.me
    if bot_member is not None:
        bot_overwrite = overwrites.get(bot_member, discord.PermissionOverwrite())
        bot_overwrite.view_channel = True
        bot_overwrite.connect = True
        bot_overwrite.manage_channels = True
        bot_overwrite.move_members = True
        overwrites[bot_member] = bot_overwrite

    await voice_channel.edit(
        overwrites=overwrites,
        reason="Voice room lock state changed by owner"
    )


async def apply_voice_hidden_state(
    voice_channel: discord.VoiceChannel,
    owner: discord.Member,
    room_type: str,
    hidden: bool,
):
    overwrites = dict(voice_channel.overwrites)
    guild = voice_channel.guild

    # 顯示：讓所有人都看得到。
    # 隱藏：只有創建者、Bot、指定三個身分組可以看得到。
    everyone_overwrite = overwrites.get(guild.default_role, discord.PermissionOverwrite())

    if hidden:
        everyone_overwrite.view_channel = False
        overwrites[guild.default_role] = everyone_overwrite

        for role in get_voice_room_hidden_visible_roles(guild):
            overwrite = overwrites.get(role, discord.PermissionOverwrite())
            overwrite.view_channel = True
            overwrite.connect = True
            overwrite.speak = True
            overwrite.stream = True
            overwrite.use_voice_activation = True
            overwrites[role] = overwrite
    else:
        everyone_overwrite.view_channel = True
        overwrites[guild.default_role] = everyone_overwrite

    owner_overwrite = overwrites.get(owner, discord.PermissionOverwrite())
    owner_overwrite.view_channel = True
    owner_overwrite.connect = True
    owner_overwrite.speak = True
    owner_overwrite.stream = True
    owner_overwrite.use_voice_activation = True
    overwrites[owner] = owner_overwrite

    bot_member = guild.me
    if bot_member is not None:
        bot_overwrite = overwrites.get(bot_member, discord.PermissionOverwrite())
        bot_overwrite.view_channel = True
        bot_overwrite.connect = True
        bot_overwrite.manage_channels = True
        bot_overwrite.move_members = True
        overwrites[bot_member] = bot_overwrite

    await voice_channel.edit(
        overwrites=overwrites,
        reason="Voice room visibility changed by owner"
    )


class VoiceRoomRenameModal(discord.ui.Modal, title="更改語音房名稱"):
    new_name = discord.ui.TextInput(
        label="新的頻道名稱",
        placeholder="請輸入新的語音房名稱",
        required=True,
        max_length=95,
    )

    def __init__(self, voice_channel_id: int, owner_id: int):
        super().__init__()
        self.voice_channel_id = voice_channel_id
        self.owner_id = owner_id

    async def on_submit(self, interaction: discord.Interaction):
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message("只有語音房創建者可以操作遙控器。", ephemeral=True)
            return

        guild = interaction.guild
        if guild is None:
            await interaction.response.send_message("這個功能只能在伺服器內使用。", ephemeral=True)
            return

        voice_channel = guild.get_channel(self.voice_channel_id)
        if not isinstance(voice_channel, discord.VoiceChannel):
            await interaction.response.send_message("找不到對應的語音房。", ephemeral=True)
            return

        try:
            await voice_channel.edit(
                name=self.new_name.value.strip()[:95],
                reason=f"Voice room renamed by {interaction.user}"
            )
        except discord.Forbidden:
            await interaction.response.send_message("Bot 權限不足，無法更改頻道名稱。", ephemeral=True)
            return
        except discord.HTTPException as e:
            await interaction.response.send_message(f"更改名稱失敗：{e}", ephemeral=True)
            return

        await interaction.response.defer()


class VoiceRoomLimitModal(discord.ui.Modal, title="設定語音房人數"):
    user_limit = discord.ui.TextInput(
        label="人數上限",
        placeholder="請輸入 0~99，0 代表不限人數",
        required=True,
        max_length=2,
    )

    def __init__(self, voice_channel_id: int, owner_id: int):
        super().__init__()
        self.voice_channel_id = voice_channel_id
        self.owner_id = owner_id

    async def on_submit(self, interaction: discord.Interaction):
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message("只有語音房創建者可以操作遙控器。", ephemeral=True)
            return

        guild = interaction.guild
        if guild is None:
            await interaction.response.send_message("這個功能只能在伺服器內使用。", ephemeral=True)
            return

        try:
            limit = int(self.user_limit.value.strip())
        except ValueError:
            await interaction.response.send_message("人數上限請輸入 0~99 的數字。", ephemeral=True)
            return

        if limit < 0 or limit > 99:
            await interaction.response.send_message("人數上限請輸入 0~99 的數字。", ephemeral=True)
            return

        voice_channel = guild.get_channel(self.voice_channel_id)
        if not isinstance(voice_channel, discord.VoiceChannel):
            await interaction.response.send_message("找不到對應的語音房。", ephemeral=True)
            return

        try:
            await voice_channel.edit(
                user_limit=limit,
                reason=f"Voice room user limit changed by {interaction.user}"
            )
        except discord.Forbidden:
            await interaction.response.send_message("Bot 權限不足，無法設定人數。", ephemeral=True)
            return
        except discord.HTTPException as e:
            await interaction.response.send_message(f"設定人數失敗：{e}", ephemeral=True)
            return

        await interaction.response.defer()


class VoiceRoomControlView(discord.ui.View):
    def __init__(self, voice_channel_id: int, owner_id: int, room_type: str):
        super().__init__(timeout=None)
        self.voice_channel_id = voice_channel_id
        self.owner_id = owner_id
        self.room_type = room_type

    async def get_voice_channel_and_owner(
        self,
        interaction: discord.Interaction
    ) -> tuple[discord.VoiceChannel | None, discord.Member | None]:
        guild = interaction.guild
        if guild is None:
            return None, None

        voice_channel = guild.get_channel(self.voice_channel_id)
        owner = guild.get_member(self.owner_id)

        if not isinstance(voice_channel, discord.VoiceChannel) or owner is None:
            return None, None

        return voice_channel, owner

    async def reject_if_not_owner(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message("只有語音房創建者可以操作遙控器。", ephemeral=True)
            return True
        return False

    @discord.ui.button(
        label="🔒 鎖定/解鎖",
        style=discord.ButtonStyle.primary,
        custom_id="voice_room_lock_toggle",
        row=0,
    )
    async def lock_toggle(self, interaction: discord.Interaction, button: discord.ui.Button):
        if await self.reject_if_not_owner(interaction):
            return

        voice_channel, owner = await self.get_voice_channel_and_owner(interaction)
        if voice_channel is None or owner is None:
            await interaction.response.send_message("找不到對應的語音房。", ephemeral=True)
            return

        data = TEMP_VOICE_CONTROL_PANELS.setdefault(
            self.voice_channel_id,
            {
                "owner_id": self.owner_id,
                "panel_channel_id": interaction.channel.id if interaction.channel else None,
                "room_type": self.room_type,
                "locked": False,
                "hidden": False,
            }
        )
        data["locked"] = not data.get("locked", False)

        try:
            await apply_voice_lock_state(voice_channel, owner, self.room_type, data["locked"])
        except discord.Forbidden:
            await interaction.response.send_message("Bot 權限不足，無法鎖定/解鎖語音房。", ephemeral=True)
            return
        except discord.HTTPException as e:
            await interaction.response.send_message(f"鎖定/解鎖失敗：{e}", ephemeral=True)
            return

        await interaction.response.defer()

    @discord.ui.button(
        label="👁️ 隱藏/顯示",
        style=discord.ButtonStyle.secondary,
        custom_id="voice_room_visibility_toggle",
        row=0,
    )
    async def visibility_toggle(self, interaction: discord.Interaction, button: discord.ui.Button):
        if await self.reject_if_not_owner(interaction):
            return

        voice_channel, owner = await self.get_voice_channel_and_owner(interaction)
        if voice_channel is None or owner is None:
            await interaction.response.send_message("找不到對應的語音房。", ephemeral=True)
            return

        data = TEMP_VOICE_CONTROL_PANELS.setdefault(
            self.voice_channel_id,
            {
                "owner_id": self.owner_id,
                "panel_channel_id": interaction.channel.id if interaction.channel else None,
                "room_type": self.room_type,
                "locked": False,
                "hidden": False,
            }
        )
        data["hidden"] = not data.get("hidden", False)

        try:
            await apply_voice_hidden_state(voice_channel, owner, self.room_type, data["hidden"])
        except discord.Forbidden:
            await interaction.response.send_message("Bot 權限不足，無法隱藏/顯示語音房。", ephemeral=True)
            return
        except discord.HTTPException as e:
            await interaction.response.send_message(f"隱藏/顯示失敗：{e}", ephemeral=True)
            return

        await interaction.response.defer()

    @discord.ui.button(
        label="✏️ 更改名稱",
        style=discord.ButtonStyle.success,
        custom_id="voice_room_rename",
        row=1,
    )
    async def rename_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if await self.reject_if_not_owner(interaction):
            return

        await interaction.response.send_modal(
            VoiceRoomRenameModal(
                voice_channel_id=self.voice_channel_id,
                owner_id=self.owner_id,
            )
        )

    @discord.ui.button(
        label="👥 設定人數",
        style=discord.ButtonStyle.danger,
        custom_id="voice_room_user_limit",
        row=1,
    )
    async def limit_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if await self.reject_if_not_owner(interaction):
            return

        await interaction.response.send_modal(
            VoiceRoomLimitModal(
                voice_channel_id=self.voice_channel_id,
                owner_id=self.owner_id,
            )
        )


async def create_voice_control_panel(
    guild: discord.Guild,
    category: discord.CategoryChannel,
    member: discord.Member,
    voice_channel: discord.VoiceChannel,
    room_type: str,
):
    # 不再額外建立文字頻道，控制面板直接發在語音房內建聊天室。
    TEMP_VOICE_CONTROL_PANELS[voice_channel.id] = {
        "owner_id": member.id,
        "panel_channel_id": voice_channel.id,
        "panel_message_id": None,
        "room_type": room_type,
        "locked": False,
        "hidden": False,
    }

    embed = discord.Embed(
        title="專屬語音房",
        description=(
            f"歡迎來到您的專屬包廂！{member.mention}\n"
            "可以使用遙控器管理頻道。\n\n"
            "⚠️ 當包廂內無人時，將自動銷毀。"
        ),
        color=discord.Color.purple()
    )

    message = await voice_channel.send(
        embed=embed,
        view=VoiceRoomControlView(
            voice_channel_id=voice_channel.id,
            owner_id=member.id,
            room_type=room_type,
        ),
        allowed_mentions=discord.AllowedMentions(
            users=True,
            roles=False,
            everyone=False,
        )
    )

    TEMP_VOICE_CONTROL_PANELS[voice_channel.id]["panel_message_id"] = message.id

async def create_private_channel(
    interaction: discord.Interaction,
    category_id: int,
    channel_name: str,
    allowed_roles: list[discord.Role],
    intro_message: str,
    view: discord.ui.View | None = None,
    topic: str | None = None,
):
    guild = interaction.guild
    member = interaction.user

    if guild is None:
        await interaction.response.send_message(
            "這個功能只能在伺服器內使用。",
            ephemeral=True
        )
        return

    category = guild.get_channel(category_id)

    if category is None or not isinstance(category, discord.CategoryChannel):
        await interaction.response.send_message(
            "找不到指定類別，請確認你填的是「類別 ID」，不是頻道 ID。",
            ephemeral=True
        )
        return

    if not interaction.response.is_done():
        await interaction.response.defer(ephemeral=True, thinking=True)

    overwrites = {
        guild.default_role: discord.PermissionOverwrite(
            view_channel=False,
            send_messages=False,
            read_message_history=False
        ),
        member: discord.PermissionOverwrite(
            view_channel=True,
            send_messages=True,
            read_message_history=True,
            attach_files=True
        ),
        guild.me: discord.PermissionOverwrite(
            view_channel=True,
            send_messages=True,
            manage_channels=True,
            read_message_history=True,
            attach_files=True
        ),
    }

    for role in allowed_roles:
        if role is not None:
            overwrites[role] = discord.PermissionOverwrite(
                view_channel=True,
                send_messages=True,
                read_message_history=True,
                attach_files=True
            )

    channel = await guild.create_text_channel(
        name=channel_name,
        category=category,
        overwrites=overwrites,
        topic=topic,
        reason=f"{member} opened a private channel"
    )

    role_mentions = " ".join(role.mention for role in allowed_roles if role is not None)

    await channel.send(
        content=f"{role_mentions}\n{intro_message}",
        view=view,
        allowed_mentions=discord.AllowedMentions(
            roles=True,
            users=True,
            everyone=False
        )
    )

    if topic and "order_customer_id=" in topic:
        await send_order_log(
            guild,
            title="新票口已建立",
            fields=[
                ("開單人", member.mention, True),
                ("票口", channel.mention, True),
                ("狀態", "已確認詳閱規章內容", False),
            ],
            color=discord.Color.purple(),
        )

    try:
        await interaction.delete_original_response()
    except discord.NotFound:
        pass
    except discord.HTTPException:
        pass


# ========= 評價暫存資料 =========

REVIEW_DRAFTS = {}


# ========= 評價 Modal / 按鈕 =========

class ReviewSubmitView(discord.ui.View):
    def __init__(self, customer_id: int, channel_id: int):
        super().__init__(timeout=86400)
        self.customer_id = customer_id
        self.channel_id = channel_id

    @discord.ui.button(
        label="送出好評",
        style=discord.ButtonStyle.success
    )
    async def submit_review(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.customer_id:
            await interaction.response.send_message(
                "只有這張票口的點單顧客可以送出評論。",
                ephemeral=True
            )
            return

        guild = interaction.guild

        if guild is None:
            await interaction.response.send_message(
                "這個功能只能在伺服器內使用。",
                ephemeral=True
            )
            return

        channel = interaction.channel

        if not isinstance(channel, discord.TextChannel):
            await interaction.response.send_message(
                "無法確認目前票口頻道。",
                ephemeral=True
            )
            return

        draft = REVIEW_DRAFTS.get(self.channel_id)

        if draft is None:
            await interaction.response.send_message(
                "找不到暫存的好評資料，請重新按「留下好評」。",
                ephemeral=True
            )
            return

        review_channel = guild.get_channel(REVIEW_CHANNEL_ID)

        if review_channel is None or not isinstance(review_channel, discord.TextChannel):
            await interaction.response.send_message(
                "找不到評價頻道，請確認 REVIEW_CHANNEL_ID 是否正確。",
                ephemeral=True
            )
            return

        if draft.get("submitting"):
            await interaction.response.send_message(
                "好評正在送出中，請不要重複按按鈕。",
                ephemeral=True
            )
            return

        draft["submitting"] = True
        REVIEW_DRAFTS[self.channel_id] = draft

        await interaction.response.defer(ephemeral=True)

        button.disabled = True
        button.label = "送出中..."
        try:
            await interaction.message.edit(view=self)
        except discord.HTTPException:
            pass

        try:
            media_attachments = []

            async for message in channel.history(
                after=draft["started_at"],
                oldest_first=True,
                limit=None
            ):
                if message.author.id != self.customer_id:
                    continue

                for attachment in message.attachments:
                    if is_review_media_attachment(attachment):
                        media_attachments.append(attachment)

            embed = discord.Embed(
                color=discord.Color.gold()
            )

            is_anonymous = draft.get("is_anonymous", False)
            review_customer_text = "匿名闆闆" if is_anonymous else interaction.user.mention

            embed.add_field(
                name="客戶",
                value=review_customer_text,
                inline=True
            )

            embed.add_field(
                name="評分",
                value=draft["stars"],
                inline=True
            )

            embed.add_field(
                name="評價內容",
                value=draft["content"],
                inline=False
            )

            embed.add_field(
                name="圖片 / 影片數量",
                value=f"{len(media_attachments)} 個附件",
                inline=True
            )

            files = []
            failed_attachment_count = 0

            for attachment in media_attachments:
                try:
                    file = await attachment.to_file()
                    files.append(file)
                except discord.HTTPException:
                    failed_attachment_count += 1
                except Exception:
                    failed_attachment_count += 1

            if failed_attachment_count:
                embed.add_field(
                    name="附件提醒",
                    value=(
                        f"有 {failed_attachment_count} 個附件未成功轉發，"
                        "可能是 Discord 檔案大小或格式限制。"
                    ),
                    inline=False
                )

            if files:
                first_batch = True

                for file_batch in chunk_list(files, 10):
                    if first_batch:
                        await review_channel.send(
                            embed=embed,
                            files=file_batch,
                            allowed_mentions=discord.AllowedMentions(
                                users=not is_anonymous,
                                roles=False,
                                everyone=False
                            )
                        )
                        first_batch = False
                    else:
                        await review_channel.send(
                            content=(
                                "匿名闆闆 的好評附件續傳"
                                if is_anonymous
                                else f"{interaction.user.mention} 的好評附件續傳"
                            ),
                            files=file_batch,
                            allowed_mentions=discord.AllowedMentions(
                                users=not is_anonymous,
                                roles=False,
                                everyone=False
                            )
                        )
            else:
                await review_channel.send(
                    embed=embed,
                    allowed_mentions=discord.AllowedMentions(
                        users=not is_anonymous,
                        roles=False,
                        everyone=False
                    )
                )

        except discord.HTTPException as e:
            draft["submitting"] = False
            REVIEW_DRAFTS[self.channel_id] = draft
            button.disabled = False
            button.label = "送出好評"
            try:
                await interaction.message.edit(view=self)
            except discord.HTTPException:
                pass
            await interaction.followup.send(
                f"好評送出失敗，請稍後再試或請客服協助。錯誤：{e}",
                ephemeral=True
            )
            return
        except Exception as e:
            draft["submitting"] = False
            REVIEW_DRAFTS[self.channel_id] = draft
            button.disabled = False
            button.label = "送出好評"
            try:
                await interaction.message.edit(view=self)
            except discord.HTTPException:
                pass
            await interaction.followup.send(
                f"好評送出失敗，請稍後再試或請客服協助。錯誤：{e}",
                ephemeral=True
            )
            return

        REVIEW_DRAFTS.pop(self.channel_id, None)

        button.disabled = True
        button.label = "已送出"
        try:
            await interaction.message.edit(view=self)
        except discord.HTTPException:
            pass

        await interaction.followup.send(
            "好評已送出，感謝闆闆支持！票口將在 3 秒後關閉。",
            ephemeral=True
        )

        await channel.send(
            f"{interaction.user.mention} 已完成評論，感謝闆闆支持！\n"
            f"票口將在 3 秒後關閉。"
        )

        await asyncio.sleep(3)

        await channel.delete(reason=f"Review completed by {interaction.user}")


class ReviewModal(discord.ui.Modal, title="留下好評"):
    rating = discord.ui.TextInput(
        label="評分",
        placeholder="請輸入 1~5",
        required=True,
        max_length=1
    )

    content = discord.ui.TextInput(
        label="評價內容",
        placeholder="請輸入你的評價內容",
        style=discord.TextStyle.paragraph,
        required=True,
        max_length=1000
    )

    anonymous = discord.ui.TextInput(
        label="是否匿名",
        placeholder="輸入：是 / 否",
        required=True,
        max_length=10
    )

    def __init__(self, customer_id: int):
        super().__init__()
        self.customer_id = customer_id

    async def on_submit(self, interaction: discord.Interaction):
        guild = interaction.guild

        if guild is None:
            await interaction.response.send_message("這個功能只能在伺服器內使用。", ephemeral=True)
            return

        if interaction.user.id != self.customer_id:
            await interaction.response.send_message("只有這張票口的點單顧客可以留下評論。", ephemeral=True)
            return

        if not isinstance(interaction.channel, discord.TextChannel):
            await interaction.response.send_message("無法確認目前票口頻道。", ephemeral=True)
            return

        rating_number, stars = rating_to_stars(self.rating.value)

        if rating_number is None or stars is None:
            await interaction.response.send_message("評分請輸入 1~5 的數字。", ephemeral=True)
            return

        REVIEW_DRAFTS[interaction.channel.id] = {
            "customer_id": self.customer_id,
            "rating_number": rating_number,
            "stars": stars,
            "content": self.content.value,
            "is_anonymous": is_anonymous_answer(self.anonymous.value),
            "started_at": interaction.created_at,
        }

        await interaction.response.send_message(
            "好評文字已填寫完成。\n\n"
            "如果有圖片或影片，請直接傳到這個票口頻道。\n"
            "圖片 / 影片可以傳很多個，也可以分很多則訊息傳。\n\n"
            "全部傳完後，請按下方的「送出好評」。",
            view=ReviewSubmitView(
                customer_id=self.customer_id,
                channel_id=interaction.channel.id
            ),
            ephemeral=False
        )


class ReviewButtonView(discord.ui.View):
    def __init__(self, customer_id: int):
        super().__init__(timeout=86400)
        self.customer_id = customer_id

    @discord.ui.button(
        label="留下好評",
        style=discord.ButtonStyle.success
    )
    async def leave_review(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.customer_id:
            await interaction.response.send_message("只有這張票口的點單顧客可以留下評論。", ephemeral=True)
            return

        await interaction.response.send_modal(
            ReviewModal(customer_id=self.customer_id)
        )


# ========= 派單 Modal =========

class DispatchModal(discord.ui.Modal, title="派單"):
    order_name = discord.ui.TextInput(
        label="單子名稱",
        placeholder="請輸入單子名稱",
        required=True,
        max_length=100
    )

    receiver = discord.ui.TextInput(
        label="接單打手/陪玩",
        placeholder="請輸入接單打手/陪玩名稱",
        required=True,
        max_length=100
    )

    async def on_submit(self, interaction: discord.Interaction):
        if not isinstance(interaction.user, discord.Member):
            await interaction.response.send_message("無法確認你的身分組。", ephemeral=True)
            return

        if not is_customer_staff(interaction.user):
            await interaction.response.send_message("只有客服可以派單。", ephemeral=True)
            return

        guild = interaction.guild

        if guild is None:
            await interaction.response.send_message("這個功能只能在伺服器內使用。", ephemeral=True)
            return

        dispatch_channel = guild.get_channel(DISPATCH_CHANNEL_ID)

        if dispatch_channel is None or not isinstance(dispatch_channel, discord.TextChannel):
            await interaction.response.send_message(
                "找不到派單頻道，請確認 DISPATCH_CHANNEL_ID 是否正確。",
                ephemeral=True
            )
            return

        source_channel = interaction.channel.mention if isinstance(interaction.channel, discord.TextChannel) else "未知頻道"

        embed = discord.Embed(
            title="新派單",
            color=discord.Color.blue()
        )

        embed.add_field(
            name="單子名稱",
            value=self.order_name.value,
            inline=False
        )

        embed.add_field(
            name="接單打手/陪玩",
            value=self.receiver.value,
            inline=False
        )

        embed.add_field(
            name="派單客服",
            value=interaction.user.mention,
            inline=False
        )

        embed.add_field(
            name="來源頻道",
            value=source_channel,
            inline=False
        )

        await dispatch_channel.send(
            embed=embed,
            allowed_mentions=discord.AllowedMentions(
                users=True,
                roles=False,
                everyone=False
            )
        )

        await interaction.response.send_message(
            f"已派單，派單資訊已送到 {dispatch_channel.mention}。",
            ephemeral=True
        )

        if isinstance(interaction.channel, discord.TextChannel):
            await interaction.channel.send(
                f"此單已由 {interaction.user.mention} 派單。\n"
                f"單子名稱：{self.order_name.value}\n"
                f"接單打手/陪玩：{self.receiver.value}"
            )


# ========= 收據 Modal =========

def get_order_summary_from_channel(channel_id: int) -> tuple[str, str]:
    """
    從自助下單暫存資料取得收據內容與付款方式。
    內容會沿用闆闆在自助下單面板選的類別、項目與指定選項。
    """
    data = SELF_SERVICE_ORDER_SELECTIONS.get(channel_id, {})

    category = data.get("category")
    item = data.get("item")
    quantity = _to_int(data.get("quantity"), 1) or 1
    companion_preference = data.get("companion_preference")
    payment_method = data.get("payment_method", "未紀錄")

    if item is None:
        return "未紀錄自助下單內容", payment_method

    parts = []

    if category is not None:
        parts.append(ORDER_CATEGORY_LABELS.get(category, category))

    parts.append(item)
    parts.append(f"數量：{quantity} 單")

    if companion_preference is not None:
        parts.append(companion_preference)

    return "｜".join(parts), payment_method


class ReceiptModal(discord.ui.Modal, title="已結單收據"):
    payee = discord.ui.TextInput(
        label="收款人",
        placeholder="例如：zYao或客服暱稱(代收)",
        required=True,
        max_length=100
    )

    amount = discord.ui.TextInput(
        label="金額",
        placeholder="例如：1275",
        required=True,
        max_length=100
    )

    staff = discord.ui.TextInput(
        label="對接客服",
        placeholder="請輸入對接客服名稱",
        required=True,
        max_length=100
    )

    receiver = discord.ui.TextInput(
        label="接單打手/陪玩",
        placeholder="請輸入接單打手/陪玩名稱",
        required=True,
        max_length=100
    )

    async def on_submit(self, interaction: discord.Interaction):
        if not isinstance(interaction.user, discord.Member):
            await interaction.response.send_message("無法確認你的身分組。", ephemeral=True)
            return

        if not is_customer_staff(interaction.user):
            await interaction.response.send_message("只有客服可以操作已結單。", ephemeral=True)
            return

        guild = interaction.guild

        if guild is None:
            await interaction.response.send_message("這個功能只能在伺服器內使用。", ephemeral=True)
            return

        if not isinstance(interaction.channel, discord.TextChannel):
            await interaction.response.send_message("無法確認目前票口頻道。", ephemeral=True)
            return

        receipt_channel = guild.get_channel(RECEIPT_CHANNEL_ID)

        if receipt_channel is None or not isinstance(receipt_channel, discord.TextChannel):
            await interaction.response.send_message(
                "找不到收據頻道，請確認 RECEIPT_CHANNEL_ID 是否正確。",
                ephemeral=True
            )
            return

        order_channel = interaction.channel
        customer_id = get_order_customer_id_from_channel(order_channel)

        if customer_id is None:
            await interaction.response.send_message(
                "無法辨識這張票口的下單顧客，因此無法自動帶入付款人。",
                ephemeral=True
            )
            return

        customer_member = guild.get_member(customer_id)
        payer_text = f"@{customer_member.display_name}" if customer_member is not None else f"@{customer_id}"

        order_content, payment_method = get_order_summary_from_channel(order_channel.id)
        date_text = get_taipei_now_text()

        parsed_amount = parse_receipt_amount(self.amount.value)
        if parsed_amount is None or parsed_amount <= 0:
            await interaction.response.send_message(
                "金額欄位無法辨識，請輸入可辨識的數字，例如：1275、NT$1275、1275T。",
                ephemeral=True
            )
            return

        receipt_id = generate_order_receipt_id()
        closed_at_text = get_taipei_now_iso()

        order_data = SELF_SERVICE_ORDER_SELECTIONS.setdefault(order_channel.id, {})
        order_data["receipt_id"] = receipt_id
        order_data["order_no"] = receipt_id
        order_data["receipt_created_at"] = closed_at_text
        order_data["closed_at"] = closed_at_text
        order_data["closed"] = True
        order_data["status"] = "closed"
        order_data["amount"] = parsed_amount
        order_data["total_amount"] = parsed_amount
        order_data["payment_method"] = payment_method
        remember_order_data(order_channel.id, order_data)

        receipt_text = (
            "```text\n"
            "收據\n"
            "\n"
            f"編號：{receipt_id}\n"
            f"日期：{date_text}\n"
            "\n"
            f"收款人：{self.payee.value}\n"
            f"付款人：{payer_text}\n"
            "\n"
            f"內容：{order_content}\n"
            "\n"
            f"金額：{self.amount.value}\n"
            f"付款方式：{payment_method}\n"
            "```"
        )

        embed = discord.Embed(
            title="收據",
            description=receipt_text,
            color=discord.Color.green()
        )

        embed.add_field(
            name="付款人",
            value=payer_text,
            inline=False
        )

        embed.add_field(
            name="對接客服",
            value=self.staff.value,
            inline=False
        )

        embed.add_field(
            name="接單打手/陪玩",
            value=self.receiver.value,
            inline=False
        )

        await receipt_channel.send(
            embed=embed,
            allowed_mentions=discord.AllowedMentions(
                users=True,
                roles=False,
                everyone=False
            )
        )

        await lock_dispatch_claim_panel(guild, order_channel.id)

        reward_result = await add_customer_reward_from_order(
            guild=guild,
            order_channel_id=order_channel.id,
            customer_id=customer_id,
            amount_text=self.amount.value,
            notify_channel=interaction.channel,
        )

        await send_order_log(
            guild,
            title="訂單已結單",
            fields=[
                ("訂單編號", receipt_id, True),
                ("顧客", f"<@{customer_id}>", True),
                ("客服", interaction.user.mention, True),
                ("金額", self.amount.value, True),
                ("付款方式", payment_method, True),
                ("票口", order_channel.mention, False),
                ("內容", order_content, False),
            ],
            color=discord.Color.green(),
        )

        await interaction.response.send_message(
            f"此單已由 {interaction.user.mention} 結單，收據已送出。\n\n"
            f"{reward_result}\n\n"
            f"請闆闆留下評論",
            view=ReviewButtonView(customer_id=customer_id),
            allowed_mentions=discord.AllowedMentions(
                users=True,
                roles=False,
                everyone=False
            )
        )


# ========= 下單操作按鈕 =========

class ConfirmCancelOrderView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=60)

    @discord.ui.button(
        label="是，取消訂單",
        style=discord.ButtonStyle.danger,
        custom_id="confirm_cancel_order_yes"
    )
    async def confirm_cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not isinstance(interaction.user, discord.Member):
            await interaction.response.send_message("無法確認你的身分組。", ephemeral=True)
            return

        if not is_customer_staff(interaction.user):
            await interaction.response.send_message("只有客服可以取消訂單。", ephemeral=True)
            return

        channel = interaction.channel

        if interaction.guild is not None and isinstance(channel, discord.TextChannel):
            await delete_dispatch_claim_panel_for_order(
                guild=interaction.guild,
                order_channel_id=channel.id,
            )

        await interaction.response.send_message(
            "已確認取消訂單，這個頻道將在 3 秒後關閉，對應的派單訊息也會一併刪除。",
            ephemeral=False
        )

        await asyncio.sleep(3)

        if isinstance(channel, discord.TextChannel):
            await channel.delete(reason=f"Order cancelled by {interaction.user}")

    @discord.ui.button(
        label="否，保留訂單",
        style=discord.ButtonStyle.secondary,
        custom_id="confirm_cancel_order_no"
    )
    async def keep_order(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not isinstance(interaction.user, discord.Member):
            await interaction.response.send_message("無法確認你的身分組。", ephemeral=True)
            return

        if not is_customer_staff(interaction.user):
            await interaction.response.send_message("只有客服可以操作。", ephemeral=True)
            return

        await interaction.response.send_message("已保留訂單。", ephemeral=True)


# ========= 自助下單資料 =========

ORDER_CONTROL_SELECTIONS = {}
STAFF_ORDER_OPERATION_SELECTIONS = {}
SELF_SERVICE_ORDER_SELECTIONS = {}

# 派單頻道接單資料
# message_id 對應該派單訊息目前有哪些陪玩 / 打手接單。
# 重要訂單資料會保存到 bot_data.json，Bot 重啟後會自動讀回。
ORDER_CLAIMS = {}

# 顧客會員 / 獎勵資料
# user_id -> {total_spent, order_count, last_order_at, points, platinum_channel_id}
CUSTOMER_REWARDS = {}
configure_reward_storage(CUSTOMER_REWARDS)

# 訂單編號計數器：YYYYMMDD -> 當日最後流水號
ORDER_COUNTERS = {}

BACKUP_TASK_STARTED = False
STORED_REMINDER_TASK_STARTED = False
VIP_DOWNGRADE_TASK_STARTED = False
STORED_ORDER_REMINDER_DAYS = [3, 7]
VIP_MAINTAIN_MIN_MONTHLY_SPEND = 500

DATA_FILE = Path(__file__).parent / "bot_data.json"  # 舊版 JSON 備援/遷移用
DB_FILE = Path(__file__).parent / "bot.db"
BACKUP_DIR = Path(__file__).parent / "backups"
CLOSED_ORDER_KEEP_DAYS = 0  # 已結單資料永久保留，不再自動刪除
CANCELLED_ORDER_KEEP_DAYS = 60  # 只清理超過 60 天的取消單暫存




def get_or_create_order_log_channel_sync_hint() -> str:
    return f"{ORDER_LOG_CHANNEL_NAME}（類別 ID：{ORDER_LOG_CATEGORY_ID}）"


async def get_or_create_order_log_channel(guild: discord.Guild) -> discord.TextChannel | None:
    category = guild.get_channel(ORDER_LOG_CATEGORY_ID)
    if not isinstance(category, discord.CategoryChannel):
        return None

    for channel in category.text_channels:
        if channel.name == ORDER_LOG_CHANNEL_NAME:
            return channel

    try:
        return await guild.create_text_channel(
            name=ORDER_LOG_CHANNEL_NAME,
            category=category,
            reason="Create order log channel"
        )
    except (discord.Forbidden, discord.HTTPException) as e:
        print(f"建立機器人日誌頻道失敗：{e}")
        return None


async def send_order_log(
    guild: discord.Guild | None,
    title: str,
    description: str | None = None,
    fields: list[tuple[str, str, bool]] | None = None,
    color: discord.Color | None = None,
) -> None:
    if guild is None:
        return

    channel = await get_or_create_order_log_channel(guild)
    if channel is None:
        print(f"找不到或無法建立機器人日誌頻道：{get_or_create_order_log_channel_sync_hint()}")
        return

    embed = discord.Embed(
        title=title,
        description=description or "",
        color=color or discord.Color.blurple(),
        timestamp=get_taipei_now(),
    )

    for name, value, inline in fields or []:
        embed.add_field(name=name, value=value if value else "未紀錄", inline=inline)

    try:
        await channel.send(embed=embed, allowed_mentions=discord.AllowedMentions.none())
    except discord.HTTPException as e:
        print(f"送出機器人日誌失敗：{e}")


async def send_lottery_announcement(
    guild: discord.Guild | None,
    content: str,
    embed: discord.Embed | None = None,
    channel: discord.TextChannel | None = None,
) -> bool:
    if guild is None:
        return False

    target_channel = channel

    if target_channel is None:
        fetched_channel = guild.get_channel(LOTTERY_ANNOUNCE_CHANNEL_ID)
        if fetched_channel is None:
            try:
                fetched_channel = await guild.fetch_channel(LOTTERY_ANNOUNCE_CHANNEL_ID)
            except (discord.NotFound, discord.Forbidden, discord.HTTPException) as e:
                print(f"找不到抽獎公告頻道：{e}")
                return False

        if not isinstance(fetched_channel, discord.TextChannel):
            print("抽獎公告頻道不是文字頻道。")
            return False

        target_channel = fetched_channel

    try:
        await target_channel.send(
            content=content,
            embed=embed,
            allowed_mentions=discord.AllowedMentions(everyone=True, users=True, roles=False),
        )
        return True
    except discord.HTTPException as e:
        print(f"送出抽獎公告失敗：{e}")
        return False



async def daily_backup_loop():
    await bot.wait_until_ready()
    while not bot.is_closed():
        try:
            backup_path = run_daily_backup_once()
            if backup_path:
                print(f"bot.db backup checked: {backup_path}")
        except Exception as e:
            print(f"每日備份 bot.db 失敗：{e}")
        await asyncio.sleep(3600)


async def check_stored_order_reminders_once(guild: discord.Guild | None = None) -> None:
    guild = guild or bot.get_guild(GUILD_ID)
    if guild is None:
        return

    now = get_taipei_now()
    changed = False

    for channel_id, data in list(SELF_SERVICE_ORDER_SELECTIONS.items()):
        if not isinstance(data, dict) or str(data.get("status", "")).lower() != "stored":
            continue

        stored_at = _parse_datetime_safe(data.get("stored_at"))
        if stored_at is None:
            continue

        age_days = max(0, (now - stored_at).days)
        sent = data.setdefault("stored_reminders_sent", [])
        if not isinstance(sent, list):
            sent = []
            data["stored_reminders_sent"] = sent

        due_days = [day for day in STORED_ORDER_REMINDER_DAYS if age_days >= day and day not in sent]
        if not due_days:
            continue

        for day in due_days:
            sent.append(day)

            customer_id = data.get("customer_id") or get_order_customer_id_from_channel(guild.get_channel(channel_id)) if isinstance(guild.get_channel(channel_id), discord.TextChannel) else data.get("customer_id")
            item = data.get("item") or "未紀錄"
            quantity = _to_int(data.get("quantity"), 1) or 1
            amount = _to_int(data.get("amount"), 0) or 0
            order_no = data.get("order_no") or "未產生"
            ticket_channel = guild.get_channel(channel_id)
            ticket_text = ticket_channel.mention if isinstance(ticket_channel, discord.TextChannel) else f"票口 ID：{channel_id}"

            description = (
                f"有一筆存單已經超過 **{day} 天**，請客服確認是否需要恢復、取消或聯絡顧客。\n\n"
                f"顧客：{f'<@{customer_id}>' if customer_id else '未紀錄'}\n"
                f"票口：{ticket_text}\n"
                f"訂單編號：{order_no}\n"
                f"項目：{item} x{quantity}\n"
                f"金額：{format_t_amount(amount) if amount else '未紀錄'}\n"
                f"存單原因：{data.get('stored_reason') or '未填寫'}\n"
                f"預計恢復：{data.get('stored_expected_time') or '未填寫'}"
            )
            await send_order_log(
                guild,
                title=f"存單提醒｜已超過 {day} 天",
                description=description,
                color=discord.Color.orange(),
            )

        SELF_SERVICE_ORDER_SELECTIONS[channel_id] = data
        changed = True

    if changed:
        save_bot_data()


async def check_vip_downgrades_once(guild: discord.Guild | None = None, force: bool = False) -> tuple[int, list[str]]:
    guild = guild or bot.get_guild(GUILD_ID)
    if guild is None:
        return 0, ["找不到伺服器，無法檢查 VIP 降階。"]

    start_dt, end_dt, check_month_key = get_previous_calendar_month_range()
    changed_count = 0
    messages = []

    for user_id, data in list(CUSTOMER_REWARDS.items()):
        if not isinstance(data, dict):
            continue

        current_index = get_effective_member_level_index(data)
        if current_index <= 0:
            data["vip_last_downgrade_check_month"] = check_month_key
            continue

        if not force and data.get("vip_last_downgrade_check_month") == check_month_key:
            continue

        monthly_spend = get_customer_closed_spend_between(user_id, start_dt, end_dt)
        data["vip_last_downgrade_check_month"] = check_month_key

        if monthly_spend >= VIP_MAINTAIN_MIN_MONTHLY_SPEND:
            continue

        old_level = get_member_level_by_index(current_index)
        new_index = max(0, current_index - 1)
        new_level = get_member_level_by_index(new_index)
        data["vip_level_index"] = new_index

        log = {
            "checked_month": check_month_key,
            "previous_month_start": start_dt.isoformat(timespec="seconds"),
            "previous_month_end": end_dt.isoformat(timespec="seconds"),
            "previous_month_spend": monthly_spend,
            "required_spend": VIP_MAINTAIN_MIN_MONTHLY_SPEND,
            "old_level": old_level["name"],
            "new_level": new_level["name"],
            "created_at": get_taipei_now_iso(),
        }
        logs = data.setdefault("vip_downgrade_logs", [])
        if isinstance(logs, list):
            logs.append(log)
            data["vip_downgrade_logs"] = logs[-24:]
        else:
            data["vip_downgrade_logs"] = [log]

        member = await fetch_member_safely(guild, user_id)
        benefit_notices = await ensure_reward_member_benefits(guild, member, data)
        CUSTOMER_REWARDS[user_id] = data
        changed_count += 1

        message = (
            f"<@{user_id}>：{old_level['name']} → {new_level['name']}｜"
            f"上月消費 {format_t_amount(monthly_spend)}，未達 {format_t_amount(VIP_MAINTAIN_MIN_MONTHLY_SPEND)}"
        )
        if benefit_notices:
            message += "｜" + "、".join(benefit_notices)
        messages.append(message)

    if changed_count:
        save_bot_data()
        await send_order_log(
            guild,
            title="VIP 會員自動降階",
            description=(
                f"檢查月份：{check_month_key}\n"
                f"統計區間：{start_dt.strftime('%Y/%m/%d')} ～ {end_dt.strftime('%Y/%m/%d')}\n"
                f"維持條件：上月消費滿 {format_t_amount(VIP_MAINTAIN_MIN_MONTHLY_SPEND)}\n\n"
                + "\n".join(messages[:20])
            ),
            color=discord.Color.orange(),
        )

    return changed_count, messages

async def vip_downgrade_loop():
    await bot.wait_until_ready()
    while not bot.is_closed():
        try:
            await check_vip_downgrades_once()
        except Exception as e:
            print(f"VIP 自動降階檢查失敗：{e}")
        await asyncio.sleep(21600)


async def stored_order_reminder_loop():
    await bot.wait_until_ready()
    while not bot.is_closed():
        try:
            await check_stored_order_reminders_once()
        except Exception as e:
            print(f"存單提醒檢查失敗：{e}")
        await asyncio.sleep(21600)




def get_dispatch_claim_view_from_data(message_id: int) -> "DispatchClaimView | None":
    data = ORDER_CLAIMS.get(message_id)

    if not data:
        return None

    required_values = [
        data.get("customer_id"),
        data.get("category_label"),
        data.get("item"),
        data.get("payment_method"),
        data.get("source_channel_id"),
    ]

    if any(value is None for value in required_values):
        return None

    return DispatchClaimView(
        customer_id=int(data["customer_id"]),
        category_label=str(data["category_label"]),
        item=str(data["item"]),
        quantity=_to_int(data.get("quantity"), 1) or 1,
        payment_method=str(data["payment_method"]),
        source_channel_id=int(data["source_channel_id"]),
        companion_preference=data.get("companion_preference"),
        locked=bool(data.get("locked", False)),
        status=str(data.get("status", "active")),
    )


def cleanup_old_closed_orders() -> None:
    """
    清理過期的非必要暫存資料。

    重要規則：
    - 已結單 closed：永久保留，因為營收、會員累積、統計都會用到。
    - 存單 stored：永久保留，避免存單被誤刪。
    - 取消單 cancelled/canceled：超過 CANCELLED_ORDER_KEEP_DAYS 天後清理。
    - 備份檔：由 run_daily_backup_once() 依 BACKUP_KEEP_DAYS 清理。
    """
    if CANCELLED_ORDER_KEEP_DAYS <= 0:
        return

    now = get_taipei_now()
    cutoff = now - timedelta(days=CANCELLED_ORDER_KEEP_DAYS)
    order_channel_ids_to_remove = []
    dispatch_message_ids_to_remove = set()

    for channel_id, data in list(SELF_SERVICE_ORDER_SELECTIONS.items()):
        if not isinstance(data, dict):
            continue

        status = str(data.get("status", "")).lower()

        # closed / stored 都是營運重要紀錄，不自動刪。
        if status in {"closed", "stored"} or data.get("closed"):
            continue

        # 只清理取消單。
        if status not in {"cancelled", "canceled"}:
            continue

        time_text = (
            data.get("cancelled_at")
            or data.get("updated_at")
            or data.get("closed_at")
            or data.get("created_at")
        )
        if not time_text:
            continue

        try:
            order_time = datetime.fromisoformat(str(time_text))
        except ValueError:
            continue

        if order_time.tzinfo is None:
            order_time = order_time.replace(tzinfo=timezone(timedelta(hours=8)))

        if order_time < cutoff:
            order_channel_ids_to_remove.append(channel_id)
            dispatch_message_id = _to_int(data.get("dispatch_message_id"))
            if dispatch_message_id is not None:
                dispatch_message_ids_to_remove.add(dispatch_message_id)

    for channel_id in order_channel_ids_to_remove:
        SELF_SERVICE_ORDER_SELECTIONS.pop(channel_id, None)
        delete_order_row_from_db(channel_id)

    for message_id in dispatch_message_ids_to_remove:
        ORDER_CLAIMS.pop(message_id, None)
        delete_claim_row_from_db(message_id=message_id)

    if order_channel_ids_to_remove or dispatch_message_ids_to_remove:
        save_bot_data()
        print(
            f"已清理 {len(order_channel_ids_to_remove)} 筆超過 "
            f"{CANCELLED_ORDER_KEEP_DAYS} 天的取消單暫存資料。"
        )


# ========= SQLite 相容修正版：正式支援 relational bot.db =========
# 這段會覆蓋上方舊的 JSON blob 版 init / save / load。
# 用途：
# 1. 讓 /add_purchase、/import_purchases、/set_customer_rewards 寫進 customers 表。
# 2. 保留直接 SQL 查詢用欄位：customer_id / total_spent / points / completed_orders / last_order_at / level。
# 3. 會員降階從 2026/06 才開始檢查，避免 2026/05 開店時被 4 月資料誤降級。
# 4. 降階後把 vip_progress_base_total_spent 設為當下累積消費，下一級進度從降階後重新開始。

VIP_DOWNGRADE_FIRST_CHECK_MONTH = "2026-06"  # 第一次檢查 2026/05 消費；不檢查 2026/04。










configure_database(DB_FILE, init_database, backup_dir=BACKUP_DIR, backup_keep_days=BACKUP_KEEP_DAYS, data_file=DATA_FILE)
configure_reward_database(DB_FILE)
configure_data_access(
    SELF_SERVICE_ORDER_SELECTIONS,
    ORDER_CLAIMS,
    CUSTOMER_REWARDS,
    ORDER_COUNTERS,
    save_bot_data,
    order_id_prefix=ORDER_ID_PREFIX,
    member_levels=MEMBER_LEVELS,
    get_member_level_index_by_total_spent_func=get_member_level_index_by_total_spent,
    get_current_reward_points_func=get_current_reward_points,
    calculate_reward_points_func=calculate_reward_points,
    get_effective_member_level_func=get_effective_member_level,
)
configure_reward_order_context(SELF_SERVICE_ORDER_SELECTIONS, save_bot_data)


async def check_vip_downgrades_once(guild: discord.Guild | None = None, force: bool = False) -> tuple[int, list[str]]:
    guild = guild or bot.get_guild(GUILD_ID)
    if guild is None:
        return 0, ["找不到伺服器，無法檢查 VIP 降階。"]

    start_dt, end_dt, check_month_key = get_previous_calendar_month_range()

    if check_month_key < VIP_DOWNGRADE_FIRST_CHECK_MONTH:
        return 0, [
            f"VIP 降階尚未啟用。第一次檢查月份為 {VIP_DOWNGRADE_FIRST_CHECK_MONTH}，"
            f"本次 {check_month_key} 不檢查，避免 2026/04 未營運資料造成誤降階。"
        ]

    changed_count = 0
    messages = []

    for user_id, data in list(CUSTOMER_REWARDS.items()):
        if not isinstance(data, dict):
            continue

        current_index = get_effective_member_level_index(data)
        if current_index <= 0:
            data["vip_last_downgrade_check_month"] = check_month_key
            CUSTOMER_REWARDS[user_id] = data
            continue

        if not force and data.get("vip_last_downgrade_check_month") == check_month_key:
            continue

        monthly_spend = get_customer_closed_spend_between(user_id, start_dt, end_dt)
        data["vip_last_downgrade_check_month"] = check_month_key

        if monthly_spend >= VIP_MAINTAIN_MIN_MONTHLY_SPEND:
            CUSTOMER_REWARDS[user_id] = data
            continue

        old_level = get_member_level_by_index(current_index)
        new_index = max(0, current_index - 1)
        new_level = get_member_level_by_index(new_index)
        data["vip_level_index"] = new_index
        # 降階後，下一級進度從降階當下重新開始累積。
        data["vip_progress_base_total_spent"] = int(data.get("total_spent", 0) or 0)

        log = {
            "checked_month": check_month_key,
            "previous_month_start": start_dt.isoformat(timespec="seconds"),
            "previous_month_end": end_dt.isoformat(timespec="seconds"),
            "previous_month_spend": monthly_spend,
            "required_spend": VIP_MAINTAIN_MIN_MONTHLY_SPEND,
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

        member = await fetch_member_safely(guild, user_id)
        benefit_notices = await ensure_reward_member_benefits(guild, member, data)
        CUSTOMER_REWARDS[user_id] = data
        changed_count += 1

        message = (
            f"<@{user_id}>：{old_level['name']} → {new_level['name']}｜"
            f"上月消費 {format_t_amount(monthly_spend)}，未達 {format_t_amount(VIP_MAINTAIN_MIN_MONTHLY_SPEND)}"
        )
        if benefit_notices:
            message += "｜" + "、".join(benefit_notices)
        messages.append(message)

    save_bot_data()

    if changed_count:
        await send_order_log(
            guild,
            title="VIP 會員自動降階",
            description=(
                f"檢查月份：{check_month_key}\n"
                f"統計區間：{start_dt.strftime('%Y/%m/%d')} ～ {end_dt.strftime('%Y/%m/%d')}\n"
                f"維持條件：上月消費滿 {format_t_amount(VIP_MAINTAIN_MIN_MONTHLY_SPEND)}\n\n"
                + "\n".join(messages[:20])
            ),
            color=discord.Color.orange(),
        )

    return changed_count, messages



load_bot_data()
cleanup_old_closed_orders()

COMPANION_PREFERENCE_OPTIONS = [
    "不指定陪玩/打手",
    "指定陪玩/打手",
]

PAYMENT_METHOD_OPTIONS = [
    "街口",
    "轉帳",
]


class OrderControlSelect(discord.ui.Select):
    def __init__(self):
        options = [
            discord.SelectOption(
                label="派單",
                value="dispatch",
                description="開啟自助下單面板給開單用戶填寫"
            ),
            discord.SelectOption(
                label="取消訂單",
                value="cancel",
                description="取消並關閉這張下單票口"
            ),
        ]

        super().__init__(
            placeholder="客服操作選項",
            min_values=1,
            max_values=1,
            options=options,
            custom_id="order_control_select",
            row=0
        )

    async def callback(self, interaction: discord.Interaction):
        if not isinstance(interaction.user, discord.Member):
            await interaction.response.send_message("無法確認你的身分組。", ephemeral=True)
            return

        if not is_customer_staff(interaction.user):
            await interaction.response.send_message("只有客服可以操作訂單。", ephemeral=True)
            return

        if not isinstance(interaction.channel, discord.TextChannel):
            await interaction.response.send_message("這個功能只能在下單票口內使用。", ephemeral=True)
            return

        ORDER_CONTROL_SELECTIONS[(interaction.channel.id, interaction.user.id)] = self.values[0]

        await interaction.response.defer()


class SelfServiceOrderCategorySelect(discord.ui.Select):
    def __init__(self, customer_id: int, channel_id: int, selected_category: str | None = None):
        self.customer_id = customer_id
        self.channel_id = channel_id

        options = [
            discord.SelectOption(
                label="基礎單",
                value="basic",
                description="油鍋單、賭約單、保底單、技術陪、娛樂陪、體驗單",
                default=selected_category == "basic"
            ),
            discord.SelectOption(
                label="趣味單",
                value="fun",
                description="豪到你了嗎、瘋狗嘶咬、這什麼鳥槍、想吃自己打",
                default=selected_category == "fun"
            ),
            discord.SelectOption(
                label="代解代肝",
                value="farm",
                description="賽季3x3、純綠代肝哈夫幣",
                default=selected_category == "farm"
            ),
            discord.SelectOption(
                label="賽季限定活動",
                value="season",
                description="勇敢者行動、S9炫彩勇敢者行動",
                default=selected_category == "season"
            ),
        ]

        super().__init__(
            placeholder="請選擇訂單類別",
            min_values=1,
            max_values=1,
            options=options,
            custom_id="self_service_order_category_select",
            row=0
        )

    async def callback(self, interaction: discord.Interaction):
        if not can_operate_self_service_order(interaction.user, self.customer_id):
            await interaction.response.send_message("只有開這張票口的用戶或客服可以選擇訂單。", ephemeral=True)
            return

        selected_category = self.values[0]

        data = SELF_SERVICE_ORDER_SELECTIONS.setdefault(self.channel_id, {})
        data["customer_id"] = self.customer_id
        data["category"] = selected_category
        data.pop("item", None)
        data.pop("quantity", None)
        data.pop("companion_preference", None)
        data.pop("payment_method", None)
        remember_order_data(self.channel_id, data)
        await log_self_service_proxy_action(
            interaction,
            self.customer_id,
            "選擇訂單類別",
            ORDER_CATEGORY_LABELS.get(selected_category, selected_category),
        )

        await interaction.response.edit_message(
            view=SelfServiceOrderView(
                customer_id=self.customer_id,
                channel_id=self.channel_id,
                selected_category=selected_category
            )
        )


class SelfServiceOrderItemSelect(discord.ui.Select):
    def __init__(
        self,
        customer_id: int,
        channel_id: int,
        selected_category: str | None = None,
        selected_item: str | None = None,
    ):
        self.customer_id = customer_id
        self.channel_id = channel_id
        self.selected_category = selected_category

        if selected_category is None:
            options = [
                discord.SelectOption(
                    label="請先選擇訂單類別",
                    value="need_category",
                    description="選完上方類別後，這裡會自動更新項目"
                )
            ]
            disabled = True
            placeholder = "請先選擇訂單類別"
        else:
            options = [
                discord.SelectOption(
                    label=item,
                    value=item,
                    description=ORDER_CATEGORY_LABELS[selected_category],
                    default=item == selected_item
                )
                for item in ORDER_ITEMS_BY_CATEGORY[selected_category]
            ]
            disabled = False
            placeholder = "請選擇訂單項目"

        super().__init__(
            placeholder=placeholder,
            min_values=1,
            max_values=1,
            options=options,
            custom_id="self_service_order_item_select",
            row=1,
            disabled=disabled
        )

    async def callback(self, interaction: discord.Interaction):
        if not can_operate_self_service_order(interaction.user, self.customer_id):
            await interaction.response.send_message("只有開這張票口的用戶或客服可以選擇訂單。", ephemeral=True)
            return

        selected_item = self.values[0]

        data = SELF_SERVICE_ORDER_SELECTIONS.setdefault(self.channel_id, {})
        data["customer_id"] = self.customer_id
        data["item"] = selected_item
        data["quantity"] = 1
        data.pop("payment_method", None)

        if selected_item in SPECIAL_COMPANION_ITEMS:
            data.pop("companion_preference", None)
        else:
            data["companion_preference"] = "不指定陪玩/打手"
        remember_order_data(self.channel_id, data)
        await log_self_service_proxy_action(
            interaction,
            self.customer_id,
            "選擇訂單項目",
            selected_item,
        )

        await interaction.response.edit_message(
            view=SelfServiceOrderView(
                customer_id=self.customer_id,
                channel_id=self.channel_id,
                selected_category=data.get("category")
            )
        )


class SelfServiceCompanionPreferenceSelect(discord.ui.Select):
    def __init__(
        self,
        customer_id: int,
        channel_id: int,
        selected_item: str | None = None,
        selected_preference: str | None = None,
    ):
        self.customer_id = customer_id
        self.channel_id = channel_id
        self.selected_item = selected_item

        if selected_item is None:
            options = [
                discord.SelectOption(
                    label="請先選擇訂單項目",
                    value="need_item",
                    description="選完上方項目後，這裡會自動更新"
                )
            ]
            disabled = True
            placeholder = "請先選擇訂單項目"
        elif selected_item in SPECIAL_COMPANION_ITEMS:
            options = [
                discord.SelectOption(
                    label="不指定陪玩/打手",
                    value="不指定陪玩/打手",
                    description="由客服安排合適人選",
                    default=selected_preference == "不指定陪玩/打手"
                ),
                discord.SelectOption(
                    label="指定陪玩/打手",
                    value="指定陪玩/打手",
                    description="由下單用戶指定人選",
                    default=selected_preference == "指定陪玩/打手"
                ),
            ]
            disabled = False
            placeholder = "請選擇是否指定陪玩/打手"
        else:
            options = [
                discord.SelectOption(
                    label="不指定陪玩/打手",
                    value="不指定陪玩/打手",
                    description="此項目不開放指定",
                    default=True
                )
            ]
            disabled = False
            placeholder = "不指定陪玩/打手"

        super().__init__(
            placeholder=placeholder,
            min_values=1,
            max_values=1,
            options=options,
            custom_id="self_service_companion_preference_select",
            row=2,
            disabled=disabled
        )

    async def callback(self, interaction: discord.Interaction):
        if not can_operate_self_service_order(interaction.user, self.customer_id):
            await interaction.response.send_message("只有開這張票口的用戶或客服可以選擇訂單。", ephemeral=True)
            return

        if self.values[0] == "need_item":
            await interaction.response.defer()
            return

        data = SELF_SERVICE_ORDER_SELECTIONS.setdefault(self.channel_id, {})
        data["customer_id"] = self.customer_id
        data["companion_preference"] = self.values[0]
        data.pop("payment_method", None)
        remember_order_data(self.channel_id, data)
        await log_self_service_proxy_action(
            interaction,
            self.customer_id,
            "選擇指定選項",
            self.values[0],
        )

        await interaction.response.defer()

class SelfServiceOrderQuantitySelect(discord.ui.Select):
    def __init__(
        self,
        customer_id: int,
        channel_id: int,
        selected_item: str | None = None,
        selected_quantity: int | None = None,
    ):
        self.customer_id = customer_id
        self.channel_id = channel_id
        self.selected_item = selected_item
        quantity = selected_quantity or 1

        if selected_item is None:
            options = [
                discord.SelectOption(
                    label="請先選擇訂單項目",
                    value="need_item",
                    description="選完上方項目後，這裡會自動更新"
                )
            ]
            disabled = True
            placeholder = "請先選擇訂單項目"
        elif selected_item in QUANTITY_SELECT_ITEMS:
            options = [
                discord.SelectOption(
                    label=f"{num} 單",
                    value=str(num),
                    description=f"{num} 單 = 約 {num} 小時",
                    default=quantity == num
                )
                for num in QUANTITY_OPTIONS
            ]
            disabled = False
            placeholder = "請選擇數量"
        else:
            options = [
                discord.SelectOption(
                    label="1 單",
                    value="1",
                    description="此項目數量固定為 1 單",
                    default=True
                )
            ]
            disabled = False
            placeholder = "數量固定為 1 單"

        super().__init__(
            placeholder=placeholder,
            min_values=1,
            max_values=1,
            options=options,
            custom_id="self_service_order_quantity_select",
            row=3,
            disabled=disabled
        )

    async def callback(self, interaction: discord.Interaction):
        if not can_operate_self_service_order(interaction.user, self.customer_id):
            await interaction.response.send_message("只有開這張票口的用戶或客服可以選擇訂單數量。", ephemeral=True)
            return

        if self.values[0] == "need_item":
            await interaction.response.defer()
            return

        data = SELF_SERVICE_ORDER_SELECTIONS.setdefault(self.channel_id, {})
        selected_item = data.get("item")

        try:
            quantity = int(self.values[0])
        except ValueError:
            await interaction.response.send_message("數量選擇異常，請重新選擇。", ephemeral=True)
            return

        if selected_item not in QUANTITY_SELECT_ITEMS:
            quantity = 1

        if quantity < 1 or quantity > max(QUANTITY_OPTIONS):
            await interaction.response.send_message("數量請選擇 1 到 8 單。", ephemeral=True)
            return

        data["customer_id"] = self.customer_id
        data["quantity"] = quantity
        data.pop("payment_method", None)
        remember_order_data(self.channel_id, data)
        await log_self_service_proxy_action(
            interaction,
            self.customer_id,
            "選擇訂單數量",
            f"{quantity} 單",
        )

        await interaction.response.defer()


async def log_self_service_proxy_action(
    interaction: discord.Interaction,
    customer_id: int,
    action: str,
    detail: str | None = None,
) -> None:
    """客服 / 店長 / 管理員代操作自助下單時，寫入機器人日誌。"""
    if interaction.user.id == customer_id:
        return

    channel_text = interaction.channel.mention if isinstance(interaction.channel, discord.TextChannel) else "未紀錄"
    fields = [
        ("操作人員", interaction.user.mention, True),
        ("原下單顧客", f"<@{customer_id}>", True),
        ("票口", channel_text, False),
        ("操作", action, True),
    ]

    if detail:
        fields.append(("內容", detail, False))

    try:
        await send_order_log(
            interaction.guild,
            title="自助下單代操作",
            fields=fields,
            color=discord.Color.teal(),
        )
    except Exception as e:
        print(f"寫入自助下單代操作日誌失敗：{e}")


def build_self_service_order_embed(
    customer_mention: str,
    category_label: str,
    item: str,
    quantity: int,
    payment_method: str,
    source_channel: discord.TextChannel,
    companion_preference: str | None = None,
    receiver_text: str | None = None,
) -> discord.Embed:
    embed = discord.Embed(
        title="新自助下單",
        color=discord.Color.blue()
    )

    embed.add_field(
        name="下單用戶",
        value=customer_mention,
        inline=False
    )

    embed.add_field(
        name="訂單類別",
        value=category_label,
        inline=True
    )

    embed.add_field(
        name="訂單項目",
        value=item,
        inline=True
    )

    embed.add_field(
        name="數量",
        value=f"{quantity} 單",
        inline=True
    )

    embed.add_field(
        name="付款方式",
        value=payment_method,
        inline=True
    )

    if companion_preference is not None:
        embed.add_field(
            name="指定選項",
            value=companion_preference,
            inline=False
        )

    if receiver_text is not None:
        embed.add_field(
            name="接單人員",
            value=receiver_text,
            inline=False
        )

    embed.add_field(
        name="來源票口",
        value=source_channel.mention,
        inline=False
    )

    return embed


class DispatchCancelClaimButton(discord.ui.Button):
    def __init__(self, disabled: bool = False):
        super().__init__(
            label="取消接單",
            style=discord.ButtonStyle.danger,
            custom_id="dispatch_cancel_claim",
            disabled=disabled
        )

    async def callback(self, interaction: discord.Interaction):
        view = self.view

        if not isinstance(view, DispatchClaimView):
            await interaction.response.send_message("接單面板狀態異常，請重新派單。", ephemeral=True)
            return

        await view.cancel_claim(interaction)


class DispatchClaimView(discord.ui.View):
    def __init__(
        self,
        customer_id: int,
        category_label: str,
        item: str,
        quantity: int,
        payment_method: str,
        source_channel_id: int,
        companion_preference: str | None = None,
        locked: bool = False,
        status: str = "active",
    ):
        super().__init__(timeout=None)
        self.customer_id = customer_id
        self.category_label = category_label
        self.item = item
        self.quantity = quantity
        self.payment_method = payment_method
        self.source_channel_id = source_channel_id
        self.companion_preference = companion_preference
        self.locked = locked
        self.status = status

        self.add_item(DispatchCancelClaimButton(disabled=locked))

        if locked:
            for item in self.children:
                item.disabled = True

    def get_receiver_label(self, claim_type: str) -> str:
        if claim_type == "companion":
            return "陪玩接單"
        return "打手接單"

    def get_required_role_id(self, claim_type: str) -> int:
        if claim_type == "companion":
            return COMPANION_RECEIVER_ROLE_ID
        return BOOSTER_RECEIVER_ROLE_ID

    def get_claim_data(self, message_id: int) -> dict:
        data = ORDER_CLAIMS.setdefault(
            message_id,
            {
                "companion": set(),
                "booster": set(),
                "locked": False,
            }
        )

        data.setdefault("customer_id", self.customer_id)
        data.setdefault("category_label", self.category_label)
        data.setdefault("item", self.item)
        data.setdefault("quantity", self.quantity)
        data.setdefault("payment_method", self.payment_method)
        data.setdefault("source_channel_id", self.source_channel_id)
        data.setdefault("companion_preference", self.companion_preference)
        data.setdefault("dispatch_channel_id", DISPATCH_CHANNEL_ID)
        data.setdefault("status", self.status)

        return data

    def build_receiver_text(self, claim_data: dict) -> str | None:
        companion_ids = sorted(claim_data.get("companion", set()))
        booster_ids = sorted(claim_data.get("booster", set()))

        lines = []

        if companion_ids:
            lines.append("陪玩接單：" + " ".join(f"<@{user_id}>" for user_id in companion_ids))

        if booster_ids:
            lines.append("打手接單：" + " ".join(f"<@{user_id}>" for user_id in booster_ids))

        if not lines:
            return None

        return "\n".join(lines)

    async def refresh_panel(self, interaction: discord.Interaction, locked: bool | None = None):
        guild = interaction.guild

        if guild is None:
            await interaction.response.send_message("這個功能只能在伺服器內使用。", ephemeral=True)
            return

        if not isinstance(interaction.channel, discord.TextChannel):
            await interaction.response.send_message("這個功能只能在派單文字頻道使用。", ephemeral=True)
            return

        source_channel = guild.get_channel(self.source_channel_id)

        if source_channel is None or not isinstance(source_channel, discord.TextChannel):
            await interaction.response.send_message("找不到來源票口。", ephemeral=True)
            return

        claim_data = self.get_claim_data(interaction.message.id)

        if locked is not None:
            claim_data["locked"] = locked

        remember_claim_data(interaction.message.id, claim_data)

        receiver_text = self.build_receiver_text(claim_data)

        new_embed = build_self_service_order_embed(
            customer_mention=f"<@{self.customer_id}>",
            category_label=self.category_label,
            item=self.item,
            quantity=_to_int(claim_data.get("quantity"), self.quantity) or 1,
            payment_method=self.payment_method,
            source_channel=source_channel,
            companion_preference=self.companion_preference,
            receiver_text=receiver_text
        )

        status = claim_data.get("status", "active")

        if status == "stored":
            new_embed.add_field(
                name="接單狀態",
                value=(
                    "已存單，接單面板已鎖定\n"
                    f"存單原因：{claim_data.get('stored_reason') or '未填寫'}\n"
                    f"預計恢復：{claim_data.get('stored_expected_time') or '未填寫'}"
                ),
                inline=False
            )
        elif claim_data.get("locked"):
            new_embed.add_field(
                name="接單狀態",
                value="已結單，接單面板已鎖定",
                inline=False
            )

        await interaction.response.edit_message(
            embed=new_embed,
            view=DispatchClaimView(
                customer_id=self.customer_id,
                category_label=self.category_label,
                item=self.item,
                quantity=_to_int(claim_data.get("quantity"), self.quantity) or 1,
                payment_method=self.payment_method,
                source_channel_id=self.source_channel_id,
                companion_preference=self.companion_preference,
                locked=bool(claim_data.get("locked")),
                status=str(claim_data.get("status", "active"))
            ),
            allowed_mentions=discord.AllowedMentions(
                users=True,
                roles=False,
                everyone=False
            )
        )

    async def claim_order(self, interaction: discord.Interaction, claim_type: str):
        if not isinstance(interaction.user, discord.Member):
            await interaction.response.send_message("無法確認你的身分組。", ephemeral=True)
            return

        if self.locked:
            await interaction.response.send_message("此單已結單，接單面板已鎖定。", ephemeral=True)
            return

        required_role_id = self.get_required_role_id(claim_type)
        receiver_label = self.get_receiver_label(claim_type)

        if not has_role(interaction.user, required_role_id):
            await interaction.response.send_message(
                f"你沒有「{receiver_label}」權限。",
                ephemeral=True
            )
            return

        claim_data = self.get_claim_data(interaction.message.id)

        if claim_data.get("locked"):
            await interaction.response.send_message("此單已結單，接單面板已鎖定。", ephemeral=True)
            return

        claim_data[claim_type].add(interaction.user.id)
        remember_claim_data(interaction.message.id, claim_data)

        await send_order_log(
            interaction.guild,
            title=f"{receiver_label}",
            fields=[
                ("接單人", interaction.user.mention, True),
                ("顧客", f"<@{self.customer_id}>", True),
                ("訂單", f"{self.category_label}｜{self.item} x{self.quantity}", False),
            ],
            color=discord.Color.green(),
        )

        await self.refresh_panel(interaction)

    async def cancel_claim(self, interaction: discord.Interaction):
        if not isinstance(interaction.user, discord.Member):
            await interaction.response.send_message("無法確認你的身分組。", ephemeral=True)
            return

        if self.locked:
            await interaction.response.send_message("此單已結單，接單面板已鎖定。", ephemeral=True)
            return

        claim_data = self.get_claim_data(interaction.message.id)

        if claim_data.get("locked"):
            await interaction.response.send_message("此單已結單，接單面板已鎖定。", ephemeral=True)
            return

        removed = False

        for key in ("companion", "booster"):
            if interaction.user.id in claim_data[key]:
                claim_data[key].remove(interaction.user.id)
                removed = True

        if not removed:
            await interaction.response.send_message("你目前沒有接這張單。", ephemeral=True)
            return

        remember_claim_data(interaction.message.id, claim_data)

        await send_order_log(
            interaction.guild,
            title="取消接單",
            fields=[
                ("操作人", interaction.user.mention, True),
                ("顧客", f"<@{self.customer_id}>", True),
                ("訂單", f"{self.category_label}｜{self.item} x{self.quantity}", False),
            ],
            color=discord.Color.orange(),
        )

        await self.refresh_panel(interaction)

    @discord.ui.button(
        label="陪玩接單",
        style=discord.ButtonStyle.success,
        custom_id="dispatch_claim_companion"
    )
    async def companion_claim(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.claim_order(interaction, "companion")

    @discord.ui.button(
        label="打手接單",
        style=discord.ButtonStyle.primary,
        custom_id="dispatch_claim_booster"
    )
    async def booster_claim(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.claim_order(interaction, "booster")


async def delete_dispatch_claim_panel_for_order(guild: discord.Guild, order_channel_id: int):
    """取消票口時，一併刪除派單頻道對應的接單面板，並清除保存資料。"""
    data = SELF_SERVICE_ORDER_SELECTIONS.get(order_channel_id, {})
    dispatch_message_id = _to_int(data.get("dispatch_message_id"))
    dispatch_channel_id = _to_int(data.get("dispatch_channel_id"), DISPATCH_CHANNEL_ID) or DISPATCH_CHANNEL_ID

    if dispatch_message_id is not None:
        dispatch_channel = guild.get_channel(dispatch_channel_id)

        if isinstance(dispatch_channel, discord.TextChannel):
            try:
                message = await dispatch_channel.fetch_message(dispatch_message_id)
                await message.delete()
            except discord.NotFound:
                pass
            except discord.Forbidden:
                print("Bot 權限不足，無法刪除派單接單面板。")
            except discord.HTTPException as e:
                print(f"刪除派單接單面板失敗：{e}")

        ORDER_CLAIMS.pop(dispatch_message_id, None)
        delete_claim_row_from_db(message_id=dispatch_message_id)

    if order_channel_id in SELF_SERVICE_ORDER_SELECTIONS:
        SELF_SERVICE_ORDER_SELECTIONS.pop(order_channel_id, None)
        delete_order_row_from_db(order_channel_id)
        save_bot_data()
    elif dispatch_message_id is not None:
        save_bot_data()


async def lock_dispatch_claim_panel(guild: discord.Guild, order_channel_id: int):
    """客服結單後，鎖定派單頻道對應的陪玩 / 打手接單面板。

    這版會同時處理「恢復訂單後重新發派單面板」的情況：
    如果 orders 裡記到的是舊 dispatch_message_id，會再從 ORDER_CLAIMS 裡找同一張票口的派單訊息，
    並把找到的派單面板全部鎖定，避免最新那則恢復訂單面板還能繼續被按。
    """
    data = SELF_SERVICE_ORDER_SELECTIONS.get(order_channel_id, {})
    dispatch_channel_id = data.get("dispatch_channel_id", DISPATCH_CHANNEL_ID)

    source_channel = guild.get_channel(order_channel_id)

    if source_channel is None or not isinstance(source_channel, discord.TextChannel):
        return

    dispatch_channel = guild.get_channel(dispatch_channel_id)

    if dispatch_channel is None or not isinstance(dispatch_channel, discord.TextChannel):
        return

    # 優先鎖 orders 目前記錄的派單訊息，同時補抓所有 claims 裡來源票口相同的派單訊息。
    candidate_message_ids: list[int] = []

    first_dispatch_message_id = _to_int(data.get("dispatch_message_id"))
    if first_dispatch_message_id is not None:
        candidate_message_ids.append(first_dispatch_message_id)

    for message_id, claim in list(ORDER_CLAIMS.items()):
        claim_source_channel_id = _to_int(claim.get("source_channel_id"))
        if claim_source_channel_id == order_channel_id:
            parsed_message_id = _to_int(message_id)
            if parsed_message_id is not None and parsed_message_id not in candidate_message_ids:
                candidate_message_ids.append(parsed_message_id)

    if not candidate_message_ids:
        return

    customer_id = data.get("customer_id")
    category = data.get("category")
    item = data.get("item", "未紀錄")
    quantity = _to_int(data.get("quantity"), 1) or 1
    payment_method = data.get("payment_method", "未紀錄")
    companion_preference = data.get("companion_preference")
    category_label = ORDER_CATEGORY_LABELS.get(category, category or data.get("category_label") or "未紀錄")
    customer_mention = f"<@{customer_id}>" if customer_id is not None else "未紀錄"

    data["closed"] = True
    data["status"] = "closed"
    data["closed_at"] = get_taipei_now_iso()
    data["quantity"] = quantity
    data["dispatch_channel_id"] = dispatch_channel_id

    locked_any = False
    newest_existing_message_id: int | None = None

    for dispatch_message_id in candidate_message_ids:
        try:
            message = await dispatch_channel.fetch_message(dispatch_message_id)
        except (discord.NotFound, discord.Forbidden, discord.HTTPException):
            continue

        claim_data = ORDER_CLAIMS.setdefault(
            dispatch_message_id,
            {
                "companion": set(),
                "booster": set(),
                "locked": False,
            }
        )

        # 若是舊資料，補齊缺少欄位。
        claim_data["customer_id"] = claim_data.get("customer_id") or customer_id
        claim_data["category_label"] = claim_data.get("category_label") or category_label
        claim_data["item"] = claim_data.get("item") or item
        claim_data["quantity"] = _to_int(claim_data.get("quantity"), quantity) or quantity
        claim_data["payment_method"] = claim_data.get("payment_method") or payment_method
        claim_data["source_channel_id"] = order_channel_id
        claim_data["companion_preference"] = claim_data.get("companion_preference") or companion_preference
        claim_data["dispatch_channel_id"] = dispatch_channel_id
        claim_data["locked"] = True
        claim_data["status"] = "closed"

        companion_ids = sorted(claim_data.get("companion", set()))
        booster_ids = sorted(claim_data.get("booster", set()))
        lines = []

        if companion_ids:
            lines.append("陪玩接單：" + " ".join(f"<@{user_id}>" for user_id in companion_ids))

        if booster_ids:
            lines.append("打手接單：" + " ".join(f"<@{user_id}>" for user_id in booster_ids))

        receiver_text = "\n".join(lines) if lines else None

        embed = build_self_service_order_embed(
            customer_mention=customer_mention,
            category_label=str(claim_data.get("category_label") or category_label),
            item=str(claim_data.get("item") or item),
            quantity=_to_int(claim_data.get("quantity"), quantity) or quantity,
            payment_method=str(claim_data.get("payment_method") or payment_method),
            source_channel=source_channel,
            companion_preference=claim_data.get("companion_preference") or companion_preference,
            receiver_text=receiver_text
        )
        embed.add_field(
            name="接單狀態",
            value="已結單，接單面板已鎖定",
            inline=False
        )

        try:
            await message.edit(
                embed=embed,
                view=DispatchClaimView(
                    customer_id=_to_int(claim_data.get("customer_id"), _to_int(customer_id, 0) or 0) or 0,
                    category_label=str(claim_data.get("category_label") or category_label),
                    item=str(claim_data.get("item") or item),
                    quantity=_to_int(claim_data.get("quantity"), quantity) or quantity,
                    payment_method=str(claim_data.get("payment_method") or payment_method),
                    source_channel_id=order_channel_id,
                    companion_preference=claim_data.get("companion_preference") or companion_preference,
                    locked=True,
                    status="closed"
                ),
                allowed_mentions=discord.AllowedMentions(
                    users=True,
                    roles=False,
                    everyone=False
                )
            )
            locked_any = True
            newest_existing_message_id = dispatch_message_id
            remember_claim_data(dispatch_message_id, claim_data)
        except (discord.NotFound, discord.Forbidden, discord.HTTPException):
            continue

    if locked_any:
        # 用實際成功鎖定的最新派單訊息覆蓋，避免之後再找到舊面板。
        if newest_existing_message_id is not None:
            data["dispatch_message_id"] = newest_existing_message_id
        remember_order_data(order_channel_id, data)
        save_bot_data()

async def store_dispatch_claim_panel(
    guild: discord.Guild,
    order_channel: discord.TextChannel,
    staff_member: discord.Member,
    reason: str,
    expected_time: str | None = None,
    note: str | None = None,
):
    """將訂單標記為存單，鎖定派單接單面板但保留票口。"""
    data = SELF_SERVICE_ORDER_SELECTIONS.get(order_channel.id, {})
    dispatch_message_id = data.get("dispatch_message_id")
    dispatch_channel_id = data.get("dispatch_channel_id", DISPATCH_CHANNEL_ID)

    if dispatch_message_id is None:
        raise ValueError("找不到這張訂單對應的派單訊息，請確認顧客是否已完成付款方式並送出派單。")

    dispatch_channel = guild.get_channel(dispatch_channel_id)

    if dispatch_channel is None or not isinstance(dispatch_channel, discord.TextChannel):
        raise ValueError("找不到派單頻道，請確認 DISPATCH_CHANNEL_ID 是否正確。")

    try:
        message = await dispatch_channel.fetch_message(dispatch_message_id)
    except discord.NotFound as exc:
        raise ValueError("找不到派單訊息，可能已被刪除。") from exc
    except discord.Forbidden as exc:
        raise ValueError("Bot 權限不足，無法讀取派單訊息。") from exc
    except discord.HTTPException as exc:
        raise ValueError(f"讀取派單訊息失敗：{exc}") from exc

    customer_id = data.get("customer_id") or get_order_customer_id_from_channel(order_channel)
    category = data.get("category")
    item = data.get("item", "未紀錄")
    quantity = _to_int(data.get("quantity"), 1) or 1
    payment_method = data.get("payment_method", "未紀錄")
    companion_preference = data.get("companion_preference")
    category_label = ORDER_CATEGORY_LABELS.get(category, category or data.get("category_label") or "未紀錄")
    customer_mention = f"<@{customer_id}>" if customer_id is not None else "未紀錄"

    claim_data = ORDER_CLAIMS.setdefault(
        dispatch_message_id,
        {
            "companion": set(),
            "booster": set(),
            "locked": False,
        }
    )
    claim_data["customer_id"] = customer_id
    claim_data["category_label"] = category_label
    claim_data["item"] = item
    claim_data["quantity"] = quantity
    claim_data["payment_method"] = payment_method
    claim_data["source_channel_id"] = order_channel.id
    claim_data["companion_preference"] = companion_preference
    claim_data["dispatch_channel_id"] = dispatch_channel_id
    claim_data["locked"] = True
    claim_data["status"] = "stored"
    claim_data["stored_at"] = get_taipei_now_iso()
    claim_data["stored_by"] = staff_member.id
    claim_data["stored_reason"] = reason
    claim_data["stored_expected_time"] = expected_time or None
    claim_data["stored_note"] = note or None

    data["customer_id"] = customer_id
    data["quantity"] = quantity
    data["dispatch_message_id"] = dispatch_message_id
    data["dispatch_channel_id"] = dispatch_channel_id
    data["closed"] = False
    data["status"] = "stored"
    data["stored_at"] = claim_data["stored_at"]
    data["stored_by"] = staff_member.id
    data["stored_reason"] = reason
    data["stored_expected_time"] = expected_time or None
    data["stored_note"] = note or None
    data["stored_reminders_sent"] = []

    remember_order_data(order_channel.id, data)
    remember_claim_data(dispatch_message_id, claim_data)

    companion_ids = sorted(claim_data.get("companion", set()))
    booster_ids = sorted(claim_data.get("booster", set()))
    lines = []

    if companion_ids:
        lines.append("陪玩接單：" + " ".join(f"<@{user_id}>" for user_id in companion_ids))

    if booster_ids:
        lines.append("打手接單：" + " ".join(f"<@{user_id}>" for user_id in booster_ids))

    receiver_text = "\n".join(lines) if lines else None

    embed = build_self_service_order_embed(
        customer_mention=customer_mention,
        category_label=category_label,
        item=item,
        quantity=quantity,
        payment_method=payment_method,
        source_channel=order_channel,
        companion_preference=companion_preference,
        receiver_text=receiver_text
    )
    embed.add_field(
        name="接單狀態",
        value=(
            "已存單，接單面板已鎖定\n"
            f"存單原因：{reason}\n"
            f"預計恢復：{expected_time or '未填寫'}"
        ),
        inline=False
    )

    if note:
        embed.add_field(
            name="存單備註",
            value=note,
            inline=False
        )

    await message.edit(
        embed=embed,
        view=DispatchClaimView(
            customer_id=customer_id or 0,
            category_label=category_label,
            item=item,
            quantity=quantity,
            payment_method=payment_method,
            source_channel_id=order_channel.id,
            companion_preference=companion_preference,
            locked=True,
            status="stored"
        ),
        allowed_mentions=discord.AllowedMentions(
            users=True,
            roles=False,
            everyone=False
        )
    )


async def resume_stored_order(
    guild: discord.Guild,
    order_channel: discord.TextChannel,
    staff_member: discord.Member,
):
    """恢復已存單的訂單，保留原本接單人員，並把派單面板重新發到派單頻道最下面。"""
    data = SELF_SERVICE_ORDER_SELECTIONS.get(order_channel.id, {})
    old_dispatch_message_id = data.get("dispatch_message_id")
    dispatch_channel_id = data.get("dispatch_channel_id", DISPATCH_CHANNEL_ID)

    if old_dispatch_message_id is None:
        raise ValueError("找不到這張訂單對應的派單訊息，無法恢復。")

    dispatch_channel = guild.get_channel(dispatch_channel_id)

    if dispatch_channel is None or not isinstance(dispatch_channel, discord.TextChannel):
        raise ValueError("找不到派單頻道，請確認 DISPATCH_CHANNEL_ID 是否正確。")

    old_message = None

    try:
        old_message = await dispatch_channel.fetch_message(old_dispatch_message_id)
    except discord.NotFound:
        # 舊訊息不見時仍可用保存資料重新發一則，只要 bot_data.json 還有接單資料。
        old_message = None
    except discord.Forbidden as exc:
        raise ValueError("Bot 權限不足，無法讀取派單訊息。") from exc
    except discord.HTTPException as exc:
        raise ValueError(f"讀取派單訊息失敗：{exc}") from exc

    claim_data = ORDER_CLAIMS.get(old_dispatch_message_id)

    if not claim_data:
        raise ValueError("找不到已保存的接單資料，請重新派單。")

    customer_id = claim_data.get("customer_id") or data.get("customer_id") or get_order_customer_id_from_channel(order_channel)
    category_label = claim_data.get("category_label") or ORDER_CATEGORY_LABELS.get(data.get("category"), data.get("category") or "未紀錄")
    item = claim_data.get("item") or data.get("item", "未紀錄")
    quantity = _to_int(claim_data.get("quantity"), _to_int(data.get("quantity"), 1)) or 1
    payment_method = claim_data.get("payment_method") or data.get("payment_method", "未紀錄")
    companion_preference = claim_data.get("companion_preference") or data.get("companion_preference")
    customer_mention = f"<@{customer_id}>" if customer_id is not None else "未紀錄"

    claim_data["locked"] = False
    claim_data["status"] = "active"
    claim_data["customer_id"] = customer_id
    claim_data["category_label"] = str(category_label)
    claim_data["item"] = str(item)
    claim_data["quantity"] = quantity
    claim_data["payment_method"] = str(payment_method)
    claim_data["source_channel_id"] = order_channel.id
    claim_data["companion_preference"] = companion_preference
    claim_data["dispatch_channel_id"] = dispatch_channel.id

    # 存單相關資料保留在 bot_data.json 裡當紀錄，但不再顯示為已存單。
    data["closed"] = False
    data["status"] = "active"
    data["quantity"] = quantity
    data["dispatch_channel_id"] = dispatch_channel.id

    companion_ids = sorted(claim_data.get("companion", set()))
    booster_ids = sorted(claim_data.get("booster", set()))
    lines = []

    if companion_ids:
        lines.append("陪玩接單：" + " ".join(f"<@{user_id}>" for user_id in companion_ids))

    if booster_ids:
        lines.append("打手接單：" + " ".join(f"<@{user_id}>" for user_id in booster_ids))

    receiver_text = "\n".join(lines) if lines else None

    embed = build_self_service_order_embed(
        customer_mention=customer_mention,
        category_label=str(category_label),
        item=str(item),
        quantity=quantity,
        payment_method=str(payment_method),
        source_channel=order_channel,
        companion_preference=companion_preference,
        receiver_text=receiver_text
    )
    embed.add_field(
        name="接單狀態",
        value=f"已由 {staff_member.mention} 恢復訂單，接單面板已重新發到最新位置。",
        inline=False
    )

    new_message = await dispatch_channel.send(
        embed=embed,
        view=DispatchClaimView(
            customer_id=customer_id or 0,
            category_label=str(category_label),
            item=str(item),
            quantity=quantity,
            payment_method=str(payment_method),
            source_channel_id=order_channel.id,
            companion_preference=companion_preference,
            locked=False,
            status="active"
        ),
        allowed_mentions=discord.AllowedMentions(
            users=True,
            roles=False,
            everyone=False
        )
    )

    # 刪除舊的存單面板，避免同一張單在派單頻道出現兩個面板。
    if old_message is not None:
        try:
            await old_message.delete(reason=f"Stored order resumed by {staff_member}")
        except (discord.NotFound, discord.Forbidden, discord.HTTPException):
            pass

    # 把接單資料移到新的 message_id，保留原本陪玩/打手接單人員。
    ORDER_CLAIMS.pop(old_dispatch_message_id, None)
    ORDER_CLAIMS[new_message.id] = claim_data
    data["dispatch_message_id"] = new_message.id

    remember_order_data(order_channel.id, data)
    remember_claim_data(new_message.id, claim_data)
    save_bot_data()


class StoreOrderModal(discord.ui.Modal, title="存單"):
    reason = discord.ui.TextInput(
        label="存單原因",
        placeholder="例如：顧客暫時無法遊玩、改約時間、等待活動開啟",
        required=True,
        max_length=200
    )

    expected_time = discord.ui.TextInput(
        label="預計恢復時間",
        placeholder="例如：今晚 20:00、明天、未定",
        required=False,
        max_length=100
    )

    note = discord.ui.TextInput(
        label="備註",
        placeholder="可填寫付款狀態、注意事項或客服備註",
        style=discord.TextStyle.paragraph,
        required=False,
        max_length=800
    )

    async def on_submit(self, interaction: discord.Interaction):
        if not isinstance(interaction.user, discord.Member):
            await interaction.response.send_message("無法確認你的身分組。", ephemeral=True)
            return

        if not is_customer_staff(interaction.user):
            await interaction.response.send_message("只有客服可以存單。", ephemeral=True)
            return

        guild = interaction.guild

        if guild is None:
            await interaction.response.send_message("這個功能只能在伺服器內使用。", ephemeral=True)
            return

        if not isinstance(interaction.channel, discord.TextChannel):
            await interaction.response.send_message("這個功能只能在下單票口內使用。", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)

        try:
            await store_dispatch_claim_panel(
                guild=guild,
                order_channel=interaction.channel,
                staff_member=interaction.user,
                reason=self.reason.value.strip(),
                expected_time=self.expected_time.value.strip() or None,
                note=self.note.value.strip() or None,
            )
            await send_order_log(
                guild,
                title="訂單已存單",
                fields=[
                    ("票口", interaction.channel.mention, True),
                    ("操作人員", interaction.user.mention, True),
                    ("存單原因", self.reason.value.strip(), False),
                    ("預計恢復", self.expected_time.value.strip() or "未填寫", True),
                    ("備註", self.note.value.strip() or "未填寫", False),
                ],
                color=discord.Color.gold(),
            )
        except ValueError as e:
            await interaction.followup.send(str(e), ephemeral=True)
            return

        await interaction.channel.send(
            f"此訂單已由 {interaction.user.mention} 存單。\n\n"
            f"存單原因：{self.reason.value.strip()}\n"
            f"預計恢復：{self.expected_time.value.strip() or '未填寫'}\n"
            f"備註：{self.note.value.strip() or '無'}",
            allowed_mentions=discord.AllowedMentions(
                users=True,
                roles=False,
                everyone=False
            )
        )

        await interaction.followup.send("已存單，派單頻道接單面板已鎖定。", ephemeral=True)


class PaymentMethodSelect(discord.ui.Select):
    def __init__(self, customer_id: int, channel_id: int):
        self.customer_id = customer_id
        self.channel_id = channel_id

        options = [
            discord.SelectOption(label=method, value=method)
            for method in PAYMENT_METHOD_OPTIONS
        ]

        super().__init__(
            placeholder="請選擇付款方式",
            min_values=1,
            max_values=1,
            options=options,
            custom_id="payment_method_select",
            row=0
        )

    async def callback(self, interaction: discord.Interaction):
        if not can_operate_self_service_order(interaction.user, self.customer_id):
            await interaction.response.send_message("只有開這張票口的用戶或客服可以選擇付款方式。", ephemeral=True)
            return

        data = SELF_SERVICE_ORDER_SELECTIONS.setdefault(self.channel_id, {})
        data["customer_id"] = self.customer_id
        selected_method = self.values[0]
        data["payment_method"] = selected_method
        remember_order_data(self.channel_id, data)
        await log_self_service_proxy_action(
            interaction,
            self.customer_id,
            "選擇付款方式",
            selected_method,
        )

        payment_info = {
            "轉帳": (
                "銀行轉帳-國泰\n"
                "代碼：013\n"
                "帳號：135700021419"
            ),
            "街口": (
                "街口支付\n"
                "代碼：396\n"
                "帳號：900884222"
            ),
        }.get(selected_method)

        if payment_info is not None:
            await interaction.response.send_message(
                f"已選擇付款方式：{selected_method}\n"
                f"請闆闆先付款再幫我們按送出喔~\n\n"
                f"```text\n{payment_info}\n```",
                ephemeral=True
            )
        else:
            await interaction.response.defer()


class PaymentMethodView(discord.ui.View):
    def __init__(self, customer_id: int, channel_id: int, submitted: bool = False):
        super().__init__(timeout=86400)
        self.customer_id = customer_id
        self.channel_id = channel_id
        self.submitted = submitted
        self.add_item(PaymentMethodSelect(customer_id, channel_id))

        if submitted:
            for child in self.children:
                child.disabled = True
                if isinstance(child, discord.ui.Button) and child.custom_id == "payment_method_submit_button":
                    child.label = "已送出"
                    child.style = discord.ButtonStyle.secondary

    @discord.ui.button(
        label="送出",
        style=discord.ButtonStyle.success,
        custom_id="payment_method_submit_button",
        row=1
    )
    async def submit_payment(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not can_operate_self_service_order(interaction.user, self.customer_id):
            await interaction.response.send_message("只有開這張票口的用戶或客服可以送出付款方式。", ephemeral=True)
            return

        guild = interaction.guild

        if guild is None:
            await interaction.response.send_message("這個功能只能在伺服器內使用。", ephemeral=True)
            return

        if not isinstance(interaction.channel, discord.TextChannel):
            await interaction.response.send_message("無法確認目前票口頻道。", ephemeral=True)
            return

        data = SELF_SERVICE_ORDER_SELECTIONS.get(self.channel_id, {})
        category = data.get("category")
        item = data.get("item")
        quantity = _to_int(data.get("quantity"), 1) or 1
        companion_preference = data.get("companion_preference")
        payment_method = data.get("payment_method")

        if category is None or item is None:
            await interaction.response.send_message("找不到訂單資料，請回到自助下單面板重新選擇。", ephemeral=True)
            return

        if payment_method is None:
            await interaction.response.send_message("請先選擇付款方式，再按送出。", ephemeral=True)
            return

        if data.get("dispatch_message_id") is not None:
            dispatch_channel_id = _to_int(data.get("dispatch_channel_id"), DISPATCH_CHANNEL_ID) or DISPATCH_CHANNEL_ID
            dispatch_message_id = _to_int(data.get("dispatch_message_id"))
            dispatch_channel = guild.get_channel(dispatch_channel_id)
            if isinstance(dispatch_channel, discord.TextChannel) and dispatch_message_id is not None:
                await interaction.response.send_message(
                    f"這張單已經送出派單，請不要重複送出。\n派單訊息：https://discord.com/channels/{guild.id}/{dispatch_channel.id}/{dispatch_message_id}",
                    ephemeral=True
                )
            else:
                await interaction.response.send_message("這張單已經送出派單，請不要重複送出。", ephemeral=True)
            return

        if data.get("dispatch_submitting"):
            await interaction.response.send_message("這張單正在送出派單，請稍等，不要重複點擊。", ephemeral=True)
            return

        item_category = ORDER_ITEM_TO_CATEGORY.get(item)

        if item_category != category:
            await interaction.response.send_message(
                "你選擇的訂單類別與訂單項目不一致，請回到自助下單面板重新選擇。",
                ephemeral=True
            )
            return

        if item in SPECIAL_COMPANION_ITEMS and companion_preference is None:
            await interaction.response.send_message(
                "這個項目請先回到自助下單面板選擇「不指定陪玩/打手」或「指定陪玩/打手」。",
                ephemeral=True
            )
            return

        if item not in QUANTITY_SELECT_ITEMS:
            quantity = 1
            data["quantity"] = 1
            remember_order_data(self.channel_id, data)
        elif quantity < 1 or quantity > max(QUANTITY_OPTIONS):
            await interaction.response.send_message("數量選擇異常，請回到自助下單面板重新選擇。", ephemeral=True)
            return

        if companion_preference is None:
            companion_preference = "不指定陪玩/打手"
            data["companion_preference"] = companion_preference
            remember_order_data(self.channel_id, data)

        dispatch_channel = guild.get_channel(DISPATCH_CHANNEL_ID)

        if dispatch_channel is None or not isinstance(dispatch_channel, discord.TextChannel):
            await interaction.response.send_message(
                "找不到派單頻道，請確認 DISPATCH_CHANNEL_ID 是否正確。",
                ephemeral=True
            )
            return

        category_label = ORDER_CATEGORY_LABELS[category]
        data["customer_id"] = self.customer_id
        remember_order_data(self.channel_id, data)

        embed = build_self_service_order_embed(
            customer_mention=f"<@{self.customer_id}>",
            category_label=category_label,
            item=item,
            quantity=quantity,
            payment_method=payment_method,
            source_channel=interaction.channel,
            companion_preference=companion_preference
        )

        data["dispatch_submitting"] = True
        remember_order_data(self.channel_id, data)

        await interaction.response.defer(ephemeral=True)

        try:
            dispatch_message = await dispatch_channel.send(
                embed=embed,
                view=DispatchClaimView(
                    customer_id=self.customer_id,
                    category_label=category_label,
                    item=item,
                    quantity=quantity,
                    payment_method=payment_method,
                    source_channel_id=interaction.channel.id,
                    companion_preference=companion_preference
                ),
                allowed_mentions=discord.AllowedMentions(
                    users=True,
                    roles=False,
                    everyone=False
                )
            )
        except discord.HTTPException as e:
            data.pop("dispatch_submitting", None)
            remember_order_data(self.channel_id, data)
            await interaction.followup.send(f"派單送出失敗：{e}", ephemeral=True)
            return

        ORDER_CLAIMS[dispatch_message.id] = {
            "companion": set(),
            "booster": set(),
            "locked": False,
            "customer_id": self.customer_id,
            "category_label": category_label,
            "item": item,
            "quantity": quantity,
            "payment_method": payment_method,
            "source_channel_id": interaction.channel.id,
            "companion_preference": companion_preference,
            "dispatch_channel_id": dispatch_channel.id,
        }
        data["quantity"] = quantity
        data["dispatch_message_id"] = dispatch_message.id
        data["dispatch_channel_id"] = dispatch_channel.id
        data["closed"] = False
        data["payment_submitted_at"] = get_taipei_now_iso()
        data["payment_submitted_by"] = interaction.user.id
        data.pop("dispatch_submitting", None)
        remember_order_data(interaction.channel.id, data)
        remember_claim_data(dispatch_message.id, ORDER_CLAIMS[dispatch_message.id])

        await log_self_service_proxy_action(
            interaction,
            self.customer_id,
            "送出派單",
            f"{category_label}｜{item} x{quantity}｜{payment_method}",
        )

        await send_order_log(
            guild,
            title="新自助下單已派單",
            fields=[
                ("顧客", f"<@{self.customer_id}>", True),
                ("訂單類別", category_label, True),
                ("訂單項目", item, True),
                ("數量", f"{quantity} 單", True),
                ("付款方式", payment_method, True),
                ("指定選項", companion_preference, True),
                ("送出人員", interaction.user.mention, True),
                ("是否代操作", "是" if interaction.user.id != self.customer_id else "否", True),
                ("票口", interaction.channel.mention, False),
                ("派單訊息", dispatch_message.jump_url, False),
            ],
            color=discord.Color.blue(),
        )

        submitted_embed = discord.Embed(
            title="付款方式",
            description=(
                f"下單用戶：<@{self.customer_id}>\n\n"
                f"訂單類別：{category_label}\n"
                f"訂單項目：{item}\n"
                f"數量：{quantity} 單\n"
                f"付款方式：{payment_method}\n\n"
                "✅ 已送出派單，此付款面板已鎖定，請勿重複操作。\n"
                f"派單訊息：{dispatch_message.jump_url}"
            ),
            color=discord.Color.green()
        )

        if companion_preference is not None:
            submitted_embed.add_field(
                name="指定選項",
                value=companion_preference,
                inline=False
            )

        try:
            await interaction.message.edit(
                embed=submitted_embed,
                view=PaymentMethodView(
                    customer_id=self.customer_id,
                    channel_id=self.channel_id,
                    submitted=True,
                ),
                allowed_mentions=discord.AllowedMentions(
                    users=True,
                    roles=False,
                    everyone=False
                )
            )
        except discord.HTTPException:
            pass

        await interaction.followup.send(
            f"已送出派單：{dispatch_message.jump_url}",
            ephemeral=True
        )

        operation_embed = discord.Embed(
            title="訂單操作",
            description="請客服從下拉式清單選擇後，按下確認。",
            color=discord.Color.green()
        )

        await interaction.channel.send(
            embed=operation_embed,
            view=StaffOrderOperationView()
        )


class SelfServiceOrderView(discord.ui.View):
    def __init__(self, customer_id: int, channel_id: int, selected_category: str | None = None):
        super().__init__(timeout=86400)
        self.customer_id = customer_id
        self.channel_id = channel_id

        data = SELF_SERVICE_ORDER_SELECTIONS.get(channel_id, {})
        category = selected_category or data.get("category")
        selected_item = data.get("item")
        selected_preference = data.get("companion_preference")
        selected_quantity = _to_int(data.get("quantity"), 1) or 1

        self.add_item(SelfServiceOrderCategorySelect(customer_id, channel_id, category))
        self.add_item(SelfServiceOrderItemSelect(customer_id, channel_id, category, selected_item))
        self.add_item(SelfServiceCompanionPreferenceSelect(customer_id, channel_id, selected_item, selected_preference))
        self.add_item(SelfServiceOrderQuantitySelect(customer_id, channel_id, selected_item, selected_quantity))

    @discord.ui.button(
        label="前往付款",
        style=discord.ButtonStyle.success,
        custom_id="self_service_order_go_payment_button",
        row=4
    )
    async def go_payment(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not can_operate_self_service_order(interaction.user, self.customer_id):
            await interaction.response.send_message("只有開這張票口的用戶或客服可以操作訂單。", ephemeral=True)
            return

        if not isinstance(interaction.channel, discord.TextChannel):
            await interaction.response.send_message("無法確認目前票口頻道。", ephemeral=True)
            return

        data = SELF_SERVICE_ORDER_SELECTIONS.get(self.channel_id, {})
        category = data.get("category")
        item = data.get("item")
        quantity = _to_int(data.get("quantity"), 1) or 1
        companion_preference = data.get("companion_preference")

        if category is None or item is None:
            await interaction.response.send_message("請先選擇訂單類別與訂單項目，再前往付款。", ephemeral=True)
            return

        item_category = ORDER_ITEM_TO_CATEGORY.get(item)

        if item_category != category:
            await interaction.response.send_message(
                "你選擇的訂單類別與訂單項目不一致，請重新選擇。",
                ephemeral=True
            )
            return

        if item in SPECIAL_COMPANION_ITEMS and companion_preference is None:
            await interaction.response.send_message(
                "這個項目請先選擇「不指定陪玩/打手」或「指定陪玩/打手」，再前往付款。",
                ephemeral=True
            )
            return

        if item not in QUANTITY_SELECT_ITEMS:
            quantity = 1
            data["quantity"] = 1
            remember_order_data(self.channel_id, data)
        elif quantity < 1 or quantity > max(QUANTITY_OPTIONS):
            await interaction.response.send_message("請重新選擇正確的數量。", ephemeral=True)
            return

        if companion_preference is None:
            companion_preference = "不指定陪玩/打手"
            data["companion_preference"] = companion_preference
            remember_order_data(self.channel_id, data)

        category_label = ORDER_CATEGORY_LABELS[category]
        payment_embed = discord.Embed(
            title="付款方式",
            description=(
                f"下單用戶：<@{self.customer_id}>\n\n"
                f"訂單類別：{category_label}\n"
                f"訂單項目：{item}\n"
                f"數量：{quantity} 單\n"
                "請選擇付款方式，完成後按「送出」。"
            ),
            color=discord.Color.gold()
        )

        if data.get("companion_preference") is not None:
            payment_embed.add_field(
                name="指定選項",
                value=data["companion_preference"],
                inline=False
            )

        await interaction.response.defer()

        await interaction.channel.send(
            embed=payment_embed,
            view=PaymentMethodView(
                customer_id=self.customer_id,
                channel_id=self.channel_id
            ),
            allowed_mentions=discord.AllowedMentions(
                users=True,
                roles=False,
                everyone=False
            )
        )
        await log_self_service_proxy_action(
            interaction,
            self.customer_id,
            "前往付款",
            f"{category_label}｜{item} x{quantity}｜{companion_preference}",
        )

class StaffOrderOperationSelect(discord.ui.Select):
    def __init__(self):
        options = [
            discord.SelectOption(
                label="已結單",
                value="done",
                description="填寫收據並送出評論按鈕"
            ),
            discord.SelectOption(
                label="存單",
                value="store",
                description="保留票口並鎖定派單接單面板"
            ),
            discord.SelectOption(
                label="恢復訂單",
                value="resume",
                description="恢復已存單訂單，重新開放接單面板"
            ),
            discord.SelectOption(
                label="取消訂單",
                value="cancel",
                description="取消並關閉這張下單票口"
            ),
        ]

        super().__init__(
            placeholder="訂單操作選項",
            min_values=1,
            max_values=1,
            options=options,
            custom_id="staff_order_operation_select",
            row=0
        )

    async def callback(self, interaction: discord.Interaction):
        if not isinstance(interaction.user, discord.Member):
            await interaction.response.send_message("無法確認你的身分組。", ephemeral=True)
            return

        if not is_customer_staff(interaction.user):
            await interaction.response.send_message("只有客服可以操作訂單。", ephemeral=True)
            return

        if not isinstance(interaction.channel, discord.TextChannel):
            await interaction.response.send_message("這個功能只能在下單票口內使用。", ephemeral=True)
            return

        STAFF_ORDER_OPERATION_SELECTIONS[(interaction.channel.id, interaction.user.id)] = self.values[0]

        await interaction.response.defer()


class StaffOrderOperationView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(StaffOrderOperationSelect())

    @discord.ui.button(
        label="確認",
        style=discord.ButtonStyle.success,
        custom_id="staff_order_operation_confirm",
        row=1
    )
    async def confirm_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not isinstance(interaction.user, discord.Member):
            await interaction.response.send_message("無法確認你的身分組。", ephemeral=True)
            return

        if not is_customer_staff(interaction.user):
            await interaction.response.send_message("只有客服可以操作訂單。", ephemeral=True)
            return

        if not isinstance(interaction.channel, discord.TextChannel):
            await interaction.response.send_message("這個功能只能在下單票口內使用。", ephemeral=True)
            return

        selected = STAFF_ORDER_OPERATION_SELECTIONS.get((interaction.channel.id, interaction.user.id))

        if selected is None:
            await interaction.response.send_message(
                "請先從下拉式清單選擇操作，再按確認。",
                ephemeral=True
            )
            return

        STAFF_ORDER_OPERATION_SELECTIONS.pop((interaction.channel.id, interaction.user.id), None)

        if selected == "done":
            await interaction.response.send_modal(ReceiptModal())
        elif selected == "store":
            await interaction.response.send_modal(StoreOrderModal())
        elif selected == "resume":
            guild = interaction.guild

            if guild is None:
                await interaction.response.send_message("這個功能只能在伺服器內使用。", ephemeral=True)
                return

            await interaction.response.defer(ephemeral=True)

            try:
                await resume_stored_order(
                    guild=guild,
                    order_channel=interaction.channel,
                    staff_member=interaction.user,
                )
                await send_order_log(
                    guild,
                    title="訂單已恢復",
                    fields=[
                        ("票口", interaction.channel.mention, True),
                        ("操作人員", interaction.user.mention, True),
                    ],
                    color=discord.Color.green(),
                )
            except ValueError as e:
                await interaction.followup.send(str(e), ephemeral=True)
                return

            await interaction.channel.send(
                f"此訂單已由 {interaction.user.mention} 恢復，派單頻道接單面板已重新開放。",
                allowed_mentions=discord.AllowedMentions(
                    users=True,
                    roles=False,
                    everyone=False
                )
            )
            await interaction.followup.send("已恢復訂單。", ephemeral=True)
        elif selected == "cancel":
            await interaction.response.send_message(
                "是否確定要取消這筆訂單？",
                view=ConfirmCancelOrderView(),
                ephemeral=True
            )
        else:
            await interaction.response.send_message(
                "選擇項目異常，請重新選擇一次。",
                ephemeral=True
            )


class OrderControlView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(OrderControlSelect())

    @discord.ui.button(
        label="確認",
        style=discord.ButtonStyle.success,
        custom_id="order_control_confirm",
        row=1
    )
    async def confirm_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not isinstance(interaction.user, discord.Member):
            await interaction.response.send_message("無法確認你的身分組。", ephemeral=True)
            return

        if not is_customer_staff(interaction.user):
            await interaction.response.send_message("只有客服可以操作訂單。", ephemeral=True)
            return

        if not isinstance(interaction.channel, discord.TextChannel):
            await interaction.response.send_message("這個功能只能在下單票口內使用。", ephemeral=True)
            return

        selected = ORDER_CONTROL_SELECTIONS.get((interaction.channel.id, interaction.user.id))

        if selected is None:
            await interaction.response.send_message(
                "請先從下拉式清單選擇操作，再按確認。",
                ephemeral=True
            )
            return

        ORDER_CONTROL_SELECTIONS.pop((interaction.channel.id, interaction.user.id), None)

        if selected == "cancel":
            await interaction.response.send_message(
                "是否確定要取消這筆訂單？",
                view=ConfirmCancelOrderView(),
                ephemeral=True
            )
            return

        if selected != "dispatch":
            await interaction.response.send_message(
                "選擇項目異常，請重新選擇一次。",
                ephemeral=True
            )
            return

        customer_id = get_order_customer_id_from_channel(interaction.channel)

        if customer_id is None:
            await interaction.response.send_message(
                "無法辨識開單用戶，請確認這張票口是不是由下單功能建立。",
                ephemeral=True
            )
            return

        customer = interaction.guild.get_member(customer_id) if interaction.guild else None
        customer_mention = customer.mention if customer is not None else f"<@{customer_id}>"

        embed = discord.Embed(
            title="自助下單",
            description=(
                f"下單用戶：{customer_mention}\n\n"
                "請下單用戶選擇訂單類別與訂單項目，完成後按「前往付款」。\n"
                "如果選擇娛樂陪、技術陪，數量欄位可選擇 1～8 單；1 單 = 1 小時，2 單 = 2 小時，依此類推。\n"
                "如果選擇娛樂陪、技術陪、保底單，請額外選擇是否指定陪玩/打手。"
            ),
            color=discord.Color.purple()
        )

        await interaction.response.defer()

        await interaction.channel.send(
            embed=embed,
            view=SelfServiceOrderView(
                customer_id=customer_id,
                channel_id=interaction.channel.id
            ),
            allowed_mentions=discord.AllowedMentions(
                users=True,
                roles=False,
                everyone=False
            )
        )

# ========= 入職操作 Modal / 按鈕 =========

class RecruitControlView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(
        label="已完成考核",
        style=discord.ButtonStyle.success,
        custom_id="recruit_exam_completed_button"
    )
    async def exam_completed(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not isinstance(interaction.user, discord.Member):
            await interaction.response.send_message("無法確認你的身分組。", ephemeral=True)
            return

        if not is_exam_staff(interaction.user):
            await interaction.response.send_message("只有考官或店長可以操作。", ephemeral=True)
            return

        channel = interaction.channel

        await interaction.response.send_message(
            f"此入職申請已由 {interaction.user.mention} 標記為已完成考核。\n"
            "頻道將在 3 秒後關閉。",
            ephemeral=False,
            allowed_mentions=discord.AllowedMentions(
                users=True,
                roles=False,
                everyone=False
            )
        )

        await asyncio.sleep(3)

        if isinstance(channel, discord.TextChannel):
            await remove_recruit_applicant_role(interaction.guild, channel)
            await channel.delete(reason=f"Recruit exam completed by {interaction.user}")


# ========= 客訴 Modal / 按鈕 =========

class ComplaintModal(discord.ui.Modal, title="客訴單"):
    complaint_content = discord.ui.TextInput(
        label="客訴內容",
        placeholder="請輸入你的客訴內容",
        style=discord.TextStyle.paragraph,
        required=True,
        max_length=1500
    )

    async def on_submit(self, interaction: discord.Interaction):
        guild = interaction.guild

        if guild is None:
            await interaction.response.send_message("這個功能只能在伺服器內使用。", ephemeral=True)
            return

        receive_channel = guild.get_channel(COMPLAINT_RECEIVE_CHANNEL_ID)

        if receive_channel is None or not isinstance(receive_channel, discord.TextChannel):
            await interaction.response.send_message(
                "找不到客訴接收頻道，請確認 COMPLAINT_RECEIVE_CHANNEL_ID 是否正確。",
                ephemeral=True
            )
            return

        boss_mention = interaction.user.mention
        boss_id = interaction.user.id

        embed = discord.Embed(
            title="客訴",
            description=(
                f"有一則來自 {boss_mention} 的客訴!\n"
                f"申請人 ID：{boss_id}\n\n"
                f"客訴內容：\n{self.complaint_content.value}"
            ),
            color=discord.Color.red()
        )

        await receive_channel.send(
            embed=embed,
            view=ComplaintResolveView(),
            allowed_mentions=discord.AllowedMentions(
                users=False,
                roles=False,
                everyone=False
            )
        )

        await interaction.response.send_message(
            "你的客訴已送出，會由相關人員處理。",
            ephemeral=True
        )


class ComplaintPanelView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(
        label="客訴單",
        style=discord.ButtonStyle.danger,
        custom_id="complaint_form_button"
    )
    async def complaint_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(ComplaintModal())


class ComplaintResolveView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(
        label="已解決",
        style=discord.ButtonStyle.success,
        custom_id="complaint_resolved_button"
    )
    async def resolved_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not isinstance(interaction.user, discord.Member):
            await interaction.response.send_message("無法確認你的身分組。", ephemeral=True)
            return

        if not is_complaint_staff(interaction.user):
            await interaction.response.send_message("只有客服或店長可以標記已解決。", ephemeral=True)
            return

        button.disabled = True
        button.label = "已解決"

        embed = interaction.message.embeds[0] if interaction.message.embeds else None

        if embed is not None:
            embed.color = discord.Color.green()
            embed.add_field(
                name="處理狀態",
                value=f"已由 {interaction.user.mention} 標記為已解決",
                inline=False
            )

            await interaction.response.edit_message(embed=embed, view=self)
        else:
            await interaction.response.edit_message(
                content=f"此客訴已由 {interaction.user.mention} 標記為已解決。",
                view=self
            )


# ========= 顧客意見箱 Modal / 按鈕 =========

class FeedbackModal(discord.ui.Modal, title="顧客意見箱"):
    feedback_content = discord.ui.TextInput(
        label="意見內容",
        placeholder="請輸入你的意見或建議",
        style=discord.TextStyle.paragraph,
        required=True,
        max_length=1500
    )

    async def on_submit(self, interaction: discord.Interaction):
        guild = interaction.guild

        if guild is None:
            await interaction.response.send_message("這個功能只能在伺服器內使用。", ephemeral=True)
            return

        receive_channel = guild.get_channel(COMPLAINT_RECEIVE_CHANNEL_ID)

        if receive_channel is None or not isinstance(receive_channel, discord.TextChannel):
            await interaction.response.send_message(
                "找不到意見接收頻道，請確認 COMPLAINT_RECEIVE_CHANNEL_ID 是否正確。",
                ephemeral=True
            )
            return

        boss_mention = interaction.user.mention
        boss_id = interaction.user.id

        embed = discord.Embed(
            title="顧客意見箱",
            description=(
                f"有一則來自 {boss_mention} 的顧客意見。\n"
                f"申請人 ID：{boss_id}\n\n"
                f"意見內容：\n{self.feedback_content.value}"
            ),
            color=discord.Color.blue()
        )

        await receive_channel.send(
            embed=embed,
            view=ComplaintResolveView(),
            allowed_mentions=discord.AllowedMentions(
                users=False,
                roles=False,
                everyone=False
            )
        )

        await interaction.response.send_message(
            "你的意見已送出，感謝闆闆回饋！",
            ephemeral=True
        )


class FeedbackPanelView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(
        label="填寫意見",
        style=discord.ButtonStyle.primary,
        custom_id="feedback_form_button"
    )
    async def feedback_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(FeedbackModal())


# ========= 下單 / 入職 Modal =========

class OrderModal(discord.ui.Modal, title="我要下單"):
    rule_confirm = discord.ui.TextInput(
        label="是否已詳閱規章內容",
        placeholder="請輸入：是",
        required=True,
        max_length=20
    )

    async def on_submit(self, interaction: discord.Interaction):
        if not is_agree_answer(self.rule_confirm.value):
            await interaction.response.send_message(
                "你尚未詳閱規章內容，暫時無法下單。請詳閱規章後再重新開單。",
                ephemeral=True
            )
            return

        guild = interaction.guild
        member = interaction.user

        if guild is None:
            await interaction.response.send_message("這個功能只能在伺服器內使用。", ephemeral=True)
            return

        customer_role = guild.get_role(CUSTOMER_ROLE_ID)

        intro = (
            f"這裡有闆闆開單。\n\n"
            f"開單人：{member.mention}\n"
            f"狀態：已確認詳閱規章內容"
            f"{format_customer_notes_for_ticket(member.id)}"
        )

        await create_private_channel(
            interaction=interaction,
            category_id=CUSTOMER_CATEGORY_ID,
            channel_name=safe_channel_name("下單", member),
            allowed_roles=[customer_role],
            intro_message=intro,
            view=OrderControlView(),
            topic=f"order_customer_id={member.id}"
        )


class RecruitModal(discord.ui.Modal, title="我要入職"):
    nickname = discord.ui.TextInput(
        label="暱稱",
        placeholder="請輸入你的暱稱",
        required=True,
        max_length=50
    )

    age = discord.ui.TextInput(
        label="年齡",
        placeholder="請輸入你的年齡",
        required=True,
        max_length=20
    )

    play_time = discord.ui.TextInput(
        label="可遊玩時段",
        placeholder="例如：平日晚上、假日整天",
        required=True,
        max_length=100
    )

    position = discord.ui.TextInput(
        label="應徵職位",
        placeholder="例如：陪玩、接待、客服、其他",
        required=True,
        max_length=100
    )

    async def on_submit(self, interaction: discord.Interaction):
        guild = interaction.guild
        member = interaction.user

        if guild is None:
            await interaction.response.send_message("這個功能只能在伺服器內使用。", ephemeral=True)
            return

        examiner_role = guild.get_role(EXAMINER_ROLE_ID)
        manager_role = guild.get_role(MANAGER_ROLE_ID)
        customer_role = guild.get_role(CUSTOMER_ROLE_ID)
        applicant_role = guild.get_role(RECRUIT_APPLICANT_ROLE_ID)

        if applicant_role is not None and isinstance(member, discord.Member):
            try:
                await member.add_roles(applicant_role, reason="Recruit ticket opened")
            except discord.Forbidden:
                print("Bot 權限不足，無法給予入職申請暫時身分組。請確認 Bot 身分組位置高於該身分組。")
            except discord.HTTPException as e:
                print(f"給予入職申請暫時身分組失敗：{e}")

        intro = (
            f"這裡有人想入職。\n\n"
            f"申請人：{member.mention}\n"
            f"暱稱：{self.nickname.value}\n"
            f"年齡：{self.age.value}\n"
            f"可遊玩時段：{self.play_time.value}\n"
            f"應徵職位：{self.position.value}"
        )

        await create_private_channel(
            interaction=interaction,
            category_id=EXAM_CATEGORY_ID,
            channel_name=safe_channel_name("入職", member),
            allowed_roles=[examiner_role, manager_role, customer_role],
            intro_message=intro,
            view=RecruitControlView(),
            topic=f"recruit_member_id={member.id};recruit_nickname={self.nickname.value};recruit_position={self.position.value}"
        )


# ========= 主面板下拉式清單 / 確認按鈕 =========

PANEL_SELECTIONS = {}


class MainPanelSelect(discord.ui.Select):
    def __init__(self):
        options = [
            discord.SelectOption(
                label="我要下單",
                value="order",
                description="開啟下單票口"
            ),
            discord.SelectOption(
                label="我要入職",
                value="recruit",
                description="開啟入職申請票口"
            ),
        ]

        super().__init__(
            placeholder="請選擇你要辦理的項目",
            min_values=1,
            max_values=1,
            options=options,
            custom_id="mawan_main_panel_select",
            row=0
        )

    async def callback(self, interaction: discord.Interaction):
        PANEL_SELECTIONS[interaction.user.id] = self.values[0]

        await interaction.response.defer()


class MainPanelView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(MainPanelSelect())

    @discord.ui.button(
        label="確認",
        style=discord.ButtonStyle.success,
        custom_id="mawan_main_panel_confirm",
        row=1
    )
    async def confirm_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        selected = PANEL_SELECTIONS.get(interaction.user.id)

        if selected is None:
            await interaction.response.send_message(
                "請先從下拉式清單選擇項目，再按確認。",
                ephemeral=True
            )
            return

        PANEL_SELECTIONS.pop(interaction.user.id, None)

        if selected == "order":
            await interaction.response.send_modal(OrderModal())
        elif selected == "recruit":
            await interaction.response.send_modal(RecruitModal())
        else:
            await interaction.response.send_message(
                "選擇項目異常，請重新選擇一次。",
                ephemeral=True
            )


# ========= Bot 事件 =========

@bot.event
async def on_member_join(member: discord.Member):
    role = member.guild.get_role(NEW_MEMBER_ROLE_ID)

    if role is not None:
        try:
            await member.add_roles(role, reason="新成員加入自動給予身分組")
        except discord.Forbidden:
            print("Bot 權限不足，無法給予新成員身分組。請確認 Bot 身分組位置高於要給的身分組。")
        except discord.HTTPException as e:
            print(f"給予新成員身分組失敗：{e}")
    else:
        print("找不到新成員身分組，請確認 NEW_MEMBER_ROLE_ID 是否正確")

    channel = member.guild.get_channel(WELCOME_CHANNEL_ID)

    if channel is None or not isinstance(channel, discord.TextChannel):
        print("找不到歡迎頻道，請確認 WELCOME_CHANNEL_ID 是否正確")
        return

    embed = discord.Embed(
        description=(
            f"**歡迎 {member.mention} 來到魔丸娛樂!**\n\n"
            f"歡迎闆闆光臨!\n"
            f"有任何問題都可以透過機器人開票口聯絡客服歐!"
        ),
        color=discord.Color.green()
    )

    embed.set_thumbnail(url=member.display_avatar.url)

    await channel.send(
        embed=embed,
        allowed_mentions=discord.AllowedMentions(
            users=True,
            roles=False,
            everyone=False
        )
    )


@bot.event
async def on_guild_channel_delete(channel: discord.abc.GuildChannel):
    # 如果入職票口被手動刪除，也嘗試收回申請人暫時身分組。
    await remove_recruit_applicant_role(channel.guild, channel)



@bot.event
async def on_voice_state_update(
    member: discord.Member,
    before: discord.VoiceState,
    after: discord.VoiceState
):
    guild = member.guild

    # 離開機器人建立的陪玩 / VIP / 公共語音房後，如果房間沒人就自動刪除
    # 這裡除了看暫存 ID，也會用頻道名稱判斷，避免 Bot 重開後忘記之前建立的臨時房。
    if before.channel is not None:
        is_temp_play_voice_room = (
            before.channel.id in TEMP_PLAY_VOICE_CHANNEL_IDS
            or (
                before.channel.category_id == PLAY_VOICE_CATEGORY_ID
                and before.channel.name.startswith("🎮┃")
                and before.channel.name.endswith("的陪玩頻道")
                and before.channel.name != PLAY_VOICE_CREATE_CHANNEL_NAME
            )
        )

        is_temp_vip_voice_room = (
            before.channel.id in TEMP_VIP_VOICE_CHANNEL_IDS
            or (
                before.channel.category_id == PLAY_VOICE_CATEGORY_ID
                and before.channel.name.startswith("👑┃")
                and before.channel.name.endswith("的𝙑𝙄𝙋頻道")
                and before.channel.name != VIP_VOICE_CREATE_CHANNEL_NAME
            )
        )

        is_temp_public_voice_room = (
            before.channel.id in TEMP_PUBLIC_VOICE_CHANNEL_IDS
            or (
                before.channel.category_id == PLAY_VOICE_CATEGORY_ID
                and before.channel.name.startswith("➕┃")
                and before.channel.name.endswith("的公共房間")
                and before.channel.name != PUBLIC_VOICE_CREATE_CHANNEL_NAME
            )
        )

        if is_temp_play_voice_room and len(before.channel.members) == 0:
            TEMP_PLAY_VOICE_CHANNEL_IDS.discard(before.channel.id)
            await delete_voice_control_panel(guild, before.channel.id)
            try:
                await before.channel.delete(reason="Temporary play voice room is empty")
            except discord.NotFound:
                pass
            except discord.Forbidden:
                print("Bot 權限不足，無法刪除陪玩語音房。")
            except discord.HTTPException as e:
                print(f"刪除陪玩語音房失敗：{e}")
            return

        if is_temp_vip_voice_room and len(before.channel.members) == 0:
            TEMP_VIP_VOICE_CHANNEL_IDS.discard(before.channel.id)
            await delete_voice_control_panel(guild, before.channel.id)
            try:
                await before.channel.delete(reason="Temporary VIP voice room is empty")
            except discord.NotFound:
                pass
            except discord.Forbidden:
                print("Bot 權限不足，無法刪除 VIP 語音房。")
            except discord.HTTPException as e:
                print(f"刪除 VIP 語音房失敗：{e}")
            return

        if is_temp_public_voice_room and len(before.channel.members) == 0:
            TEMP_PUBLIC_VOICE_CHANNEL_IDS.discard(before.channel.id)
            await delete_voice_control_panel(guild, before.channel.id)
            try:
                await before.channel.delete(reason="Temporary public voice room is empty")
            except discord.NotFound:
                pass
            except discord.Forbidden:
                print("Bot 權限不足，無法刪除公共語音房。")
            except discord.HTTPException as e:
                print(f"刪除公共語音房失敗：{e}")
            return

    # 沒有加入新語音頻道就不用處理
    if after.channel is None:
        return

    category = guild.get_channel(PLAY_VOICE_CATEGORY_ID)

    if category is None or not isinstance(category, discord.CategoryChannel):
        return

    # 取得或建立兩種入口語音頻道
    play_lobby_channel = await get_or_create_play_voice_lobby(guild)
    vip_lobby_channel = await get_or_create_vip_voice_lobby(guild)
    public_lobby_channel = await get_or_create_public_voice_lobby(guild)

    # 進入一般陪玩入口：建立一般陪玩語音房
    if play_lobby_channel is not None and after.channel.id == play_lobby_channel.id:
        try:
            overwrites = build_play_voice_overwrites(guild)
            overwrites[member] = build_creator_voice_overwrite()

            new_channel = await guild.create_voice_channel(
                name=safe_voice_channel_name(member),
                category=category,
                overwrites=overwrites,
                reason=f"Temporary play voice room created by {member}"
            )
            TEMP_PLAY_VOICE_CHANNEL_IDS.add(new_channel.id)

            await create_voice_control_panel(
                guild=guild,
                category=category,
                member=member,
                voice_channel=new_channel,
                room_type="play"
            )

            await member.move_to(
                new_channel,
                reason="Move member to created play voice room"
            )
        except discord.Forbidden:
            print("Bot 權限不足，無法建立或移動陪玩語音房。")
        except discord.HTTPException as e:
            print(f"建立或移動陪玩語音房失敗：{e}")

        return

    # 進入 VIP 入口：建立 VIP 專用語音房
    if vip_lobby_channel is not None and after.channel.id == vip_lobby_channel.id:
        try:
            new_channel = await guild.create_voice_channel(
                name=safe_vip_voice_channel_name(member),
                category=category,
                overwrites=build_vip_room_overwrites(guild, member),
                reason=f"Temporary VIP voice room created by {member}"
            )
            TEMP_VIP_VOICE_CHANNEL_IDS.add(new_channel.id)

            await create_voice_control_panel(
                guild=guild,
                category=category,
                member=member,
                voice_channel=new_channel,
                room_type="vip"
            )

            await member.move_to(
                new_channel,
                reason="Move member to created VIP voice room"
            )
        except discord.Forbidden:
            print("Bot 權限不足，無法建立或移動 VIP 語音房。")
        except discord.HTTPException as e:
            print(f"建立或移動 VIP 語音房失敗：{e}")

        return

    # 進入公共入口：建立所有人可見 / 可加入的公共語音房
    if public_lobby_channel is not None and after.channel.id == public_lobby_channel.id:
        try:
            overwrites = build_public_voice_overwrites(guild)
            overwrites[member] = build_creator_voice_overwrite()

            new_channel = await guild.create_voice_channel(
                name=safe_public_voice_channel_name(member),
                category=category,
                overwrites=overwrites,
                reason=f"Temporary public voice room created by {member}"
            )
            TEMP_PUBLIC_VOICE_CHANNEL_IDS.add(new_channel.id)

            await create_voice_control_panel(
                guild=guild,
                category=category,
                member=member,
                voice_channel=new_channel,
                room_type="public"
            )

            await member.move_to(
                new_channel,
                reason="Move member to created public voice room"
            )
        except discord.Forbidden:
            print("Bot 權限不足，無法建立或移動公共語音房。")
        except discord.HTTPException as e:
            print(f"建立或移動公共語音房失敗：{e}")

        return

@bot.event
async def on_ready():
    global BACKUP_TASK_STARTED, STORED_REMINDER_TASK_STARTED, VIP_DOWNGRADE_TASK_STARTED
    bot.add_view(MainPanelView())
    bot.add_view(OrderControlView())
    bot.add_view(StaffOrderOperationView())
    bot.add_view(RecruitControlView())
    bot.add_view(ComplaintPanelView())
    bot.add_view(FeedbackPanelView())
    bot.add_view(ComplaintResolveView())

    restored_dispatch_views = 0
    for message_id in list(ORDER_CLAIMS.keys()):
        view = get_dispatch_claim_view_from_data(message_id)
        if view is None:
            continue

        try:
            bot.add_view(view, message_id=message_id)
            restored_dispatch_views += 1
        except ValueError:
            pass

    if restored_dispatch_views:
        print(f"Restored dispatch claim views: {restored_dispatch_views}")

    guild_for_voice = bot.get_guild(GUILD_ID)
    if guild_for_voice is not None:
        await get_or_create_order_log_channel(guild_for_voice)
        if not BACKUP_TASK_STARTED:
            BACKUP_TASK_STARTED = True
            asyncio.create_task(daily_backup_loop())
        if not STORED_REMINDER_TASK_STARTED:
            STORED_REMINDER_TASK_STARTED = True
            asyncio.create_task(stored_order_reminder_loop())
        if not VIP_DOWNGRADE_TASK_STARTED:
            VIP_DOWNGRADE_TASK_STARTED = True
            asyncio.create_task(vip_downgrade_loop())
        try:
            await get_or_create_play_voice_lobby(guild_for_voice)
            await get_or_create_vip_voice_lobby(guild_for_voice)
            await get_or_create_public_voice_lobby(guild_for_voice)
        except discord.Forbidden:
            print("Bot 權限不足，無法建立陪玩 / VIP / 公共語音入口。")
        except discord.HTTPException as e:
            print(f"建立陪玩 / VIP / 公共語音入口失敗：{e}")

    try:
        guild = discord.Object(id=GUILD_ID)
        synced = await bot.tree.sync(guild=guild)
        print(f"Slash commands synced: {len(synced)}")
    except Exception as e:
        print(f"Sync error: {e}")

    print(f"Logged in as {bot.user}")


# ========= Slash 指令 =========



# ========= 點數抽獎系統 =========

LOTTERY_COST_PER_CHANCE_DEFAULT = 5
LOTTERY_MAX_CHANCES_PER_USER_DEFAULT = 20


def get_default_lottery_period() -> str:
    return get_taipei_now().strftime("%Y-%m")


def get_lottery_settings() -> dict:
    init_database()
    default = {
        "period": get_default_lottery_period(),
        "title": "魔丸點數抽獎",
        "note": "獎品由管理層討論後設定。",
        "prizes": "獎池尚未設定，請等待管理層公告。",
        "status": "open",
        "cost_per_chance": LOTTERY_COST_PER_CHANCE_DEFAULT,
        "max_chances_per_user": LOTTERY_MAX_CHANCES_PER_USER_DEFAULT,
        "updated_at": get_taipei_now_iso(),
    }

    try:
        with sqlite3.connect(DB_FILE) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute("SELECT data FROM lottery_settings WHERE key='current'").fetchone()
    except sqlite3.Error as e:
        print(f"讀取抽獎設定失敗：{e}")
        return default

    if row is None:
        save_lottery_settings(default)
        return default

    try:
        data = json.loads(row["data"])
    except json.JSONDecodeError:
        return default

    for key, value in default.items():
        data.setdefault(key, value)

    return data


def save_lottery_settings(data: dict) -> None:
    init_database()
    data["updated_at"] = get_taipei_now_iso()
    try:
        with sqlite3.connect(DB_FILE) as conn:
            conn.execute(
                "INSERT OR REPLACE INTO lottery_settings (key, data, updated_at) VALUES (?, ?, ?)",
                ("current", json.dumps(data, ensure_ascii=False), data["updated_at"]),
            )
            conn.commit()
    except sqlite3.Error as e:
        print(f"保存抽獎設定失敗：{e}")


def get_lottery_entries(period: str) -> list[dict]:
    init_database()
    try:
        with sqlite3.connect(DB_FILE) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                """
                SELECT user_id, chances, points_used, updated_at
                FROM lottery_entries
                WHERE period=? AND chances > 0
                ORDER BY chances DESC, updated_at ASC
                """,
                (period,),
            ).fetchall()
    except sqlite3.Error as e:
        print(f"讀取抽獎池失敗：{e}")
        return []

    return [
        {
            "user_id": int(row["user_id"]),
            "chances": int(row["chances"]),
            "points_used": int(row["points_used"]),
            "updated_at": row["updated_at"],
        }
        for row in rows
    ]


def get_lottery_entry(period: str, user_id: int) -> dict | None:
    init_database()
    try:
        with sqlite3.connect(DB_FILE) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT user_id, chances, points_used, updated_at FROM lottery_entries WHERE period=? AND user_id=?",
                (period, user_id),
            ).fetchone()
    except sqlite3.Error as e:
        print(f"讀取抽獎報名資料失敗：{e}")
        return None

    if row is None:
        return None

    return {
        "user_id": int(row["user_id"]),
        "chances": int(row["chances"]),
        "points_used": int(row["points_used"]),
        "updated_at": row["updated_at"],
    }


def upsert_lottery_entry(period: str, user_id: int, chances_delta: int, points_delta: int) -> None:
    init_database()
    now_text = get_taipei_now_iso()
    current = get_lottery_entry(period, user_id)
    new_chances = chances_delta if current is None else int(current["chances"]) + chances_delta
    new_points_used = points_delta if current is None else int(current["points_used"]) + points_delta

    try:
        with sqlite3.connect(DB_FILE) as conn:
            if new_chances <= 0:
                conn.execute("DELETE FROM lottery_entries WHERE period=? AND user_id=?", (period, user_id))
            else:
                conn.execute(
                    """
                    INSERT OR REPLACE INTO lottery_entries (period, user_id, chances, points_used, updated_at)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (period, user_id, new_chances, max(new_points_used, 0), now_text),
                )
            conn.commit()
    except sqlite3.Error as e:
        print(f"更新抽獎報名資料失敗：{e}")


def clear_lottery_entries(period: str) -> None:
    init_database()
    try:
        with sqlite3.connect(DB_FILE) as conn:
            conn.execute("DELETE FROM lottery_entries WHERE period=?", (period,))
            conn.commit()
    except sqlite3.Error as e:
        print(f"清空抽獎池失敗：{e}")


def record_lottery_draw(period: str, prize: str, winner_id: int, drawn_by: int) -> None:
    init_database()
    try:
        with sqlite3.connect(DB_FILE) as conn:
            conn.execute(
                """
                INSERT INTO lottery_draws (period, prize, winner_id, drawn_by, drawn_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (period, prize, winner_id, drawn_by, get_taipei_now_iso()),
            )
            conn.commit()
    except sqlite3.Error as e:
        print(f"保存抽獎結果失敗：{e}")


def build_lottery_info_embed(settings: dict) -> discord.Embed:
    period = str(settings.get("period", get_default_lottery_period()))
    entries = get_lottery_entries(period)
    total_chances = sum(int(row["chances"]) for row in entries)
    participant_count = len(entries)
    cost = int(settings.get("cost_per_chance", LOTTERY_COST_PER_CHANCE_DEFAULT))
    max_chances = int(settings.get("max_chances_per_user", LOTTERY_MAX_CHANCES_PER_USER_DEFAULT))
    status_text = "開放報名" if settings.get("status") == "open" else "已關閉"

    embed = discord.Embed(
        title=str(settings.get("title") or "魔丸點數抽獎"),
        color=discord.Color.gold(),
    )
    embed.add_field(name="本期", value=period, inline=True)
    embed.add_field(name="狀態", value=status_text, inline=True)
    embed.add_field(name="規則", value=f"{cost} 點 = 1 次抽獎機會\n每人本期最多 {max_chances} 次", inline=False)
    embed.add_field(name="目前抽獎池", value=f"參與人數：{participant_count} 人\n總抽獎次數：{total_chances} 次", inline=False)
    prizes = str(settings.get("prizes") or "獎池尚未設定，請等待管理層公告。")
    embed.add_field(name="獎池內容", value=prizes[:1000], inline=False)

    note = str(settings.get("note") or "獎品由管理層討論後設定。")
    embed.add_field(name="活動備註", value=note[:1000], inline=False)
    return embed


def build_lottery_status_embed(settings: dict) -> discord.Embed:
    period = str(settings.get("period", get_default_lottery_period()))
    entries = get_lottery_entries(period)
    total_chances = sum(int(row["chances"]) for row in entries)

    embed = build_lottery_info_embed(settings)
    embed.title = f"抽獎池狀態｜{period}"

    if not entries:
        embed.add_field(name="參加名單", value="目前沒有人參加。", inline=False)
        return embed

    lines = []
    for index, row in enumerate(entries[:20], start=1):
        chance_rate = (int(row["chances"]) / total_chances * 100) if total_chances else 0
        lines.append(f"{index}. <@{row['user_id']}>｜{row['chances']} 次｜約 {chance_rate:.1f}%")

    if len(entries) > 20:
        lines.append(f"...另有 {len(entries) - 20} 人")

    embed.add_field(name="參加名單", value="\n".join(lines), inline=False)
    return embed


def pick_weighted_lottery_winners(entries: list[dict], winners: int) -> list[int]:
    pool = [dict(row) for row in entries if int(row.get("chances", 0)) > 0]
    picked: list[int] = []

    for _ in range(max(winners, 0)):
        if not pool:
            break

        total_weight = sum(int(row["chances"]) for row in pool)
        if total_weight <= 0:
            break

        ticket = random.randint(1, total_weight)
        running = 0
        chosen_index = 0

        for index, row in enumerate(pool):
            running += int(row["chances"])
            if ticket <= running:
                chosen_index = index
                break

        winner = pool.pop(chosen_index)
        picked.append(int(winner["user_id"]))

    return picked


def is_lottery_admin(member: discord.Member) -> bool:
    return is_customer_staff(member) or has_role(member, MANAGER_ROLE_ID) or member.guild_permissions.administrator


@bot.tree.command(
    name="lottery_info",
    description="查看目前魔丸點數抽獎活動",
    guild=discord.Object(id=GUILD_ID)
)
async def lottery_info(interaction: discord.Interaction):
    settings = get_lottery_settings()
    await interaction.response.send_message(embed=build_lottery_info_embed(settings), ephemeral=True)


@bot.tree.command(
    name="join_lottery",
    description="使用魔丸點數參加抽獎，5 點 = 1 次抽獎機會",
    guild=discord.Object(id=GUILD_ID)
)
@app_commands.describe(chances="要參加幾次抽獎，每次會消耗 5 點")
async def join_lottery(interaction: discord.Interaction, chances: int):
    if chances <= 0:
        await interaction.response.send_message("抽獎次數必須大於 0。", ephemeral=True)
        return

    settings = get_lottery_settings()
    if settings.get("status") != "open":
        await interaction.response.send_message("目前抽獎尚未開放報名。", ephemeral=True)
        return

    period = str(settings.get("period", get_default_lottery_period()))
    cost = int(settings.get("cost_per_chance", LOTTERY_COST_PER_CHANCE_DEFAULT))
    max_chances = int(settings.get("max_chances_per_user", LOTTERY_MAX_CHANCES_PER_USER_DEFAULT))
    current_entry = get_lottery_entry(period, interaction.user.id)
    current_chances = int(current_entry["chances"]) if current_entry else 0

    if current_chances + chances > max_chances:
        await interaction.response.send_message(
            f"本期每人最多 {max_chances} 次，你目前已有 {current_chances} 次，最多還能加 {max(0, max_chances - current_chances)} 次。",
            ephemeral=True,
        )
        return

    points_needed = chances * cost
    data = get_customer_reward_data(interaction.user.id)
    current_points = get_current_reward_points(data)

    if current_points < points_needed:
        await interaction.response.send_message(
            f"點數不足。你目前有 {current_points:,} 點，本次需要 {points_needed:,} 點。",
            ephemeral=True,
        )
        return

    ok, message = await adjust_customer_points(
        customer_id=interaction.user.id,
        delta_points=-points_needed,
        operator_id=interaction.user.id,
        reason=f"參加 {period} 點數抽獎 {chances} 次",
    )
    if not ok:
        await interaction.response.send_message(message, ephemeral=True)
        return

    upsert_lottery_entry(period, interaction.user.id, chances, points_needed)

    await send_order_log(
        interaction.guild,
        title="抽獎報名",
        fields=[
            ("顧客", f"<@{self.customer_id}>", True),
            ("期別", period, True),
            ("抽獎次數", f"{chances} 次", True),
            ("消耗點數", f"{points_needed:,} 點", True),
        ],
        color=discord.Color.gold(),
    )

    await interaction.response.send_message(
        f"已成功參加 **{period}** 抽獎 {chances} 次，消耗 {points_needed:,} 點。\n"
        f"你本期目前共 {current_chances + chances} 次抽獎機會。",
        ephemeral=True,
    )


@bot.tree.command(
    name="lottery_status",
    description="客服查看目前抽獎池狀態",
    guild=discord.Object(id=GUILD_ID)
)
async def lottery_status(interaction: discord.Interaction):
    if not isinstance(interaction.user, discord.Member) or not is_lottery_admin(interaction.user):
        await interaction.response.send_message("只有客服、店長或管理員可以查看抽獎池。", ephemeral=True)
        return

    settings = get_lottery_settings()
    await interaction.response.send_message(embed=build_lottery_status_embed(settings), ephemeral=True)


@bot.tree.command(
    name="lottery_open",
    description="管理層設定或開啟本期點數抽獎",
    guild=discord.Object(id=GUILD_ID)
)
@app_commands.describe(
    period="期別，例如 2026-05；不填則使用本月",
    title="抽獎活動名稱，可不填",
    note="活動備註，可先寫：獎品內部討論中",
    max_chances_per_user="每人本期最多可投入幾次，預設 20",
    announce_channel="抽獎開始公告要發到哪個頻道；不填則用預設公告頻道"
)
async def lottery_open(
    interaction: discord.Interaction,
    period: str | None = None,
    title: str | None = None,
    note: str | None = None,
    max_chances_per_user: int | None = None,
    announce_channel: discord.TextChannel | None = None,
):
    if not isinstance(interaction.user, discord.Member) or not is_lottery_admin(interaction.user):
        await interaction.response.send_message("只有客服、店長或管理員可以設定抽獎。", ephemeral=True)
        return

    if max_chances_per_user is not None and max_chances_per_user <= 0:
        await interaction.response.send_message("每人上限必須大於 0。", ephemeral=True)
        return

    settings = get_lottery_settings()
    settings["period"] = (period or get_default_lottery_period()).strip()
    settings["title"] = (title or settings.get("title") or "魔丸點數抽獎").strip()
    settings["note"] = (note or settings.get("note") or "獎品由管理層討論後設定。").strip()
    settings["status"] = "open"
    settings["cost_per_chance"] = LOTTERY_COST_PER_CHANCE_DEFAULT
    settings["max_chances_per_user"] = int(max_chances_per_user or LOTTERY_MAX_CHANCES_PER_USER_DEFAULT)
    save_lottery_settings(settings)

    await send_order_log(
        interaction.guild,
        title="抽獎已開啟 / 設定",
        fields=[
            ("期別", settings["period"], True),
            ("名稱", settings["title"], True),
            ("每人上限", f"{settings['max_chances_per_user']} 次", True),
            ("設定人員", interaction.user.mention, True),
            ("備註", settings["note"], False),
        ],
        color=discord.Color.gold(),
    )

    announcement_embed = build_lottery_info_embed(settings)
    announcement_embed.title = f"🎁 {settings['title']} 開始報名"
    announced = await send_lottery_announcement(
        interaction.guild,
        content="@everyone 🎁 魔丸點數抽獎已開放報名！使用 `/lottery_info` 查看活動，使用 `/join_lottery` 參加抽獎。",
        embed=announcement_embed,
        channel=announce_channel,
    )

    announce_text = f"公告已送出到 {announce_channel.mention if announce_channel else '預設公告頻道'}。" if announced else "公告送出失敗，請確認 Bot 權限與公告頻道設定。"
    await interaction.response.send_message(f"抽獎已設定並開放報名，{announce_text}", embed=build_lottery_info_embed(settings), ephemeral=True)


@bot.tree.command(
    name="lottery_set_prizes",
    description="管理層設定本期抽獎獎池內容",
    guild=discord.Object(id=GUILD_ID)
)
@app_commands.describe(
    prizes="獎池內容，例如：一獎：500T折抵券 x1｜二獎：指定費免費 x2",
    announce="是否發公告，預設否",
    announce_channel="獎池公告要發到哪個頻道；不填則用預設公告頻道"
)
async def lottery_set_prizes(
    interaction: discord.Interaction,
    prizes: str,
    announce: bool = False,
    announce_channel: discord.TextChannel | None = None,
):
    if not isinstance(interaction.user, discord.Member) or not is_lottery_admin(interaction.user):
        await interaction.response.send_message("只有客服、店長或管理員可以設定獎池。", ephemeral=True)
        return

    prize_text = prizes.strip()
    if not prize_text:
        await interaction.response.send_message("獎池內容不能是空的。", ephemeral=True)
        return

    if len(prize_text) > 1000:
        await interaction.response.send_message("獎池內容太長，請控制在 1000 字以內。", ephemeral=True)
        return

    settings = get_lottery_settings()
    settings["prizes"] = prize_text
    save_lottery_settings(settings)

    await send_order_log(
        interaction.guild,
        title="抽獎獎池已設定",
        fields=[
            ("期別", str(settings.get("period", get_default_lottery_period())), True),
            ("設定人員", interaction.user.mention, True),
            ("獎池內容", prize_text, False),
        ],
        color=discord.Color.gold(),
    )

    embed = build_lottery_info_embed(settings)
    embed.title = f"🎁 {settings.get('title', '魔丸點數抽獎')} 獎池更新"

    if announce:
        announced = await send_lottery_announcement(
            interaction.guild,
            content="@everyone 🎁 魔丸點數抽獎獎池已更新！使用 `/lottery_info` 查看活動詳情。",
            embed=embed,
            channel=announce_channel,
        )
        announce_text = f"公告已送出到 {announce_channel.mention if announce_channel else '預設公告頻道'}。" if announced else "公告送出失敗，請確認 Bot 權限與公告頻道設定。"
        await interaction.response.send_message(f"獎池已設定，{announce_text}", embed=embed, ephemeral=True)
    else:
        await interaction.response.send_message("獎池已設定。", embed=embed, ephemeral=True)


@bot.tree.command(
    name="lottery_close",
    description="管理層關閉本期抽獎報名",
    guild=discord.Object(id=GUILD_ID)
)
async def lottery_close(interaction: discord.Interaction):
    if not isinstance(interaction.user, discord.Member) or not is_lottery_admin(interaction.user):
        await interaction.response.send_message("只有客服、店長或管理員可以關閉抽獎。", ephemeral=True)
        return

    settings = get_lottery_settings()
    settings["status"] = "closed"
    save_lottery_settings(settings)
    await interaction.response.send_message(f"已關閉 **{settings['period']}** 抽獎報名。", ephemeral=True)


@bot.tree.command(
    name="draw_lottery",
    description="客服開獎；可依照已設定獎池輸入本次要抽的獎品",
    guild=discord.Object(id=GUILD_ID)
)
@app_commands.describe(
    prize="本次要抽的獎品名稱，例如 一獎：500T折抵券",
    winners="要抽出幾位得主，預設 1",
    announce_channel="開獎公告要發到哪個頻道；不填則用預設公告頻道"
)
async def draw_lottery(
    interaction: discord.Interaction,
    prize: str,
    winners: int = 1,
    announce_channel: discord.TextChannel | None = None,
):
    if not isinstance(interaction.user, discord.Member) or not is_lottery_admin(interaction.user):
        await interaction.response.send_message("只有客服、店長或管理員可以開獎。", ephemeral=True)
        return

    if winners <= 0:
        await interaction.response.send_message("得獎人數必須大於 0。", ephemeral=True)
        return

    settings = get_lottery_settings()
    period = str(settings.get("period", get_default_lottery_period()))
    entries = get_lottery_entries(period)

    if not entries:
        await interaction.response.send_message("目前抽獎池沒有人參加，無法開獎。", ephemeral=True)
        return

    if winners > len(entries):
        winners = len(entries)

    picked = pick_weighted_lottery_winners(entries, winners)
    for winner_id in picked:
        record_lottery_draw(period, prize, winner_id, interaction.user.id)

    result_lines = [f"{index}. <@{winner_id}>" for index, winner_id in enumerate(picked, start=1)]
    embed = discord.Embed(
        title="🎁 魔丸點數抽獎開獎",
        color=discord.Color.gold(),
    )
    embed.add_field(name="期別", value=period, inline=True)
    embed.add_field(name="獎品", value=prize, inline=True)
    embed.add_field(name="開獎人", value=interaction.user.mention, inline=True)
    embed.add_field(name="得獎者", value="\n".join(result_lines), inline=False)

    await send_order_log(
        interaction.guild,
        title="抽獎開獎",
        fields=[
            ("期別", period, True),
            ("獎品", prize, True),
            ("開獎人", interaction.user.mention, True),
            ("得獎者", "\n".join(result_lines), False),
        ],
        color=discord.Color.gold(),
    )

    announced = await send_lottery_announcement(
        interaction.guild,
        content="@everyone 🎉 魔丸點數抽獎開獎啦！恭喜得獎者！",
        embed=embed,
        channel=announce_channel,
    )

    announce_text = f"公告已送出到 {announce_channel.mention if announce_channel else '預設公告頻道'}。" if announced else "公告送出失敗，請確認 Bot 權限與公告頻道設定。"
    await interaction.response.send_message(f"開獎完成，{announce_text}", embed=embed, ephemeral=True)


@bot.tree.command(
    name="cancel_lottery_entry",
    description="客服取消顧客本期抽獎報名並退還點數",
    guild=discord.Object(id=GUILD_ID)
)
@app_commands.describe(customer="要取消報名的顧客", reason="取消原因，可不填")
async def cancel_lottery_entry(interaction: discord.Interaction, customer: discord.Member, reason: str | None = None):
    if not isinstance(interaction.user, discord.Member) or not is_lottery_admin(interaction.user):
        await interaction.response.send_message("只有客服、店長或管理員可以取消抽獎報名。", ephemeral=True)
        return

    settings = get_lottery_settings()
    period = str(settings.get("period", get_default_lottery_period()))
    entry = get_lottery_entry(period, customer.id)

    if entry is None or int(entry.get("chances", 0)) <= 0:
        await interaction.response.send_message(f"{customer.mention} 本期沒有抽獎報名紀錄。", ephemeral=True)
        return

    refund_points = int(entry["points_used"])
    upsert_lottery_entry(period, customer.id, -int(entry["chances"]), -refund_points)
    ok, message = await adjust_customer_points(
        customer_id=customer.id,
        delta_points=refund_points,
        operator_id=interaction.user.id,
        reason=f"取消 {period} 抽獎報名退點：{reason or '未填寫'}",
    )

    await send_order_log(
        interaction.guild,
        title="抽獎報名已取消",
        fields=[
            ("顧客", customer.mention, True),
            ("期別", period, True),
            ("退還點數", f"{refund_points:,} 點", True),
            ("操作人員", interaction.user.mention, True),
            ("原因", reason or "未填寫", False),
        ],
        color=discord.Color.orange(),
    )

    await interaction.response.send_message(message, ephemeral=True)


@bot.tree.command(
    name="reset_lottery",
    description="清空本期抽獎池，不自動退點。需輸入確認文字",
    guild=discord.Object(id=GUILD_ID)
)
@app_commands.describe(confirm_text="請輸入：確認清空", reason="清空原因，可不填")
async def reset_lottery(interaction: discord.Interaction, confirm_text: str, reason: str | None = None):
    if not isinstance(interaction.user, discord.Member) or not is_lottery_admin(interaction.user):
        await interaction.response.send_message("只有客服、店長或管理員可以清空抽獎池。", ephemeral=True)
        return

    if confirm_text != "確認清空":
        await interaction.response.send_message("未清空。若確定要清空，confirm_text 請輸入：確認清空", ephemeral=True)
        return

    settings = get_lottery_settings()
    period = str(settings.get("period", get_default_lottery_period()))
    entries = get_lottery_entries(period)
    clear_lottery_entries(period)

    await send_order_log(
        interaction.guild,
        title="抽獎池已清空",
        fields=[
            ("期別", period, True),
            ("清空人員", interaction.user.mention, True),
            ("原參與人數", f"{len(entries)} 人", True),
            ("原因", reason or "未填寫", False),
        ],
        color=discord.Color.red(),
    )

    await interaction.response.send_message(f"已清空 **{period}** 抽獎池。注意：此操作不會自動退點。", ephemeral=True)


@bot.tree.command(
    name="my_points",
    description="查詢自己的魔丸會員資料",
    guild=discord.Object(id=GUILD_ID)
)
async def my_points(interaction: discord.Interaction):
    data = get_customer_reward_data(interaction.user.id)
    embed = build_member_info_embed(interaction.user, data, show_points=True)
    await interaction.response.send_message(embed=embed, ephemeral=True)


@bot.tree.command(
    name="customer_points",
    description="客服查詢指定顧客的魔丸會員資料",
    guild=discord.Object(id=GUILD_ID)
)
@app_commands.describe(customer="要查詢的顧客")
async def customer_points(interaction: discord.Interaction, customer: discord.Member):
    if not isinstance(interaction.user, discord.Member):
        await interaction.response.send_message("無法確認你的身分組。", ephemeral=True)
        return

    if not is_customer_staff(interaction.user) and not has_role(interaction.user, MANAGER_ROLE_ID):
        await interaction.response.send_message("只有客服或店長可以查詢顧客會員資料。", ephemeral=True)
        return

    data = get_customer_reward_data(customer.id)
    embed = build_member_info_embed(customer, data, show_points=True)
    embed.title = "顧客會員資料"
    await interaction.response.send_message(embed=embed, ephemeral=True)



@bot.tree.command(
    name="adjust_points",
    description="客服調整顧客魔丸點數，可輸入正數加點或負數扣點",
    guild=discord.Object(id=GUILD_ID)
)
@app_commands.describe(
    customer="要調整點數的顧客",
    points="調整點數，正數為加點，負數為扣點，例如 10 或 -10",
    reason="調整原因，可不填"
)
async def adjust_points(
    interaction: discord.Interaction,
    customer: discord.Member,
    points: int,
    reason: str | None = None,
):
    if not isinstance(interaction.user, discord.Member):
        await interaction.response.send_message("無法確認你的身分組。", ephemeral=True)
        return

    if not is_customer_staff(interaction.user) and not has_role(interaction.user, MANAGER_ROLE_ID):
        await interaction.response.send_message("只有客服或店長可以調整顧客點數。", ephemeral=True)
        return

    ok, message = await adjust_customer_points(
        customer_id=customer.id,
        delta_points=points,
        operator_id=interaction.user.id,
        reason=reason,
    )

    if ok:
        await send_order_log(
            interaction.guild,
            title="會員點數已調整",
            fields=[
                ("顧客", customer.mention, True),
                ("操作人員", interaction.user.mention, True),
                ("點數變動", f"{points:+,} 點", True),
                ("原因", reason or "未填寫", False),
            ],
            color=discord.Color.orange(),
        )

    await interaction.response.send_message(message, ephemeral=True)


@bot.tree.command(
    name="add_purchase",
    description="客服補登單筆顧客歷史消費",
    guild=discord.Object(id=GUILD_ID)
)
@app_commands.describe(
    customer="要補登的顧客",
    amount="消費金額，例如 900",
    date="完成日期，例如 20260512、2026/05/12 或 2026-05-12",
    note="備註，可不填"
)
async def add_purchase(
    interaction: discord.Interaction,
    customer: discord.Member,
    amount: int,
    date: str,
    note: str | None = None,
):
    if not isinstance(interaction.user, discord.Member):
        await interaction.response.send_message("無法確認你的身分組。", ephemeral=True)
        return

    if not is_customer_staff(interaction.user) and not has_role(interaction.user, MANAGER_ROLE_ID):
        await interaction.response.send_message("只有客服或店長可以補登會員消費。", ephemeral=True)
        return

    guild = interaction.guild
    if guild is None:
        await interaction.response.send_message("這個功能只能在伺服器內使用。", ephemeral=True)
        return

    ok, message = await add_manual_purchase(
        guild=guild,
        customer_id=customer.id,
        amount=amount,
        date_text=date,
        operator_id=interaction.user.id,
        note=note,
    )

    if ok:
        await send_order_log(
            guild,
            title="歷史消費已補登",
            fields=[
                ("顧客", customer.mention, True),
                ("操作人員", interaction.user.mention, True),
                ("金額", format_t_amount(amount), True),
                ("日期", date, True),
                ("備註", note or "未填寫", False),
            ],
            color=discord.Color.blue(),
        )

    await interaction.response.send_message(message, ephemeral=True)


@bot.tree.command(
    name="import_purchases",
    description="客服批量補登歷史消費，多行格式：顧客ID,金額,日期,備註",
    guild=discord.Object(id=GUILD_ID)
)
@app_commands.describe(
    records="每行一筆：顧客ID,金額,日期,備註；備註可省略"
)
async def import_purchases(interaction: discord.Interaction, records: str):
    if not isinstance(interaction.user, discord.Member):
        await interaction.response.send_message("無法確認你的身分組。", ephemeral=True)
        return

    if not is_customer_staff(interaction.user) and not has_role(interaction.user, MANAGER_ROLE_ID):
        await interaction.response.send_message("只有客服或店長可以批量補登會員消費。", ephemeral=True)
        return

    guild = interaction.guild
    if guild is None:
        await interaction.response.send_message("這個功能只能在伺服器內使用。", ephemeral=True)
        return

    await interaction.response.defer(ephemeral=True, thinking=True)

    success_count = 0
    skipped_count = 0
    result_lines = []

    for line_number, raw_line in enumerate(records.splitlines(), start=1):
        line = raw_line.strip()
        if not line:
            continue

        parts = [part.strip() for part in line.split(",")]
        if len(parts) < 3:
            skipped_count += 1
            result_lines.append(f"第 {line_number} 行失敗：格式不足，請用 顧客ID,金額,日期,備註")
            continue

        customer_text, amount_text, date_text = parts[0], parts[1], parts[2]
        note = ",".join(parts[3:]).strip() if len(parts) >= 4 else None
        customer_text = customer_text.replace("<@", "").replace(">", "").replace("!", "")

        try:
            customer_id = int(customer_text)
            amount = int(amount_text.replace("T", "").replace("t", "").replace(",", ""))
        except ValueError:
            skipped_count += 1
            result_lines.append(f"第 {line_number} 行失敗：顧客 ID 或金額不是數字。")
            continue

        ok, message = await add_manual_purchase(
            guild=guild,
            customer_id=customer_id,
            amount=amount,
            date_text=date_text,
            operator_id=interaction.user.id,
            note=note,
        )

        if ok:
            success_count += 1
        else:
            skipped_count += 1

        result_lines.append(message)

    summary = f"批量補登完成：成功 {success_count} 筆，跳過/失敗 {skipped_count} 筆。"
    detail = "\n".join(result_lines)
    if len(detail) > 1700:
        detail = detail[:1700] + "\n...（結果太長，已截斷）"

    await interaction.followup.send(f"{summary}\n\n{detail}", ephemeral=True)



@bot.tree.command(
    name="set_customer_rewards",
    description="管理員手動修正顧客會員資料",
    guild=discord.Object(id=GUILD_ID)
)
@app_commands.describe(
    customer="要修正的顧客",
    total_spent="累積消費總額，不填則不修改",
    order_count="完成訂單數，不填則不修改",
    last_order_date="最後下單日期，例如 20260512、2026/05/12；不填則不修改",
    point_adjustment="額外點數修正值，可正可負；不填則不修改",
    reason="修正原因，可不填"
)
async def set_customer_rewards(
    interaction: discord.Interaction,
    customer: discord.Member,
    total_spent: int | None = None,
    order_count: int | None = None,
    last_order_date: str | None = None,
    point_adjustment: int | None = None,
    reason: str | None = None,
):
    if not isinstance(interaction.user, discord.Member):
        await interaction.response.send_message("無法確認你的身分組。", ephemeral=True)
        return

    if not is_manager_or_admin(interaction.user):
        await interaction.response.send_message("只有管理員或店長可以手動修正顧客會員資料。", ephemeral=True)
        return

    if total_spent is None and order_count is None and last_order_date is None and point_adjustment is None:
        await interaction.response.send_message("請至少填一個要修正的欄位。", ephemeral=True)
        return

    if total_spent is not None and total_spent < 0:
        await interaction.response.send_message("累積消費不能小於 0。", ephemeral=True)
        return

    if order_count is not None and order_count < 0:
        await interaction.response.send_message("完成訂單數不能小於 0。", ephemeral=True)
        return

    date_iso = None
    display_date = None
    if last_order_date is not None:
        date_iso, display_date = parse_manual_purchase_date(last_order_date)
        if date_iso is None:
            await interaction.response.send_message("最後下單日期格式錯誤，請用 20260512、2026/05/12 或 2026-05-12。", ephemeral=True)
            return

    data = get_customer_reward_data(customer.id)
    before_embed = build_member_info_embed(customer, data, show_points=True)

    if total_spent is not None:
        data["total_spent"] = total_spent
    if order_count is not None:
        data["order_count"] = order_count
    if date_iso is not None:
        data["last_order_at"] = date_iso
    if point_adjustment is not None:
        data["point_adjustment"] = point_adjustment

    data["points"] = get_current_reward_points(data)
    data["last_manual_fixed_at"] = get_taipei_now_iso()
    data["last_manual_fixed_by"] = interaction.user.id
    data["last_manual_fixed_reason"] = (reason or "").strip()
    CUSTOMER_REWARDS[customer.id] = data

    benefit_notices = await ensure_reward_member_benefits(interaction.guild, customer, data) if interaction.guild else []
    save_bot_data()

    after_embed = build_member_info_embed(customer, data, show_points=True)
    after_embed.title = "顧客會員資料已修正"
    if reason:
        after_embed.add_field(name="修正原因", value=reason, inline=False)
    if benefit_notices:
        after_embed.add_field(name="會員權益處理", value="\n".join(benefit_notices), inline=False)

    await send_order_log(
        interaction.guild,
        title="顧客會員資料已手動修正",
        fields=[
            ("顧客", customer.mention, True),
            ("操作人員", interaction.user.mention, True),
            ("累積消費", format_t_amount(int(data.get("total_spent", 0) or 0)), True),
            ("完成訂單", f"{int(data.get('order_count', 0) or 0)} 單", True),
            ("目前點數", f"{get_current_reward_points(data):,} 點", True),
            ("原因", reason or "未填寫", False),
        ],
        color=discord.Color.orange(),
    )

    await interaction.response.send_message(embed=after_embed, ephemeral=True)


VIP_LEVEL_NAME_TO_INDEX = {level["name"]: index for index, level in enumerate(MEMBER_LEVELS)}
VIP_LEVEL_CHOICES = [
    app_commands.Choice(name=level["name"], value=level["name"])
    for level in MEMBER_LEVELS
]


@bot.tree.command(
    name="set_customer_level",
    description="管理員直接指定顧客 VIP 等級",
    guild=discord.Object(id=GUILD_ID)
)
@app_commands.describe(
    customer="要調整 VIP 等級的顧客",
    level="要指定的會員等級",
    reason="調整原因，可不填"
)
@app_commands.choices(level=VIP_LEVEL_CHOICES)
async def set_customer_level(
    interaction: discord.Interaction,
    customer: discord.Member,
    level: app_commands.Choice[str],
    reason: str | None = None,
):
    if not isinstance(interaction.user, discord.Member):
        await interaction.response.send_message("無法確認你的身分組。", ephemeral=True)
        return

    if not is_manager_or_admin(interaction.user):
        await interaction.response.send_message("只有管理員或店長可以直接調整顧客 VIP 等級。", ephemeral=True)
        return

    target_index = VIP_LEVEL_NAME_TO_INDEX.get(level.value)
    if target_index is None:
        await interaction.response.send_message("會員等級不存在，請重新選擇。", ephemeral=True)
        return

    data = get_customer_reward_data(customer.id)
    old_level = get_effective_member_level(data)

    data["vip_level_index"] = target_index
    # 直接調整 / 降階後，都從目前等級的 0 開始重新累積下一級進度。
    data["vip_progress_base_total_spent"] = int(data.get("total_spent", 0) or 0)
    data["last_level_manual_fixed_at"] = get_taipei_now_iso()
    data["last_level_manual_fixed_by"] = interaction.user.id
    data["last_level_manual_fixed_reason"] = (reason or "").strip()

    CUSTOMER_REWARDS[customer.id] = data
    benefit_notices = await ensure_reward_member_benefits(interaction.guild, customer, data) if interaction.guild else []
    save_bot_data()

    embed = build_member_info_embed(customer, data, show_points=True)
    embed.title = "顧客 VIP 等級已調整"
    embed.add_field(name="原等級", value=old_level["name"], inline=True)
    embed.add_field(name="新等級", value=get_effective_member_level(data)["name"], inline=True)
    if reason:
        embed.add_field(name="調整原因", value=reason, inline=False)
    if benefit_notices:
        embed.add_field(name="會員權益處理", value="\n".join(benefit_notices), inline=False)

    await send_order_log(
        interaction.guild,
        title="顧客 VIP 等級已手動調整",
        fields=[
            ("顧客", customer.mention, True),
            ("操作人員", interaction.user.mention, True),
            ("原等級", old_level["name"], True),
            ("新等級", get_effective_member_level(data)["name"], True),
            ("原因", reason or "未填寫", False),
        ],
        color=discord.Color.orange(),
    )

    await interaction.response.send_message(embed=embed, ephemeral=True)



def _parse_iso_datetime_safely(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(str(value))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone(timedelta(hours=8)))
    return dt


def _get_order_closed_time(data: dict) -> datetime | None:
    return (
        _parse_iso_datetime_safely(data.get("closed_at"))
        or _parse_iso_datetime_safely(data.get("reward_counted_at"))
        or _parse_iso_datetime_safely(data.get("updated_at"))
    )


def _get_order_amount_for_stats(data: dict) -> int:
    for key in ("reward_amount", "amount", "total_amount"):
        value = data.get(key)
        if value is None:
            continue
        try:
            return int(value)
        except (TypeError, ValueError):
            parsed = parse_receipt_amount(str(value))
            if parsed is not None:
                return parsed
    return 0


def _is_closed_order_for_stats(data: dict) -> bool:
    return bool(data.get("closed")) or str(data.get("status", "")).lower() == "closed"


def _is_stored_order_for_stats(data: dict) -> bool:
    return str(data.get("status", "")).lower() == "stored"


def _is_cancelled_order_for_stats(data: dict) -> bool:
    return str(data.get("status", "")).lower() in {"cancelled", "canceled"}


def _normalize_stats_datetime_text(value: str | None) -> str | None:
    if not value:
        return None
    dt = _parse_iso_datetime_safely(str(value))
    if dt is None:
        # 支援 YYYYMMDD 這種舊補登日期
        text = str(value).strip()
        if len(text) == 8 and text.isdigit():
            return f"{text[0:4]}-{text[4:6]}-{text[6:8]}T00:00:00+08:00"
        return None
    return dt.isoformat(timespec="seconds")


def _get_sales_stats_from_sqlite(start_dt: datetime, end_dt: datetime) -> tuple[int, int, int, int]:
    """直接從 SQLite 統計營收，並相容兩種資料：
    1. 目前 Bot 使用的 JSON blob orders.data
    2. 舊營業額補登用的 relational/manual_revenue 資料
    回傳：完成訂單數、營收、目前存單數、目前取消單數
    """
    init_database()
    start_text = start_dt.isoformat(timespec="seconds")
    end_text = end_dt.isoformat(timespec="seconds")

    completed_count = 0
    total_revenue = 0
    stored_count = 0
    cancelled_count = 0

    try:
        with sqlite3.connect(DB_FILE) as conn:
            conn.row_factory = sqlite3.Row
            cur = conn.cursor()

            table_names = {
                row[0]
                for row in cur.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
            }

            if "orders" in table_names:
                order_columns = {
                    row[1]
                    for row in cur.execute("PRAGMA table_info(orders)").fetchall()
                }

                # 新版 SQLite 過渡資料表：orders(channel_id, data, updated_at)
                if "data" in order_columns:
                    for row in cur.execute("SELECT data FROM orders").fetchall():
                        try:
                            data = json.loads(row["data"])
                        except (TypeError, json.JSONDecodeError):
                            continue
                        if not isinstance(data, dict):
                            continue

                        if _is_stored_order_for_stats(data):
                            stored_count += 1
                        if _is_cancelled_order_for_stats(data):
                            cancelled_count += 1
                        if not _is_closed_order_for_stats(data):
                            continue

                        closed_text = _normalize_stats_datetime_text(
                            data.get("closed_at") or data.get("reward_counted_at") or data.get("updated_at")
                        )
                        if closed_text is None or not (start_text <= closed_text < end_text):
                            continue

                        completed_count += 1
                        total_revenue += _get_order_amount_for_stats(data)

                # 舊補登或正式 relational orders：orders(... amount/status/closed_at ...)
                if {"amount", "status"}.issubset(order_columns):
                    date_column = "closed_at" if "closed_at" in order_columns else "created_at"

                    if date_column in order_columns:
                        query = f"""
                            SELECT COUNT(*) AS count_value, COALESCE(SUM(amount), 0) AS revenue_value
                            FROM orders
                            WHERE status = 'closed'
                              AND {date_column} >= ?
                              AND {date_column} < ?
                        """
                        row = cur.execute(query, (start_text, end_text)).fetchone()
                        completed_count += int(row["count_value"] or 0)
                        total_revenue += int(row["revenue_value"] or 0)

                    stored_row = cur.execute("SELECT COUNT(*) AS c FROM orders WHERE status = 'stored'").fetchone()
                    cancelled_row = cur.execute("SELECT COUNT(*) AS c FROM orders WHERE status IN ('cancelled', 'canceled')").fetchone()
                    stored_count += int(stored_row["c"] or 0)
                    cancelled_count += int(cancelled_row["c"] or 0)

            # 建議之後舊營業額統一補進 manual_revenue，避免跟正式 orders 混在一起。
            if "manual_revenue" in table_names:
                manual_columns = {
                    row[1]
                    for row in cur.execute("PRAGMA table_info(manual_revenue)").fetchall()
                }
                if {"date_text", "amount", "status"}.issubset(manual_columns):
                    row = cur.execute(
                        """
                        SELECT COUNT(*) AS count_value, COALESCE(SUM(amount), 0) AS revenue_value
                        FROM manual_revenue
                        WHERE status = 'closed'
                          AND date_text >= ?
                          AND date_text < ?
                        """,
                        (start_text[:10], end_text[:10]),
                    ).fetchone()
                    completed_count += int(row["count_value"] or 0)
                    total_revenue += int(row["revenue_value"] or 0)

                    stored_row = cur.execute("SELECT COUNT(*) AS c FROM manual_revenue WHERE status = 'stored'").fetchone()
                    cancelled_row = cur.execute("SELECT COUNT(*) AS c FROM manual_revenue WHERE status IN ('cancelled', 'canceled')").fetchone()
                    stored_count += int(stored_row["c"] or 0)
                    cancelled_count += int(cancelled_row["c"] or 0)

    except sqlite3.Error as e:
        print(f"讀取 SQLite 統計失敗：{e}")

    return completed_count, total_revenue, stored_count, cancelled_count


def build_sales_stats_embed(title: str, start_dt: datetime, end_dt: datetime) -> discord.Embed:
    completed_count, total_revenue, stored_count, cancelled_count = _get_sales_stats_from_sqlite(start_dt, end_dt)
    avg_order = total_revenue // completed_count if completed_count else 0

    embed = discord.Embed(
        title=title,
        color=discord.Color.green(),
        timestamp=get_taipei_now(),
    )
    embed.add_field(name="完成訂單數", value=f"{completed_count:,} 單", inline=True)
    embed.add_field(name="營收", value=format_t_amount(total_revenue), inline=True)
    embed.add_field(name="平均客單價", value=format_t_amount(avg_order), inline=True)
    embed.add_field(name="目前存單數", value=f"{stored_count:,} 單", inline=True)
    embed.add_field(name="目前取消單數", value=f"{cancelled_count:,} 單", inline=True)
    embed.set_footer(text=f"統計區間：{start_dt.strftime('%Y/%m/%d %H:%M')} ～ {end_dt.strftime('%Y/%m/%d %H:%M')}")
    return embed

def _require_customer_staff_or_manager(interaction: discord.Interaction) -> bool:
    return (
        isinstance(interaction.user, discord.Member)
        and (is_customer_staff(interaction.user) or has_role(interaction.user, MANAGER_ROLE_ID) or interaction.user.guild_permissions.administrator)
    )


@bot.tree.command(
    name="stats_today",
    description="客服查詢今日營運統計",
    guild=discord.Object(id=GUILD_ID)
)
async def stats_today(interaction: discord.Interaction):
    if not _require_customer_staff_or_manager(interaction):
        await interaction.response.send_message("只有客服、店長或管理員可以查詢營運統計。", ephemeral=True)
        return

    now = get_taipei_now()
    start_dt = now.replace(hour=0, minute=0, second=0, microsecond=0)
    end_dt = start_dt + timedelta(days=1)
    embed = build_sales_stats_embed("今日營運統計", start_dt, end_dt)
    await interaction.response.send_message(embed=embed, ephemeral=True)


@bot.tree.command(
    name="stats_month",
    description="客服查詢本月營運統計",
    guild=discord.Object(id=GUILD_ID)
)
async def stats_month(interaction: discord.Interaction):
    if not _require_customer_staff_or_manager(interaction):
        await interaction.response.send_message("只有客服、店長或管理員可以查詢營運統計。", ephemeral=True)
        return

    now = get_taipei_now()
    start_dt = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    if start_dt.month == 12:
        end_dt = start_dt.replace(year=start_dt.year + 1, month=1)
    else:
        end_dt = start_dt.replace(month=start_dt.month + 1)
    embed = build_sales_stats_embed("本月營運統計", start_dt, end_dt)
    await interaction.response.send_message(embed=embed, ephemeral=True)


@bot.tree.command(
    name="top_customers",
    description="客服查詢顧客累積消費排行前 10 名",
    guild=discord.Object(id=GUILD_ID)
)
async def top_customers(interaction: discord.Interaction):
    if not _require_customer_staff_or_manager(interaction):
        await interaction.response.send_message("只有客服、店長或管理員可以查詢顧客排行。", ephemeral=True)
        return

    ranked = []
    for user_id, data in CUSTOMER_REWARDS.items():
        if not isinstance(data, dict):
            continue
        total_spent = int(data.get("total_spent", 0) or 0)
        if total_spent <= 0:
            continue
        ranked.append((user_id, total_spent, int(data.get("order_count", 0) or 0), get_effective_member_level(data)["name"]))

    ranked.sort(key=lambda row: row[1], reverse=True)
    top_rows = ranked[:10]

    embed = discord.Embed(
        title="顧客消費排行 TOP 10",
        color=discord.Color.gold(),
        timestamp=get_taipei_now(),
    )

    if not top_rows:
        embed.description = "目前還沒有可排行的顧客消費資料。"
    else:
        lines = []
        medals = ["🥇", "🥈", "🥉"]
        for index, (user_id, total_spent, order_count, level_name) in enumerate(top_rows, start=1):
            prefix = medals[index - 1] if index <= 3 else f"#{index}"
            lines.append(
                f"{prefix} <@{user_id}>｜{format_t_amount(total_spent)}｜{order_count:,} 單｜{level_name}"
            )
        embed.description = "\n".join(lines)

    await interaction.response.send_message(embed=embed, ephemeral=True)



@bot.tree.command(
    name="check_vip_downgrades",
    description="管理員手動檢查 VIP 維持條件並執行降階",
    guild=discord.Object(id=GUILD_ID)
)
@app_commands.describe(force="是否強制重新檢查本月，預設否")
async def check_vip_downgrades(interaction: discord.Interaction, force: bool = False):
    if not _require_customer_staff_or_manager(interaction):
        await interaction.response.send_message("只有客服、店長或管理員可以檢查 VIP 降階。", ephemeral=True)
        return

    await interaction.response.defer(ephemeral=True)
    changed_count, messages = await check_vip_downgrades_once(interaction.guild, force=force)

    if changed_count == 0:
        await interaction.followup.send(
            f"檢查完成，目前沒有需要降階的會員。維持條件：上月消費滿 {format_t_amount(VIP_MAINTAIN_MIN_MONTHLY_SPEND)}。",
            ephemeral=True
        )
        return

    preview = "\n".join(messages[:10])
    if len(messages) > 10:
        preview += f"\n…還有 {len(messages) - 10} 位"

    await interaction.followup.send(
        f"VIP 降階檢查完成，已降階 {changed_count} 位會員。\n{preview}",
        ephemeral=True,
        allowed_mentions=discord.AllowedMentions(users=True, roles=False, everyone=False),
    )


@bot.tree.command(
    name="order_search",
    description="客服搜尋訂單，可用訂單編號、顧客 ID、項目或狀態查詢",
    guild=discord.Object(id=GUILD_ID)
)
@app_commands.describe(
    keyword="關鍵字：訂單編號、顧客ID、項目名稱，可不填",
    status="狀態：active / stored / closed / cancelled，可不填",
    limit="最多顯示幾筆，預設 10，最多 20"
)
async def order_search(
    interaction: discord.Interaction,
    keyword: str | None = None,
    status: str | None = None,
    limit: int = 10,
):
    if not _require_customer_staff_or_manager(interaction):
        await interaction.response.send_message("只有客服、店長或管理員可以搜尋訂單。", ephemeral=True)
        return

    limit = max(1, min(int(limit or 10), 20))
    keyword_text = (keyword or "").strip().lower()
    status_text = (status or "").strip().lower()

    matches = []
    for channel_id, data in SELF_SERVICE_ORDER_SELECTIONS.items():
        if not isinstance(data, dict):
            continue

        order_status = str(data.get("status") or ("closed" if data.get("closed") else "active")).lower()
        if status_text and order_status != status_text:
            continue

        customer_id = data.get("customer_id") or ""
        haystack = " ".join([
            str(data.get("order_no") or ""),
            str(customer_id),
            str(data.get("category") or ""),
            str(data.get("item") or ""),
            str(data.get("payment_method") or ""),
            str(channel_id),
            order_status,
        ]).lower()

        if keyword_text and keyword_text not in haystack:
            continue

        matches.append((channel_id, data))

    def sort_key(row):
        _, data = row
        return str(data.get("closed_at") or data.get("stored_at") or data.get("created_at") or data.get("updated_at") or "")

    matches.sort(key=sort_key, reverse=True)
    shown = matches[:limit]

    embed = discord.Embed(
        title="訂單搜尋結果",
        color=discord.Color.blurple(),
        timestamp=get_taipei_now(),
    )

    if not shown:
        embed.description = "沒有找到符合條件的訂單。"
    else:
        lines = []
        for channel_id, data in shown:
            order_no = data.get("order_no") or "未產生"
            customer_id = data.get("customer_id")
            customer_text = f"<@{customer_id}>" if customer_id else "未紀錄"
            item = data.get("item") or "未紀錄"
            quantity = _to_int(data.get("quantity"), 1) or 1
            amount = _to_int(data.get("amount"), 0) or 0
            order_status = str(data.get("status") or ("closed" if data.get("closed") else "active"))
            ticket_text = f"<#{channel_id}>" if int(channel_id) > 0 else f"歷史資料 {channel_id}"
            lines.append(
                f"**{order_no}**｜{order_status}\n"
                f"顧客：{customer_text}｜項目：{item} x{quantity}｜金額：{format_t_amount(amount) if amount else '未紀錄'}\n"
                f"票口：{ticket_text}"
            )
        embed.description = "\n\n".join(lines)
        if len(matches) > limit:
            embed.set_footer(text=f"只顯示前 {limit} 筆，共找到 {len(matches)} 筆")

    await interaction.response.send_message(embed=embed, ephemeral=True)


# ========= 訂單修正 / 刪除指令 =========

ORDER_MAINTENANCE_BACKUP_PREFIX = "manual_order_maintenance"


def find_order_by_identifier(identifier: str) -> tuple[int | None, dict | None]:
    """用訂單編號或票口 ID 從記憶體訂單資料找單。"""
    key = str(identifier or "").strip()
    if not key:
        return None, None

    channel_id = _to_int(key)
    if channel_id is not None and channel_id in SELF_SERVICE_ORDER_SELECTIONS:
        data = SELF_SERVICE_ORDER_SELECTIONS.get(channel_id)
        if isinstance(data, dict):
            return channel_id, data

    key_lower = key.lower()
    for order_channel_id, data in SELF_SERVICE_ORDER_SELECTIONS.items():
        if not isinstance(data, dict):
            continue
        candidates = [
            data.get("order_no"),
            data.get("receipt_id"),
            str(order_channel_id),
        ]
        if any(str(value or "").strip().lower() == key_lower for value in candidates):
            return int(order_channel_id), data

    return None, None


def is_order_closed_for_rewards(data: dict) -> bool:
    status = str(data.get("status") or "").lower()
    return bool(data.get("reward_counted") or data.get("closed") or status == "closed")


def get_order_amount_for_maintenance(data: dict) -> int:
    """Safely parse order amount for maintenance commands.

    This stays local to bot.py so maintenance/audit tools do not depend on
    private database-module helpers during modularization.
    """
    if not isinstance(data, dict):
        return 0

    for key in ("amount", "total_amount", "reward_amount"):
        value = data.get(key)
        if value is None or value == "":
            continue
        try:
            return max(0, int(value))
        except (TypeError, ValueError):
            parsed = parse_receipt_amount(str(value))
            if parsed is not None:
                return max(0, int(parsed))

    return 0


def adjust_customer_totals_for_order(customer_id: int | None, amount_delta: int, order_delta: int) -> dict | None:
    """手動修單時同步 customers 記憶體資料；amount_delta 可正可負。"""
    parsed_customer_id = _to_int(customer_id)
    if parsed_customer_id is None:
        return None

    data = get_customer_reward_data(parsed_customer_id)
    data["total_spent"] = max(0, int(data.get("total_spent", 0) or 0) + int(amount_delta or 0))
    data["order_count"] = max(0, int(data.get("order_count", 0) or 0) + int(order_delta or 0))
    data["points"] = get_current_reward_points(data)
    data["vip_level_index"] = get_effective_member_level_index(data)
    if amount_delta or order_delta:
        data["last_manual_fixed_at"] = get_taipei_now_iso()
    CUSTOMER_REWARDS[parsed_customer_id] = data
    return data


async def refresh_customer_benefits_after_manual_fix(guild: discord.Guild | None, customer_ids: list[int | None]) -> list[str]:
    if guild is None:
        return []

    notices = []
    seen: set[int] = set()
    for raw_customer_id in customer_ids:
        customer_id = _to_int(raw_customer_id)
        if customer_id is None or customer_id in seen:
            continue
        seen.add(customer_id)
        data = CUSTOMER_REWARDS.get(customer_id)
        if not isinstance(data, dict):
            continue
        member = await fetch_member_safely(guild, customer_id)
        benefit_notices = await ensure_reward_member_benefits(guild, member, data)
        if benefit_notices:
            notices.extend([f"<@{customer_id}>：{notice}" for notice in benefit_notices])
    return notices


def backup_database_for_manual_order_fix() -> str | None:
    if not DB_FILE.exists():
        return None
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    backup_path = BACKUP_DIR / f"{ORDER_MAINTENANCE_BACKUP_PREFIX}_{get_taipei_now().strftime('%Y%m%d_%H%M%S')}.db"
    try:
        shutil.copy2(DB_FILE, backup_path)
        return str(backup_path)
    except OSError as e:
        print(f"建立手動修單備份失敗：{e}")
        return None


async def delete_dispatch_message_for_order(guild: discord.Guild | None, data: dict) -> bool:
    if guild is None:
        return False

    dispatch_message_id = _to_int(data.get("dispatch_message_id"))
    if dispatch_message_id is None:
        return False

    dispatch_channel_id = _to_int(data.get("dispatch_channel_id"), DISPATCH_CHANNEL_ID) or DISPATCH_CHANNEL_ID
    dispatch_channel = guild.get_channel(dispatch_channel_id)
    if not isinstance(dispatch_channel, discord.TextChannel):
        return False

    try:
        message = await dispatch_channel.fetch_message(dispatch_message_id)
        await message.delete(reason="Order manually deleted by staff")
        return True
    except (discord.NotFound, discord.Forbidden, discord.HTTPException):
        return False


def build_order_maintenance_result_embed(title: str, description: str, data: dict | None = None) -> discord.Embed:
    embed = discord.Embed(
        title=title,
        description=description,
        color=discord.Color.orange(),
        timestamp=get_taipei_now(),
    )
    if data:
        embed.add_field(name="訂單編號", value=str(data.get("order_no") or data.get("receipt_id") or "未產生"), inline=True)
        embed.add_field(name="顧客", value=f"<@{data.get('customer_id')}>" if data.get("customer_id") else "未紀錄", inline=True)
        embed.add_field(name="項目", value=str(data.get("item") or "未紀錄"), inline=True)
        embed.add_field(name="金額", value=format_t_amount(get_order_amount_for_maintenance(data)), inline=True)
        embed.add_field(name="狀態", value=str(data.get("status") or ("closed" if data.get("closed") else "active")), inline=True)
    return embed


@bot.tree.command(
    name="delete_order",
    description="客服刪除訂單資料，支援訂單編號或票口 ID",
    guild=discord.Object(id=GUILD_ID)
)
@app_commands.describe(
    order="訂單編號或票口 ID，例如 MO20260521003 或 1506712687458123917",
    adjust_customer="若訂單已結單，是否同步扣回會員累積與完成單數，預設是",
    delete_dispatch_panel="是否嘗試刪除派單頻道接單面板，預設是"
)
async def delete_order(
    interaction: discord.Interaction,
    order: str,
    adjust_customer: bool = True,
    delete_dispatch_panel: bool = True,
):
    if not _require_customer_staff_or_manager(interaction):
        await interaction.response.send_message("只有客服、店長或管理員可以刪除訂單。", ephemeral=True)
        return

    channel_id, data = find_order_by_identifier(order)
    if channel_id is None or data is None:
        await interaction.response.send_message("找不到這筆訂單，請確認訂單編號或票口 ID 是否正確。", ephemeral=True)
        return

    await interaction.response.defer(ephemeral=True)
    backup_path = backup_database_for_manual_order_fix()

    old_data = dict(data)
    customer_id = _to_int(data.get("customer_id"))
    amount = get_order_amount_for_maintenance(data)
    order_count_delta = -1 if is_order_closed_for_rewards(data) else 0

    if adjust_customer and is_order_closed_for_rewards(data):
        adjust_customer_totals_for_order(customer_id, -amount, order_count_delta)

    dispatch_deleted = False
    if delete_dispatch_panel:
        dispatch_deleted = await delete_dispatch_message_for_order(interaction.guild, data)

    dispatch_message_id = _to_int(data.get("dispatch_message_id"))
    if dispatch_message_id is not None:
        ORDER_CLAIMS.pop(dispatch_message_id, None)
        delete_claim_row_from_db(message_id=dispatch_message_id)

    SELF_SERVICE_ORDER_SELECTIONS.pop(channel_id, None)
    delete_order_row_from_db(channel_id)
    save_bot_data()
    benefit_notices = await refresh_customer_benefits_after_manual_fix(interaction.guild, [customer_id])

    description = (
        f"已刪除訂單資料。\n"
        f"票口 ID：`{channel_id}`\n"
        f"會員同步：{'已扣回' if adjust_customer and is_order_closed_for_rewards(old_data) else '未扣回 / 不適用'}\n"
        f"派單面板：{'已刪除' if dispatch_deleted else '未刪除或找不到'}\n"
        f"備份：`{backup_path or '建立失敗或無資料庫'}`"
    )
    if benefit_notices:
        description += "\n" + "\n".join(benefit_notices[:5])

    embed = build_order_maintenance_result_embed("刪除訂單完成", description, old_data)
    await interaction.followup.send(embed=embed, ephemeral=True, allowed_mentions=discord.AllowedMentions(users=True, roles=False, everyone=False))

    await send_order_log(
        interaction.guild,
        title="手動刪除訂單",
        description=description,
        fields=[
            ("操作人員", interaction.user.mention, True),
            ("訂單", str(old_data.get("order_no") or order), True),
            ("顧客", f"<@{customer_id}>" if customer_id else "未紀錄", True),
        ],
        color=discord.Color.red(),
    )


@bot.tree.command(
    name="fix_order_amount",
    description="客服修正訂單金額，可同步調整會員累積",
    guild=discord.Object(id=GUILD_ID)
)
@app_commands.describe(
    order="訂單編號或票口 ID",
    amount="新的金額，只能輸入數字，例如 1275",
    adjust_customer="若訂單已結單，是否同步調整會員累積，預設是"
)
async def fix_order_amount(
    interaction: discord.Interaction,
    order: str,
    amount: int,
    adjust_customer: bool = True,
):
    if not _require_customer_staff_or_manager(interaction):
        await interaction.response.send_message("只有客服、店長或管理員可以修正訂單金額。", ephemeral=True)
        return

    if amount < 0:
        await interaction.response.send_message("金額不能小於 0。", ephemeral=True)
        return

    channel_id, data = find_order_by_identifier(order)
    if channel_id is None or data is None:
        await interaction.response.send_message("找不到這筆訂單，請確認訂單編號或票口 ID 是否正確。", ephemeral=True)
        return

    await interaction.response.defer(ephemeral=True)
    backup_path = backup_database_for_manual_order_fix()

    old_amount = get_order_amount_for_maintenance(data)
    delta = int(amount) - old_amount
    customer_id = _to_int(data.get("customer_id"))

    data["amount"] = int(amount)
    data["total_amount"] = int(amount)
    if data.get("reward_counted") or data.get("reward_amount") is not None:
        data["reward_amount"] = int(amount)
    data["manual_fixed_at"] = get_taipei_now_iso()
    data["manual_fixed_by"] = interaction.user.id
    data["manual_fix_note"] = f"金額由 {old_amount} 修正為 {amount}"
    SELF_SERVICE_ORDER_SELECTIONS[channel_id] = data

    if adjust_customer and is_order_closed_for_rewards(data) and delta != 0:
        adjust_customer_totals_for_order(customer_id, delta, 0)

    remember_order_data(channel_id, data)
    save_bot_data()
    benefit_notices = await refresh_customer_benefits_after_manual_fix(interaction.guild, [customer_id])

    description = (
        f"已修正訂單金額。\n"
        f"票口 ID：`{channel_id}`\n"
        f"原金額：{format_t_amount(old_amount)}\n"
        f"新金額：{format_t_amount(int(amount))}\n"
        f"差額：{format_t_amount(delta)}\n"
        f"會員同步：{'已同步' if adjust_customer and is_order_closed_for_rewards(data) else '未同步 / 不適用'}\n"
        f"備份：`{backup_path or '建立失敗或無資料庫'}`"
    )
    if benefit_notices:
        description += "\n" + "\n".join(benefit_notices[:5])

    embed = build_order_maintenance_result_embed("修正訂單金額完成", description, data)
    await interaction.followup.send(embed=embed, ephemeral=True, allowed_mentions=discord.AllowedMentions(users=True, roles=False, everyone=False))

    await send_order_log(
        interaction.guild,
        title="手動修正訂單金額",
        description=description,
        fields=[
            ("操作人員", interaction.user.mention, True),
            ("訂單", str(data.get("order_no") or order), True),
            ("顧客", f"<@{customer_id}>" if customer_id else "未紀錄", True),
        ],
        color=discord.Color.orange(),
    )


@bot.tree.command(
    name="fix_order_customer",
    description="客服修正訂單顧客，可同步搬移會員累積",
    guild=discord.Object(id=GUILD_ID)
)
@app_commands.describe(
    order="訂單編號或票口 ID",
    customer="正確的顧客",
    adjust_customer="若訂單已結單，是否把會員累積從舊顧客搬到新顧客，預設是"
)
async def fix_order_customer(
    interaction: discord.Interaction,
    order: str,
    customer: discord.Member,
    adjust_customer: bool = True,
):
    if not _require_customer_staff_or_manager(interaction):
        await interaction.response.send_message("只有客服、店長或管理員可以修正訂單顧客。", ephemeral=True)
        return

    channel_id, data = find_order_by_identifier(order)
    if channel_id is None or data is None:
        await interaction.response.send_message("找不到這筆訂單，請確認訂單編號或票口 ID 是否正確。", ephemeral=True)
        return

    await interaction.response.defer(ephemeral=True)
    backup_path = backup_database_for_manual_order_fix()

    old_customer_id = _to_int(data.get("customer_id"))
    new_customer_id = int(customer.id)
    amount = get_order_amount_for_maintenance(data)
    closed = is_order_closed_for_rewards(data)

    data["customer_id"] = new_customer_id
    data["manual_fixed_at"] = get_taipei_now_iso()
    data["manual_fixed_by"] = interaction.user.id
    data["manual_fix_note"] = f"顧客由 {old_customer_id or '未紀錄'} 修正為 {new_customer_id}"
    SELF_SERVICE_ORDER_SELECTIONS[channel_id] = data

    dispatch_message_id = _to_int(data.get("dispatch_message_id"))
    if dispatch_message_id is not None and dispatch_message_id in ORDER_CLAIMS:
        ORDER_CLAIMS[dispatch_message_id]["customer_id"] = new_customer_id
        remember_claim_data(dispatch_message_id, ORDER_CLAIMS[dispatch_message_id])

    if adjust_customer and closed and amount > 0 and old_customer_id != new_customer_id:
        adjust_customer_totals_for_order(old_customer_id, -amount, -1)
        adjust_customer_totals_for_order(new_customer_id, amount, 1)

    remember_order_data(channel_id, data)
    save_bot_data()
    benefit_notices = await refresh_customer_benefits_after_manual_fix(interaction.guild, [old_customer_id, new_customer_id])

    description = (
        f"已修正訂單顧客。\n"
        f"票口 ID：`{channel_id}`\n"
        f"原顧客：{f'<@{old_customer_id}>' if old_customer_id else '未紀錄'}\n"
        f"新顧客：{customer.mention}\n"
        f"金額：{format_t_amount(amount)}\n"
        f"會員同步：{'已搬移' if adjust_customer and closed and old_customer_id != new_customer_id else '未搬移 / 不適用'}\n"
        f"備份：`{backup_path or '建立失敗或無資料庫'}`"
    )
    if benefit_notices:
        description += "\n" + "\n".join(benefit_notices[:5])

    embed = build_order_maintenance_result_embed("修正訂單顧客完成", description, data)
    await interaction.followup.send(embed=embed, ephemeral=True, allowed_mentions=discord.AllowedMentions(users=True, roles=False, everyone=False))

    await send_order_log(
        interaction.guild,
        title="手動修正訂單顧客",
        description=description,
        fields=[
            ("操作人員", interaction.user.mention, True),
            ("訂單", str(data.get("order_no") or order), True),
            ("新顧客", customer.mention, True),
        ],
        color=discord.Color.orange(),
    )



@bot.tree.command(
    name="resend_dispatch",
    description="重新發送指定票口的派單面板"
)
@app_commands.describe(
    order_channel_id="票口頻道 ID，例如 1506962556928131112"
)
async def resend_dispatch(interaction: discord.Interaction, order_channel_id: str):
    """重新建立可操作的派單面板。\n\n    用於派單頻道訊息被刪除、按鈕失效、claims 重複或連結錯亂時。\n    會清除同一票口舊 claims，發一則新的 DispatchClaimView，並把新訊息 ID 寫回資料。\n    """
    if not isinstance(interaction.user, discord.Member):
        await interaction.response.send_message("無法確認你的身分組。", ephemeral=True)
        return

    if not (is_customer_staff(interaction.user) or is_manager_or_admin(interaction.user)):
        await interaction.response.send_message("只有客服、店長或管理員可以重新派單。", ephemeral=True)
        return

    guild = interaction.guild
    if guild is None:
        await interaction.response.send_message("這個功能只能在伺服器內使用。", ephemeral=True)
        return

    try:
        source_channel_id = int(str(order_channel_id).strip())
    except ValueError:
        await interaction.response.send_message("票口 ID 格式錯誤，請輸入純數字。", ephemeral=True)
        return

    await interaction.response.defer(ephemeral=True)

    source_channel = guild.get_channel(source_channel_id)
    if source_channel is None:
        try:
            fetched_channel = await guild.fetch_channel(source_channel_id)
            source_channel = fetched_channel if isinstance(fetched_channel, discord.TextChannel) else None
        except (discord.NotFound, discord.Forbidden, discord.HTTPException):
            source_channel = None

    if source_channel is None or not isinstance(source_channel, discord.TextChannel):
        await interaction.followup.send("找不到這個票口頻道，請確認票口 ID 是否正確。", ephemeral=True)
        return

    dispatch_channel = guild.get_channel(DISPATCH_CHANNEL_ID)
    if dispatch_channel is None:
        try:
            fetched_dispatch = await guild.fetch_channel(DISPATCH_CHANNEL_ID)
            dispatch_channel = fetched_dispatch if isinstance(fetched_dispatch, discord.TextChannel) else None
        except (discord.NotFound, discord.Forbidden, discord.HTTPException):
            dispatch_channel = None

    if dispatch_channel is None or not isinstance(dispatch_channel, discord.TextChannel):
        await interaction.followup.send("找不到派單頻道，請確認 DISPATCH_CHANNEL_ID 是否正確。", ephemeral=True)
        return

    data = SELF_SERVICE_ORDER_SELECTIONS.get(source_channel_id)
    if not isinstance(data, dict):
        await interaction.followup.send("找不到這張票口的訂單資料，無法重新派單。", ephemeral=True)
        return

    # 清掉同一票口舊 claims，避免一張票口對到多則派單訊息。
    for message_id, claim_data in list(ORDER_CLAIMS.items()):
        if _to_int(claim_data.get("source_channel_id")) == source_channel_id:
            ORDER_CLAIMS.pop(message_id, None)
            delete_claim_row_from_db(message_id=_to_int(message_id), source_channel_id=source_channel_id)

    old_dispatch_message_id = _to_int(data.get("dispatch_message_id"))
    if old_dispatch_message_id is not None:
        delete_claim_row_from_db(message_id=old_dispatch_message_id)

    customer_id = _to_int(data.get("customer_id")) or get_order_customer_id_from_channel(source_channel)
    category = data.get("category")
    category_label = ORDER_CATEGORY_LABELS.get(category, data.get("category_label") or category or "未紀錄")
    item = str(data.get("item") or "未紀錄")
    quantity = _to_int(data.get("quantity"), 1) or 1
    payment_method = str(data.get("payment_method") or "未紀錄")
    companion_preference = data.get("companion_preference") or "不指定陪玩/打手"
    customer_mention = f"<@{customer_id}>" if customer_id is not None else "未紀錄"

    embed = build_self_service_order_embed(
        customer_mention=customer_mention,
        category_label=str(category_label),
        item=item,
        quantity=quantity,
        payment_method=payment_method,
        source_channel=source_channel,
        companion_preference=companion_preference,
    )
    embed.add_field(
        name="重新派單",
        value=f"由 {interaction.user.mention} 使用 `/resend_dispatch` 重新發送。",
        inline=False,
    )

    view = DispatchClaimView(
        customer_id=customer_id or 0,
        category_label=str(category_label),
        item=item,
        quantity=quantity,
        payment_method=payment_method,
        source_channel_id=source_channel_id,
        companion_preference=companion_preference,
        locked=False,
        status="active",
    )

    dispatch_message = await dispatch_channel.send(
        embed=embed,
        view=view,
        allowed_mentions=discord.AllowedMentions(users=True, roles=False, everyone=False),
    )

    claim_data = {
        "companion": set(),
        "booster": set(),
        "locked": False,
        "status": "active",
        "customer_id": customer_id,
        "category_label": str(category_label),
        "item": item,
        "quantity": quantity,
        "payment_method": payment_method,
        "source_channel_id": source_channel_id,
        "companion_preference": companion_preference,
        "dispatch_channel_id": dispatch_channel.id,
    }

    ORDER_CLAIMS[dispatch_message.id] = claim_data

    data["customer_id"] = customer_id
    data["item"] = item
    data["quantity"] = quantity
    data["payment_method"] = payment_method
    data["companion_preference"] = companion_preference
    data["closed"] = False
    data["status"] = "active"
    data["closed_at"] = None
    data["stored_at"] = None
    data["stored_by"] = None
    data["stored_reason"] = None
    data["stored_expected_time"] = None
    data["stored_note"] = None
    data["dispatch_channel_id"] = dispatch_channel.id
    data["dispatch_message_id"] = dispatch_message.id

    remember_order_data(source_channel_id, data)
    remember_claim_data(dispatch_message.id, claim_data)
    save_bot_data()

    await send_order_log(
        guild,
        title="重新發送派單面板",
        fields=[
            ("操作人員", interaction.user.mention, True),
            ("顧客", customer_mention, True),
            ("項目", f"{item} x{quantity}", True),
            ("票口", source_channel.mention, False),
            ("新派單訊息", dispatch_message.jump_url, False),
        ],
        color=discord.Color.orange(),
    )

    await interaction.followup.send(
        f"已重新發送可操作派單訊息：{dispatch_message.jump_url}",
        ephemeral=True,
    )


# ========= 資料庫健康檢查指令 =========

def audit_amount_text(amount) -> str:
    """Format money for /audit_data.

    This function is intentionally local to the audit block and does not depend on
    reward-service helpers, so /audit_data will not break during modularization.
    """
    try:
        value = int(amount or 0)
    except (TypeError, ValueError):
        return f"{amount}T"
    return f"{value:,}T"


def _audit_order_status(data: dict) -> str:
    return str(data.get("status") or ("closed" if data.get("closed") else "active")).lower()


def _audit_order_amount(data: dict) -> int:
    return get_order_amount_for_maintenance(data)


def _audit_closed_orders_by_customer() -> dict[int, dict]:
    totals: dict[int, dict] = {}

    for channel_id, data in SELF_SERVICE_ORDER_SELECTIONS.items():
        if not isinstance(data, dict):
            continue

        if _audit_order_status(data) != "closed" and not data.get("closed"):
            continue

        customer_id = _to_int(data.get("customer_id"))
        if customer_id is None:
            continue

        bucket = totals.setdefault(
            customer_id,
            {
                "amount": 0,
                "quantity": 0,
                "orders": 0,
                "channel_ids": [],
            }
        )
        bucket["amount"] += _audit_order_amount(data)
        bucket["quantity"] += _to_int(data.get("quantity"), 1) or 1
        bucket["orders"] += 1
        bucket["channel_ids"].append(channel_id)

    return totals


def build_audit_data_report(limit: int = 10) -> tuple[discord.Embed, str]:
    safe_limit = max(1, min(int(limit or 10), 25))
    closed_totals = _audit_closed_orders_by_customer()

    customer_mismatches = []
    checked_customer_ids = set(CUSTOMER_REWARDS.keys()) | set(closed_totals.keys())

    for customer_id in sorted(checked_customer_ids):
        customer_data = CUSTOMER_REWARDS.get(customer_id, {})
        if not isinstance(customer_data, dict):
            customer_data = {}

        customer_total = int(customer_data.get("total_spent", 0) or 0)
        customer_order_count = int(customer_data.get("order_count", 0) or 0)
        order_bucket = closed_totals.get(customer_id, {"amount": 0, "quantity": 0, "orders": 0})
        closed_amount = int(order_bucket.get("amount", 0) or 0)
        closed_quantity = int(order_bucket.get("quantity", 0) or 0)

        amount_diff = customer_total - closed_amount
        count_diff = customer_order_count - closed_quantity

        if amount_diff != 0 or count_diff != 0:
            customer_mismatches.append({
                "customer_id": customer_id,
                "customer_total": customer_total,
                "closed_amount": closed_amount,
                "amount_diff": amount_diff,
                "customer_order_count": customer_order_count,
                "closed_quantity": closed_quantity,
                "count_diff": count_diff,
            })

    closed_zero_orders = []
    missing_customer_orders = []
    stored_orders = []
    active_orders = []
    reward_not_counted_closed = []
    duplicate_order_nos: dict[str, list[int]] = {}
    duplicate_dispatch_ids: dict[int, list[int]] = {}
    orphan_claims = []

    known_order_channels = set(SELF_SERVICE_ORDER_SELECTIONS.keys())

    for channel_id, data in SELF_SERVICE_ORDER_SELECTIONS.items():
        if not isinstance(data, dict):
            continue

        status = _audit_order_status(data)
        amount = _audit_order_amount(data)
        order_no = str(data.get("order_no") or data.get("receipt_id") or "").strip()
        dispatch_message_id = _to_int(data.get("dispatch_message_id"))

        if order_no:
            duplicate_order_nos.setdefault(order_no, []).append(int(channel_id))
        if dispatch_message_id is not None:
            duplicate_dispatch_ids.setdefault(dispatch_message_id, []).append(int(channel_id))

        if status == "closed" or data.get("closed"):
            if amount <= 0:
                closed_zero_orders.append((channel_id, data))
            if not data.get("reward_counted"):
                reward_not_counted_closed.append((channel_id, data))

        if _to_int(data.get("customer_id")) is None:
            missing_customer_orders.append((channel_id, data))

        if status == "stored":
            stored_orders.append((channel_id, data))
        elif status == "active":
            active_orders.append((channel_id, data))

    for message_id, claim in ORDER_CLAIMS.items():
        if not isinstance(claim, dict):
            continue
        source_channel_id = _to_int(claim.get("source_channel_id"))
        if source_channel_id is None or source_channel_id not in known_order_channels:
            orphan_claims.append((message_id, claim))

    duplicated_order_nos = {k: v for k, v in duplicate_order_nos.items() if len(v) > 1}
    duplicated_dispatch_ids = {k: v for k, v in duplicate_dispatch_ids.items() if len(v) > 1}

    summary_lines = [
        "資料庫健康檢查完成。",
        f"總訂單暫存：{len(SELF_SERVICE_ORDER_SELECTIONS):,} 筆",
        f"顧客資料：{len(CUSTOMER_REWARDS):,} 筆",
        f"接單面板 claims：{len(ORDER_CLAIMS):,} 筆",
        "",
        f"會員 / 已結訂單對帳異常：{len(customer_mismatches):,} 筆",
        f"已結單金額為 0：{len(closed_zero_orders):,} 筆",
        f"缺少 customer_id 訂單：{len(missing_customer_orders):,} 筆",
        f"存單：{len(stored_orders):,} 筆",
        f"進行中訂單：{len(active_orders):,} 筆",
        f"已結但未標記 reward_counted：{len(reward_not_counted_closed):,} 筆",
        f"重複訂單編號：{len(duplicated_order_nos):,} 組",
        f"重複派單訊息 ID：{len(duplicated_dispatch_ids):,} 組",
        f"找不到來源訂單的 claims：{len(orphan_claims):,} 筆",
    ]

    detail_lines = []

    def order_line(channel_id: int, data: dict) -> str:
        order_no = data.get("order_no") or data.get("receipt_id") or "未產生"
        customer_id = data.get("customer_id")
        customer_text = f"<@{customer_id}>" if customer_id else "未紀錄"
        item = data.get("item") or "未紀錄"
        amount = _audit_order_amount(data)
        status = _audit_order_status(data)
        return f"{order_no}｜票口 {channel_id}｜{customer_text}｜{item}｜{audit_amount_text(amount)}｜{status}"

    if customer_mismatches:
        detail_lines.append("\n【會員 / 已結訂單對帳異常】")
        for item in customer_mismatches[:safe_limit]:
            detail_lines.append(
                f"<@{item['customer_id']}>｜會員累積 {audit_amount_text(item['customer_total'])} / "
                f"已結訂單 {audit_amount_text(item['closed_amount'])} / 差額 {audit_amount_text(item['amount_diff'])}｜"
                f"會員單數 {item['customer_order_count']} / 已結數量 {item['closed_quantity']} / 差 {item['count_diff']}"
            )
        if len(customer_mismatches) > safe_limit:
            detail_lines.append(f"…還有 {len(customer_mismatches) - safe_limit} 筆")

    for title, rows in [
        ("已結單金額為 0", closed_zero_orders),
        ("缺少 customer_id 訂單", missing_customer_orders),
        ("存單", stored_orders),
        ("已結但未標記 reward_counted", reward_not_counted_closed),
    ]:
        if rows:
            detail_lines.append(f"\n【{title}】")
            for channel_id, data in rows[:safe_limit]:
                detail_lines.append(order_line(channel_id, data))
            if len(rows) > safe_limit:
                detail_lines.append(f"…還有 {len(rows) - safe_limit} 筆")

    if duplicated_order_nos:
        detail_lines.append("\n【重複訂單編號】")
        for order_no, channel_ids in list(duplicated_order_nos.items())[:safe_limit]:
            detail_lines.append(f"{order_no}｜票口：{', '.join(str(cid) for cid in channel_ids)}")

    if duplicated_dispatch_ids:
        detail_lines.append("\n【重複派單訊息 ID】")
        for message_id, channel_ids in list(duplicated_dispatch_ids.items())[:safe_limit]:
            detail_lines.append(f"{message_id}｜票口：{', '.join(str(cid) for cid in channel_ids)}")

    if orphan_claims:
        detail_lines.append("\n【找不到來源訂單的 claims】")
        for message_id, claim in orphan_claims[:safe_limit]:
            detail_lines.append(f"派單訊息 {message_id}｜來源票口：{claim.get('source_channel_id') or '未紀錄'}｜項目：{claim.get('item') or '未紀錄'}")

    full_report = "\n".join(summary_lines + detail_lines)

    has_problem = any([
        customer_mismatches,
        closed_zero_orders,
        missing_customer_orders,
        reward_not_counted_closed,
        duplicated_order_nos,
        duplicated_dispatch_ids,
        orphan_claims,
    ])

    embed = discord.Embed(
        title="資料庫健康檢查",
        description="\n".join(summary_lines),
        color=discord.Color.orange() if has_problem else discord.Color.green(),
        timestamp=get_taipei_now(),
    )
    embed.set_footer(text=f"明細上限：每類 {safe_limit} 筆。完整內容會在訊息或附件中提供。")

    return embed, full_report


@bot.tree.command(
    name="audit_data",
    description="客服檢查訂單、會員累積、存單與接單面板資料是否異常",
    guild=discord.Object(id=GUILD_ID)
)
@app_commands.describe(limit="每一類最多顯示幾筆明細，預設 10，最高 25")
async def audit_data(interaction: discord.Interaction, limit: int = 10):
    if not _require_customer_staff_or_manager(interaction):
        await interaction.response.send_message("只有客服、店長或管理員可以檢查資料庫健康狀態。", ephemeral=True)
        return

    await interaction.response.defer(ephemeral=True)
    started_at = get_taipei_now()

    try:
        embed, full_report = build_audit_data_report(limit=limit)
    except Exception as e:
        error_text = f"/audit_data 執行失敗：{type(e).__name__}: {e}"
        await interaction.followup.send(error_text, ephemeral=True)
        await send_order_log(
            interaction.guild,
            title="資料庫健康檢查失敗",
            description=f"操作人員：{interaction.user.mention}\n```text\n{error_text[:1500]}\n```",
            color=discord.Color.red(),
        )
        return

    elapsed = (get_taipei_now() - started_at).total_seconds()
    embed.add_field(name="檢查耗時", value=f"{elapsed:.2f} 秒", inline=True)

    if len(full_report) <= 3500:
        embed.add_field(
            name="檢查明細",
            value=f"```text\n{full_report[:1000]}\n```" if len(full_report) <= 1000 else "明細較長，請看下方文字。",
            inline=False,
        )
        await interaction.followup.send(
            embed=embed,
            content=f"```text\n{full_report[:1900]}\n```" if len(full_report) <= 1900 else None,
            ephemeral=True,
            allowed_mentions=discord.AllowedMentions(users=True, roles=False, everyone=False),
        )
    else:
        report_file = discord.File(
            io.BytesIO(full_report.encode("utf-8")),
            filename=f"audit_data_{get_taipei_now().strftime('%Y%m%d_%H%M%S')}.txt",
        )
        await interaction.followup.send(
            embed=embed,
            file=report_file,
            ephemeral=True,
            allowed_mentions=discord.AllowedMentions(users=True, roles=False, everyone=False),
        )

    await send_order_log(
        interaction.guild,
        title="資料庫健康檢查",
        description=f"操作人員：{interaction.user.mention}\n耗時：{elapsed:.2f} 秒\n{embed.description}",
        color=embed.color,
    )


# ========= 存單管理面板 =========

def get_stored_order_records(limit: int = 25) -> list[tuple[int, dict]]:
    """回傳目前記憶體中的存單，依存單時間新到舊排序。"""
    records: list[tuple[int, dict]] = []

    for channel_id, data in SELF_SERVICE_ORDER_SELECTIONS.items():
        if not isinstance(data, dict):
            continue
        if str(data.get("status", "")).lower() != "stored":
            continue
        records.append((int(channel_id), data))

    records.sort(
        key=lambda item: str(item[1].get("stored_at") or item[1].get("created_at") or ""),
        reverse=True,
    )
    return records[:max(1, min(int(limit or 25), 25))]


def format_stored_order_option_label(channel_id: int, data: dict) -> str:
    item = str(data.get("item") or "未紀錄")[:30]
    customer_id = data.get("customer_id") or "未紀錄"
    amount = _to_int(data.get("amount"), 0) or 0
    amount_text = f"{amount}T" if amount else "未紀錄金額"
    return f"{item}｜{customer_id}｜{amount_text}"[:100]


def format_stored_order_option_description(channel_id: int, data: dict) -> str:
    quantity = _to_int(data.get("quantity"), 1) or 1
    stored_at = str(data.get("stored_at") or "未紀錄時間")[:19]
    reason = str(data.get("stored_reason") or data.get("store_reason") or "未填寫原因")[:35]
    return f"{quantity} 單｜{stored_at}｜{reason}"[:100]


def build_stored_order_detail_embed(
    guild: discord.Guild | None,
    channel_id: int | None,
    data: dict | None,
    total_count: int,
) -> discord.Embed:
    embed = discord.Embed(
        title="存單管理面板",
        color=discord.Color.gold(),
        timestamp=get_taipei_now(),
    )

    if channel_id is None or not data:
        embed.description = "目前沒有存單。"
        embed.add_field(name="存單數量", value="0 筆", inline=True)
        return embed

    customer_id = data.get("customer_id")
    ticket_channel = guild.get_channel(channel_id) if guild is not None else None
    dispatch_channel_id = _to_int(data.get("dispatch_channel_id"), DISPATCH_CHANNEL_ID) or DISPATCH_CHANNEL_ID
    dispatch_message_id = _to_int(data.get("dispatch_message_id"))
    dispatch_channel = guild.get_channel(dispatch_channel_id) if guild is not None else None

    ticket_text = ticket_channel.mention if isinstance(ticket_channel, discord.TextChannel) else f"票口 ID：{channel_id}"
    if isinstance(dispatch_channel, discord.TextChannel) and dispatch_message_id is not None:
        dispatch_text = f"https://discord.com/channels/{GUILD_ID}/{dispatch_channel.id}/{dispatch_message_id}"
    elif dispatch_message_id is not None:
        dispatch_text = f"派單訊息 ID：{dispatch_message_id}"
    else:
        dispatch_text = "未紀錄"

    amount = _to_int(data.get("amount"), 0) or 0
    quantity = _to_int(data.get("quantity"), 1) or 1
    item = data.get("item") or "未紀錄"
    category = data.get("category")
    category_label = ORDER_CATEGORY_LABELS.get(category, data.get("category_label") or category or "未紀錄")

    embed.description = f"目前共有 **{total_count}** 筆存單。請先選擇存單，再按下方按鈕操作。"
    embed.add_field(name="顧客", value=f"<@{customer_id}>" if customer_id else "未紀錄", inline=True)
    embed.add_field(name="票口", value=ticket_text, inline=True)
    embed.add_field(name="狀態", value=str(data.get("status") or "stored"), inline=True)
    embed.add_field(name="訂單", value=f"{category_label}｜{item} x{quantity}", inline=False)
    embed.add_field(name="金額", value=format_t_amount(amount) if amount else "未紀錄", inline=True)
    embed.add_field(name="付款方式", value=str(data.get("payment_method") or "未紀錄"), inline=True)
    embed.add_field(name="存單時間", value=str(data.get("stored_at") or "未紀錄"), inline=False)
    embed.add_field(name="存單原因", value=str(data.get("stored_reason") or data.get("store_reason") or "未填寫"), inline=False)
    embed.add_field(name="預計恢復", value=str(data.get("stored_expected_time") or data.get("resume_at") or "未填寫"), inline=True)
    embed.add_field(name="存單備註", value=str(data.get("stored_note") or data.get("note") or "無")[:1024], inline=False)
    embed.add_field(name="派單訊息", value=dispatch_text, inline=False)
    return embed


async def update_stored_order_note_and_panel(
    guild: discord.Guild,
    order_channel_id: int,
    reason: str,
    expected_time: str | None,
    note: str | None,
    operator: discord.Member,
) -> None:
    data = SELF_SERVICE_ORDER_SELECTIONS.get(order_channel_id)
    if not isinstance(data, dict) or str(data.get("status", "")).lower() != "stored":
        raise ValueError("找不到這筆存單，可能已被恢復、取消或結單。")

    data["stored_reason"] = reason
    data["stored_expected_time"] = expected_time or None
    data["stored_note"] = note or None
    data["stored_note_updated_at"] = get_taipei_now_iso()
    data["stored_note_updated_by"] = operator.id
    SELF_SERVICE_ORDER_SELECTIONS[order_channel_id] = data

    dispatch_message_id = _to_int(data.get("dispatch_message_id"))
    if dispatch_message_id is not None:
        claim_data = ORDER_CLAIMS.get(dispatch_message_id, {})
        if isinstance(claim_data, dict):
            claim_data["stored_reason"] = reason
            claim_data["stored_expected_time"] = expected_time or None
            claim_data["stored_note"] = note or None
            claim_data["status"] = "stored"
            claim_data["locked"] = True
            ORDER_CLAIMS[dispatch_message_id] = claim_data

    remember_order_data(order_channel_id, data)
    if dispatch_message_id is not None and dispatch_message_id in ORDER_CLAIMS:
        remember_claim_data(dispatch_message_id, ORDER_CLAIMS[dispatch_message_id])

    order_channel = guild.get_channel(order_channel_id)
    dispatch_channel_id = _to_int(data.get("dispatch_channel_id"), DISPATCH_CHANNEL_ID) or DISPATCH_CHANNEL_ID
    dispatch_channel = guild.get_channel(dispatch_channel_id)

    if not isinstance(order_channel, discord.TextChannel) or not isinstance(dispatch_channel, discord.TextChannel) or dispatch_message_id is None:
        return

    try:
        message = await dispatch_channel.fetch_message(dispatch_message_id)
    except (discord.NotFound, discord.Forbidden, discord.HTTPException):
        return

    customer_id = data.get("customer_id") or get_order_customer_id_from_channel(order_channel)
    category = data.get("category")
    item = data.get("item", "未紀錄")
    quantity = _to_int(data.get("quantity"), 1) or 1
    payment_method = data.get("payment_method", "未紀錄")
    companion_preference = data.get("companion_preference")
    category_label = ORDER_CATEGORY_LABELS.get(category, category or data.get("category_label") or "未紀錄")
    customer_mention = f"<@{customer_id}>" if customer_id is not None else "未紀錄"

    claim_data = ORDER_CLAIMS.get(dispatch_message_id, {})
    companion_ids = sorted(claim_data.get("companion", set())) if isinstance(claim_data, dict) else []
    booster_ids = sorted(claim_data.get("booster", set())) if isinstance(claim_data, dict) else []
    receiver_lines = []
    if companion_ids:
        receiver_lines.append("陪玩接單：" + " ".join(f"<@{user_id}>" for user_id in companion_ids))
    if booster_ids:
        receiver_lines.append("打手接單：" + " ".join(f"<@{user_id}>" for user_id in booster_ids))

    embed = build_self_service_order_embed(
        customer_mention=customer_mention,
        category_label=category_label,
        item=item,
        quantity=quantity,
        payment_method=payment_method,
        source_channel=order_channel,
        companion_preference=companion_preference,
        receiver_text="\n".join(receiver_lines) if receiver_lines else None,
    )
    embed.add_field(
        name="接單狀態",
        value=(
            "已存單，接單面板已鎖定\n"
            f"存單原因：{reason}\n"
            f"預計恢復：{expected_time or '未填寫'}"
        ),
        inline=False,
    )
    if note:
        embed.add_field(name="存單備註", value=note[:1024], inline=False)

    await message.edit(
        embed=embed,
        view=DispatchClaimView(
            customer_id=customer_id or 0,
            category_label=category_label,
            item=item,
            quantity=quantity,
            payment_method=payment_method,
            source_channel_id=order_channel.id,
            companion_preference=companion_preference,
            locked=True,
            status="stored",
        ),
        allowed_mentions=discord.AllowedMentions(users=True, roles=False, everyone=False),
    )


class StoredOrderNoteModal(discord.ui.Modal, title="修改存單備註"):
    reason = discord.ui.TextInput(
        label="存單原因",
        placeholder="例如：顧客改約、等待活動、暫停服務",
        required=True,
        max_length=200,
    )
    expected_time = discord.ui.TextInput(
        label="預計恢復時間",
        placeholder="例如：今晚 20:00、明天、未定",
        required=False,
        max_length=100,
    )
    note = discord.ui.TextInput(
        label="備註",
        placeholder="可填寫付款狀態、注意事項或客服備註",
        style=discord.TextStyle.paragraph,
        required=False,
        max_length=800,
    )

    def __init__(self, order_channel_id: int, parent_view: "StoredOrderManageView"):
        super().__init__()
        self.order_channel_id = order_channel_id
        self.parent_view = parent_view
        data = SELF_SERVICE_ORDER_SELECTIONS.get(order_channel_id, {})
        self.reason.default = str(data.get("stored_reason") or data.get("store_reason") or "")[:200]
        self.expected_time.default = str(data.get("stored_expected_time") or data.get("resume_at") or "")[:100]
        self.note.default = str(data.get("stored_note") or data.get("note") or "")[:800]

    async def on_submit(self, interaction: discord.Interaction):
        if not _require_customer_staff_or_manager(interaction):
            await interaction.response.send_message("只有客服、店長或管理員可以修改存單。", ephemeral=True)
            return
        if interaction.guild is None or not isinstance(interaction.user, discord.Member):
            await interaction.response.send_message("這個功能只能在伺服器內使用。", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)
        try:
            await update_stored_order_note_and_panel(
                guild=interaction.guild,
                order_channel_id=self.order_channel_id,
                reason=self.reason.value.strip(),
                expected_time=self.expected_time.value.strip() or None,
                note=self.note.value.strip() or None,
                operator=interaction.user,
            )
        except ValueError as e:
            await interaction.followup.send(str(e), ephemeral=True)
            return

        await send_order_log(
            interaction.guild,
            title="修改存單備註",
            fields=[
                ("票口 ID", str(self.order_channel_id), True),
                ("操作人員", interaction.user.mention, True),
                ("存單原因", self.reason.value.strip(), False),
                ("預計恢復", self.expected_time.value.strip() or "未填寫", True),
                ("備註", self.note.value.strip() or "未填寫", False),
            ],
            color=discord.Color.gold(),
        )
        await interaction.followup.send("已更新存單備註。", ephemeral=True)


class StoredOrderSelect(discord.ui.Select):
    def __init__(self, records: list[tuple[int, dict]], selected_channel_id: int | None = None):
        options = []
        for channel_id, data in records[:25]:
            options.append(
                discord.SelectOption(
                    label=format_stored_order_option_label(channel_id, data),
                    value=str(channel_id),
                    description=format_stored_order_option_description(channel_id, data),
                    default=selected_channel_id == channel_id,
                )
            )

        if not options:
            options = [discord.SelectOption(label="目前沒有存單", value="none", description="沒有可管理的存單")]
            disabled = True
        else:
            disabled = False

        super().__init__(
            placeholder="選擇要管理的存單",
            min_values=1,
            max_values=1,
            options=options,
            custom_id="stored_order_select",
            disabled=disabled,
            row=0,
        )

    async def callback(self, interaction: discord.Interaction):
        if not _require_customer_staff_or_manager(interaction):
            await interaction.response.send_message("只有客服、店長或管理員可以管理存單。", ephemeral=True)
            return
        if self.values[0] == "none":
            await interaction.response.defer()
            return

        view = self.view
        if not isinstance(view, StoredOrderManageView):
            await interaction.response.send_message("存單面板狀態異常，請重新使用 /stored_orders。", ephemeral=True)
            return

        view.selected_channel_id = int(self.values[0])
        view.refresh_items()
        embed = view.build_embed(interaction.guild)
        await interaction.response.edit_message(embed=embed, view=view)


class StoredOrderCancelConfirmView(discord.ui.View):
    def __init__(self, order_channel_id: int):
        super().__init__(timeout=60)
        self.order_channel_id = order_channel_id

    @discord.ui.button(label="確認取消存單", style=discord.ButtonStyle.danger)
    async def confirm_cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not _require_customer_staff_or_manager(interaction):
            await interaction.response.send_message("只有客服、店長或管理員可以取消存單。", ephemeral=True)
            return
        if interaction.guild is None:
            await interaction.response.send_message("這個功能只能在伺服器內使用。", ephemeral=True)
            return

        channel = interaction.guild.get_channel(self.order_channel_id)
        await interaction.response.defer(ephemeral=True)

        await delete_dispatch_claim_panel_for_order(interaction.guild, self.order_channel_id)

        if isinstance(channel, discord.TextChannel):
            try:
                await channel.send(
                    f"此存單已由 {interaction.user.mention} 取消，票口將在 3 秒後關閉。",
                    allowed_mentions=discord.AllowedMentions(users=True, roles=False, everyone=False),
                )
                await asyncio.sleep(3)
                await channel.delete(reason=f"Stored order cancelled by {interaction.user}")
            except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                pass

        await send_order_log(
            interaction.guild,
            title="存單已取消",
            fields=[
                ("票口 ID", str(self.order_channel_id), True),
                ("操作人員", interaction.user.mention, True),
            ],
            color=discord.Color.red(),
        )
        await interaction.followup.send("已取消存單，並嘗試刪除票口與派單面板。", ephemeral=True)

    @discord.ui.button(label="保留存單", style=discord.ButtonStyle.secondary)
    async def keep_stored(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(content="已保留存單。", view=None)


class StoredOrderManageView(discord.ui.View):
    def __init__(self, records: list[tuple[int, dict]]):
        super().__init__(timeout=300)
        self.records = records
        self.selected_channel_id = records[0][0] if records else None
        self.refresh_items()

    def refresh_items(self):
        self.clear_items()
        current_ids = {channel_id for channel_id, _ in self.records}
        if self.selected_channel_id not in current_ids:
            self.selected_channel_id = self.records[0][0] if self.records else None
        self.add_item(StoredOrderSelect(self.records, self.selected_channel_id))
        self.add_item(StoredOrderResumeButton())
        self.add_item(StoredOrderEditNoteButton())
        self.add_item(StoredOrderCancelButton())
        self.add_item(StoredOrderRefreshButton())
        disabled = self.selected_channel_id is None
        for child in self.children:
            if isinstance(child, discord.ui.Button) and child.custom_id != "stored_order_refresh_button":
                child.disabled = disabled

    def get_selected_data(self) -> tuple[int | None, dict | None]:
        if self.selected_channel_id is None:
            return None, None
        data = SELF_SERVICE_ORDER_SELECTIONS.get(self.selected_channel_id)
        if not isinstance(data, dict) or str(data.get("status", "")).lower() != "stored":
            return self.selected_channel_id, None
        return self.selected_channel_id, data

    def build_embed(self, guild: discord.Guild | None) -> discord.Embed:
        channel_id, data = self.get_selected_data()
        return build_stored_order_detail_embed(guild, channel_id, data, len(get_stored_order_records(25)))

    async def refresh_message(self, interaction: discord.Interaction):
        self.records = get_stored_order_records(25)
        self.refresh_items()
        await interaction.response.edit_message(embed=self.build_embed(interaction.guild), view=self)


class StoredOrderResumeButton(discord.ui.Button):
    def __init__(self):
        super().__init__(label="恢復訂單", style=discord.ButtonStyle.success, custom_id="stored_order_resume_button", row=1)

    async def callback(self, interaction: discord.Interaction):
        if not _require_customer_staff_or_manager(interaction):
            await interaction.response.send_message("只有客服、店長或管理員可以恢復存單。", ephemeral=True)
            return
        view = self.view
        if not isinstance(view, StoredOrderManageView) or view.selected_channel_id is None:
            await interaction.response.send_message("請先選擇要恢復的存單。", ephemeral=True)
            return
        if interaction.guild is None or not isinstance(interaction.user, discord.Member):
            await interaction.response.send_message("這個功能只能在伺服器內使用。", ephemeral=True)
            return
        order_channel = interaction.guild.get_channel(view.selected_channel_id)
        if not isinstance(order_channel, discord.TextChannel):
            await interaction.response.send_message("找不到這筆存單的票口，無法恢復。", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)
        try:
            await resume_stored_order(interaction.guild, order_channel, interaction.user)
        except ValueError as e:
            await interaction.followup.send(str(e), ephemeral=True)
            return

        await order_channel.send(
            f"此訂單已由 {interaction.user.mention} 恢復，派單頻道接單面板已重新開放。",
            allowed_mentions=discord.AllowedMentions(users=True, roles=False, everyone=False),
        )
        await send_order_log(
            interaction.guild,
            title="存單已恢復",
            fields=[("票口", order_channel.mention, True), ("操作人員", interaction.user.mention, True)],
            color=discord.Color.green(),
        )
        await interaction.followup.send("已恢復存單。", ephemeral=True)


class StoredOrderEditNoteButton(discord.ui.Button):
    def __init__(self):
        super().__init__(label="修改備註", style=discord.ButtonStyle.primary, custom_id="stored_order_edit_note_button", row=1)

    async def callback(self, interaction: discord.Interaction):
        if not _require_customer_staff_or_manager(interaction):
            await interaction.response.send_message("只有客服、店長或管理員可以修改存單。", ephemeral=True)
            return
        view = self.view
        if not isinstance(view, StoredOrderManageView) or view.selected_channel_id is None:
            await interaction.response.send_message("請先選擇要修改的存單。", ephemeral=True)
            return
        await interaction.response.send_modal(StoredOrderNoteModal(view.selected_channel_id, view))


class StoredOrderCancelButton(discord.ui.Button):
    def __init__(self):
        super().__init__(label="取消存單", style=discord.ButtonStyle.danger, custom_id="stored_order_cancel_button", row=1)

    async def callback(self, interaction: discord.Interaction):
        if not _require_customer_staff_or_manager(interaction):
            await interaction.response.send_message("只有客服、店長或管理員可以取消存單。", ephemeral=True)
            return
        view = self.view
        if not isinstance(view, StoredOrderManageView) or view.selected_channel_id is None:
            await interaction.response.send_message("請先選擇要取消的存單。", ephemeral=True)
            return
        await interaction.response.send_message(
            "確定要取消這筆存單嗎？這會嘗試刪除派單面板與票口，且不會列入已結營收。",
            view=StoredOrderCancelConfirmView(view.selected_channel_id),
            ephemeral=True,
        )


class StoredOrderRefreshButton(discord.ui.Button):
    def __init__(self):
        super().__init__(label="重新整理", style=discord.ButtonStyle.secondary, custom_id="stored_order_refresh_button", row=1)

    async def callback(self, interaction: discord.Interaction):
        if not _require_customer_staff_or_manager(interaction):
            await interaction.response.send_message("只有客服、店長或管理員可以管理存單。", ephemeral=True)
            return
        view = self.view
        if not isinstance(view, StoredOrderManageView):
            await interaction.response.send_message("存單面板狀態異常，請重新使用 /stored_orders。", ephemeral=True)
            return
        await view.refresh_message(interaction)


@bot.tree.command(
    name="stored_orders",
    description="客服查看與管理目前所有存單",
    guild=discord.Object(id=GUILD_ID)
)
@app_commands.describe(limit="最多顯示幾筆存單，預設 25，最多 25")
async def stored_orders(interaction: discord.Interaction, limit: int = 25):
    if not _require_customer_staff_or_manager(interaction):
        await interaction.response.send_message("只有客服、店長或管理員可以查看存單。", ephemeral=True)
        return

    safe_limit = max(1, min(int(limit or 25), 25))
    records = get_stored_order_records(safe_limit)
    view = StoredOrderManageView(records)
    await interaction.response.send_message(
        embed=view.build_embed(interaction.guild),
        view=view,
        ephemeral=True,
        allowed_mentions=discord.AllowedMentions(users=True, roles=False, everyone=False),
    )



@bot.tree.command(
    name="check_stored_orders",
    description="客服手動檢查是否有超過 3/7 天的存單提醒",
    guild=discord.Object(id=GUILD_ID)
)
async def check_stored_orders(interaction: discord.Interaction):
    if not _require_customer_staff_or_manager(interaction):
        await interaction.response.send_message("只有客服、店長或管理員可以檢查存單提醒。", ephemeral=True)
        return

    await interaction.response.defer(ephemeral=True)
    await check_stored_order_reminders_once(interaction.guild)
    await interaction.followup.send("已檢查存單提醒，若有逾期存單會發到機器人日誌。", ephemeral=True)


@bot.tree.command(
    name="add_customer_note",
    description="客服新增顧客備註或黑名單紀錄",
    guild=discord.Object(id=GUILD_ID)
)
@app_commands.describe(
    customer="要新增備註的顧客",
    note="備註內容",
    blacklist="是否標記為黑名單 / 高風險備註"
)
async def add_customer_note(
    interaction: discord.Interaction,
    customer: discord.Member,
    note: str,
    blacklist: bool = False,
):
    if not _require_customer_staff_or_manager(interaction):
        await interaction.response.send_message("只有客服、店長或管理員可以新增顧客備註。", ephemeral=True)
        return

    content = note.strip()[:500]
    if not content:
        await interaction.response.send_message("備註內容不能空白。", ephemeral=True)
        return

    data = get_customer_reward_data(customer.id)
    notes = data.setdefault("notes", [])
    notes.append({
        "content": content,
        "is_blacklist": bool(blacklist),
        "operator_id": interaction.user.id,
        "created_at": get_taipei_now_iso(),
    })
    CUSTOMER_REWARDS[customer.id] = data
    save_bot_data()

    await send_order_log(
        interaction.guild,
        title="新增顧客備註",
        fields=[
            ("顧客", customer.mention, True),
            ("類型", "黑名單 / 高風險" if blacklist else "一般備註", True),
            ("操作人員", interaction.user.mention, True),
            ("內容", content, False),
        ],
        color=discord.Color.red() if blacklist else discord.Color.blue(),
    )

    await interaction.response.send_message(
        f"已新增 {'黑名單 / 高風險' if blacklist else '一般'}備註給 {customer.mention}。",
        ephemeral=True,
        allowed_mentions=discord.AllowedMentions(users=True, roles=False, everyone=False),
    )


@bot.tree.command(
    name="customer_notes",
    description="客服查詢顧客備註 / 黑名單紀錄",
    guild=discord.Object(id=GUILD_ID)
)
@app_commands.describe(customer="要查詢備註的顧客")
async def customer_notes(interaction: discord.Interaction, customer: discord.Member):
    if not _require_customer_staff_or_manager(interaction):
        await interaction.response.send_message("只有客服、店長或管理員可以查詢顧客備註。", ephemeral=True)
        return

    embed = discord.Embed(
        title="顧客備註 / 黑名單紀錄",
        description=format_customer_notes_for_staff(customer.id, limit=15),
        color=discord.Color.red() if any(n.get("is_blacklist") for n in get_customer_notes(customer.id)) else discord.Color.blue(),
        timestamp=get_taipei_now(),
    )
    embed.add_field(name="顧客", value=customer.mention, inline=False)
    await interaction.response.send_message(embed=embed, ephemeral=True)


@bot.tree.command(
    name="remove_customer_note",
    description="客服刪除顧客備註，index 請看 /customer_notes 的編號",
    guild=discord.Object(id=GUILD_ID)
)
@app_commands.describe(
    customer="要刪除備註的顧客",
    index="要刪除第幾筆備註，從 1 開始"
)
async def remove_customer_note(interaction: discord.Interaction, customer: discord.Member, index: int):
    if not _require_customer_staff_or_manager(interaction):
        await interaction.response.send_message("只有客服、店長或管理員可以刪除顧客備註。", ephemeral=True)
        return

    data = get_customer_reward_data(customer.id)
    notes = data.setdefault("notes", [])
    if index < 1 or index > len(notes):
        await interaction.response.send_message("找不到這個備註編號，請先用 /customer_notes 查看。", ephemeral=True)
        return

    removed = notes.pop(index - 1)
    CUSTOMER_REWARDS[customer.id] = data
    save_bot_data()

    await send_order_log(
        interaction.guild,
        title="刪除顧客備註",
        fields=[
            ("顧客", customer.mention, True),
            ("操作人員", interaction.user.mention, True),
            ("刪除內容", str(removed.get("content") or "未填寫"), False),
        ],
        color=discord.Color.dark_grey(),
    )

    await interaction.response.send_message(f"已刪除 {customer.mention} 的第 {index} 筆備註。", ephemeral=True)


@bot.tree.command(
    name="setup_panel",
    description="建立魔丸娛樂客服面板",
    guild=discord.Object(id=GUILD_ID)
)
@app_commands.checks.has_permissions(administrator=True)
async def setup_panel(interaction: discord.Interaction):
    embed = discord.Embed(
        title="魔丸娛樂客服中心",
        description="歡迎來到魔丸娛樂，點擊下方按鈕聯絡客服",
        color=discord.Color.purple()
    )

    await interaction.channel.send(
        embed=embed,
        view=MainPanelView()
    )

    await interaction.response.send_message(
        "客服面板已建立。",
        ephemeral=True
    )


@bot.tree.command(
    name="setup_complaint_panel",
    description="建立客訴表單面板",
    guild=discord.Object(id=GUILD_ID)
)
@app_commands.checks.has_permissions(administrator=True)
async def setup_complaint_panel(interaction: discord.Interaction):
    guild = interaction.guild

    if guild is None:
        await interaction.response.send_message("這個功能只能在伺服器內使用。", ephemeral=True)
        return

    panel_channel = guild.get_channel(COMPLAINT_PANEL_CHANNEL_ID)

    if panel_channel is None or not isinstance(panel_channel, discord.TextChannel):
        await interaction.response.send_message(
            "找不到客訴面板頻道，請確認 COMPLAINT_PANEL_CHANNEL_ID 是否正確。",
            ephemeral=True
        )
        return

    embed = discord.Embed(
        title="我要客訴!!",
        description="如有任何客訴內容，請點擊下方按鈕填寫客訴單。",
        color=discord.Color.red()
    )

    embed.set_footer(text="魔丸娛樂｜客訴表單")

    await panel_channel.send(
        embed=embed,
        view=ComplaintPanelView()
    )

    await interaction.response.send_message(
        f"客訴表單面板已建立在 {panel_channel.mention}。",
        ephemeral=True
    )


@bot.tree.command(
    name="setup_feedback_panel",
    description="建立顧客意見箱面板",
    guild=discord.Object(id=GUILD_ID)
)
@app_commands.checks.has_permissions(administrator=True)
async def setup_feedback_panel(interaction: discord.Interaction):
    guild = interaction.guild

    if guild is None:
        await interaction.response.send_message("這個功能只能在伺服器內使用。", ephemeral=True)
        return

    panel_channel = guild.get_channel(FEEDBACK_PANEL_CHANNEL_ID)

    if panel_channel is None or not isinstance(panel_channel, discord.TextChannel):
        await interaction.response.send_message(
            "找不到顧客意見箱面板頻道，請確認 FEEDBACK_PANEL_CHANNEL_ID 是否正確。",
            ephemeral=True
        )
        return

    embed = discord.Embed(
        title="顧客意見箱",
        description="如有任何意見或建議，請點擊下方按鈕填寫。",
        color=discord.Color.blue()
    )

    embed.set_footer(text="魔丸娛樂｜顧客意見箱")

    await panel_channel.send(
        embed=embed,
        view=FeedbackPanelView()
    )

    await interaction.response.send_message(
        f"顧客意見箱面板已建立在 {panel_channel.mention}。",
        ephemeral=True
    )


@bot.tree.command(
    name="setup_play_voice",
    description="建立陪玩語音入口頻道",
    guild=discord.Object(id=GUILD_ID)
)
@app_commands.checks.has_permissions(administrator=True)
async def setup_play_voice(interaction: discord.Interaction):
    guild = interaction.guild

    if guild is None:
        await interaction.response.send_message("這個功能只能在伺服器內使用。", ephemeral=True)
        return

    lobby_channel = await get_or_create_play_voice_lobby(guild)

    if lobby_channel is None:
        await interaction.response.send_message(
            "建立失敗，請確認 PLAY_VOICE_CATEGORY_ID 是否正確。",
            ephemeral=True
        )
        return

    await interaction.response.send_message(
        f"陪玩語音入口已建立 / 確認存在：{lobby_channel.mention}",
        ephemeral=True
    )




@bot.tree.command(
    name="setup_vip_voice",
    description="建立 VIP 語音入口頻道",
    guild=discord.Object(id=GUILD_ID)
)
@app_commands.checks.has_permissions(administrator=True)
async def setup_vip_voice(interaction: discord.Interaction):
    guild = interaction.guild

    if guild is None:
        await interaction.response.send_message("這個功能只能在伺服器內使用。", ephemeral=True)
        return

    lobby_channel = await get_or_create_vip_voice_lobby(guild)

    if lobby_channel is None:
        await interaction.response.send_message(
            "建立失敗，請確認 PLAY_VOICE_CATEGORY_ID 是否正確。",
            ephemeral=True
        )
        return

    await interaction.response.send_message(
        f"VIP 語音入口已建立 / 確認存在：{lobby_channel.mention}",
        ephemeral=True
    )



@bot.tree.command(
    name="setup_public_voice",
    description="建立公共語音入口頻道",
    guild=discord.Object(id=GUILD_ID)
)
@app_commands.checks.has_permissions(administrator=True)
async def setup_public_voice(interaction: discord.Interaction):
    guild = interaction.guild

    if guild is None:
        await interaction.response.send_message("這個功能只能在伺服器內使用。", ephemeral=True)
        return

    lobby_channel = await get_or_create_public_voice_lobby(guild)

    if lobby_channel is None:
        await interaction.response.send_message(
            "建立失敗，請確認 PLAY_VOICE_CATEGORY_ID 是否正確。",
            ephemeral=True
        )
        return

    await interaction.response.send_message(
        f"公共語音入口已建立 / 確認存在：{lobby_channel.mention}",
        ephemeral=True
    )



@bot.tree.command(
    name="delete_dispatch_panel",
    description="刪除派單頻道中已取消訂單的接單面板",
    guild=discord.Object(id=GUILD_ID)
)
@app_commands.describe(
    message_id="要刪除的派單訊息 ID",
    channel="派單訊息所在頻道；不填則使用目前頻道"
)
async def delete_dispatch_panel(
    interaction: discord.Interaction,
    message_id: str,
    channel: discord.TextChannel | None = None,
):
    if not isinstance(interaction.user, discord.Member):
        await interaction.response.send_message("無法確認你的身分組。", ephemeral=True)
        return

    if not is_customer_staff(interaction.user) and not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message("只有客服或管理員可以刪除派單面板。", ephemeral=True)
        return

    target_channel = channel or interaction.channel

    if not isinstance(target_channel, discord.TextChannel):
        await interaction.response.send_message("請在文字頻道使用，或指定派單訊息所在頻道。", ephemeral=True)
        return

    try:
        target_message_id = int(message_id.strip())
    except ValueError:
        await interaction.response.send_message("訊息 ID 格式錯誤，請貼純數字訊息 ID。", ephemeral=True)
        return

    try:
        message = await target_channel.fetch_message(target_message_id)
    except discord.NotFound:
        await interaction.response.send_message("找不到這則派單訊息，可能已經被刪除了。", ephemeral=True)
        return
    except discord.Forbidden:
        await interaction.response.send_message("Bot 權限不足，無法讀取該頻道訊息。", ephemeral=True)
        return
    except discord.HTTPException as e:
        await interaction.response.send_message(f"讀取派單訊息失敗：{e}", ephemeral=True)
        return

    try:
        await message.delete()
    except discord.Forbidden:
        await interaction.response.send_message("Bot 權限不足，無法刪除該派單訊息。", ephemeral=True)
        return
    except discord.HTTPException as e:
        await interaction.response.send_message(f"刪除派單訊息失敗：{e}", ephemeral=True)
        return

    ORDER_CLAIMS.pop(target_message_id, None)
    delete_claim_row_from_db(message_id=target_message_id)

    removed_order_links = 0
    for order_channel_id, data in list(SELF_SERVICE_ORDER_SELECTIONS.items()):
        if _to_int(data.get("dispatch_message_id")) == target_message_id:
            data["status"] = "cancelled"
            data["cancelled"] = True
            data["cancelled_at"] = get_taipei_now_iso()
            data["dispatch_message_id"] = None
            SELF_SERVICE_ORDER_SELECTIONS[order_channel_id] = data
            removed_order_links += 1

    save_bot_data()

    await interaction.response.send_message(
        f"已刪除派單面板，並清理相關接單暫存資料。關聯訂單：{removed_order_links} 筆。",
        ephemeral=True
    )

    await send_order_log(
        interaction.guild,
        "刪除派單面板",
        (
            f"操作人員：{interaction.user.mention}\n"
            f"派單頻道：{target_channel.mention}\n"
            f"訊息 ID：{target_message_id}\n"
            f"關聯訂單：{removed_order_links} 筆"
        ),
        color=discord.Color.red()
    )

@setup_panel.error
@setup_complaint_panel.error
@setup_feedback_panel.error
@setup_play_voice.error
@setup_vip_voice.error
@setup_public_voice.error
async def command_error(
    interaction: discord.Interaction,
    error: app_commands.AppCommandError
):
    if interaction.response.is_done():
        send = interaction.followup.send
    else:
        send = interaction.response.send_message

    if isinstance(error, app_commands.MissingPermissions):
        await send(
            "你需要管理員權限才能使用這個指令。",
            ephemeral=True
        )
    elif isinstance(error, discord.Forbidden):
        await send(
            "Bot 權限不足。請確認 Bot 有檢視頻道、傳送訊息、嵌入連結、管理頻道、管理身分組等必要權限。",
            ephemeral=True
        )
    else:
        await send(
            f"發生錯誤：{error}",
            ephemeral=True
        )


bot.run(TOKEN)