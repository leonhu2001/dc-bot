import os
from dotenv import load_dotenv

from shared.web_order_sync import sync_web_worker_claim_from_dispatch

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
    run_vip_downgrade_check,
)

from services.lottery import (
    configure_lottery_storage,
    LOTTERY_COST_PER_CHANCE_DEFAULT,
    LOTTERY_MAX_CHANCES_PER_USER_DEFAULT,
    get_default_lottery_period,
    get_lottery_settings,
    save_lottery_settings,
    get_lottery_entries,
    get_lottery_entry,
    upsert_lottery_entry,
    clear_lottery_entries,
    record_lottery_draw,
    build_lottery_info_embed,
    build_lottery_status_embed,
    pick_weighted_lottery_winners,
    configure_lottery_runtime,
    send_lottery_announcement,
)

from services.stats import (
    configure_stats,
    build_sales_stats_embed,
)

from services.audit import (
    configure_audit_service,
    build_audit_data_report,
)

from services.logging_service import (
    configure_order_logging,
    get_or_create_order_log_channel,
    send_order_log,
)

from services.orders import (
    _to_int,
    configure_order_helpers,
    ORDER_CATEGORY_LABELS,
    ORDER_ITEMS_BY_CATEGORY,
    ORDER_ITEM_TO_CATEGORY,
    SPECIAL_COMPANION_ITEMS,
    QUANTITY_SELECT_ITEMS,
    QUANTITY_OPTIONS,
    find_order_by_identifier,
    is_order_closed_for_rewards,
    get_order_amount_for_maintenance,
    get_order_amount_for_stats,
    is_closed_order_for_stats,
    is_stored_order_for_stats,
    is_cancelled_order_for_stats,
    get_order_summary_from_channel,
    build_self_service_order_embed,
    get_stored_order_records,
    format_stored_order_option_label,
    format_stored_order_option_description,
    build_stored_order_detail_embed,
)

from services.order_flow import (
    build_payment_method_embed,
    get_payment_method_info,
)

from views.review import (
    configure_review_views,
    ReviewButtonView,
)

from views.support import (
    configure_support_views,
    RecruitControlView,
    ComplaintPanelView,
    ComplaintResolveView,
    FeedbackPanelView,
)

from views.voice import (
    configure_voice_helpers,
    safe_voice_channel_name,
    safe_vip_voice_channel_name,
    safe_public_voice_channel_name,
    get_play_voice_allowed_roles,
    get_voice_room_hidden_visible_roles,
    build_play_voice_overwrites,
    build_vip_lobby_overwrites,
    build_vip_room_overwrites,
    build_public_voice_overwrites,
    get_or_create_play_voice_lobby,
    get_or_create_vip_voice_lobby,
    get_or_create_public_voice_lobby,
    build_creator_voice_overwrite,
    build_voice_control_panel_overwrites,
    safe_voice_control_panel_name,
    delete_voice_control_panel,
    get_room_targets_for_control,
    create_voice_control_panel,
    grant_play_voice_room_chat_access,
    revoke_play_voice_room_chat_access,
)

from views.panels import (
    configure_panel_views,
    MainPanelView,
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


# 可看見創建後陪玩 / VIP 語音房，但不可連接的身分組 ID
VOICE_VIEW_ONLY_ROLE_IDS = [
    1507204925766242425,
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
VOICE_VIEW_ONLY_ROLE_IDS = _config_int_list("VOICE_VIEW_ONLY_ROLE_IDS", VOICE_VIEW_ONLY_ROLE_IDS)

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

configure_voice_helpers(
    play_voice_category_id=PLAY_VOICE_CATEGORY_ID,
    play_voice_create_channel_name=PLAY_VOICE_CREATE_CHANNEL_NAME,
    old_play_voice_create_channel_names=OLD_PLAY_VOICE_CREATE_CHANNEL_NAMES,
    vip_voice_create_channel_name=VIP_VOICE_CREATE_CHANNEL_NAME,
    old_vip_voice_create_channel_names=OLD_VIP_VOICE_CREATE_CHANNEL_NAMES,
    public_voice_create_channel_name=PUBLIC_VOICE_CREATE_CHANNEL_NAME,
    vip_voice_lobby_role_id=VIP_VOICE_LOBBY_ROLE_ID,
    play_voice_allowed_role_ids=PLAY_VOICE_ALLOWED_ROLE_IDS,
    voice_room_hidden_visible_role_ids=VOICE_ROOM_HIDDEN_VISIBLE_ROLE_IDS,
    temp_voice_control_panels=TEMP_VOICE_CONTROL_PANELS,
)

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

configure_order_logging(
    order_log_channel_name=ORDER_LOG_CHANNEL_NAME,
    order_log_category_id=ORDER_LOG_CATEGORY_ID,
    get_now_func=get_taipei_now,
)

configure_review_views(
    review_channel_id=REVIEW_CHANNEL_ID,
)

# ========= Bot 設定 =========

intents = discord.Intents.default()
intents.guilds = True
intents.members = True
intents.voice_states = True
intents.message_content = True

bot = commands.Bot(command_prefix="!", intents=intents)
bot.guild_id_value = GUILD_ID
bot.manager_role_id_value = MANAGER_ROLE_ID
bot.complaint_panel_channel_id_value = COMPLAINT_PANEL_CHANNEL_ID
bot.feedback_panel_channel_id_value = FEEDBACK_PANEL_CHANNEL_ID
bot._extensions_loaded = False

# ========= Slash 指令群組 =========
order_group = app_commands.Group(name="order", description="訂單管理")
vip_group = app_commands.Group(name="vip", description="VIP / 會員管理")


# ========= 工具函式 =========

def _clean_ticket_channel_part(value: str, *, fallback: str = "user") -> str:
    clean = "".join(ch.lower() if ch.isalnum() else "-" for ch in str(value))
    clean = re.sub(r"-+", "-", clean).strip("-")
    return clean or fallback


def build_ticket_channel_name(prefix: str, member: discord.Member | None = None, *, display_name: str | None = None) -> str:
    raw_name = display_name or (member.display_name if member is not None else None) or "user"
    prefix_part = _clean_ticket_channel_part(prefix, fallback="ticket")
    name_part = _clean_ticket_channel_part(raw_name, fallback="user")
    date_part = get_taipei_now().strftime("%m%d")
    return f"{prefix_part}-{name_part}-{date_part}"[:90]


def safe_channel_name(prefix: str, member: discord.Member) -> str:
    return build_ticket_channel_name(prefix, member)


async def rename_ticket_channel(
    channel: discord.abc.GuildChannel | None,
    prefix: str,
    member: discord.Member | None = None,
    *,
    display_name: str | None = None,
) -> None:
    if not isinstance(channel, discord.TextChannel):
        return

    new_name = build_ticket_channel_name(prefix, member, display_name=display_name)

    if channel.name == new_name:
        return

    try:
        await channel.edit(name=new_name, reason=f"Ticket status changed: {prefix}")
    except discord.Forbidden:
        print(f"Bot 權限不足，無法更改票口名稱：{channel.id} -> {new_name}")
    except discord.HTTPException as e:
        print(f"更改票口名稱失敗：{channel.id} -> {new_name}：{e}")


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


configure_support_views(
    complaint_receive_channel_id=COMPLAINT_RECEIVE_CHANNEL_ID,
    remove_recruit_applicant_role=remove_recruit_applicant_role,
)


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


# ========= 評價 Modal / 按鈕 =========
# Review modal/button views moved to views/review.py

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




def sync_web_order_closed_from_bot(ticket_channel_id, dispatch_message_id=None) -> None:
    """DC bot 結單後，把網站訂單狀態同步成 closed。"""
    try:
        from shared.web_order_sync import update_web_order_status_by_ticket_channel

        ok = update_web_order_status_by_ticket_channel(
            ticket_channel_id=ticket_channel_id,
            status="closed",
            dispatch_message_id=dispatch_message_id,
            note="由 DC bot 結單同步。",
        )
        print(f"[web-sync] close order ticket_channel_id={ticket_channel_id} dispatch_message_id={dispatch_message_id} ok={ok}")
    except Exception as exc:
        print(f"[web-sync] 結單同步網站失敗 ticket_channel_id={ticket_channel_id}: {exc}")


# ========= 收據 Modal =========

class ReceiptModal(discord.ui.Modal, title="已結單收據"):
    payee = discord.ui.TextInput(
        label="收款人",
        placeholder="例如：zYao或客服暱稱(代收)",
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

        order_data = SELF_SERVICE_ORDER_SELECTIONS.setdefault(order_channel.id, {})
        parsed_amount = _to_int(order_data.get("amount"), 0) or _to_int(order_data.get("total_amount"), 0) or 0
        if parsed_amount <= 0:
            await interaction.response.send_message(
                "這張單還沒有訂單價格，請先在付款面板按「填寫訂單價格」讓客服輸入金額。",
                ephemeral=True
            )
            return

        amount_text = str(order_data.get("amount_text") or format_t_amount(parsed_amount))

        receipt_id = generate_order_receipt_id()
        closed_at_text = get_taipei_now_iso()

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
        sync_web_order_closed_from_bot(
            ticket_channel_id=order_channel.id,
            dispatch_message_id=order_data.get("dispatch_message_id"),
        )

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
            f"金額：{amount_text}\n"
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
        await rename_ticket_channel(order_channel, "已結單", member=customer_member)

        reward_result = "會員累積已在顧客送出付款方式時處理。" if order_data.get("reward_counted") else "提醒：這張單尚未標記會員累積，請確認顧客是否已送出付款方式。"

        await send_order_log(
            guild,
            title="訂單已結單",
            fields=[
                ("訂單編號", receipt_id, True),
                ("顧客", f"<@{customer_id}>", True),
                ("客服", interaction.user.mention, True),
                ("金額", amount_text, True),
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
configure_order_helpers(
    SELF_SERVICE_ORDER_SELECTIONS,
    parse_receipt_amount,
    guild_id=GUILD_ID,
    dispatch_channel_id=DISPATCH_CHANNEL_ID,
    format_amount_func=format_t_amount,
    get_now_func=get_taipei_now,
)

# 派單頻道接單資料
# message_id 對應該派單訊息目前有哪些陪玩 / 打手接單。
# 重要訂單資料會保存到 bot_data.json，Bot 重啟後會自動讀回。
ORDER_CLAIMS = {}

# 顧客會員 / 獎勵資料
# user_id -> {total_spent, order_count, last_order_at, points, platinum_channel_id}
CUSTOMER_REWARDS = {}
configure_reward_storage(CUSTOMER_REWARDS)
configure_audit_service(SELF_SERVICE_ORDER_SELECTIONS, ORDER_CLAIMS, CUSTOMER_REWARDS)

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
configure_lottery_storage(DB_FILE, init_database)
configure_lottery_runtime(lottery_announce_channel_id=LOTTERY_ANNOUNCE_CHANNEL_ID)
configure_stats(DB_FILE, init_database)
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

    return await run_vip_downgrade_check(
        guild,
        force=force,
        maintain_min_monthly_spend=VIP_MAINTAIN_MIN_MONTHLY_SPEND,
        first_check_month=VIP_DOWNGRADE_FIRST_CHECK_MONTH,
        send_log_func=send_order_log,
    )



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
                description="賽季3x3、哈夫幣代洗",
                default=selected_category == "farm"
            ),
            discord.SelectOption(
                label="賽季限定活動",
                value="season",
                description="勇敢者行動、S9炫彩勇敢者行動",
                default=selected_category == "season"
            ),
            discord.SelectOption(
                label="Valorant",
                value="valorant",
                description="陪打、代打",
                default=selected_category == "valorant"
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
            if selected_item == "陪打":
                options = [
                    discord.SelectOption(
                        label="不指定打手",
                        value="不指定打手",
                        description="由客服安排合適人選",
                        default=selected_preference in {"不指定打手", "不指定陪玩/打手", None}
                    ),
                    discord.SelectOption(
                        label="指定打手",
                        value="指定打手",
                        description="由下單用戶指定人選",
                        default=selected_preference in {"指定打手", "指定陪玩/打手"}
                    ),
                ]
                placeholder = "請選擇是否指定打手"
            else:
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
                placeholder = "請選擇是否指定陪玩/打手"
            disabled = False
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

        await interaction.response.edit_message(
            view=SelfServiceOrderView(
                customer_id=self.customer_id,
                channel_id=self.channel_id,
                selected_category=data.get("category")
            )
        )

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

        await interaction.response.edit_message(
            view=SelfServiceOrderView(
                customer_id=self.customer_id,
                channel_id=self.channel_id,
                selected_category=data.get("category")
            )
        )


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




def sync_single_discord_claim_event_to_web(interaction, claim_type: str, action: str) -> None:
    """把 Discord 接單按鈕單一操作同步到網站。

    action:
    - claim：只新增目前這個人
    - unclaim：只移除目前這個人
    """
    try:
        from shared.web_order_sync import apply_discord_claim_event_to_web

        if interaction.message is None:
            return

        role_type = "companion" if claim_type == "companion" else "booster"

        apply_discord_claim_event_to_web(
            dispatch_message_id=interaction.message.id,
            worker_discord_id=interaction.user.id,
            worker_display_name=getattr(interaction.user, "display_name", None) or getattr(interaction.user, "name", None) or str(interaction.user.id),
            role_type=role_type,
            action=action,
        )
    except Exception as exc:
        print(
            f"[web-sync] Discord 接單事件同步網站失敗 "
            f"message_id={getattr(getattr(interaction, 'message', None), 'id', None)} "
            f"user_id={getattr(getattr(interaction, 'user', None), 'id', None)} "
            f"claim_type={claim_type} action={action}: {exc}"
        )


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
        sync_single_discord_claim_event_to_web(interaction, claim_type, "claim")

        try:
            sync_web_worker_claim_from_dispatch(
                dispatch_message_id=interaction.message.id,
                worker_discord_id=interaction.user.id,
                worker_display_name=getattr(interaction.user, "display_name", None) or getattr(interaction.user, "name", None),
                role_type=claim_type,
                claimed=True,
            )
        except Exception as e:
            print(f"同步 Discord 接單到網站失敗：{e}")

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
        sync_single_discord_claim_event_to_web(interaction, "booster", "unclaim")
        sync_single_discord_claim_event_to_web(interaction, "companion", "unclaim")


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



def sync_web_order_status_from_bot(ticket_channel_id, status: str, dispatch_message_id=None, note: str | None = None) -> None:
    """DC bot 訂單狀態變更後，同步網站 web_orders.status。"""
    try:
        from shared.web_order_sync import update_web_order_status_by_ticket_channel

        ok = update_web_order_status_by_ticket_channel(
            ticket_channel_id=ticket_channel_id,
            status=status,
            dispatch_message_id=dispatch_message_id,
            note=note,
        )
        print(
            f"[web-sync] order status sync "
            f"ticket_channel_id={ticket_channel_id} "
            f"dispatch_message_id={dispatch_message_id} "
            f"status={status} ok={ok}"
        )
    except Exception as exc:
        print(
            f"[web-sync] 訂單狀態同步網站失敗 "
            f"ticket_channel_id={ticket_channel_id} "
            f"status={status}: {exc}"
        )


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
    sync_web_order_status_from_bot(
        ticket_channel_id=order_channel.id,
        status="stored",
        dispatch_message_id=dispatch_message_id,
        note="由 DC bot 存單同步。",
    )
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
    """恢復已存單的訂單，保留原本接單人員，重新發派單面板，並清掉舊派單訊息。"""
    data = SELF_SERVICE_ORDER_SELECTIONS.get(order_channel.id, {})
    old_dispatch_message_id = _to_int(data.get("dispatch_message_id"))
    dispatch_channel_id = _to_int(data.get("dispatch_channel_id"), DISPATCH_CHANNEL_ID) or DISPATCH_CHANNEL_ID

    # 收集這張票口所有舊派單訊息，避免同一張存單恢復後派單頻道殘留舊面板。
    old_dispatch_message_ids: set[int] = set()

    if old_dispatch_message_id:
        old_dispatch_message_ids.add(old_dispatch_message_id)

    for message_id, claim in list(ORDER_CLAIMS.items()):
        if not isinstance(claim, dict):
            continue

        claim_source_channel_id = _to_int(claim.get("source_channel_id"))

        if claim_source_channel_id == order_channel.id:
            parsed_message_id = _to_int(message_id)
            if parsed_message_id:
                old_dispatch_message_ids.add(parsed_message_id)

    if not old_dispatch_message_ids:
        raise ValueError("找不到這張訂單對應的派單訊息，無法恢復。")

    dispatch_channel = guild.get_channel(dispatch_channel_id)

    if dispatch_channel is None or not isinstance(dispatch_channel, discord.TextChannel):
        raise ValueError("找不到派單頻道，請確認 DISPATCH_CHANNEL_ID 是否正確。")

    # 優先取原本 dispatch_message_id 的 claim；沒有的話，找同票口任一 claim。
    claim_data = ORDER_CLAIMS.get(old_dispatch_message_id) if old_dispatch_message_id else None

    if not claim_data:
        for message_id in old_dispatch_message_ids:
            possible_claim = ORDER_CLAIMS.get(message_id)
            if isinstance(possible_claim, dict):
                claim_data = possible_claim
                break

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

    # 存單相關資料保留在資料中當紀錄，但狀態改回 active。
    data["closed"] = False
    data["status"] = "active"
    data["quantity"] = quantity
    data["dispatch_channel_id"] = dispatch_channel.id
    data["stored_at"] = None
    data["stored_by"] = None
    data["stored_reason"] = None
    data["stored_expected_time"] = None
    data["stored_note"] = None

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

    # 刪除同一張票口的所有舊派單訊息，避免存單恢復後殘留不能操作的舊面板。
    for message_id in old_dispatch_message_ids:
        if message_id == new_message.id:
            continue

        try:
            old_message = await dispatch_channel.fetch_message(message_id)
        except discord.NotFound:
            old_message = None
        except (discord.Forbidden, discord.HTTPException):
            old_message = None

        if old_message is not None:
            try:
                await old_message.delete()
            except (discord.NotFound, discord.Forbidden, discord.HTTPException, TypeError):
                pass

        ORDER_CLAIMS.pop(message_id, None)
        delete_claim_row_from_db(message_id=message_id, source_channel_id=order_channel.id)

    # 把接單資料移到新的 message_id，保留原本陪玩/打手接單人員。
    ORDER_CLAIMS[new_message.id] = claim_data
    data["dispatch_message_id"] = new_message.id
    data["dispatch_channel_id"] = dispatch_channel.id

    remember_order_data(order_channel.id, data)
    sync_web_order_status_from_bot(
        ticket_channel_id=order_channel.id,
        status="active",
        dispatch_message_id=data.get("dispatch_message_id"),
        note="由 DC bot 恢復存單同步。",
    )
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
            store_data = SELF_SERVICE_ORDER_SELECTIONS.get(interaction.channel.id, {})
            store_item = str(store_data.get("item") or store_data.get("category_label") or "訂單")
            store_customer_id = get_order_customer_id_from_channel(interaction.channel)
            store_customer_member = guild.get_member(store_customer_id) if store_customer_id is not None else None
            await rename_ticket_channel(interaction.channel, f"存單-{store_item}", member=store_customer_member)
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



class OrderAmountModal(discord.ui.Modal, title="填寫訂單價格"):
    amount = discord.ui.TextInput(
        label="本次訂單總價",
        placeholder="例如：1275、NT$1,275、750+595",
        required=True,
        max_length=100,
    )

    def __init__(self, customer_id: int, channel_id: int):
        super().__init__()
        self.customer_id = customer_id
        self.channel_id = channel_id

    async def on_submit(self, interaction: discord.Interaction):
        if not isinstance(interaction.user, discord.Member):
            await interaction.response.send_message("無法確認你的身分組。", ephemeral=True)
            return

        if not is_customer_staff(interaction.user):
            await interaction.response.send_message("只有客服可以填寫訂單價格。", ephemeral=True)
            return

        if interaction.guild is None or not isinstance(interaction.channel, discord.TextChannel):
            await interaction.response.send_message("這個功能只能在下單票口內使用。", ephemeral=True)
            return

        parsed_amount = parse_receipt_amount(str(self.amount.value))
        if parsed_amount is None or parsed_amount <= 0:
            await interaction.response.send_message(
                "金額欄位無法辨識，請輸入可辨識的數字，例如：1275、NT$1275、1275T。",
                ephemeral=True,
            )
            return

        data = SELF_SERVICE_ORDER_SELECTIONS.setdefault(self.channel_id, {})
        data["customer_id"] = self.customer_id
        data["amount"] = parsed_amount
        data["total_amount"] = parsed_amount
        data["amount_text"] = format_t_amount(parsed_amount)
        data["amount_set_at"] = get_taipei_now_iso()
        data["amount_set_by"] = interaction.user.id
        remember_order_data(self.channel_id, data)

        await send_order_log(
            interaction.guild,
            title="訂單價格已確認",
            fields=[
                ("顧客", f"<@{self.customer_id}>", True),
                ("金額", format_t_amount(parsed_amount), True),
                ("填寫人員", interaction.user.mention, True),
                ("票口", interaction.channel.mention, False),
            ],
            color=discord.Color.gold(),
        )

        category = data.get("category")
        item = data.get("item")
        quantity = _to_int(data.get("quantity"), 1) or 1
        companion_preference = data.get("companion_preference")
        if category is None or item is None:
            await interaction.response.send_message(
                "找不到訂單資料，請回到自助下單面板重新選擇。",
                ephemeral=True,
            )
            return

        payment_embed = build_payment_method_embed(
            customer_id=self.customer_id,
            category_label=ORDER_CATEGORY_LABELS.get(category, str(category)),
            item=str(item),
            quantity=quantity,
            companion_preference=companion_preference,
            amount=parsed_amount,
        )

        await interaction.response.send_message(
            f"已填寫訂單金額：{format_t_amount(parsed_amount)}\n請闆闆選擇付款方式。",
            ephemeral=True,
        )

        payment_message = await interaction.channel.send(
            embed=payment_embed,
            view=PaymentMethodView(
                customer_id=self.customer_id,
                channel_id=self.channel_id,
            ),
            allowed_mentions=discord.AllowedMentions(
                users=True,
                roles=False,
                everyone=False,
            ),
        )
        data["payment_channel_id"] = interaction.channel.id
        data["payment_message_id"] = payment_message.id
        remember_order_data(self.channel_id, data)


class StaffOrderAmountView(discord.ui.View):
    def __init__(self, customer_id: int, channel_id: int):
        super().__init__(timeout=86400)
        self.customer_id = customer_id
        self.channel_id = channel_id

    @discord.ui.button(
        label="填寫",
        style=discord.ButtonStyle.primary,
        custom_id="staff_order_amount_button",
    )
    async def fill_amount(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not isinstance(interaction.user, discord.Member):
            await interaction.response.send_message("無法確認你的身分組。", ephemeral=True)
            return

        if not is_customer_staff(interaction.user):
            await interaction.response.send_message("只有客服可以填寫訂單價格。", ephemeral=True)
            return

        await interaction.response.send_modal(OrderAmountModal(self.customer_id, self.channel_id))


async def send_staff_amount_panel(
    interaction: discord.Interaction,
    customer_id: int,
    channel_id: int,
) -> None:
    if not isinstance(interaction.channel, discord.TextChannel):
        await interaction.followup.send("無法確認目前票口頻道。", ephemeral=True)
        return

    data = SELF_SERVICE_ORDER_SELECTIONS.setdefault(channel_id, {})
    panel_message_id = _to_int(data.get("amount_panel_message_id"))
    if panel_message_id is not None:
        await interaction.followup.send("已通知客服填寫訂單價格，請不要重複送出。", ephemeral=True)
        return

    embed = discord.Embed(
        title="請客服填寫訂單金額",
        description=(
            f"下單用戶：<@{customer_id}>\n"
            "請客服確認本次訂單總價，按下方「填寫」輸入金額。\n"
            "客服送出金額後，才會出現付款方式面板。"
        ),
        color=discord.Color.gold(),
    )
    message = await interaction.channel.send(
        embed=embed,
        view=StaffOrderAmountView(customer_id, channel_id),
        allowed_mentions=discord.AllowedMentions(users=True, roles=False, everyone=False),
    )
    data["amount_panel_message_id"] = message.id
    remember_order_data(channel_id, data)
    await interaction.followup.send("已送出訂單金額面板，請客服填寫本次訂單總價。", ephemeral=True)


async def finalize_payment_and_dispatch(
    *,
    interaction: discord.Interaction,
    customer_id: int,
    channel_id: int,
    reward_result: str | None = None,
) -> None:
    guild = interaction.guild

    if guild is None:
        await interaction.response.send_message("這個功能只能在伺服器內使用。", ephemeral=True)
        return

    if not isinstance(interaction.channel, discord.TextChannel):
        await interaction.response.send_message("無法確認目前票口頻道。", ephemeral=True)
        return

    data = SELF_SERVICE_ORDER_SELECTIONS.get(channel_id, {})
    category = data.get("category")
    item = data.get("item")
    quantity = _to_int(data.get("quantity"), 1) or 1
    companion_preference = data.get("companion_preference")
    payment_method = data.get("payment_method")
    parsed_amount = _to_int(data.get("amount"), 0) or _to_int(data.get("total_amount"), 0) or 0

    if category is None or item is None:
        await interaction.response.send_message("找不到訂單資料，請回到自助下單面板重新選擇。", ephemeral=True)
        return

    if payment_method is None:
        await interaction.response.send_message("請先選擇付款方式，再按送出。", ephemeral=True)
        return

    if parsed_amount <= 0:
        if isinstance(interaction.user, discord.Member) and is_customer_staff(interaction.user):
            await interaction.response.send_modal(OrderAmountModal(customer_id, channel_id))
        else:
            await interaction.response.defer(ephemeral=True)
            await send_staff_amount_panel(interaction, customer_id, channel_id)
        return

    if data.get("dispatch_message_id") is not None:
        dispatch_channel_id = _to_int(data.get("dispatch_channel_id"), DISPATCH_CHANNEL_ID) or DISPATCH_CHANNEL_ID
        dispatch_message_id = _to_int(data.get("dispatch_message_id"))
        dispatch_channel = guild.get_channel(dispatch_channel_id)
        if isinstance(dispatch_channel, discord.TextChannel) and dispatch_message_id is not None:
            message = f"這張單已經送出派單，請不要重複送出。\n派單訊息：https://discord.com/channels/{guild.id}/{dispatch_channel.id}/{dispatch_message_id}"
        else:
            message = "這張單已經送出派單，請不要重複送出。"
        if interaction.response.is_done():
            await interaction.followup.send(message, ephemeral=True)
        else:
            await interaction.response.send_message(message, ephemeral=True)
        return

    if data.get("dispatch_submitting"):
        message = "這張單正在送出派單，請稍等，不要重複點擊。"
        if interaction.response.is_done():
            await interaction.followup.send(message, ephemeral=True)
        else:
            await interaction.response.send_message(message, ephemeral=True)
        return

    item_category = ORDER_ITEM_TO_CATEGORY.get(item)

    if item_category != category:
        await interaction.response.send_message(
            "你選擇的訂單類別與訂單項目不一致，請回到自助下單面板重新選擇。",
            ephemeral=True,
        )
        return

    if item in SPECIAL_COMPANION_ITEMS and companion_preference is None:
        await interaction.response.send_message(
            "這個項目請先回到自助下單面板選擇「不指定陪玩/打手」或「指定陪玩/打手」。",
            ephemeral=True,
        )
        return

    if item not in QUANTITY_SELECT_ITEMS:
        quantity = 1
        data["quantity"] = 1
        remember_order_data(channel_id, data)
    elif quantity < 1 or quantity > max(QUANTITY_OPTIONS):
        await interaction.response.send_message("數量選擇異常，請回到自助下單面板重新選擇。", ephemeral=True)
        return

    if companion_preference is None:
        companion_preference = "不指定陪玩/打手"
        data["companion_preference"] = companion_preference
        remember_order_data(channel_id, data)

    dispatch_channel = guild.get_channel(DISPATCH_CHANNEL_ID)

    if dispatch_channel is None or not isinstance(dispatch_channel, discord.TextChannel):
        await interaction.response.send_message(
            "找不到派單頻道，請確認 DISPATCH_CHANNEL_ID 是否正確。",
            ephemeral=True,
        )
        return

    category_label = ORDER_CATEGORY_LABELS[category]
    data["customer_id"] = customer_id
    data["amount"] = parsed_amount
    data["total_amount"] = parsed_amount
    data["amount_text"] = format_t_amount(parsed_amount)
    remember_order_data(channel_id, data)

    reward_result = await add_customer_reward_from_order(
        guild=guild,
        order_channel_id=channel_id,
        customer_id=customer_id,
        amount_text=str(parsed_amount),
        notify_channel=interaction.channel,
    )

    embed = build_self_service_order_embed(
        customer_mention=f"<@{customer_id}>",
        category_label=category_label,
        item=item,
        quantity=quantity,
        payment_method=payment_method,
        source_channel=interaction.channel,
        companion_preference=companion_preference,
    )
    embed.add_field(name="訂單總價", value=format_t_amount(parsed_amount), inline=True)

    data["dispatch_submitting"] = True
    remember_order_data(channel_id, data)

    if not interaction.response.is_done():
        await interaction.response.defer(ephemeral=True)

    try:
        dispatch_message = await dispatch_channel.send(
            embed=embed,
            view=DispatchClaimView(
                customer_id=customer_id,
                category_label=category_label,
                item=item,
                quantity=quantity,
                payment_method=payment_method,
                source_channel_id=interaction.channel.id,
                companion_preference=companion_preference,
            ),
            allowed_mentions=discord.AllowedMentions(users=True, roles=False, everyone=False),
        )
    except discord.HTTPException as e:
        data.pop("dispatch_submitting", None)
        remember_order_data(channel_id, data)
        await interaction.followup.send(f"派單送出失敗：{e}", ephemeral=True)
        return

    ORDER_CLAIMS[dispatch_message.id] = {
        "companion": set(),
        "booster": set(),
        "locked": False,
        "customer_id": customer_id,
        "category_label": category_label,
        "item": item,
        "quantity": quantity,
        "payment_method": payment_method,
        "amount": parsed_amount,
        "total_amount": parsed_amount,
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

    customer_member = guild.get_member(customer_id) if customer_id is not None else None
    await rename_ticket_channel(interaction.channel, str(item), member=customer_member)
    sync_web_order_active_from_dispatch_from_bot(
        ticket_channel_id=interaction.channel.id,
        dispatch_channel_id=dispatch_channel.id,
        dispatch_message_id=dispatch_message.id,
        customer_id=customer_id,
        customer_display_name=getattr(customer_member, "display_name", None) or str(customer_id),
        category_label=category_label,
        item=item,
        quantity=quantity,
        amount=parsed_amount,
        payment_method=payment_method,
        customer_service_member=interaction.user if isinstance(interaction.user, discord.Member) else None,
        bot_order_no=data.get("order_no"),
    )

    await log_self_service_proxy_action(
        interaction,
        customer_id,
        "送出派單",
        f"{category_label}｜{item} x{quantity}｜{payment_method}｜{format_t_amount(parsed_amount)}",
    )

    await send_order_log(
        guild,
        title="新自助下單已派單",
        fields=[
            ("顧客", f"<@{customer_id}>", True),
            ("訂單類別", category_label, True),
            ("訂單項目", item, True),
            ("數量", f"{quantity} 單", True),
            ("訂單總價", format_t_amount(parsed_amount), True),
            ("付款方式", payment_method, True),
            ("指定選項", companion_preference, True),
            ("送出人員", interaction.user.mention, True),
            ("是否代操作", "是" if interaction.user.id != customer_id else "否", True),
            ("票口", interaction.channel.mention, False),
            ("派單訊息", dispatch_message.jump_url, False),
        ],
        color=discord.Color.blue(),
    )

    submitted_embed = build_payment_method_embed(
        customer_id=customer_id,
        category_label=category_label,
        item=item,
        quantity=quantity,
        payment_method=payment_method,
        companion_preference=companion_preference,
        amount=parsed_amount,
        submitted=True,
        dispatch_url=dispatch_message.jump_url,
    )

    payment_channel_id = _to_int(data.get("payment_channel_id"), interaction.channel.id) or interaction.channel.id
    payment_message_id = _to_int(data.get("payment_message_id"))
    payment_channel = guild.get_channel(payment_channel_id)

    if isinstance(payment_channel, discord.TextChannel) and payment_message_id is not None:
        try:
            payment_message = await payment_channel.fetch_message(payment_message_id)
            await payment_message.edit(
                embed=submitted_embed,
                view=PaymentMethodView(customer_id=customer_id, channel_id=channel_id, submitted=True),
                allowed_mentions=discord.AllowedMentions(users=True, roles=False, everyone=False),
            )
        except discord.HTTPException:
            pass

    amount_panel_message_id = _to_int(data.get("amount_panel_message_id"))
    if amount_panel_message_id is not None:
        try:
            panel_message = await interaction.channel.fetch_message(amount_panel_message_id)
            await panel_message.edit(view=None)
        except discord.HTTPException:
            pass
        data.pop("amount_panel_message_id", None)
        remember_order_data(interaction.channel.id, data)

    response_text = f"已確認訂單總價 {format_t_amount(parsed_amount)}，並送出派單：{dispatch_message.jump_url}"
    if reward_result:
        response_text += f"\n\n{reward_result}"
    await interaction.followup.send(response_text, ephemeral=True)

    operation_embed = discord.Embed(
        title="訂單操作",
        description="請客服從下拉式清單選擇後，按下確認。",
        color=discord.Color.green(),
    )

    await interaction.channel.send(embed=operation_embed, view=StaffOrderOperationView())




def sync_web_order_active_from_dispatch_from_bot(
    *,
    ticket_channel_id,
    dispatch_channel_id,
    dispatch_message_id,
    customer_id,
    customer_display_name,
    category_label,
    item,
    quantity,
    amount,
    payment_method,
    customer_service_member=None,
    bot_order_no=None,
) -> None:
    """DC bot 新派單後，把 active 訂單寫進網站資料庫。"""
    try:
        from shared.web_order_sync import upsert_web_order_from_dispatch

        upsert_web_order_from_dispatch(
            ticket_channel_id=ticket_channel_id,
            dispatch_channel_id=dispatch_channel_id,
            dispatch_message_id=dispatch_message_id,
            customer_discord_id=customer_id,
            customer_display_name=customer_display_name,
            category=category_label,
            item=item,
            quantity=quantity,
            amount=amount,
            payment_method=payment_method,
            status="active",
            customer_service_discord_id=getattr(customer_service_member, "id", None),
            customer_service_display_name=getattr(customer_service_member, "display_name", None),
            bot_order_no=bot_order_no,
            note="由 DC bot 派單同步。",
        )

        print(
            f"[web-sync] dispatch upsert ok "
            f"ticket_channel_id={ticket_channel_id} "
            f"dispatch_message_id={dispatch_message_id}"
        )
    except Exception as exc:
        print(
            f"[web-sync] dispatch upsert failed "
            f"ticket_channel_id={ticket_channel_id} "
            f"dispatch_message_id={dispatch_message_id}: {exc}"
        )


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

        category = data.get("category")
        item = data.get("item")
        quantity = _to_int(data.get("quantity"), 1) or 1
        companion_preference = data.get("companion_preference")
        amount = _to_int(data.get("amount"), 0) or _to_int(data.get("total_amount"), 0) or 0

        if category is not None and item is not None:
            payment_embed = build_payment_method_embed(
                customer_id=self.customer_id,
                category_label=ORDER_CATEGORY_LABELS.get(category, str(category)),
                item=str(item),
                quantity=quantity,
                payment_method=selected_method,
                companion_preference=companion_preference,
                amount=amount or None,
            )
            await interaction.response.edit_message(embed=payment_embed, view=self.view)
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

        await finalize_payment_and_dispatch(
            interaction=interaction,
            customer_id=self.customer_id,
            channel_id=self.channel_id,
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
        label="取得訂單金額",
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
            await interaction.response.send_message("請先選擇訂單類別與訂單項目，再取得訂單金額。", ephemeral=True)
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
                "這個項目請先選擇「不指定陪玩/打手」或「指定陪玩/打手」，再取得訂單金額。",
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

        await interaction.response.defer(ephemeral=True)

        await send_staff_amount_panel(
            interaction=interaction,
            customer_id=self.customer_id,
            channel_id=self.channel_id,
        )

        button.disabled = True
        button.label = "已送出，等待客服填價"
        try:
            await interaction.message.edit(view=self)
        except discord.HTTPException:
            pass

        await log_self_service_proxy_action(
            interaction,
            self.customer_id,
            "取得訂單金額",
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
                resume_data = SELF_SERVICE_ORDER_SELECTIONS.get(interaction.channel.id, {})
                resume_item = str(resume_data.get("item") or resume_data.get("category_label") or "恢復訂單")
                resume_customer_id = get_order_customer_id_from_channel(interaction.channel)
                resume_customer_member = guild.get_member(resume_customer_id) if resume_customer_id is not None else None
                await rename_ticket_channel(interaction.channel, resume_item, member=resume_customer_member)
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
                "請下單用戶選擇訂單類別與訂單項目，完成後按「取得訂單金額」。\n"
                "如果選擇娛樂陪、技術陪、Valorant 陪打、Valorant 代打，數量欄位可選擇 1～8 單；1 單 = 1 小時，2 單 = 2 小時，依此類推。\n"
                "如果選擇娛樂陪、技術陪、保底單，請額外選擇是否指定陪玩/打手；Valorant 陪打可選擇指定或不指定打手。"
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

# ========= 主面板 / 下單入口 View 設定 =========

configure_panel_views(
    customer_category_id=CUSTOMER_CATEGORY_ID,
    exam_category_id=EXAM_CATEGORY_ID,
    customer_role_id=CUSTOMER_ROLE_ID,
    examiner_role_id=EXAMINER_ROLE_ID,
    manager_role_id=MANAGER_ROLE_ID,
    recruit_applicant_role_id=RECRUIT_APPLICANT_ROLE_ID,
    safe_channel_name=safe_channel_name,
    is_agree_answer=is_agree_answer,
    format_customer_notes_for_ticket=format_customer_notes_for_ticket,
    create_private_channel=create_private_channel,
    order_control_view_factory=OrderControlView,
    recruit_control_view_factory=RecruitControlView,
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

        if is_temp_play_voice_room and before.channel != after.channel and len(before.channel.members) > 0:
            await revoke_play_voice_room_chat_access(before.channel, member)

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

    if before.channel != after.channel:
        await grant_play_voice_room_chat_access(after.channel, member)

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
    ensure_web_sync_event_worker_started()
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

    if not getattr(bot, "_extensions_loaded", False):
        try:
            for extension_name in (
                "cogs.lottery_commands",
                "cogs.reward_commands",
                "cogs.stats_commands",
                "cogs.setup_commands",
                "cogs.customer_commands",
                "cogs.audit_commands",
                "cogs.staff_sync",
            ):
                await bot.load_extension(extension_name)
            bot.tree.copy_global_to(guild=discord.Object(id=GUILD_ID))
            bot._extensions_loaded = True
        except Exception as e:
            print(f"Extension load error: {e}")

    try:
        guild = discord.Object(id=GUILD_ID)
        synced = await bot.tree.sync(guild=guild)
        print(f"Slash commands synced: {len(synced)}")
    except Exception as e:
        print(f"Sync error: {e}")

    print(f"Logged in as {bot.user}")


# ========= Slash 指令 =========



# ========= 點數抽獎系統 =========

# 抽獎 slash 指令已搬到 cogs/lottery_commands.py


# 會員點數 / 補登 slash 指令已搬到 cogs/reward_commands.py


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
@app_commands.default_permissions(manage_messages=True)
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



def _require_customer_staff_or_manager(interaction: discord.Interaction) -> bool:
    return (
        isinstance(interaction.user, discord.Member)
        and (is_customer_staff(interaction.user) or has_role(interaction.user, MANAGER_ROLE_ID) or interaction.user.guild_permissions.administrator)
    )


# 營運統計 / VIP 降階查詢 slash 指令已搬到 cogs/stats_commands.py


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
@app_commands.default_permissions(manage_messages=True)
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

    if dispatch_channel is None:
        try:
            fetched_channel = await asyncio.wait_for(guild.fetch_channel(dispatch_channel_id), timeout=5)
            dispatch_channel = fetched_channel if isinstance(fetched_channel, discord.TextChannel) else None
        except (asyncio.TimeoutError, discord.NotFound, discord.Forbidden, discord.HTTPException):
            dispatch_channel = None

    if not isinstance(dispatch_channel, discord.TextChannel):
        return False

    try:
        message = await asyncio.wait_for(dispatch_channel.fetch_message(dispatch_message_id), timeout=5)
        await asyncio.wait_for(message.delete(), timeout=5)
        return True
    except (asyncio.TimeoutError, discord.NotFound, discord.Forbidden, discord.HTTPException):
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




def sync_web_order_cancelled_from_bot(ticket_channel_id, dispatch_message_id=None, note: str | None = None) -> None:
    """DC bot 刪除/取消訂單後，把網站訂單狀態同步成 cancelled。"""
    try:
        from shared.web_order_sync import update_web_order_status_by_ticket_channel

        ok = update_web_order_status_by_ticket_channel(
            ticket_channel_id=ticket_channel_id,
            status="cancelled",
            dispatch_message_id=dispatch_message_id,
            note=note or "由 DC bot 刪除/取消訂單同步。",
        )
        print(
            f"[web-sync] cancel order "
            f"ticket_channel_id={ticket_channel_id} "
            f"dispatch_message_id={dispatch_message_id} ok={ok}"
        )
    except Exception as exc:
        print(
            f"[web-sync] 刪除/取消訂單同步網站失敗 "
            f"ticket_channel_id={ticket_channel_id}: {exc}"
        )




def sync_web_order_deleted_from_bot(ticket_channel_id, dispatch_message_id=None, note: str | None = None) -> None:
    """DC bot 刪除訂單後，從網站資料庫直接刪除對應 web_order。"""
    try:
        from shared.web_order_sync import delete_web_order_by_ticket_channel

        ok = delete_web_order_by_ticket_channel(
            ticket_channel_id=ticket_channel_id,
            dispatch_message_id=dispatch_message_id,
        )

        print(
            f"[web-sync] delete web order "
            f"ticket_channel_id={ticket_channel_id} "
            f"dispatch_message_id={dispatch_message_id} ok={ok}"
        )
    except Exception as exc:
        print(
            f"[web-sync] 刪除網站訂單失敗 "
            f"ticket_channel_id={ticket_channel_id} "
            f"dispatch_message_id={dispatch_message_id}: {exc}"
        )


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
@app_commands.default_permissions(manage_messages=True)
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

    try:
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

        sync_web_order_deleted_from_bot(
            ticket_channel_id=channel_id,
            dispatch_message_id=dispatch_message_id,
            note="由 /delete_order 刪除網站訂單。",
        )

        SELF_SERVICE_ORDER_SELECTIONS.pop(channel_id, None)
        delete_order_row_from_db(channel_id)
        save_bot_data()
        benefit_notices = await asyncio.wait_for(
            refresh_customer_benefits_after_manual_fix(interaction.guild, [customer_id]),
            timeout=15,
        )

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
    except Exception as e:
        error_text = f"/delete_order 執行失敗：{type(e).__name__}: {e}"
        try:
            await interaction.followup.send(
                f"刪除訂單失敗：`{type(e).__name__}: {e}`\n請到 VPS 查看 journalctl 取得完整 Traceback。",
                ephemeral=True,
            )
        except discord.HTTPException:
            pass
        await send_order_log(
            interaction.guild,
            title="刪除訂單失敗",
            description=error_text,
            fields=[
                ("操作人員", interaction.user.mention, True),
                ("輸入訂單", str(order), True),
                ("票口 ID", str(channel_id), True),
            ],
            color=discord.Color.red(),
        )
        raise


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
@app_commands.default_permissions(manage_messages=True)
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
@app_commands.default_permissions(manage_messages=True)
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
@app_commands.default_permissions(manage_messages=True)
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




WEB_SYNC_EVENT_TASK = None


def _web_dashboard_db_path_for_bot() -> str:
    from pathlib import Path

    return str(Path(__file__).with_name("web_dashboard.db"))


def _web_sync_fetch_pending_events(limit: int = 10) -> list[dict]:
    import sqlite3

    conn = sqlite3.connect(_web_dashboard_db_path_for_bot())
    conn.row_factory = sqlite3.Row

    try:
        rows = conn.execute(
            """
            SELECT
                e.id AS event_id,
                e.order_id,
                e.event_type,
                e.retry_count,
                w.id AS web_order_id,
                w.dispatch_channel_id,
                w.dispatch_message_id,
                w.category,
                w.item,
                w.quantity,
                w.amount,
                w.customer_discord_id,
                w.customer_display_name
            FROM sync_events e
            JOIN web_orders w ON w.id = e.order_id
            WHERE e.status = 'pending'
            ORDER BY e.id ASC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()

        return [dict(row) for row in rows]
    finally:
        conn.close()


def _web_sync_get_assignments(order_id: int) -> list[dict]:
    import sqlite3

    conn = sqlite3.connect(_web_dashboard_db_path_for_bot())
    conn.row_factory = sqlite3.Row

    try:
        rows = conn.execute(
            """
            SELECT
                worker_discord_id,
                worker_display_name,
                role_type,
                is_active
            FROM order_assignments
            WHERE order_id = ?
              AND is_active = 1
            ORDER BY id ASC
            """,
            (order_id,),
        ).fetchall()

        return [dict(row) for row in rows]
    finally:
        conn.close()


def _web_sync_mark_event_done(event_id: int) -> None:
    import sqlite3

    conn = sqlite3.connect(_web_dashboard_db_path_for_bot())

    try:
        conn.execute(
            """
            UPDATE sync_events
            SET status = 'done',
                error_message = NULL,
                processed_at = datetime('now')
            WHERE id = ?
            """,
            (event_id,),
        )
        conn.commit()
    finally:
        conn.close()


def _web_sync_mark_event_failed(event_id: int, error_message: str, retry_count: int) -> None:
    import sqlite3

    next_retry = int(retry_count or 0) + 1
    next_status = "failed" if next_retry >= 3 else "pending"

    conn = sqlite3.connect(_web_dashboard_db_path_for_bot())

    try:
        conn.execute(
            """
            UPDATE sync_events
            SET status = ?,
                error_message = ?,
                retry_count = ?,
                processed_at = CASE WHEN ? = 'failed' THEN datetime('now') ELSE processed_at END
            WHERE id = ?
            """,
            (next_status, error_message[:1000], next_retry, next_status, event_id),
        )
        conn.commit()
    finally:
        conn.close()


def _web_sync_build_receiver_text(assignments: list[dict]) -> str:
    companions = []
    boosters = []

    for row in assignments:
        user_id = str(row.get("worker_discord_id") or "").strip()
        display_name = str(row.get("worker_display_name") or user_id).strip()
        role_type = str(row.get("role_type") or "booster").strip()

        if not user_id:
            continue

        text = f"<@{user_id}>"

        if role_type == "companion":
            companions.append(text)
        else:
            boosters.append(text)

    parts = []

    if boosters:
        parts.append("打手：" + "、".join(boosters))

    if companions:
        parts.append("陪玩：" + "、".join(companions))

    if not parts:
        return "尚未有人接單"

    return "\n".join(parts)


def _web_sync_embed_without_receiver_fields(embed):
    blocked_names = {
        "目前接單",
        "目前接單人",
        "接單狀態",
        "接單人員",
        "打手接單",
        "陪玩接單",
        "已接人員",
    }

    old_fields = list(embed.fields)
    embed.clear_fields()

    for field in old_fields:
        if str(field.name).strip() in blocked_names:
            continue

        embed.add_field(
            name=field.name,
            value=field.value,
            inline=field.inline,
        )

    return embed


async def process_one_web_sync_event(event: dict) -> None:
    event_id = int(event["event_id"])
    retry_count = int(event.get("retry_count") or 0)

    try:
        dispatch_channel_id = int(event.get("dispatch_channel_id") or 0)
        dispatch_message_id = int(event.get("dispatch_message_id") or 0)

        if not dispatch_channel_id or not dispatch_message_id:
            raise RuntimeError("web order missing dispatch channel/message id")

        channel = bot.get_channel(dispatch_channel_id)

        if channel is None:
            channel = await bot.fetch_channel(dispatch_channel_id)

        message = await channel.fetch_message(dispatch_message_id)

        assignments = _web_sync_get_assignments(int(event["order_id"]))
        receiver_text = _web_sync_build_receiver_text(assignments)

        if message.embeds:
            embed = message.embeds[0].copy()
        else:
            embed = discord.Embed(title="派單訊息", color=discord.Color.blue())

        embed = _web_sync_embed_without_receiver_fields(embed)
        embed.add_field(
            name="目前接單",
            value=receiver_text,
            inline=False,
        )

        await message.edit(
            embed=embed,
            allowed_mentions=discord.AllowedMentions(users=True, roles=False, everyone=False),
        )

        _web_sync_mark_event_done(event_id)
        print(f"[web-sync] event_id={event_id} done order_id={event.get('order_id')}")

    except Exception as exc:
        _web_sync_mark_event_failed(event_id, str(exc), retry_count)
        print(f"處理網站同步事件失敗 event_id={event_id}：{exc}")


async def web_sync_event_worker() -> None:
    await bot.wait_until_ready()

    while not bot.is_closed():
        try:
            events = _web_sync_fetch_pending_events(limit=10)

            for event in events:
                await process_one_web_sync_event(event)

        except Exception as exc:
            print(f"[web-sync] 背景處理器失敗：{exc}")

        await asyncio.sleep(5)


def ensure_web_sync_event_worker_started() -> None:
    global WEB_SYNC_EVENT_TASK

    if WEB_SYNC_EVENT_TASK is not None and not WEB_SYNC_EVENT_TASK.done():
        return

    WEB_SYNC_EVENT_TASK = bot.loop.create_task(web_sync_event_worker())
    print("[web-sync] 背景同步事件處理器已啟動")


# ========= 資料庫健康檢查指令 =========

# /audit_data 已搬到 cogs/audit_commands.py


# ========= 存單管理面板 =========

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
@app_commands.default_permissions(manage_messages=True)
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
@app_commands.default_permissions(manage_messages=True)
async def check_stored_orders(interaction: discord.Interaction):
    if not _require_customer_staff_or_manager(interaction):
        await interaction.response.send_message("只有客服、店長或管理員可以檢查存單提醒。", ephemeral=True)
        return

    await interaction.response.defer(ephemeral=True)
    await check_stored_order_reminders_once(interaction.guild)
    await interaction.followup.send("已檢查存單提醒，若有逾期存單會發到機器人日誌。", ephemeral=True)


# 顧客備註 slash 指令已搬到 cogs/customer_commands.py


@bot.tree.command(
    name="delete_dispatch_panel",
    description="刪除派單頻道中已取消訂單的接單面板",
    guild=discord.Object(id=GUILD_ID)
)
@app_commands.describe(
    message_id="要刪除的派單訊息 ID",
    channel="派單訊息所在頻道；不填則使用目前頻道"
)
@app_commands.default_permissions(manage_messages=True)
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


# 註冊 bot.py 裡的 top-level slash 指令群組
try:
    bot.tree.add_command(order_group)
except app_commands.CommandAlreadyRegistered:
    pass
try:
    bot.tree.add_command(vip_group)
except app_commands.CommandAlreadyRegistered:
    pass

bot.run(TOKEN)

def _sync_dispatch_claims_to_web_from_bot(dispatch_message_id, claim_data, guild):
    """Discord 派單訊息按接單/取消接單後，同步寫回網站資料庫。"""
    try:
        from shared.web_order_sync import sync_dispatch_claims_to_web

        companion_ids = sorted(int(user_id) for user_id in claim_data.get("companion", set()))
        booster_ids = sorted(int(user_id) for user_id in claim_data.get("booster", set()))

        display_names = {}

        for user_id in companion_ids + booster_ids:
            member = guild.get_member(user_id) if guild is not None else None
            display_names[str(user_id)] = (
                getattr(member, "display_name", None)
                or getattr(member, "name", None)
                or str(user_id)
            )

        sync_dispatch_claims_to_web(
            dispatch_message_id=dispatch_message_id,
            companion_ids=companion_ids,
            booster_ids=booster_ids,
            worker_display_names=display_names,
        )
    except Exception as exc:
        print(f"[web-sync] Discord 接單同步網站失敗 dispatch_message_id={dispatch_message_id}: {exc}")

