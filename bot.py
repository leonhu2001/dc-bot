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


# ========= 霈??.env =========

env_path = Path(__file__).parent / ".env"
load_dotenv(dotenv_path=env_path)

TOKEN = os.getenv("DISCORD_TOKEN")

if TOKEN is None:
    raise RuntimeError("霈銝 DISCORD_TOKEN嚗?蝣箄? .env 瑼???bot.py ?????冗")


# ========= ?箏? ID =========

GUILD_ID = 1129474191226306672

# 憿 ID
CUSTOMER_CATEGORY_ID = 1483895536938651809
EXAM_CATEGORY_ID = 1483873316702781471
PLAY_VOICE_CATEGORY_ID = 1482016208638447699

# ?芰隤?亙?駁??迂
PLAY_VOICE_CREATE_CHANNEL_NAME = "??暺??萄遣?芰?駁?"
OLD_PLAY_VOICE_CREATE_CHANNEL_NAMES = ["???拚??撱粹??]

# VIP 隤?亙?駁??迂
VIP_VOICE_CREATE_CHANNEL_NAME = "??暺??萄遣VIP?駁?"
OLD_VIP_VOICE_CREATE_CHANNEL_NAMES = ["????????券??撱粹??]

# ?砍隤?亙?駁??迂
PUBLIC_VOICE_CREATE_CHANNEL_NAME = "??暺??萄遣?砍?駁?"

# VIP 隤?亙?航? / ?舫脣頨怠?蝯?ID
VIP_VOICE_LOBBY_ROLE_ID = 1482080566760177706

# 頨怠?蝯?ID
CUSTOMER_ROLE_ID = 1482084782031638548
EXAMINER_ROLE_ID = 1497427024644411543
MANAGER_ROLE_ID = 1131128849443328030
RECRUIT_APPLICANT_ROLE_ID = 1498829171042943057  # ?亥蟡典????頨怠?蝯?

# ??嗅漲 ID / 閮剖?
SILVER_MEMBER_ROLE_ID = 1482080566760177706
PLATINUM_PRIVATE_CATEGORY_ID = 1483871504419520654
PLATINUM_CHAT_ROLE_IDS = [
    1503706721883783218,
    1503701170504339458,
]
REWARD_POINT_DIVISOR = 100
MEMBER_LEVELS = [
    {"name": "?桅?銝?, "threshold": 0},
    {"name": "?蝝?銝?, "threshold": 2500},
    {"name": "??擳虜", "threshold": 7000},
    {"name": "?賡?擳虜", "threshold": 13000},
    {"name": "?賜擳虜", "threshold": 30000},
    {"name": "??擳虜", "threshold": 77777},
]

# 閮?亥? / ?遢閮剖?
ORDER_LOG_CATEGORY_ID = 1483895536938651809
ORDER_LOG_CHANNEL_NAME = "?????其犖?亥?"
LOTTERY_ANNOUNCE_CHANNEL_ID = 1482079302739693739
BACKUP_KEEP_DAYS = 30
ORDER_ID_PREFIX = "MO"

# ?亙頨怠?蝯?ID
COMPANION_RECEIVER_ROLE_ID = 1503706721883783218  # ?芰?亙
BOOSTER_RECEIVER_ROLE_ID = 1503701170504339458    # ???亙

# ?嗆??駁? ID
RECEIPT_CHANNEL_ID = 1497623878619627682

# ???駁? ID
EXAM_NOTICE_CHANNEL_ID = 1482083066531942563

# 摰Ｚ迄?Ｘ?駁? ID
COMPLAINT_PANEL_CHANNEL_ID = 1497653883948765344

# 憿批恥??蝞梢?輸??ID
FEEDBACK_PANEL_CHANNEL_ID = 1504345505633927178

# 摰Ｚ迄??駁? ID
COMPLAINT_RECEIVE_CHANNEL_ID = 1502040302649872394

# 瘣曉?駁? ID
DISPATCH_CHANNEL_ID = 1483868763446186036

# 閰?駁? ID
REVIEW_CHANNEL_ID = 1482998033091268691

# 甇∟??駁? ID
WELCOME_CHANNEL_ID = 1482080953353375752

# ?唳??∟?策鈭澈?? ID
NEW_MEMBER_ROLE_ID = 1483872591457550494

# ?芰隤?亙 / ?芰隤?踹閬??舫脣頨怠?蝯?ID
# ?桀??芷??橘??芰?亙????柴恥??
PLAY_VOICE_ALLOWED_ROLE_IDS = [
    1503706721883783218,
    1503701170504339458,
    1482084782031638548,
]

# 隤?踵????嚗??舐?閬??頨怠?蝯?ID
VOICE_ROOM_HIDDEN_VISIBLE_ROLE_IDS = [
    1503706721883783218,
    1503701170504339458,
    1482084782031638548,
]

# ?怠??望??其犖撱箇???抵??單 ID
TEMP_PLAY_VOICE_CHANNEL_IDS = set()

# ?怠??望??其犖撱箇???VIP 隤??ID
TEMP_VIP_VOICE_CHANNEL_IDS = set()

# ?怠??望??其犖撱箇???梯??單 ID
TEMP_PUBLIC_VOICE_CHANNEL_IDS = set()

# ?怠?隤?踵?園?輯???
# voice_channel_id -> {owner_id, panel_channel_id, room_type, locked, hidden}
TEMP_VOICE_CONTROL_PANELS = {}


# ========= 憭閮剖?瑼???=========
# config.json 霈??頛臬歇?砍 core/config.py??
# ?ㄐ?芯???閮剖?憟?圈?閮剖潦??憛??? bot.py 鞎???


# 隡箸???/ 憿
GUILD_ID = _config_int("GUILD_ID", GUILD_ID)
CUSTOMER_CATEGORY_ID = _config_int("CUSTOMER_CATEGORY_ID", CUSTOMER_CATEGORY_ID)
EXAM_CATEGORY_ID = _config_int("EXAM_CATEGORY_ID", EXAM_CATEGORY_ID)
PLAY_VOICE_CATEGORY_ID = _config_int("PLAY_VOICE_CATEGORY_ID", PLAY_VOICE_CATEGORY_ID)
PLATINUM_PRIVATE_CATEGORY_ID = _config_int("PLATINUM_PRIVATE_CATEGORY_ID", PLATINUM_PRIVATE_CATEGORY_ID)
ORDER_LOG_CATEGORY_ID = _config_int("ORDER_LOG_CATEGORY_ID", ORDER_LOG_CATEGORY_ID)

# ?駁?
LOTTERY_ANNOUNCE_CHANNEL_ID = _config_int("LOTTERY_ANNOUNCE_CHANNEL_ID", LOTTERY_ANNOUNCE_CHANNEL_ID)
RECEIPT_CHANNEL_ID = _config_int("RECEIPT_CHANNEL_ID", RECEIPT_CHANNEL_ID)
EXAM_NOTICE_CHANNEL_ID = _config_int("EXAM_NOTICE_CHANNEL_ID", EXAM_NOTICE_CHANNEL_ID)
COMPLAINT_PANEL_CHANNEL_ID = _config_int("COMPLAINT_PANEL_CHANNEL_ID", COMPLAINT_PANEL_CHANNEL_ID)
FEEDBACK_PANEL_CHANNEL_ID = _config_int("FEEDBACK_PANEL_CHANNEL_ID", FEEDBACK_PANEL_CHANNEL_ID)
COMPLAINT_RECEIVE_CHANNEL_ID = _config_int("COMPLAINT_RECEIVE_CHANNEL_ID", COMPLAINT_RECEIVE_CHANNEL_ID)
DISPATCH_CHANNEL_ID = _config_int("DISPATCH_CHANNEL_ID", DISPATCH_CHANNEL_ID)
REVIEW_CHANNEL_ID = _config_int("REVIEW_CHANNEL_ID", REVIEW_CHANNEL_ID)
WELCOME_CHANNEL_ID = _config_int("WELCOME_CHANNEL_ID", WELCOME_CHANNEL_ID)

# 頨怠?蝯?
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

# ?迂 / ?嗡?閮剖?
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

# ========= Bot 閮剖? =========

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


# ========= 撌亙?賢? =========

def safe_channel_name(prefix: str, member: discord.Member) -> str:
    name = member.name.lower()
    clean = "".join(c if c.isalnum() else "-" for c in name)
    return f"{prefix}-{clean}-{member.id}"[:90]


def is_agree_answer(text: str) -> bool:
    answer = text.strip().lower()

    agree_words = {
        "??,
        "??,
        "撌脰底??,
        "撌脰底霈",
        "撌脤霈",
        "?歇閰喲",
        "?歇閰唾?",
        "?歇?梯?",
        "??",
        "yes",
        "y",
        "ok",
        "okay",
    }

    return answer in agree_words



def get_recruit_info_from_channel(channel: discord.TextChannel) -> tuple[str, str]:
    if not channel.topic:
        return "?芰??蝔?, "?芰??雿?

    data = {}

    for part in channel.topic.split(";"):
        if "=" in part:
            key, value = part.split("=", 1)
            data[key.strip()] = value.strip()

    nickname = data.get("recruit_nickname", "?芰??蝔?)
    position = data.get("recruit_position", "?芰??雿?)

    return nickname, position


def get_recruit_member_id_from_channel(channel: discord.TextChannel) -> int | None:
    """敺?瑞巨??topic 霈?隢犖 ID??""
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
    """?亥蟡典????隢犖?急?頨怠?蝯?""
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
        print("Bot 甈?銝雲嚗瘜??瑞隢?澈????蝣箄? Bot 頨怠?蝯?蝵桅??潸府頨怠?蝯?)
    except discord.HTTPException as e:
        print(f"?嗅??亥?唾??急?頨怠?蝯仃??{e}")


configure_support_views(
    complaint_receive_channel_id=COMPLAINT_RECEIVE_CHANNEL_ID,
    remove_recruit_applicant_role=remove_recruit_applicant_role,
)


def get_order_customer_id_from_channel(channel: discord.TextChannel) -> int | None:
    """
    ?芸?敺??topic 霈???桅“摰?ID??
    ?交?巨?????topic嚗??岫敺??蝔望?敺?畾菔???ID??
    ?駁??迂?澆??虜?嚗?????-雿輻?D
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
            "???賢?賢隡箸??典雿輻??,
            ephemeral=True
        )
        return

    category = guild.get_channel(category_id)

    if category is None or not isinstance(category, discord.CategoryChannel):
        await interaction.response.send_message(
            "?曆??唳?摰??伐?隢Ⅱ隤?憛怎??胯???ID??銝?駁? ID??,
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
            title="?啁巨??歇撱箇?",
            fields=[
                ("?鈭?, member.mention, True),
                ("蟡典", channel.mention, True),
                ("???, "撌脩Ⅱ隤底?梯?蝡摰?, False),
            ],
            color=discord.Color.purple(),
        )

    try:
        await interaction.delete_original_response()
    except discord.NotFound:
        pass
    except discord.HTTPException:
        pass


# ========= 閰 Modal / ?? =========
# Review modal/button views moved to views/review.py

# ========= 瘣曉 Modal =========

class DispatchModal(discord.ui.Modal, title="瘣曉"):
    order_name = discord.ui.TextInput(
        label="?桀??迂",
        placeholder="隢撓?亙摮?蝔?,
        required=True,
        max_length=100
    )

    receiver = discord.ui.TextInput(
        label="?亙??/?芰",
        placeholder="隢撓?交?格????芰?迂",
        required=True,
        max_length=100
    )

    async def on_submit(self, interaction: discord.Interaction):
        if not isinstance(interaction.user, discord.Member):
            await interaction.response.send_message("?⊥?蝣箄?雿?頨怠?蝯?, ephemeral=True)
            return

        if not is_customer_staff(interaction.user):
            await interaction.response.send_message("?芣?摰Ｘ??臭誑瘣曉??, ephemeral=True)
            return

        guild = interaction.guild

        if guild is None:
            await interaction.response.send_message("???賢?賢隡箸??典雿輻??, ephemeral=True)
            return

        dispatch_channel = guild.get_channel(DISPATCH_CHANNEL_ID)

        if dispatch_channel is None or not isinstance(dispatch_channel, discord.TextChannel):
            await interaction.response.send_message(
                "?曆??唳晷?桅??隢Ⅱ隤?DISPATCH_CHANNEL_ID ?臬甇?Ⅱ??,
                ephemeral=True
            )
            return

        source_channel = interaction.channel.mention if isinstance(interaction.channel, discord.TextChannel) else "?芰?駁?"

        embed = discord.Embed(
            title="?唳晷??,
            color=discord.Color.blue()
        )

        embed.add_field(
            name="?桀??迂",
            value=self.order_name.value,
            inline=False
        )

        embed.add_field(
            name="?亙??/?芰",
            value=self.receiver.value,
            inline=False
        )

        embed.add_field(
            name="瘣曉摰Ｘ?",
            value=interaction.user.mention,
            inline=False
        )

        embed.add_field(
            name="靘??駁?",
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
            f"撌脫晷?殷?瘣曉鞈?撌脤 {dispatch_channel.mention}??,
            ephemeral=True
        )

        if isinstance(interaction.channel, discord.TextChannel):
            await interaction.channel.send(
                f"甇文撌脩 {interaction.user.mention} 瘣曉?n"
                f"?桀??迂嚗self.order_name.value}\n"
                f"?亙??/?芰嚗self.receiver.value}"
            )




def sync_web_order_closed_from_bot(ticket_channel_id, dispatch_message_id=None) -> None:
    """DC bot 蝯敺??雯蝡??桃???甇交? closed??""
    try:
        from shared.web_order_sync import update_web_order_status_by_ticket_channel

        ok = update_web_order_status_by_ticket_channel(
            ticket_channel_id=ticket_channel_id,
            status="closed",
            dispatch_message_id=dispatch_message_id,
            note="??DC bot 蝯?郊??,
        )
        print(f"[web-sync] close order ticket_channel_id={ticket_channel_id} dispatch_message_id={dispatch_message_id} ok={ok}")
    except Exception as exc:
        print(f"[web-sync] 蝯?郊蝬脩?憭望? ticket_channel_id={ticket_channel_id}: {exc}")


# ========= ?嗆? Modal =========

class ReceiptModal(discord.ui.Modal, title="撌脩??格??):
    payee = discord.ui.TextInput(
        label="?嗆狡鈭?,
        placeholder="靘?嚗Yao?恥?蝔?隞?)",
        required=True,
        max_length=100
    )

    staff = discord.ui.TextInput(
        label="撠摰Ｘ?",
        placeholder="隢撓?亙??亙恥??蝔?,
        required=True,
        max_length=100
    )

    receiver = discord.ui.TextInput(
        label="?亙??/?芰",
        placeholder="隢撓?交?格????芰?迂",
        required=True,
        max_length=100
    )

    async def on_submit(self, interaction: discord.Interaction):
        if not isinstance(interaction.user, discord.Member):
            await interaction.response.send_message("?⊥?蝣箄?雿?頨怠?蝯?, ephemeral=True)
            return

        if not is_customer_staff(interaction.user):
            await interaction.response.send_message("?芣?摰Ｘ??臭誑??撌脩??柴?, ephemeral=True)
            return

        guild = interaction.guild

        if guild is None:
            await interaction.response.send_message("???賢?賢隡箸??典雿輻??, ephemeral=True)
            return

        if not isinstance(interaction.channel, discord.TextChannel):
            await interaction.response.send_message("?⊥?蝣箄??桀?蟡典?駁???, ephemeral=True)
            return

        receipt_channel = guild.get_channel(RECEIPT_CHANNEL_ID)

        if receipt_channel is None or not isinstance(receipt_channel, discord.TextChannel):
            await interaction.response.send_message(
                "?曆??唳???隢Ⅱ隤?RECEIPT_CHANNEL_ID ?臬甇?Ⅱ??,
                ephemeral=True
            )
            return

        order_channel = interaction.channel
        customer_id = get_order_customer_id_from_channel(order_channel)

        if customer_id is None:
            await interaction.response.send_message(
                "?⊥?颲刻??撐蟡典???桅“摰ｇ??迨?⊥??芸?撣嗅隞狡鈭箝?,
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
                "?撐?桅?瘝?閮?寞嚗??隞狡?Ｘ?‵撖怨??桀?潦?摰Ｘ?頛詨????,
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
            "?嗆?\n"
            "\n"
            f"蝺刻?嚗receipt_id}\n"
            f"?交?嚗date_text}\n"
            "\n"
            f"?嗆狡鈭綽?{self.payee.value}\n"
            f"隞狡鈭綽?{payer_text}\n"
            "\n"
            f"?批捆嚗order_content}\n"
            "\n"
            f"??嚗amount_text}\n"
            f"隞狡?孵?嚗payment_method}\n"
            "```"
        )

        embed = discord.Embed(
            title="?嗆?",
            description=receipt_text,
            color=discord.Color.green()
        )

        embed.add_field(
            name="隞狡鈭?,
            value=payer_text,
            inline=False
        )

        embed.add_field(
            name="撠摰Ｘ?",
            value=self.staff.value,
            inline=False
        )

        embed.add_field(
            name="?亙??/?芰",
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

        reward_result = "?蝝舐?撌脣憿批恥?隞狡?孵????? if order_data.get("reward_counted") else "??嚗撐?桀??芣?閮??∠敞蝛?隢Ⅱ隤“摰Ｘ?血歇?隞狡?孵???

        await send_order_log(
            guild,
            title="閮撌脩???,
            fields=[
                ("閮蝺刻?", receipt_id, True),
                ("憿批恥", f"<@{customer_id}>", True),
                ("摰Ｘ?", interaction.user.mention, True),
                ("??", amount_text, True),
                ("隞狡?孵?", payment_method, True),
                ("蟡典", order_channel.mention, False),
                ("?批捆", order_content, False),
            ],
            color=discord.Color.green(),
        )

        await interaction.response.send_message(
            f"甇文撌脩 {interaction.user.mention} 蝯嚗?歇??n\n"
            f"{reward_result}\n\n"
            f"隢???銝?隢?,
            view=ReviewButtonView(customer_id=customer_id),
            allowed_mentions=discord.AllowedMentions(
                users=True,
                roles=False,
                everyone=False
            )
        )


# ========= 銝???? =========

class ConfirmCancelOrderView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=60)

    @discord.ui.button(
        label="?荔???閮",
        style=discord.ButtonStyle.danger,
        custom_id="confirm_cancel_order_yes"
    )
    async def confirm_cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not isinstance(interaction.user, discord.Member):
            await interaction.response.send_message("?⊥?蝣箄?雿?頨怠?蝯?, ephemeral=True)
            return

        if not is_customer_staff(interaction.user):
            await interaction.response.send_message("?芣?摰Ｘ??臭誑??閮??, ephemeral=True)
            return

        channel = interaction.channel

        if interaction.guild is not None and isinstance(channel, discord.TextChannel):
            await delete_dispatch_claim_panel_for_order(
                guild=interaction.guild,
                order_channel_id=channel.id,
            )

        await interaction.response.send_message(
            "撌脩Ⅱ隤?瘨??殷??????3 蝘???嚗???瘣曉閮銋?銝雿萄?扎?,
            ephemeral=False
        )

        await asyncio.sleep(3)

        if isinstance(channel, discord.TextChannel):
            await channel.delete(reason=f"Order cancelled by {interaction.user}")

    @discord.ui.button(
        label="?佗?靽?閮",
        style=discord.ButtonStyle.secondary,
        custom_id="confirm_cancel_order_no"
    )
    async def keep_order(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not isinstance(interaction.user, discord.Member):
            await interaction.response.send_message("?⊥?蝣箄?雿?頨怠?蝯?, ephemeral=True)
            return

        if not is_customer_staff(interaction.user):
            await interaction.response.send_message("?芣?摰Ｘ??臭誑????, ephemeral=True)
            return

        await interaction.response.send_message("撌脖????柴?, ephemeral=True)


# ========= ?芸銝鞈? =========

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

# 瘣曉?駁??亙鞈?
# message_id 撠?閰脫晷?株??舐???芯??芰 / ???亙??
# ??閮鞈???摮 bot_data.json嚗ot ??敺??芸?霈??
ORDER_CLAIMS = {}

# 憿批恥? / ?鞈?
# user_id -> {total_spent, order_count, last_order_at, points, platinum_channel_id}
CUSTOMER_REWARDS = {}
configure_reward_storage(CUSTOMER_REWARDS)
configure_audit_service(SELF_SERVICE_ORDER_SELECTIONS, ORDER_CLAIMS, CUSTOMER_REWARDS)

# 閮蝺刻?閮?剁?YYYYMMDD -> ?嗆?敺?瘞渲?
ORDER_COUNTERS = {}

BACKUP_TASK_STARTED = False
STORED_REMINDER_TASK_STARTED = False
VIP_DOWNGRADE_TASK_STARTED = False
STORED_ORDER_REMINDER_DAYS = [3, 7]
VIP_MAINTAIN_MIN_MONTHLY_SPEND = 500

DATA_FILE = Path(__file__).parent / "bot_data.json"  # ?? JSON ?/?瑞宏??
DB_FILE = Path(__file__).parent / "bot.db"
BACKUP_DIR = Path(__file__).parent / "backups"
CLOSED_ORDER_KEEP_DAYS = 0  # 撌脩??株??偶銋???銝??芸??芷
CANCELLED_ORDER_KEEP_DAYS = 60  # ?芣?????60 憭拍????格摮?








async def daily_backup_loop():
    await bot.wait_until_ready()
    while not bot.is_closed():
        try:
            backup_path = run_daily_backup_once()
            if backup_path:
                print(f"bot.db backup checked: {backup_path}")
        except Exception as e:
            print(f"瘥?遢 bot.db 憭望?嚗e}")
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
            item = data.get("item") or "?芰???
            quantity = _to_int(data.get("quantity"), 1) or 1
            amount = _to_int(data.get("amount"), 0) or 0
            order_no = data.get("order_no") or "?芰??
            ticket_channel = guild.get_channel(channel_id)
            ticket_text = ticket_channel.mention if isinstance(ticket_channel, discord.TextChannel) else f"蟡典 ID嚗channel_id}"

            description = (
                f"??蝑??桀歇蝬???**{day} 憭?*嚗?摰Ｘ?蝣箄??臬?閬敺押?瘨??舐窗憿批恥?n\n"
                f"憿批恥嚗f'<@{customer_id}>' if customer_id else '?芰???}\n"
                f"蟡典嚗ticket_text}\n"
                f"閮蝺刻?嚗order_no}\n"
                f"?嚗item} x{quantity}\n"
                f"??嚗format_t_amount(amount) if amount else '?芰???}\n"
                f"摮??嚗data.get('stored_reason') or '?芸‵撖?}\n"
                f"???Ｗ儔嚗data.get('stored_expected_time') or '?芸‵撖?}"
            )
            await send_order_log(
                guild,
                title=f"摮??嚚歇頞? {day} 憭?,
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
            print(f"VIP ?芸???瑼Ｘ憭望?嚗e}")
        await asyncio.sleep(21600)


async def stored_order_reminder_loop():
    await bot.wait_until_ready()
    while not bot.is_closed():
        try:
            await check_stored_order_reminders_once()
        except Exception as e:
            print(f"摮??瑼Ｘ憭望?嚗e}")
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
    皜?????敹??怠?鞈???

    ??閬?嚗?
    - 撌脩???closed嚗偶銋????????∠敞蝛絞閮??啜?
    - 摮 stored嚗偶銋????踹?摮鋡怨炊?芥?
    - ????cancelled/canceled嚗???CANCELLED_ORDER_KEEP_DAYS 憭拙?皜???
    - ?遢瑼???run_daily_backup_once() 靘?BACKUP_KEEP_DAYS 皜???
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

        # closed / stored ?賣????蝝??銝???
        if status in {"closed", "stored"} or data.get("closed"):
            continue

        # ?芣???瘨??
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
            f"撌脫???{len(order_channel_ids_to_remove)} 蝑???"
            f"{CANCELLED_ORDER_KEEP_DAYS} 憭拍????格摮???
        )


# ========= SQLite ?詨捆靽格迤??甇???舀 relational bot.db =========
# ?挾?????寡???JSON blob ??init / save / load??
# ?券?
# 1. 霈?/add_purchase??import_purchases??set_customer_rewards 撖恍?customers 銵具?
# 2. 靽??湔 SQL ?亥岷?冽?雿?customer_id / total_spent / points / completed_orders / last_order_at / level??
# 3. ???敺?2026/06 ??憪炎?伐??踹? 2026/05 ???◤ 4 ???炊????
# 4. ??敺? vip_progress_base_total_spent 閮剔?嗡?蝝舐?瘨祥嚗?銝蝝脣漲敺????????

VIP_DOWNGRADE_FIRST_CHECK_MONTH = "2026-06"  # 蝚砌?甈⊥炎??2026/05 瘨祥嚗?瑼Ｘ 2026/04??










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
    "銝?摰????",
    "???芰/??",
]

PAYMENT_METHOD_OPTIONS = [
    "銵",
    "頧董",
]


class OrderControlSelect(discord.ui.Select):
    def __init__(self):
        options = [
            discord.SelectOption(
                label="瘣曉",
                value="dispatch",
                description="???芸銝?Ｘ蝯阡??桃?嗅‵撖?
            ),
            discord.SelectOption(
                label="??閮",
                value="cancel",
                description="??銝阡??撐銝蟡典"
            ),
        ]

        super().__init__(
            placeholder="摰Ｘ????賊?",
            min_values=1,
            max_values=1,
            options=options,
            custom_id="order_control_select",
            row=0
        )

    async def callback(self, interaction: discord.Interaction):
        if not isinstance(interaction.user, discord.Member):
            await interaction.response.send_message("?⊥?蝣箄?雿?頨怠?蝯?, ephemeral=True)
            return

        if not is_customer_staff(interaction.user):
            await interaction.response.send_message("?芣?摰Ｘ??臭誑??閮??, ephemeral=True)
            return

        if not isinstance(interaction.channel, discord.TextChannel):
            await interaction.response.send_message("???賢?賢銝蟡典?找蝙?具?, ephemeral=True)
            return

        ORDER_CONTROL_SELECTIONS[(interaction.channel.id, interaction.user.id)] = self.values[0]

        await interaction.response.defer()


class SelfServiceOrderCategorySelect(discord.ui.Select):
    def __init__(self, customer_id: int, channel_id: int, selected_category: str | None = None):
        self.customer_id = customer_id
        self.channel_id = channel_id

        options = [
            discord.SelectOption(
                label="?箇???,
                value="basic",
                description="瘝寥??柴陪蝝??摨??銵??璅??撽",
                default=selected_category == "basic"
            ),
            discord.SelectOption(
                label="頞???,
                value="fun",
                description="鞊芸雿?????研?暻潮野瑽?撌望?",
                default=selected_category == "fun"
            ),
            discord.SelectOption(
                label="隞?圾隞??",
                value="farm",
                description="鞈賢迤3x3??蝬誨??憭怠馳",
                default=selected_category == "farm"
            ),
            discord.SelectOption(
                label="鞈賢迤??瘣餃?",
                value="season",
                description="????9?怠蔗?????,
                default=selected_category == "season"
            ),
            discord.SelectOption(
                label="Valorant",
                value="valorant",
                description="?芣??誨??,
                default=selected_category == "valorant"
            ),
        ]

        super().__init__(
            placeholder="隢???桅???,
            min_values=1,
            max_values=1,
            options=options,
            custom_id="self_service_order_category_select",
            row=0
        )

    async def callback(self, interaction: discord.Interaction):
        if not can_operate_self_service_order(interaction.user, self.customer_id):
            await interaction.response.send_message("?芣??撐蟡典??嗆?摰Ｘ??臭誑?豢?閮??, ephemeral=True)
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
            "?豢?閮憿",
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
                    label="隢??豢?閮憿",
                    value="need_category",
                    description="?詨?銝憿敺??ㄐ???圈???
                )
            ]
            disabled = True
            placeholder = "隢??豢?閮憿"
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
            placeholder = "隢???桅???

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
            await interaction.response.send_message("?芣??撐蟡典??嗆?摰Ｘ??臭誑?豢?閮??, ephemeral=True)
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
            data["companion_preference"] = "銝?摰????"
        remember_order_data(self.channel_id, data)
        await log_self_service_proxy_action(
            interaction,
            self.customer_id,
            "?豢?閮?",
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
                    label="隢??豢?閮?",
                    value="need_item",
                    description="?詨?銝?敺??ㄐ????
                )
            ]
            disabled = True
            placeholder = "隢??豢?閮?"
        elif selected_item in SPECIAL_COMPANION_ITEMS:
            if selected_item == "?芣?":
                options = [
                    discord.SelectOption(
                        label="銝?摰???,
                        value="銝?摰???,
                        description="?勗恥?????拐犖??,
                        default=selected_preference in {"銝?摰???, "銝?摰????", None}
                    ),
                    discord.SelectOption(
                        label="????",
                        value="????",
                        description="?曹??桃?嗆?摰犖??,
                        default=selected_preference in {"????", "???芰/??"}
                    ),
                ]
                placeholder = "隢??行?摰???
            else:
                options = [
                    discord.SelectOption(
                        label="銝?摰????",
                        value="銝?摰????",
                        description="?勗恥?????拐犖??,
                        default=selected_preference == "銝?摰????"
                    ),
                    discord.SelectOption(
                        label="???芰/??",
                        value="???芰/??",
                        description="?曹??桃?嗆?摰犖??,
                        default=selected_preference == "???芰/??"
                    ),
                ]
                placeholder = "隢??行?摰????"
            disabled = False
        else:
            options = [
                discord.SelectOption(
                    label="銝?摰????",
                    value="銝?摰????",
                    description="甇日??桐????",
                    default=True
                )
            ]
            disabled = False
            placeholder = "銝?摰????"

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
            await interaction.response.send_message("?芣??撐蟡典??嗆?摰Ｘ??臭誑?豢?閮??, ephemeral=True)
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
            "?豢????賊?",
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
                    label="隢??豢?閮?",
                    value="need_item",
                    description="?詨?銝?敺??ㄐ????
                )
            ]
            disabled = True
            placeholder = "隢??豢?閮?"
        elif selected_item in QUANTITY_SELECT_ITEMS:
            options = [
                discord.SelectOption(
                    label=f"{num} ??,
                    value=str(num),
                    description=f"{num} ??= 蝝?{num} 撠?",
                    default=quantity == num
                )
                for num in QUANTITY_OPTIONS
            ]
            disabled = False
            placeholder = "隢???
        else:
            options = [
                discord.SelectOption(
                    label="1 ??,
                    value="1",
                    description="甇日??格?摰 1 ??,
                    default=True
                )
            ]
            disabled = False
            placeholder = "?賊??箏???1 ??

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
            await interaction.response.send_message("?芣??撐蟡典??嗆?摰Ｘ??臭誑?豢?閮?賊???, ephemeral=True)
            return

        if self.values[0] == "need_item":
            await interaction.response.defer()
            return

        data = SELF_SERVICE_ORDER_SELECTIONS.setdefault(self.channel_id, {})
        selected_item = data.get("item")

        try:
            quantity = int(self.values[0])
        except ValueError:
            await interaction.response.send_message("?賊??豢??啣虜嚗???豢???, ephemeral=True)
            return

        if selected_item not in QUANTITY_SELECT_ITEMS:
            quantity = 1

        if quantity < 1 or quantity > max(QUANTITY_OPTIONS):
            await interaction.response.send_message("?賊?隢??1 ??8 ?柴?, ephemeral=True)
            return

        data["customer_id"] = self.customer_id
        data["quantity"] = quantity
        data.pop("payment_method", None)
        remember_order_data(self.channel_id, data)
        await log_self_service_proxy_action(
            interaction,
            self.customer_id,
            "?豢?閮?賊?",
            f"{quantity} ??,
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
    """摰Ｘ? / 摨 / 蝞∠??∩誨???芸銝??撖怠璈鈭箸隤?""
    if interaction.user.id == customer_id:
        return

    channel_text = interaction.channel.mention if isinstance(interaction.channel, discord.TextChannel) else "?芰???
    fields = [
        ("??鈭箏", interaction.user.mention, True),
        ("???桅“摰?, f"<@{customer_id}>", True),
        ("蟡典", channel_text, False),
        ("??", action, True),
    ]

    if detail:
        fields.append(("?批捆", detail, False))

    try:
        await send_order_log(
            interaction.guild,
            title="?芸銝隞??雿?,
            fields=fields,
            color=discord.Color.teal(),
        )
    except Exception as e:
        print(f"撖怠?芸銝隞??雿隤仃??{e}")


class DispatchCancelClaimButton(discord.ui.Button):
    def __init__(self, disabled: bool = False):
        super().__init__(
            label="???亙",
            style=discord.ButtonStyle.danger,
            custom_id="dispatch_cancel_claim",
            disabled=disabled
        )

    async def callback(self, interaction: discord.Interaction):
        view = self.view

        if not isinstance(view, DispatchClaimView):
            await interaction.response.send_message("?亙?Ｘ??撣賂?隢??唳晷?柴?, ephemeral=True)
            return

        await view.cancel_claim(interaction)




def sync_single_discord_claim_event_to_web(interaction, claim_type: str, action: str) -> None:
    """??Discord ?亙???桐????郊?啁雯蝡?

    action:
    - claim嚗?啣??桀??犖
    - unclaim嚗蝘駁?桀??犖
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
            f"[web-sync] Discord ?亙鈭辣?郊蝬脩?憭望? "
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
            return "?芰?亙"
        return "???亙"

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
            lines.append("?芰?亙嚗? + " ".join(f"<@{user_id}>" for user_id in companion_ids))

        if booster_ids:
            lines.append("???亙嚗? + " ".join(f"<@{user_id}>" for user_id in booster_ids))

        if not lines:
            return None

        return "\n".join(lines)

    async def refresh_panel(self, interaction: discord.Interaction, locked: bool | None = None):
        guild = interaction.guild

        if guild is None:
            await interaction.response.send_message("???賢?賢隡箸??典雿輻??, ephemeral=True)
            return

        if not isinstance(interaction.channel, discord.TextChannel):
            await interaction.response.send_message("???賢?賢瘣曉???駁?雿輻??, ephemeral=True)
            return

        source_channel = guild.get_channel(self.source_channel_id)

        if source_channel is None or not isinstance(source_channel, discord.TextChannel):
            await interaction.response.send_message("?曆??唬?皞巨???, ephemeral=True)
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
                name="?亙???,
                value=(
                    "撌脣??殷??亙?Ｘ撌脤?摰n"
                    f"摮??嚗claim_data.get('stored_reason') or '?芸‵撖?}\n"
                    f"???Ｗ儔嚗claim_data.get('stored_expected_time') or '?芸‵撖?}"
                ),
                inline=False
            )
        elif claim_data.get("locked"):
            new_embed.add_field(
                name="?亙???,
                value="撌脩??殷??亙?Ｘ撌脤?摰?,
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
            await interaction.response.send_message("?⊥?蝣箄?雿?頨怠?蝯?, ephemeral=True)
            return

        if self.locked:
            await interaction.response.send_message("甇文撌脩??殷??亙?Ｘ撌脤?摰?, ephemeral=True)
            return

        required_role_id = self.get_required_role_id(claim_type)
        receiver_label = self.get_receiver_label(claim_type)

        if not has_role(interaction.user, required_role_id):
            await interaction.response.send_message(
                f"雿??receiver_label}????,
                ephemeral=True
            )
            return

        claim_data = self.get_claim_data(interaction.message.id)

        if claim_data.get("locked"):
            await interaction.response.send_message("甇文撌脩??殷??亙?Ｘ撌脤?摰?, ephemeral=True)
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
            print(f"?郊 Discord ?亙?啁雯蝡仃??{e}")

        await send_order_log(
            interaction.guild,
            title=f"{receiver_label}",
            fields=[
                ("?亙鈭?, interaction.user.mention, True),
                ("憿批恥", f"<@{self.customer_id}>", True),
                ("閮", f"{self.category_label}嚚self.item} x{self.quantity}", False),
            ],
            color=discord.Color.green(),
        )

        await self.refresh_panel(interaction)

    async def cancel_claim(self, interaction: discord.Interaction):
        if not isinstance(interaction.user, discord.Member):
            await interaction.response.send_message("?⊥?蝣箄?雿?頨怠?蝯?, ephemeral=True)
            return

        if self.locked:
            await interaction.response.send_message("甇文撌脩??殷??亙?Ｘ撌脤?摰?, ephemeral=True)
            return

        claim_data = self.get_claim_data(interaction.message.id)

        if claim_data.get("locked"):
            await interaction.response.send_message("甇文撌脩??殷??亙?Ｘ撌脤?摰?, ephemeral=True)
            return

        removed = False

        for key in ("companion", "booster"):
            if interaction.user.id in claim_data[key]:
                claim_data[key].remove(interaction.user.id)
                removed = True

        if not removed:
            await interaction.response.send_message("雿????撐?柴?, ephemeral=True)
            return

        remember_claim_data(interaction.message.id, claim_data)
        sync_single_discord_claim_event_to_web(interaction, "booster", "unclaim")
        sync_single_discord_claim_event_to_web(interaction, "companion", "unclaim")


        await send_order_log(
            interaction.guild,
            title="???亙",
            fields=[
                ("??鈭?, interaction.user.mention, True),
                ("憿批恥", f"<@{self.customer_id}>", True),
                ("閮", f"{self.category_label}嚚self.item} x{self.quantity}", False),
            ],
            color=discord.Color.orange(),
        )

        await self.refresh_panel(interaction)

    @discord.ui.button(
        label="?芰?亙",
        style=discord.ButtonStyle.success,
        custom_id="dispatch_claim_companion"
    )
    async def companion_claim(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.claim_order(interaction, "companion")

    @discord.ui.button(
        label="???亙",
        style=discord.ButtonStyle.primary,
        custom_id="dispatch_claim_booster"
    )
    async def booster_claim(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.claim_order(interaction, "booster")


async def delete_dispatch_claim_panel_for_order(guild: discord.Guild, order_channel_id: int):
    """??蟡典??銝雿萄?斗晷?桅?????亙?Ｘ嚗蒂皜靽?鞈???""
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
                print("Bot 甈?銝雲嚗瘜?斗晷?格?桅?踴?)
            except discord.HTTPException as e:
                print(f"?芷瘣曉?亙?Ｘ憭望?嚗e}")

        ORDER_CLAIMS.pop(dispatch_message_id, None)
        delete_claim_row_from_db(message_id=dispatch_message_id)

    if order_channel_id in SELF_SERVICE_ORDER_SELECTIONS:
        SELF_SERVICE_ORDER_SELECTIONS.pop(order_channel_id, None)
        delete_order_row_from_db(order_channel_id)
        save_bot_data()
    elif dispatch_message_id is not None:
        save_bot_data()


async def lock_dispatch_claim_panel(guild: discord.Guild, order_channel_id: int):
    """摰Ｘ?蝯敺???瘣曉?駁?撠????/ ???亙?Ｘ??

    ???????敺抵??桀???潭晷?桅?踴???嚗?
    憒? orders 鋆∟??啁??航? dispatch_message_id嚗??? ORDER_CLAIMS 鋆⊥??撘萇巨???瘣曉閮嚗?
    銝行??曉?晷?桅?踹?券?摰??踹???圈?敺抵??桅?輸??賜匱蝥◤??
    """
    data = SELF_SERVICE_ORDER_SELECTIONS.get(order_channel_id, {})
    dispatch_channel_id = data.get("dispatch_channel_id", DISPATCH_CHANNEL_ID)

    source_channel = guild.get_channel(order_channel_id)

    if source_channel is None or not isinstance(source_channel, discord.TextChannel):
        return

    dispatch_channel = guild.get_channel(dispatch_channel_id)

    if dispatch_channel is None or not isinstance(dispatch_channel, discord.TextChannel):
        return

    # ?芸???orders ?桀?閮??晷?株??荔???鋆????claims 鋆∩?皞巨????瘣曉閮??
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
    item = data.get("item", "?芰???)
    quantity = _to_int(data.get("quantity"), 1) or 1
    payment_method = data.get("payment_method", "?芰???)
    companion_preference = data.get("companion_preference")
    category_label = ORDER_CATEGORY_LABELS.get(category, category or data.get("category_label") or "?芰???)
    customer_mention = f"<@{customer_id}>" if customer_id is not None else "?芰???

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

        # ?交????鋆?蝻箏?甈???
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
            lines.append("?芰?亙嚗? + " ".join(f"<@{user_id}>" for user_id in companion_ids))

        if booster_ids:
            lines.append("???亙嚗? + " ".join(f"<@{user_id}>" for user_id in booster_ids))

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
            name="?亙???,
            value="撌脩??殷??亙?Ｘ撌脤?摰?,
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
        # ?典祕????摰???唳晷?株??航????踹?銋???啗??Ｘ??
        if newest_existing_message_id is not None:
            data["dispatch_message_id"] = newest_existing_message_id
        remember_order_data(order_channel_id, data)
        save_bot_data()



def sync_web_order_status_from_bot(ticket_channel_id, status: str, dispatch_message_id=None, note: str | None = None) -> None:
    """DC bot 閮????游?嚗?甇亦雯蝡?web_orders.status??""
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
            f"[web-sync] 閮???甇亦雯蝡仃??"
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
    """撠??格?閮摮嚗?摰晷?格?桅?蹂?靽?蟡典??""
    data = SELF_SERVICE_ORDER_SELECTIONS.get(order_channel.id, {})
    dispatch_message_id = data.get("dispatch_message_id")
    dispatch_channel_id = data.get("dispatch_channel_id", DISPATCH_CHANNEL_ID)

    if dispatch_message_id is None:
        raise ValueError("?曆??圈撐閮撠??晷?株??荔?隢Ⅱ隤“摰Ｘ?血歇摰?隞狡?孵?銝阡瘣曉??)

    dispatch_channel = guild.get_channel(dispatch_channel_id)

    if dispatch_channel is None or not isinstance(dispatch_channel, discord.TextChannel):
        raise ValueError("?曆??唳晷?桅??隢Ⅱ隤?DISPATCH_CHANNEL_ID ?臬甇?Ⅱ??)

    try:
        message = await dispatch_channel.fetch_message(dispatch_message_id)
    except discord.NotFound as exc:
        raise ValueError("?曆??唳晷?株??荔??航撌脰◤?芷??) from exc
    except discord.Forbidden as exc:
        raise ValueError("Bot 甈?銝雲嚗瘜??晷?株??胯?) from exc
    except discord.HTTPException as exc:
        raise ValueError(f"霈?晷?株??臬仃??{exc}") from exc

    customer_id = data.get("customer_id") or get_order_customer_id_from_channel(order_channel)
    category = data.get("category")
    item = data.get("item", "?芰???)
    quantity = _to_int(data.get("quantity"), 1) or 1
    payment_method = data.get("payment_method", "?芰???)
    companion_preference = data.get("companion_preference")
    category_label = ORDER_CATEGORY_LABELS.get(category, category or data.get("category_label") or "?芰???)
    customer_mention = f"<@{customer_id}>" if customer_id is not None else "?芰???

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
        note="??DC bot 摮?郊??,
    )
    remember_claim_data(dispatch_message_id, claim_data)

    companion_ids = sorted(claim_data.get("companion", set()))
    booster_ids = sorted(claim_data.get("booster", set()))
    lines = []

    if companion_ids:
        lines.append("?芰?亙嚗? + " ".join(f"<@{user_id}>" for user_id in companion_ids))

    if booster_ids:
        lines.append("???亙嚗? + " ".join(f"<@{user_id}>" for user_id in booster_ids))

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
        name="?亙???,
        value=(
            "撌脣??殷??亙?Ｘ撌脤?摰n"
            f"摮??嚗reason}\n"
            f"???Ｗ儔嚗expected_time or '?芸‵撖?}"
        ),
        inline=False
    )

    if note:
        embed.add_field(
            name="摮?酉",
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
    """?Ｗ儔撌脣??桃?閮嚗????祆?桐犖?∴???潭晷?桅?選?銝行???瘣曉閮??""
    data = SELF_SERVICE_ORDER_SELECTIONS.get(order_channel.id, {})
    old_dispatch_message_id = _to_int(data.get("dispatch_message_id"))
    dispatch_channel_id = _to_int(data.get("dispatch_channel_id"), DISPATCH_CHANNEL_ID) or DISPATCH_CHANNEL_ID

    # ?園??撐蟡典???瘣曉閮嚗??銝撘萄??格敺拙?瘣曉?駁?畾???踴?
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
        raise ValueError("?曆??圈撐閮撠??晷?株??荔??⊥??Ｗ儔??)

    dispatch_channel = guild.get_channel(dispatch_channel_id)

    if dispatch_channel is None or not isinstance(dispatch_channel, discord.TextChannel):
        raise ValueError("?曆??唳晷?桅??隢Ⅱ隤?DISPATCH_CHANNEL_ID ?臬甇?Ⅱ??)

    # ?芸?????dispatch_message_id ??claim嚗???閰梧??曉?蟡典隞颱? claim??
    claim_data = ORDER_CLAIMS.get(old_dispatch_message_id) if old_dispatch_message_id else None

    if not claim_data:
        for message_id in old_dispatch_message_ids:
            possible_claim = ORDER_CLAIMS.get(message_id)
            if isinstance(possible_claim, dict):
                claim_data = possible_claim
                break

    if not claim_data:
        raise ValueError("?曆??啣歇靽???株???隢??唳晷?柴?)

    customer_id = claim_data.get("customer_id") or data.get("customer_id") or get_order_customer_id_from_channel(order_channel)
    category_label = claim_data.get("category_label") or ORDER_CATEGORY_LABELS.get(data.get("category"), data.get("category") or "?芰???)
    item = claim_data.get("item") or data.get("item", "?芰???)
    quantity = _to_int(claim_data.get("quantity"), _to_int(data.get("quantity"), 1)) or 1
    payment_method = claim_data.get("payment_method") or data.get("payment_method", "?芰???)
    companion_preference = claim_data.get("companion_preference") or data.get("companion_preference")
    customer_mention = f"<@{customer_id}>" if customer_id is not None else "?芰???

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

    # 摮?賊?鞈?靽??刻??葉?嗥???雿????active??
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
        lines.append("?芰?亙嚗? + " ".join(f"<@{user_id}>" for user_id in companion_ids))

    if booster_ids:
        lines.append("???亙嚗? + " ".join(f"<@{user_id}>" for user_id in booster_ids))

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
        name="?亙???,
        value=f"撌脩 {staff_member.mention} ?Ｗ儔閮嚗?桅?踹歇??澆??唬?蝵柴?,
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

    # ?芷??撘萇巨??????瘣曉閮嚗???格敺拙?畾?銝?????Ｘ??
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

    # ??株??宏?唳??message_id嚗????祇?????亙鈭箏??
    ORDER_CLAIMS[new_message.id] = claim_data
    data["dispatch_message_id"] = new_message.id
    data["dispatch_channel_id"] = dispatch_channel.id

    remember_order_data(order_channel.id, data)
    sync_web_order_status_from_bot(
        ticket_channel_id=order_channel.id,
        status="active",
        dispatch_message_id=data.get("dispatch_message_id"),
        note="??DC bot ?Ｗ儔摮?郊??,
    )
    remember_claim_data(new_message.id, claim_data)
    save_bot_data()


class StoreOrderModal(discord.ui.Modal, title="摮"):
    reason = discord.ui.TextInput(
        label="摮??",
        placeholder="靘?嚗“摰Ｘ?瘜??押蝝???敺暑????,
        required=True,
        max_length=200
    )

    expected_time = discord.ui.TextInput(
        label="???Ｗ儔??",
        placeholder="靘?嚗???20:00??憭押摰?,
        required=False,
        max_length=100
    )

    note = discord.ui.TextInput(
        label="?酉",
        placeholder="?臬‵撖思?甈曄??釣????摰Ｘ??酉",
        style=discord.TextStyle.paragraph,
        required=False,
        max_length=800
    )

    async def on_submit(self, interaction: discord.Interaction):
        if not isinstance(interaction.user, discord.Member):
            await interaction.response.send_message("?⊥?蝣箄?雿?頨怠?蝯?, ephemeral=True)
            return

        if not is_customer_staff(interaction.user):
            await interaction.response.send_message("?芣?摰Ｘ??臭誑摮??, ephemeral=True)
            return

        guild = interaction.guild

        if guild is None:
            await interaction.response.send_message("???賢?賢隡箸??典雿輻??, ephemeral=True)
            return

        if not isinstance(interaction.channel, discord.TextChannel):
            await interaction.response.send_message("???賢?賢銝蟡典?找蝙?具?, ephemeral=True)
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
                title="閮撌脣???,
                fields=[
                    ("蟡典", interaction.channel.mention, True),
                    ("??鈭箏", interaction.user.mention, True),
                    ("摮??", self.reason.value.strip(), False),
                    ("???Ｗ儔", self.expected_time.value.strip() or "?芸‵撖?, True),
                    ("?酉", self.note.value.strip() or "?芸‵撖?, False),
                ],
                color=discord.Color.gold(),
            )
        except ValueError as e:
            await interaction.followup.send(str(e), ephemeral=True)
            return

        await interaction.channel.send(
            f"甇方??桀歇??{interaction.user.mention} 摮?n\n"
            f"摮??嚗self.reason.value.strip()}\n"
            f"???Ｗ儔嚗self.expected_time.value.strip() or '?芸‵撖?}\n"
            f"?酉嚗self.note.value.strip() or '??}",
            allowed_mentions=discord.AllowedMentions(
                users=True,
                roles=False,
                everyone=False
            )
        )

        await interaction.followup.send("撌脣??殷?瘣曉?駁??亙?Ｘ撌脤?摰?, ephemeral=True)



def get_payment_method_info(method: str | None) -> str | None:
    return {
        "頧董": (
            "?銵?撣??陸\n"
            "隞?Ⅳ嚗?13\n"
            "撣唾?嚗?35700021419"
        ),
        "銵": (
            "銵?臭?\n"
            "隞?Ⅳ嚗?96\n"
            "撣唾?嚗?00884222"
        ),
    }.get(str(method or ""))


def build_payment_method_embed(
    *,
    customer_id: int,
    category_label: str,
    item: str,
    quantity: int,
    payment_method: str | None = None,
    companion_preference: str | None = None,
    amount: int | None = None,
    submitted: bool = False,
    dispatch_url: str | None = None,
) -> discord.Embed:
    payment_info = get_payment_method_info(payment_method)
    amount_text = format_t_amount(amount) if amount else "敺恥?‵撖?
    description = (
        f"銝?冽嚗?@{customer_id}>\n\n"
        f"閮憿嚗category_label}\n"
        f"閮?嚗item}\n"
        f"?賊?嚗quantity} ?娉n"
        f"閮蝮賢嚗amount_text}\n"
        f"隞狡?孵?嚗payment_method or '撠?豢?'}\n"
    )

    if submitted and dispatch_url:
        description += "\n??撌脤瘣曉嚗迨隞狡?Ｘ撌脤?摰?隢?????n"
        description += f"瘣曉閮嚗dispatch_url}"
    elif amount and payment_info:
        description += "\n隢??Ⅱ隤蜇?寡?隞狡鞈?嚗??甈暹撘????
    else:
        description += "\n隢??甈暹撘?摰?敺????

    embed = discord.Embed(
        title="隞狡?孵?",
        description=description,
        color=discord.Color.green() if submitted else discord.Color.gold(),
    )

    if companion_preference is not None:
        embed.add_field(name="???賊?", value=companion_preference, inline=False)

    if amount and payment_info:
        embed.add_field(name="隞狡鞈?", value=f"```text\n{payment_info}\n```", inline=False)

    return embed


class OrderAmountModal(discord.ui.Modal, title="憛怠神閮?寞"):
    amount = discord.ui.TextInput(
        label="?祆活閮蝮賢",
        placeholder="靘?嚗?275?T$1,275??50+595",
        required=True,
        max_length=100,
    )

    def __init__(self, customer_id: int, channel_id: int):
        super().__init__()
        self.customer_id = customer_id
        self.channel_id = channel_id

    async def on_submit(self, interaction: discord.Interaction):
        if not isinstance(interaction.user, discord.Member):
            await interaction.response.send_message("?⊥?蝣箄?雿?頨怠?蝯?, ephemeral=True)
            return

        if not is_customer_staff(interaction.user):
            await interaction.response.send_message("?芣?摰Ｘ??臭誑憛怠神閮?寞??, ephemeral=True)
            return

        if interaction.guild is None or not isinstance(interaction.channel, discord.TextChannel):
            await interaction.response.send_message("???賢?賢銝蟡典?找蝙?具?, ephemeral=True)
            return

        parsed_amount = parse_receipt_amount(str(self.amount.value))
        if parsed_amount is None or parsed_amount <= 0:
            await interaction.response.send_message(
                "??甈??⊥?颲刻?嚗?頛詨?航儘霅??詨?嚗?憒?1275?T$1275??275T??,
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
            title="閮?寞撌脩Ⅱ隤?,
            fields=[
                ("憿批恥", f"<@{self.customer_id}>", True),
                ("??", format_t_amount(parsed_amount), True),
                ("憛怠神鈭箏", interaction.user.mention, True),
                ("蟡典", interaction.channel.mention, False),
            ],
            color=discord.Color.gold(),
        )

        category = data.get("category")
        item = data.get("item")
        quantity = _to_int(data.get("quantity"), 1) or 1
        companion_preference = data.get("companion_preference")
        if category is None or item is None:
            await interaction.response.send_message(
                "?曆??啗??株???隢??啗?拐??桅?輸??圈??,
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
            f"撌脣‵撖怨??桅?憿?{format_t_amount(parsed_amount)}\n隢????甈暹撘?,
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
        label="憛怠神",
        style=discord.ButtonStyle.primary,
        custom_id="staff_order_amount_button",
    )
    async def fill_amount(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not isinstance(interaction.user, discord.Member):
            await interaction.response.send_message("?⊥?蝣箄?雿?頨怠?蝯?, ephemeral=True)
            return

        if not is_customer_staff(interaction.user):
            await interaction.response.send_message("?芣?摰Ｘ??臭誑憛怠神閮?寞??, ephemeral=True)
            return

        await interaction.response.send_modal(OrderAmountModal(self.customer_id, self.channel_id))


async def send_staff_amount_panel(
    interaction: discord.Interaction,
    customer_id: int,
    channel_id: int,
) -> None:
    if not isinstance(interaction.channel, discord.TextChannel):
        await interaction.followup.send("?⊥?蝣箄??桀?蟡典?駁???, ephemeral=True)
        return

    data = SELF_SERVICE_ORDER_SELECTIONS.setdefault(channel_id, {})
    panel_message_id = _to_int(data.get("amount_panel_message_id"))
    if panel_message_id is not None:
        await interaction.followup.send("撌脤摰Ｘ?憛怠神閮?寞嚗?銝??????, ephemeral=True)
        return

    embed = discord.Embed(
        title="隢恥?‵撖怨??桅?憿?,
        description=(
            f"銝?冽嚗?@{customer_id}>\n"
            "隢恥?Ⅱ隤甈∟??桃蜇?對????嫘‵撖怒撓?仿?憿n"
            "摰Ｘ????敺????箇隞狡?孵??Ｘ??
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
    await interaction.followup.send("撌脤閮???Ｘ嚗?摰Ｘ?憛怠神?祆活閮蝮賢??, ephemeral=True)


async def finalize_payment_and_dispatch(
    *,
    interaction: discord.Interaction,
    customer_id: int,
    channel_id: int,
    reward_result: str | None = None,
) -> None:
    guild = interaction.guild

    if guild is None:
        await interaction.response.send_message("???賢?賢隡箸??典雿輻??, ephemeral=True)
        return

    if not isinstance(interaction.channel, discord.TextChannel):
        await interaction.response.send_message("?⊥?蝣箄??桀?蟡典?駁???, ephemeral=True)
        return

    data = SELF_SERVICE_ORDER_SELECTIONS.get(channel_id, {})
    category = data.get("category")
    item = data.get("item")
    quantity = _to_int(data.get("quantity"), 1) or 1
    companion_preference = data.get("companion_preference")
    payment_method = data.get("payment_method")
    parsed_amount = _to_int(data.get("amount"), 0) or _to_int(data.get("total_amount"), 0) or 0

    if category is None or item is None:
        await interaction.response.send_message("?曆??啗??株???隢??啗?拐??桅?輸??圈??, ephemeral=True)
        return

    if payment_method is None:
        await interaction.response.send_message("隢??豢?隞狡?孵?嚗????, ephemeral=True)
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
            message = f"?撐?桀歇蝬瘣曉嚗?銝?????n瘣曉閮嚗ttps://discord.com/channels/{guild.id}/{dispatch_channel.id}/{dispatch_message_id}"
        else:
            message = "?撐?桀歇蝬瘣曉嚗?銝??????
        if interaction.response.is_done():
            await interaction.followup.send(message, ephemeral=True)
        else:
            await interaction.response.send_message(message, ephemeral=True)
        return

    if data.get("dispatch_submitting"):
        message = "?撐?格迤?券瘣曉嚗?蝔?嚗?閬?銴???
        if interaction.response.is_done():
            await interaction.followup.send(message, ephemeral=True)
        else:
            await interaction.response.send_message(message, ephemeral=True)
        return

    item_category = ORDER_ITEM_TO_CATEGORY.get(item)

    if item_category != category:
        await interaction.response.send_message(
            "雿??閮憿???桅??桐?銝?湛?隢??啗?拐??桅?輸??圈??,
            ephemeral=True,
        )
        return

    if item in SPECIAL_COMPANION_ITEMS and companion_preference is None:
        await interaction.response.send_message(
            "???株????啗?拐??桅?輸?????芰/??????摰??????,
            ephemeral=True,
        )
        return

    if item not in QUANTITY_SELECT_ITEMS:
        quantity = 1
        data["quantity"] = 1
        remember_order_data(channel_id, data)
    elif quantity < 1 or quantity > max(QUANTITY_OPTIONS):
        await interaction.response.send_message("?賊??豢??啣虜嚗???芸銝?Ｘ??豢???, ephemeral=True)
        return

    if companion_preference is None:
        companion_preference = "銝?摰????"
        data["companion_preference"] = companion_preference
        remember_order_data(channel_id, data)

    dispatch_channel = guild.get_channel(DISPATCH_CHANNEL_ID)

    if dispatch_channel is None or not isinstance(dispatch_channel, discord.TextChannel):
        await interaction.response.send_message(
            "?曆??唳晷?桅??隢Ⅱ隤?DISPATCH_CHANNEL_ID ?臬甇?Ⅱ??,
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
    embed.add_field(name="閮蝮賢", value=format_t_amount(parsed_amount), inline=True)

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
        await interaction.followup.send(f"瘣曉?憭望?嚗e}", ephemeral=True)
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
        "?瘣曉",
        f"{category_label}嚚item} x{quantity}嚚payment_method}嚚format_t_amount(parsed_amount)}",
    )

    await send_order_log(
        guild,
        title="?啗?拐??桀歇瘣曉",
        fields=[
            ("憿批恥", f"<@{customer_id}>", True),
            ("閮憿", category_label, True),
            ("閮?", item, True),
            ("?賊?", f"{quantity} ??, True),
            ("閮蝮賢", format_t_amount(parsed_amount), True),
            ("隞狡?孵?", payment_method, True),
            ("???賊?", companion_preference, True),
            ("?鈭箏", interaction.user.mention, True),
            ("?臬隞??雿?, "?? if interaction.user.id != customer_id else "??, True),
            ("蟡典", interaction.channel.mention, False),
            ("瘣曉閮", dispatch_message.jump_url, False),
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

    response_text = f"撌脩Ⅱ隤??桃蜇??{format_t_amount(parsed_amount)}嚗蒂?瘣曉嚗dispatch_message.jump_url}"
    if reward_result:
        response_text += f"\n\n{reward_result}"
    await interaction.followup.send(response_text, ephemeral=True)

    operation_embed = discord.Embed(
        title="閮??",
        description="隢恥??銝?撘??桅??嚗?銝Ⅱ隤?,
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
    """DC bot ?唳晷?桀?嚗? active 閮撖恍脩雯蝡??澈??""
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
            note="??DC bot 瘣曉?郊??,
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
            placeholder="隢??甈暹撘?,
            min_values=1,
            max_values=1,
            options=options,
            custom_id="payment_method_select",
            row=0
        )

    async def callback(self, interaction: discord.Interaction):
        if not can_operate_self_service_order(interaction.user, self.customer_id):
            await interaction.response.send_message("?芣??撐蟡典??嗆?摰Ｘ??臭誑?豢?隞狡?孵???, ephemeral=True)
            return

        data = SELF_SERVICE_ORDER_SELECTIONS.setdefault(self.channel_id, {})
        data["customer_id"] = self.customer_id
        selected_method = self.values[0]
        data["payment_method"] = selected_method
        remember_order_data(self.channel_id, data)
        await log_self_service_proxy_action(
            interaction,
            self.customer_id,
            "?豢?隞狡?孵?",
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
                    child.label = "撌脤"
                    child.style = discord.ButtonStyle.secondary

    @discord.ui.button(
        label="?",
        style=discord.ButtonStyle.success,
        custom_id="payment_method_submit_button",
        row=1
    )
    async def submit_payment(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not can_operate_self_service_order(interaction.user, self.customer_id):
            await interaction.response.send_message("?芣??撐蟡典??嗆?摰Ｘ??臭誑?隞狡?孵???, ephemeral=True)
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
        label="??閮??",
        style=discord.ButtonStyle.success,
        custom_id="self_service_order_go_payment_button",
        row=4
    )
    async def go_payment(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not can_operate_self_service_order(interaction.user, self.customer_id):
            await interaction.response.send_message("?芣??撐蟡典??嗆?摰Ｘ??臭誑??閮??, ephemeral=True)
            return

        if not isinstance(interaction.channel, discord.TextChannel):
            await interaction.response.send_message("?⊥?蝣箄??桀?蟡典?駁???, ephemeral=True)
            return

        data = SELF_SERVICE_ORDER_SELECTIONS.get(self.channel_id, {})
        category = data.get("category")
        item = data.get("item")
        quantity = _to_int(data.get("quantity"), 1) or 1
        companion_preference = data.get("companion_preference")

        if category is None or item is None:
            await interaction.response.send_message("隢??豢?閮憿???桅??殷???敺??桅?憿?, ephemeral=True)
            return

        item_category = ORDER_ITEM_TO_CATEGORY.get(item)

        if item_category != category:
            await interaction.response.send_message(
                "雿??閮憿???桅??桐?銝?湛?隢??圈??,
                ephemeral=True
            )
            return

        if item in SPECIAL_COMPANION_ITEMS and companion_preference is None:
            await interaction.response.send_message(
                "???株???????芰/??????摰????????敺??桅?憿?,
                ephemeral=True
            )
            return

        if item not in QUANTITY_SELECT_ITEMS:
            quantity = 1
            data["quantity"] = 1
            remember_order_data(self.channel_id, data)
        elif quantity < 1 or quantity > max(QUANTITY_OPTIONS):
            await interaction.response.send_message("隢??圈?迤蝣箇??賊???, ephemeral=True)
            return

        if companion_preference is None:
            companion_preference = "銝?摰????"
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
        button.label = "撌脤嚗?敺恥?‵??
        try:
            await interaction.message.edit(view=self)
        except discord.HTTPException:
            pass

        await log_self_service_proxy_action(
            interaction,
            self.customer_id,
            "??閮??",
            f"{category_label}嚚item} x{quantity}嚚companion_preference}",
        )

class StaffOrderOperationSelect(discord.ui.Select):
    def __init__(self):
        options = [
            discord.SelectOption(
                label="撌脩???,
                value="done",
                description="憛怠神?嗆?銝阡閰???"
            ),
            discord.SelectOption(
                label="摮",
                value="store",
                description="靽?蟡典銝阡?摰晷?格?桅??
            ),
            discord.SelectOption(
                label="?Ｗ儔閮",
                value="resume",
                description="?Ｗ儔撌脣??株??殷????亙?Ｘ"
            ),
            discord.SelectOption(
                label="??閮",
                value="cancel",
                description="??銝阡??撐銝蟡典"
            ),
        ]

        super().__init__(
            placeholder="閮???賊?",
            min_values=1,
            max_values=1,
            options=options,
            custom_id="staff_order_operation_select",
            row=0
        )

    async def callback(self, interaction: discord.Interaction):
        if not isinstance(interaction.user, discord.Member):
            await interaction.response.send_message("?⊥?蝣箄?雿?頨怠?蝯?, ephemeral=True)
            return

        if not is_customer_staff(interaction.user):
            await interaction.response.send_message("?芣?摰Ｘ??臭誑??閮??, ephemeral=True)
            return

        if not isinstance(interaction.channel, discord.TextChannel):
            await interaction.response.send_message("???賢?賢銝蟡典?找蝙?具?, ephemeral=True)
            return

        STAFF_ORDER_OPERATION_SELECTIONS[(interaction.channel.id, interaction.user.id)] = self.values[0]

        await interaction.response.defer()


class StaffOrderOperationView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(StaffOrderOperationSelect())

    @discord.ui.button(
        label="蝣箄?",
        style=discord.ButtonStyle.success,
        custom_id="staff_order_operation_confirm",
        row=1
    )
    async def confirm_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not isinstance(interaction.user, discord.Member):
            await interaction.response.send_message("?⊥?蝣箄?雿?頨怠?蝯?, ephemeral=True)
            return

        if not is_customer_staff(interaction.user):
            await interaction.response.send_message("?芣?摰Ｘ??臭誑??閮??, ephemeral=True)
            return

        if not isinstance(interaction.channel, discord.TextChannel):
            await interaction.response.send_message("???賢?賢銝蟡典?找蝙?具?, ephemeral=True)
            return

        selected = STAFF_ORDER_OPERATION_SELECTIONS.get((interaction.channel.id, interaction.user.id))

        if selected is None:
            await interaction.response.send_message(
                "隢?敺???皜?豢???嚗??Ⅱ隤?,
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
                await interaction.response.send_message("???賢?賢隡箸??典雿輻??, ephemeral=True)
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
                    title="閮撌脫敺?,
                    fields=[
                        ("蟡典", interaction.channel.mention, True),
                        ("??鈭箏", interaction.user.mention, True),
                    ],
                    color=discord.Color.green(),
                )
            except ValueError as e:
                await interaction.followup.send(str(e), ephemeral=True)
                return

            await interaction.channel.send(
                f"甇方??桀歇??{interaction.user.mention} ?Ｗ儔嚗晷?桅??桅?踹歇????,
                allowed_mentions=discord.AllowedMentions(
                    users=True,
                    roles=False,
                    everyone=False
                )
            )
            await interaction.followup.send("撌脫敺抵??柴?, ephemeral=True)
        elif selected == "cancel":
            await interaction.response.send_message(
                "?臬蝣箏?閬?瘨?閮嚗?,
                view=ConfirmCancelOrderView(),
                ephemeral=True
            )
        else:
            await interaction.response.send_message(
                "?豢???啣虜嚗???豢?銝甈～?,
                ephemeral=True
            )


class OrderControlView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(OrderControlSelect())

    @discord.ui.button(
        label="蝣箄?",
        style=discord.ButtonStyle.success,
        custom_id="order_control_confirm",
        row=1
    )
    async def confirm_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not isinstance(interaction.user, discord.Member):
            await interaction.response.send_message("?⊥?蝣箄?雿?頨怠?蝯?, ephemeral=True)
            return

        if not is_customer_staff(interaction.user):
            await interaction.response.send_message("?芣?摰Ｘ??臭誑??閮??, ephemeral=True)
            return

        if not isinstance(interaction.channel, discord.TextChannel):
            await interaction.response.send_message("???賢?賢銝蟡典?找蝙?具?, ephemeral=True)
            return

        selected = ORDER_CONTROL_SELECTIONS.get((interaction.channel.id, interaction.user.id))

        if selected is None:
            await interaction.response.send_message(
                "隢?敺???皜?豢???嚗??Ⅱ隤?,
                ephemeral=True
            )
            return

        ORDER_CONTROL_SELECTIONS.pop((interaction.channel.id, interaction.user.id), None)

        if selected == "cancel":
            await interaction.response.send_message(
                "?臬蝣箏?閬?瘨?閮嚗?,
                view=ConfirmCancelOrderView(),
                ephemeral=True
            )
            return

        if selected != "dispatch":
            await interaction.response.send_message(
                "?豢???啣虜嚗???豢?銝甈～?,
                ephemeral=True
            )
            return

        customer_id = get_order_customer_id_from_channel(interaction.channel)

        if customer_id is None:
            await interaction.response.send_message(
                "?⊥?颲刻???冽嚗?蝣箄??撐蟡典?臭??舐銝?撱箇???,
                ephemeral=True
            )
            return

        customer = interaction.guild.get_member(customer_id) if interaction.guild else None
        customer_mention = customer.mention if customer is not None else f"<@{customer_id}>"

        embed = discord.Embed(
            title="?芸銝",
            description=(
                f"銝?冽嚗customer_mention}\n\n"
                "隢??桃?園???桅??亥?閮?嚗?????敺??桅?憿n"
                "憒??豢?憡??芥?銵?alorant ?芣??alorant 隞??嚗??雿?豢? 1嚚? ?殷?1 ??= 1 撠?嚗? ??= 2 撠?嚗?甇日??具n"
                "憒??豢?憡??芥?銵??摨嚗?憿??豢??臬???芰/??嚗alorant ?芣??舫??摰?銝?摰???
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

# ========= 銝駁??/ 銝?亙 View 閮剖? =========

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


# ========= Bot 鈭辣 =========

@bot.event
async def on_member_join(member: discord.Member):
    role = member.guild.get_role(NEW_MEMBER_ROLE_ID)

    if role is not None:
        try:
            await member.add_roles(role, reason="?唳??∪??亥?策鈭澈??")
        except discord.Forbidden:
            print("Bot 甈?銝雲嚗瘜策鈭?頨怠?蝯?蝣箄? Bot 頨怠?蝯?蝵桅??潸?蝯衣?頨怠?蝯?)
        except discord.HTTPException as e:
            print(f"蝯虫??唳??∟澈??憭望?嚗e}")
    else:
        print("?曆??唳?頨怠?蝯?隢Ⅱ隤?NEW_MEMBER_ROLE_ID ?臬甇?Ⅱ")

    channel = member.guild.get_channel(WELCOME_CHANNEL_ID)

    if channel is None or not isinstance(channel, discord.TextChannel):
        print("?曆??唳迭餈??隢Ⅱ隤?WELCOME_CHANNEL_ID ?臬甇?Ⅱ")
        return

    embed = discord.Embed(
        description=(
            f"**甇∟? {member.mention} 靘擳虜憡?!**\n\n"
            f"甇∟????!\n"
            f"?遙雿?憿?臭誑??璈鈭粹?蟡典?舐窗摰Ｘ?甇?"
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
    # 憒??亥蟡典鋡急???歹?銋?閰行?隢犖?急?頨怠?蝯?
    await remove_recruit_applicant_role(channel.guild, channel)



@bot.event
async def on_voice_state_update(
    member: discord.Member,
    before: discord.VoiceState,
    after: discord.VoiceState
):
    guild = member.guild

    # ?ａ?璈鈭箏遣蝡??芰 / VIP / ?砍隤?踹?嚗????鈭箏停?芸??芷
    # ?ㄐ?支??摮?ID嚗???駁??迂?斗嚗??Bot ??敺?閮??遣蝡??冽??踴?
    if before.channel is not None:
        is_temp_play_voice_room = (
            before.channel.id in TEMP_PLAY_VOICE_CHANNEL_IDS
            or (
                before.channel.category_id == PLAY_VOICE_CATEGORY_ID
                and before.channel.name.startswith("???)
                and before.channel.name.endswith("??拚??)
                and before.channel.name != PLAY_VOICE_CREATE_CHANNEL_NAME
            )
        )

        is_temp_vip_voice_room = (
            before.channel.id in TEMP_VIP_VOICE_CHANNEL_IDS
            or (
                before.channel.category_id == PLAY_VOICE_CATEGORY_ID
                and before.channel.name.startswith("????)
                and before.channel.name.endswith("??????)
                and before.channel.name != VIP_VOICE_CREATE_CHANNEL_NAME
            )
        )

        is_temp_public_voice_room = (
            before.channel.id in TEMP_PUBLIC_VOICE_CHANNEL_IDS
            or (
                before.channel.category_id == PLAY_VOICE_CATEGORY_ID
                and before.channel.name.startswith("??")
                and before.channel.name.endswith("??望??)
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
                print("Bot 甈?銝雲嚗瘜?日?抵??單??)
            except discord.HTTPException as e:
                print(f"?芷?芰隤?踹仃??{e}")
            return

        if is_temp_vip_voice_room and len(before.channel.members) == 0:
            TEMP_VIP_VOICE_CHANNEL_IDS.discard(before.channel.id)
            await delete_voice_control_panel(guild, before.channel.id)
            try:
                await before.channel.delete(reason="Temporary VIP voice room is empty")
            except discord.NotFound:
                pass
            except discord.Forbidden:
                print("Bot 甈?銝雲嚗瘜??VIP 隤?踴?)
            except discord.HTTPException as e:
                print(f"?芷 VIP 隤?踹仃??{e}")
            return

        if is_temp_public_voice_room and len(before.channel.members) == 0:
            TEMP_PUBLIC_VOICE_CHANNEL_IDS.discard(before.channel.id)
            await delete_voice_control_panel(guild, before.channel.id)
            try:
                await before.channel.delete(reason="Temporary public voice room is empty")
            except discord.NotFound:
                pass
            except discord.Forbidden:
                print("Bot 甈?銝雲嚗瘜?文?梯??單??)
            except discord.HTTPException as e:
                print(f"?芷?砍隤?踹仃??{e}")
            return

    # 瘝???啗??喲?停銝??
    if after.channel is None:
        return

    category = guild.get_channel(PLAY_VOICE_CATEGORY_ID)

    if category is None or not isinstance(category, discord.CategoryChannel):
        return

    # ???遣蝡蝔桀????喲??
    play_lobby_channel = await get_or_create_play_voice_lobby(guild)
    vip_lobby_channel = await get_or_create_vip_voice_lobby(guild)
    public_lobby_channel = await get_or_create_public_voice_lobby(guild)

    # ?脣銝?祇?拙???撱箇?銝?祇?抵??單
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
            print("Bot 甈?銝雲嚗瘜遣蝡?蝘餃??芰隤?踴?)
        except discord.HTTPException as e:
            print(f"撱箇??宏??抵??單憭望?嚗e}")

        return

    # ?脣 VIP ?亙嚗遣蝡?VIP 撠隤??
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
            print("Bot 甈?銝雲嚗瘜遣蝡?蝘餃? VIP 隤?踴?)
        except discord.HTTPException as e:
            print(f"撱箇??宏??VIP 隤?踹仃??{e}")

        return

    # ?脣?砍?亙嚗遣蝡??犖?航? / ?臬??亦??砍隤??
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
            print("Bot 甈?銝雲嚗瘜遣蝡?蝘餃??砍隤?踴?)
        except discord.HTTPException as e:
            print(f"撱箇??宏??梯??單憭望?嚗e}")

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
            print("Bot 甈?銝雲嚗瘜遣蝡??/ VIP / ?砍隤?亙??)
        except discord.HTTPException as e:
            print(f"撱箇??芰 / VIP / ?砍隤?亙憭望?嚗e}")

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


# ========= Slash ?誘 =========



# ========= 暺?賜?蝟餌絞 =========

# ?賜? slash ?誘撌脫??cogs/lottery_commands.py


# ?暺 / 鋆 slash ?誘撌脫??cogs/reward_commands.py


VIP_LEVEL_NAME_TO_INDEX = {level["name"]: index for index, level in enumerate(MEMBER_LEVELS)}
VIP_LEVEL_CHOICES = [
    app_commands.Choice(name=level["name"], value=level["name"])
    for level in MEMBER_LEVELS
]


@bot.tree.command(
    name="set_customer_level",
    description="蝞∠??∠?交?摰“摰?VIP 蝑?",
    guild=discord.Object(id=GUILD_ID)
)
@app_commands.describe(
    customer="閬矽??VIP 蝑??“摰?,
    level="閬?摰??蝑?",
    reason="隤踵??嚗銝‵"
)
@app_commands.choices(level=VIP_LEVEL_CHOICES)
async def set_customer_level(
    interaction: discord.Interaction,
    customer: discord.Member,
    level: app_commands.Choice[str],
    reason: str | None = None,
):
    if not isinstance(interaction.user, discord.Member):
        await interaction.response.send_message("?⊥?蝣箄?雿?頨怠?蝯?, ephemeral=True)
        return

    if not is_manager_or_admin(interaction.user):
        await interaction.response.send_message("?芣?蝞∠??⊥?摨?臭誑?湔隤踵憿批恥 VIP 蝑???, ephemeral=True)
        return

    target_index = VIP_LEVEL_NAME_TO_INDEX.get(level.value)
    if target_index is None:
        await interaction.response.send_message("?蝑?銝??剁?隢??圈??, ephemeral=True)
        return

    data = get_customer_reward_data(customer.id)
    old_level = get_effective_member_level(data)

    data["vip_level_index"] = target_index
    # ?湔隤踵 / ??敺??賢??桀?蝑???0 ???蝝舐?銝?蝝脣漲??
    data["vip_progress_base_total_spent"] = int(data.get("total_spent", 0) or 0)
    data["last_level_manual_fixed_at"] = get_taipei_now_iso()
    data["last_level_manual_fixed_by"] = interaction.user.id
    data["last_level_manual_fixed_reason"] = (reason or "").strip()

    CUSTOMER_REWARDS[customer.id] = data
    benefit_notices = await ensure_reward_member_benefits(interaction.guild, customer, data) if interaction.guild else []
    save_bot_data()

    embed = build_member_info_embed(customer, data, show_points=True)
    embed.title = "憿批恥 VIP 蝑?撌脰矽??
    embed.add_field(name="??蝝?, value=old_level["name"], inline=True)
    embed.add_field(name="?啁?蝝?, value=get_effective_member_level(data)["name"], inline=True)
    if reason:
        embed.add_field(name="隤踵??", value=reason, inline=False)
    if benefit_notices:
        embed.add_field(name="?甈???", value="\n".join(benefit_notices), inline=False)

    await send_order_log(
        interaction.guild,
        title="憿批恥 VIP 蝑?撌脫??矽??,
        fields=[
            ("憿批恥", customer.mention, True),
            ("??鈭箏", interaction.user.mention, True),
            ("??蝝?, old_level["name"], True),
            ("?啁?蝝?, get_effective_member_level(data)["name"], True),
            ("??", reason or "?芸‵撖?, False),
        ],
        color=discord.Color.orange(),
    )

    await interaction.response.send_message(embed=embed, ephemeral=True)



def _require_customer_staff_or_manager(interaction: discord.Interaction) -> bool:
    return (
        isinstance(interaction.user, discord.Member)
        and (is_customer_staff(interaction.user) or has_role(interaction.user, MANAGER_ROLE_ID) or interaction.user.guild_permissions.administrator)
    )


# ??蝯梯? / VIP ???亥岷 slash ?誘撌脫??cogs/stats_commands.py


@bot.tree.command(
    name="order_search",
    description="摰Ｘ???閮嚗?刻??桃楊?“摰?ID???格???閰?,
    guild=discord.Object(id=GUILD_ID)
)
@app_commands.describe(
    keyword="?摮?閮蝺刻??“摰＠D???桀?蝔梧??臭?憛?,
    status="???active / stored / closed / cancelled嚗銝‵",
    limit="?憭＊蝷箏嗾蝑??身 10嚗?憭?20"
)
async def order_search(
    interaction: discord.Interaction,
    keyword: str | None = None,
    status: str | None = None,
    limit: int = 10,
):
    if not _require_customer_staff_or_manager(interaction):
        await interaction.response.send_message("?芣?摰Ｘ????瑟?蝞∠??∪隞交?撠??柴?, ephemeral=True)
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
        title="閮??蝯?",
        color=discord.Color.blurple(),
        timestamp=get_taipei_now(),
    )

    if not shown:
        embed.description = "瘝??曉蝚血?璇辣???柴?
    else:
        lines = []
        for channel_id, data in shown:
            order_no = data.get("order_no") or "?芰??
            customer_id = data.get("customer_id")
            customer_text = f"<@{customer_id}>" if customer_id else "?芰???
            item = data.get("item") or "?芰???
            quantity = _to_int(data.get("quantity"), 1) or 1
            amount = _to_int(data.get("amount"), 0) or 0
            order_status = str(data.get("status") or ("closed" if data.get("closed") else "active"))
            ticket_text = f"<#{channel_id}>" if int(channel_id) > 0 else f"甇瑕鞈? {channel_id}"
            lines.append(
                f"**{order_no}**嚚order_status}\n"
                f"憿批恥嚗customer_text}嚚??殷?{item} x{quantity}嚚?憿?{format_t_amount(amount) if amount else '?芰???}\n"
                f"蟡典嚗ticket_text}"
            )
        embed.description = "\n\n".join(lines)
        if len(matches) > limit:
            embed.set_footer(text=f"?芷＊蝷箏? {limit} 蝑??望??{len(matches)} 蝑?)

    await interaction.response.send_message(embed=embed, ephemeral=True)


# ========= 閮靽格迤 / ?芷?誘 =========

ORDER_MAINTENANCE_BACKUP_PREFIX = "manual_order_maintenance"


def adjust_customer_totals_for_order(customer_id: int | None, amount_delta: int, order_delta: int) -> dict | None:
    """??靽桀??甇?customers 閮擃???amount_delta ?舀迤?航???""
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
            notices.extend([f"<@{customer_id}>嚗notice}" for notice in benefit_notices])
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
        print(f"撱箇???靽桀?遢憭望?嚗e}")
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
        embed.add_field(name="閮蝺刻?", value=str(data.get("order_no") or data.get("receipt_id") or "?芰??), inline=True)
        embed.add_field(name="憿批恥", value=f"<@{data.get('customer_id')}>" if data.get("customer_id") else "?芰???, inline=True)
        embed.add_field(name="?", value=str(data.get("item") or "?芰???), inline=True)
        embed.add_field(name="??", value=format_t_amount(get_order_amount_for_maintenance(data)), inline=True)
        embed.add_field(name="???, value=str(data.get("status") or ("closed" if data.get("closed") else "active")), inline=True)
    return embed




def sync_web_order_cancelled_from_bot(ticket_channel_id, dispatch_message_id=None, note: str | None = None) -> None:
    """DC bot ?芷/??閮敺??雯蝡??桃???甇交? cancelled??""
    try:
        from shared.web_order_sync import update_web_order_status_by_ticket_channel

        ok = update_web_order_status_by_ticket_channel(
            ticket_channel_id=ticket_channel_id,
            status="cancelled",
            dispatch_message_id=dispatch_message_id,
            note=note or "??DC bot ?芷/??閮?郊??,
        )
        print(
            f"[web-sync] cancel order "
            f"ticket_channel_id={ticket_channel_id} "
            f"dispatch_message_id={dispatch_message_id} ok={ok}"
        )
    except Exception as exc:
        print(
            f"[web-sync] ?芷/??閮?郊蝬脩?憭望? "
            f"ticket_channel_id={ticket_channel_id}: {exc}"
        )




def sync_web_order_deleted_from_bot(ticket_channel_id, dispatch_message_id=None, note: str | None = None) -> None:
    """DC bot ?芷閮敺?敺雯蝡??澈?湔?芷撠? web_order??""
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
            f"[web-sync] ?芷蝬脩?閮憭望? "
            f"ticket_channel_id={ticket_channel_id} "
            f"dispatch_message_id={dispatch_message_id}: {exc}"
        )


@bot.tree.command(
    name="delete_order",
    description="摰Ｘ??芷閮鞈?嚗?渲??桃楊??蟡典 ID",
    guild=discord.Object(id=GUILD_ID)
)
@app_commands.describe(
    order="閮蝺刻??巨??ID嚗?憒?MO20260521003 ??1506712687458123917",
    adjust_customer="?亥??桀歇蝯嚗?血?甇交???∠敞蝛?摰??格嚗?閮剜",
    delete_dispatch_panel="?臬?岫?芷瘣曉?駁??亙?Ｘ嚗?閮剜"
)
async def delete_order(
    interaction: discord.Interaction,
    order: str,
    adjust_customer: bool = True,
    delete_dispatch_panel: bool = True,
):
    if not _require_customer_staff_or_manager(interaction):
        await interaction.response.send_message("?芣?摰Ｘ????瑟?蝞∠??∪隞亙?方??柴?, ephemeral=True)
        return

    channel_id, data = find_order_by_identifier(order)
    if channel_id is None or data is None:
        await interaction.response.send_message("?曆??圈?閮嚗?蝣箄?閮蝺刻??巨??ID ?臬甇?Ⅱ??, ephemeral=True)
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
            note="??/delete_order ?芷蝬脩?閮??,
        )

        SELF_SERVICE_ORDER_SELECTIONS.pop(channel_id, None)
        delete_order_row_from_db(channel_id)
        save_bot_data()
        benefit_notices = await asyncio.wait_for(
            refresh_customer_benefits_after_manual_fix(interaction.guild, [customer_id]),
            timeout=15,
        )

        description = (
            f"撌脣?方??株??n"
            f"蟡典 ID嚗{channel_id}`\n"
            f"??郊嚗'撌脫?? if adjust_customer and is_order_closed_for_rewards(old_data) else '?芣??/ 銝??}\n"
            f"瘣曉?Ｘ嚗'撌脣?? if dispatch_deleted else '?芸?斗??曆???}\n"
            f"?遢嚗{backup_path or '撱箇?憭望??鞈?摨?}`"
        )
        if benefit_notices:
            description += "\n" + "\n".join(benefit_notices[:5])

        embed = build_order_maintenance_result_embed("?芷閮摰?", description, old_data)
        await interaction.followup.send(embed=embed, ephemeral=True, allowed_mentions=discord.AllowedMentions(users=True, roles=False, everyone=False))

        await send_order_log(
            interaction.guild,
            title="???芷閮",
            description=description,
            fields=[
                ("??鈭箏", interaction.user.mention, True),
                ("閮", str(old_data.get("order_no") or order), True),
                ("憿批恥", f"<@{customer_id}>" if customer_id else "?芰???, True),
            ],
            color=discord.Color.red(),
        )
    except Exception as e:
        error_text = f"/delete_order ?瑁?憭望?嚗type(e).__name__}: {e}"
        try:
            await interaction.followup.send(
                f"?芷閮憭望?嚗{type(e).__name__}: {e}`\n隢 VPS ?亦? journalctl ??摰 Traceback??,
                ephemeral=True,
            )
        except discord.HTTPException:
            pass
        await send_order_log(
            interaction.guild,
            title="?芷閮憭望?",
            description=error_text,
            fields=[
                ("??鈭箏", interaction.user.mention, True),
                ("頛詨閮", str(order), True),
                ("蟡典 ID", str(channel_id), True),
            ],
            color=discord.Color.red(),
        )
        raise


@bot.tree.command(
    name="fix_order_amount",
    description="摰Ｘ?靽格迤閮??嚗?郊隤踵?蝝舐?",
    guild=discord.Object(id=GUILD_ID)
)
@app_commands.describe(
    order="閮蝺刻??巨??ID",
    amount="?啁???嚗?質撓?交摮?靘? 1275",
    adjust_customer="?亥??桀歇蝯嚗?血?甇亥矽?湔??∠敞蝛??身??
)
async def fix_order_amount(
    interaction: discord.Interaction,
    order: str,
    amount: int,
    adjust_customer: bool = True,
):
    if not _require_customer_staff_or_manager(interaction):
        await interaction.response.send_message("?芣?摰Ｘ????瑟?蝞∠??∪隞乩耨甇???桅?憿?, ephemeral=True)
        return

    if amount < 0:
        await interaction.response.send_message("??銝撠 0??, ephemeral=True)
        return

    channel_id, data = find_order_by_identifier(order)
    if channel_id is None or data is None:
        await interaction.response.send_message("?曆??圈?閮嚗?蝣箄?閮蝺刻??巨??ID ?臬甇?Ⅱ??, ephemeral=True)
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
    data["manual_fix_note"] = f"????{old_amount} 靽格迤??{amount}"
    SELF_SERVICE_ORDER_SELECTIONS[channel_id] = data

    if adjust_customer and is_order_closed_for_rewards(data) and delta != 0:
        adjust_customer_totals_for_order(customer_id, delta, 0)

    remember_order_data(channel_id, data)
    save_bot_data()
    benefit_notices = await refresh_customer_benefits_after_manual_fix(interaction.guild, [customer_id])

    description = (
        f"撌脖耨甇???桅?憿n"
        f"蟡典 ID嚗{channel_id}`\n"
        f"??憿?{format_t_amount(old_amount)}\n"
        f"?圈?憿?{format_t_amount(int(amount))}\n"
        f"撌桅?嚗format_t_amount(delta)}\n"
        f"??郊嚗'撌脣?甇? if adjust_customer and is_order_closed_for_rewards(data) else '?芸?甇?/ 銝??}\n"
        f"?遢嚗{backup_path or '撱箇?憭望??鞈?摨?}`"
    )
    if benefit_notices:
        description += "\n" + "\n".join(benefit_notices[:5])

    embed = build_order_maintenance_result_embed("靽格迤閮??摰?", description, data)
    await interaction.followup.send(embed=embed, ephemeral=True, allowed_mentions=discord.AllowedMentions(users=True, roles=False, everyone=False))

    await send_order_log(
        interaction.guild,
        title="??靽格迤閮??",
        description=description,
        fields=[
            ("??鈭箏", interaction.user.mention, True),
            ("閮", str(data.get("order_no") or order), True),
            ("憿批恥", f"<@{customer_id}>" if customer_id else "?芰???, True),
        ],
        color=discord.Color.orange(),
    )


@bot.tree.command(
    name="fix_order_customer",
    description="摰Ｘ?靽格迤閮憿批恥嚗?郊?祉宏?蝝舐?",
    guild=discord.Object(id=GUILD_ID)
)
@app_commands.describe(
    order="閮蝺刻??巨??ID",
    customer="甇?Ⅱ?“摰?,
    adjust_customer="?亥??桀歇蝯嚗?行??蝝舐?敺?憿批恥?砍?圈“摰ｇ??身??
)
async def fix_order_customer(
    interaction: discord.Interaction,
    order: str,
    customer: discord.Member,
    adjust_customer: bool = True,
):
    if not _require_customer_staff_or_manager(interaction):
        await interaction.response.send_message("?芣?摰Ｘ????瑟?蝞∠??∪隞乩耨甇???桅“摰Ｕ?, ephemeral=True)
        return

    channel_id, data = find_order_by_identifier(order)
    if channel_id is None or data is None:
        await interaction.response.send_message("?曆??圈?閮嚗?蝣箄?閮蝺刻??巨??ID ?臬甇?Ⅱ??, ephemeral=True)
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
    data["manual_fix_note"] = f"憿批恥??{old_customer_id or '?芰???} 靽格迤??{new_customer_id}"
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
        f"撌脖耨甇???桅“摰Ｕn"
        f"蟡典 ID嚗{channel_id}`\n"
        f"?“摰ｇ?{f'<@{old_customer_id}>' if old_customer_id else '?芰???}\n"
        f"?圈“摰ｇ?{customer.mention}\n"
        f"??嚗format_t_amount(amount)}\n"
        f"??郊嚗'撌脫蝘? if adjust_customer and closed and old_customer_id != new_customer_id else '?芣蝘?/ 銝??}\n"
        f"?遢嚗{backup_path or '撱箇?憭望??鞈?摨?}`"
    )
    if benefit_notices:
        description += "\n" + "\n".join(benefit_notices[:5])

    embed = build_order_maintenance_result_embed("靽格迤閮憿批恥摰?", description, data)
    await interaction.followup.send(embed=embed, ephemeral=True, allowed_mentions=discord.AllowedMentions(users=True, roles=False, everyone=False))

    await send_order_log(
        interaction.guild,
        title="??靽格迤閮憿批恥",
        description=description,
        fields=[
            ("??鈭箏", interaction.user.mention, True),
            ("閮", str(data.get("order_no") or order), True),
            ("?圈“摰?, customer.mention, True),
        ],
        color=discord.Color.orange(),
    )



@bot.tree.command(
    name="resend_dispatch",
    description="??潮?摰巨???瘣曉?Ｘ"
)
@app_commands.describe(
    order_channel_id="蟡典?駁? ID嚗?憒?1506962556928131112"
)
async def resend_dispatch(interaction: discord.Interaction, order_channel_id: str):
    """?撱箇??舀?雿?瘣曉?Ｘ?n\n    ?冽瘣曉?駁?閮鋡怠?扎??仃?laims ??????臭??n    ???文?銝蟡典??claims嚗銝???DispatchClaimView嚗蒂?閮 ID 撖怠?鞈??n    """
    if not isinstance(interaction.user, discord.Member):
        await interaction.response.send_message("?⊥?蝣箄?雿?頨怠?蝯?, ephemeral=True)
        return

    if not (is_customer_staff(interaction.user) or is_manager_or_admin(interaction.user)):
        await interaction.response.send_message("?芣?摰Ｘ????瑟?蝞∠??∪隞仿??唳晷?柴?, ephemeral=True)
        return

    guild = interaction.guild
    if guild is None:
        await interaction.response.send_message("???賢?賢隡箸??典雿輻??, ephemeral=True)
        return

    try:
        source_channel_id = int(str(order_channel_id).strip())
    except ValueError:
        await interaction.response.send_message("蟡典 ID ?澆??航炊嚗?頛詨蝝摮?, ephemeral=True)
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
        await interaction.followup.send("?曆??圈巨????隢Ⅱ隤巨??ID ?臬甇?Ⅱ??, ephemeral=True)
        return

    dispatch_channel = guild.get_channel(DISPATCH_CHANNEL_ID)
    if dispatch_channel is None:
        try:
            fetched_dispatch = await guild.fetch_channel(DISPATCH_CHANNEL_ID)
            dispatch_channel = fetched_dispatch if isinstance(fetched_dispatch, discord.TextChannel) else None
        except (discord.NotFound, discord.Forbidden, discord.HTTPException):
            dispatch_channel = None

    if dispatch_channel is None or not isinstance(dispatch_channel, discord.TextChannel):
        await interaction.followup.send("?曆??唳晷?桅??隢Ⅱ隤?DISPATCH_CHANNEL_ID ?臬甇?Ⅱ??, ephemeral=True)
        return

    data = SELF_SERVICE_ORDER_SELECTIONS.get(source_channel_id)
    if not isinstance(data, dict):
        await interaction.followup.send("?曆??圈撐蟡典???株????⊥??瘣曉??, ephemeral=True)
        return

    # 皜???蟡典??claims嚗??撘萇巨????啣??晷?株??胯?
    for message_id, claim_data in list(ORDER_CLAIMS.items()):
        if _to_int(claim_data.get("source_channel_id")) == source_channel_id:
            ORDER_CLAIMS.pop(message_id, None)
            delete_claim_row_from_db(message_id=_to_int(message_id), source_channel_id=source_channel_id)

    old_dispatch_message_id = _to_int(data.get("dispatch_message_id"))
    if old_dispatch_message_id is not None:
        delete_claim_row_from_db(message_id=old_dispatch_message_id)

    customer_id = _to_int(data.get("customer_id")) or get_order_customer_id_from_channel(source_channel)
    category = data.get("category")
    category_label = ORDER_CATEGORY_LABELS.get(category, data.get("category_label") or category or "?芰???)
    item = str(data.get("item") or "?芰???)
    quantity = _to_int(data.get("quantity"), 1) or 1
    payment_method = str(data.get("payment_method") or "?芰???)
    companion_preference = data.get("companion_preference") or "銝?摰????"
    customer_mention = f"<@{customer_id}>" if customer_id is not None else "?芰???

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
        name="?瘣曉",
        value=f"??{interaction.user.mention} 雿輻 `/resend_dispatch` ??潮?,
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
        title="??潮晷?桅??,
        fields=[
            ("??鈭箏", interaction.user.mention, True),
            ("憿批恥", customer_mention, True),
            ("?", f"{item} x{quantity}", True),
            ("蟡典", source_channel.mention, False),
            ("?唳晷?株???, dispatch_message.jump_url, False),
        ],
        color=discord.Color.orange(),
    )

    await interaction.followup.send(
        f"撌脤??啁???瘣曉閮嚗dispatch_message.jump_url}",
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
        parts.append("??嚗? + "??.join(boosters))

    if companions:
        parts.append("?芰嚗? + "??.join(companions))

    if not parts:
        return "撠?犖?亙"

    return "\n".join(parts)


def _web_sync_embed_without_receiver_fields(embed):
    blocked_names = {
        "?桀??亙",
        "?桀??亙鈭?,
        "?亙???,
        "?亙鈭箏",
        "???亙",
        "?芰?亙",
        "撌脫鈭箏",
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
            embed = discord.Embed(title="瘣曉閮", color=discord.Color.blue())

        embed = _web_sync_embed_without_receiver_fields(embed)
        embed.add_field(
            name="?桀??亙",
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
        print(f"??蝬脩??郊鈭辣憭望? event_id={event_id}嚗exc}")


async def web_sync_event_worker() -> None:
    await bot.wait_until_ready()

    while not bot.is_closed():
        try:
            events = _web_sync_fetch_pending_events(limit=10)

            for event in events:
                await process_one_web_sync_event(event)

        except Exception as exc:
            print(f"[web-sync] ????典仃??{exc}")

        await asyncio.sleep(5)


def ensure_web_sync_event_worker_started() -> None:
    global WEB_SYNC_EVENT_TASK

    if WEB_SYNC_EVENT_TASK is not None and not WEB_SYNC_EVENT_TASK.done():
        return

    WEB_SYNC_EVENT_TASK = bot.loop.create_task(web_sync_event_worker())
    print("[web-sync] ??郊鈭辣???典歇??")


# ========= 鞈?摨怠摨瑟炎?交?隞?=========

# /audit_data 撌脫??cogs/audit_commands.py


# ========= 摮蝞∠??Ｘ =========

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
        raise ValueError("?曆??圈?摮嚗?賢歇鋡急敺押?瘨?蝯??)

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
    item = data.get("item", "?芰???)
    quantity = _to_int(data.get("quantity"), 1) or 1
    payment_method = data.get("payment_method", "?芰???)
    companion_preference = data.get("companion_preference")
    category_label = ORDER_CATEGORY_LABELS.get(category, category or data.get("category_label") or "?芰???)
    customer_mention = f"<@{customer_id}>" if customer_id is not None else "?芰???

    claim_data = ORDER_CLAIMS.get(dispatch_message_id, {})
    companion_ids = sorted(claim_data.get("companion", set())) if isinstance(claim_data, dict) else []
    booster_ids = sorted(claim_data.get("booster", set())) if isinstance(claim_data, dict) else []
    receiver_lines = []
    if companion_ids:
        receiver_lines.append("?芰?亙嚗? + " ".join(f"<@{user_id}>" for user_id in companion_ids))
    if booster_ids:
        receiver_lines.append("???亙嚗? + " ".join(f"<@{user_id}>" for user_id in booster_ids))

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
        name="?亙???,
        value=(
            "撌脣??殷??亙?Ｘ撌脤?摰n"
            f"摮??嚗reason}\n"
            f"???Ｗ儔嚗expected_time or '?芸‵撖?}"
        ),
        inline=False,
    )
    if note:
        embed.add_field(name="摮?酉", value=note[:1024], inline=False)

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


class StoredOrderNoteModal(discord.ui.Modal, title="靽格摮?酉"):
    reason = discord.ui.TextInput(
        label="摮??",
        placeholder="靘?嚗“摰Ｘ蝝?敺暑?????,
        required=True,
        max_length=200,
    )
    expected_time = discord.ui.TextInput(
        label="???Ｗ儔??",
        placeholder="靘?嚗???20:00??憭押摰?,
        required=False,
        max_length=100,
    )
    note = discord.ui.TextInput(
        label="?酉",
        placeholder="?臬‵撖思?甈曄??釣????摰Ｘ??酉",
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
            await interaction.response.send_message("?芣?摰Ｘ????瑟?蝞∠??∪隞乩耨?孵??柴?, ephemeral=True)
            return
        if interaction.guild is None or not isinstance(interaction.user, discord.Member):
            await interaction.response.send_message("???賢?賢隡箸??典雿輻??, ephemeral=True)
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
            title="靽格摮?酉",
            fields=[
                ("蟡典 ID", str(self.order_channel_id), True),
                ("??鈭箏", interaction.user.mention, True),
                ("摮??", self.reason.value.strip(), False),
                ("???Ｗ儔", self.expected_time.value.strip() or "?芸‵撖?, True),
                ("?酉", self.note.value.strip() or "?芸‵撖?, False),
            ],
            color=discord.Color.gold(),
        )
        await interaction.followup.send("撌脫?啣??桀?閮颯?, ephemeral=True)


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
            options = [discord.SelectOption(label="?桀?瘝?摮", value="none", description="瘝??舐恣??摮")]
            disabled = True
        else:
            disabled = False

        super().__init__(
            placeholder="?豢?閬恣??摮",
            min_values=1,
            max_values=1,
            options=options,
            custom_id="stored_order_select",
            disabled=disabled,
            row=0,
        )

    async def callback(self, interaction: discord.Interaction):
        if not _require_customer_staff_or_manager(interaction):
            await interaction.response.send_message("?芣?摰Ｘ????瑟?蝞∠??∪隞亦恣???柴?, ephemeral=True)
            return
        if self.values[0] == "none":
            await interaction.response.defer()
            return

        view = self.view
        if not isinstance(view, StoredOrderManageView):
            await interaction.response.send_message("摮?Ｘ??撣賂?隢??唬蝙??/stored_orders??, ephemeral=True)
            return

        view.selected_channel_id = int(self.values[0])
        view.refresh_items()
        embed = view.build_embed(interaction.guild)
        await interaction.response.edit_message(embed=embed, view=view)


class StoredOrderCancelConfirmView(discord.ui.View):
    def __init__(self, order_channel_id: int):
        super().__init__(timeout=60)
        self.order_channel_id = order_channel_id

    @discord.ui.button(label="蝣箄???摮", style=discord.ButtonStyle.danger)
    async def confirm_cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not _require_customer_staff_or_manager(interaction):
            await interaction.response.send_message("?芣?摰Ｘ????瑟?蝞∠??∪隞亙?瘨??柴?, ephemeral=True)
            return
        if interaction.guild is None:
            await interaction.response.send_message("???賢?賢隡箸??典雿輻??, ephemeral=True)
            return

        channel = interaction.guild.get_channel(self.order_channel_id)
        await interaction.response.defer(ephemeral=True)

        await delete_dispatch_claim_panel_for_order(interaction.guild, self.order_channel_id)

        if isinstance(channel, discord.TextChannel):
            try:
                await channel.send(
                    f"甇文??桀歇??{interaction.user.mention} ??嚗巨?????3 蝘?????,
                    allowed_mentions=discord.AllowedMentions(users=True, roles=False, everyone=False),
                )
                await asyncio.sleep(3)
                await channel.delete(reason=f"Stored order cancelled by {interaction.user}")
            except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                pass

        await send_order_log(
            interaction.guild,
            title="摮撌脣?瘨?,
            fields=[
                ("蟡典 ID", str(self.order_channel_id), True),
                ("??鈭箏", interaction.user.mention, True),
            ],
            color=discord.Color.red(),
        )
        await interaction.followup.send("撌脣?瘨??殷?銝血?閰血?斤巨???瘣曉?Ｘ??, ephemeral=True)

    @discord.ui.button(label="靽?摮", style=discord.ButtonStyle.secondary)
    async def keep_stored(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(content="撌脖????柴?, view=None)


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
        super().__init__(label="?Ｗ儔閮", style=discord.ButtonStyle.success, custom_id="stored_order_resume_button", row=1)

    async def callback(self, interaction: discord.Interaction):
        if not _require_customer_staff_or_manager(interaction):
            await interaction.response.send_message("?芣?摰Ｘ????瑟?蝞∠??∪隞交敺拙??柴?, ephemeral=True)
            return
        view = self.view
        if not isinstance(view, StoredOrderManageView) or view.selected_channel_id is None:
            await interaction.response.send_message("隢??豢?閬敺拍?摮??, ephemeral=True)
            return
        if interaction.guild is None or not isinstance(interaction.user, discord.Member):
            await interaction.response.send_message("???賢?賢隡箸??典雿輻??, ephemeral=True)
            return
        order_channel = interaction.guild.get_channel(view.selected_channel_id)
        if not isinstance(order_channel, discord.TextChannel):
            await interaction.response.send_message("?曆??圈?摮?巨????⊥??Ｗ儔??, ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)
        try:
            await resume_stored_order(interaction.guild, order_channel, interaction.user)
        except ValueError as e:
            await interaction.followup.send(str(e), ephemeral=True)
            return

        await order_channel.send(
            f"甇方??桀歇??{interaction.user.mention} ?Ｗ儔嚗晷?桅??桅?踹歇????,
            allowed_mentions=discord.AllowedMentions(users=True, roles=False, everyone=False),
        )
        await send_order_log(
            interaction.guild,
            title="摮撌脫敺?,
            fields=[("蟡典", order_channel.mention, True), ("??鈭箏", interaction.user.mention, True)],
            color=discord.Color.green(),
        )
        await interaction.followup.send("撌脫敺拙??柴?, ephemeral=True)


class StoredOrderEditNoteButton(discord.ui.Button):
    def __init__(self):
        super().__init__(label="靽格?酉", style=discord.ButtonStyle.primary, custom_id="stored_order_edit_note_button", row=1)

    async def callback(self, interaction: discord.Interaction):
        if not _require_customer_staff_or_manager(interaction):
            await interaction.response.send_message("?芣?摰Ｘ????瑟?蝞∠??∪隞乩耨?孵??柴?, ephemeral=True)
            return
        view = self.view
        if not isinstance(view, StoredOrderManageView) or view.selected_channel_id is None:
            await interaction.response.send_message("隢??豢?閬耨?寧?摮??, ephemeral=True)
            return
        await interaction.response.send_modal(StoredOrderNoteModal(view.selected_channel_id, view))


class StoredOrderCancelButton(discord.ui.Button):
    def __init__(self):
        super().__init__(label="??摮", style=discord.ButtonStyle.danger, custom_id="stored_order_cancel_button", row=1)

    async def callback(self, interaction: discord.Interaction):
        if not _require_customer_staff_or_manager(interaction):
            await interaction.response.send_message("?芣?摰Ｘ????瑟?蝞∠??∪隞亙?瘨??柴?, ephemeral=True)
            return
        view = self.view
        if not isinstance(view, StoredOrderManageView) or view.selected_channel_id is None:
            await interaction.response.send_message("隢??豢?閬?瘨?摮??, ephemeral=True)
            return
        await interaction.response.send_message(
            "蝣箏?閬?瘨?摮?????岫?芷瘣曉?Ｘ?巨???銝????亙歇蝯??嗚?,
            view=StoredOrderCancelConfirmView(view.selected_channel_id),
            ephemeral=True,
        )


class StoredOrderRefreshButton(discord.ui.Button):
    def __init__(self):
        super().__init__(label="??渡?", style=discord.ButtonStyle.secondary, custom_id="stored_order_refresh_button", row=1)

    async def callback(self, interaction: discord.Interaction):
        if not _require_customer_staff_or_manager(interaction):
            await interaction.response.send_message("?芣?摰Ｘ????瑟?蝞∠??∪隞亦恣???柴?, ephemeral=True)
            return
        view = self.view
        if not isinstance(view, StoredOrderManageView):
            await interaction.response.send_message("摮?Ｘ??撣賂?隢??唬蝙??/stored_orders??, ephemeral=True)
            return
        await view.refresh_message(interaction)


@bot.tree.command(
    name="stored_orders",
    description="摰Ｘ??亦??恣???????,
    guild=discord.Object(id=GUILD_ID)
)
@app_commands.describe(limit="?憭＊蝷箏嗾蝑??殷??身 25嚗?憭?25")
async def stored_orders(interaction: discord.Interaction, limit: int = 25):
    if not _require_customer_staff_or_manager(interaction):
        await interaction.response.send_message("?芣?摰Ｘ????瑟?蝞∠??∪隞交???柴?, ephemeral=True)
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
    description="摰Ｘ???瑼Ｘ?臬????3/7 憭拍?摮??",
    guild=discord.Object(id=GUILD_ID)
)
async def check_stored_orders(interaction: discord.Interaction):
    if not _require_customer_staff_or_manager(interaction):
        await interaction.response.send_message("?芣?摰Ｘ????瑟?蝞∠??∪隞交炎?亙??格???, ephemeral=True)
        return

    await interaction.response.defer(ephemeral=True)
    await check_stored_order_reminders_once(interaction.guild)
    await interaction.followup.send("撌脫炎?亙??格????交??暹?摮??唳??其犖?亥???, ephemeral=True)


# 憿批恥?酉 slash ?誘撌脫??cogs/customer_commands.py


@bot.tree.command(
    name="delete_dispatch_panel",
    description="?芷瘣曉?駁?銝剖歇??閮??桅??,
    guild=discord.Object(id=GUILD_ID)
)
@app_commands.describe(
    message_id="閬?斤?瘣曉閮 ID",
    channel="瘣曉閮??券??銝‵?蝙?函???
)
async def delete_dispatch_panel(
    interaction: discord.Interaction,
    message_id: str,
    channel: discord.TextChannel | None = None,
):
    if not isinstance(interaction.user, discord.Member):
        await interaction.response.send_message("?⊥?蝣箄?雿?頨怠?蝯?, ephemeral=True)
        return

    if not is_customer_staff(interaction.user) and not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message("?芣?摰Ｘ??恣??臭誑?芷瘣曉?Ｘ??, ephemeral=True)
        return

    target_channel = channel or interaction.channel

    if not isinstance(target_channel, discord.TextChannel):
        await interaction.response.send_message("隢???駁?雿輻嚗???瘣曉閮??券??, ephemeral=True)
        return

    try:
        target_message_id = int(message_id.strip())
    except ValueError:
        await interaction.response.send_message("閮 ID ?澆??航炊嚗?鞎潛??詨?閮 ID??, ephemeral=True)
        return

    try:
        message = await target_channel.fetch_message(target_message_id)
    except discord.NotFound:
        await interaction.response.send_message("?曆??圈?瘣曉閮嚗?賢歇蝬◤?芷鈭?, ephemeral=True)
        return
    except discord.Forbidden:
        await interaction.response.send_message("Bot 甈?銝雲嚗瘜??府?駁?閮??, ephemeral=True)
        return
    except discord.HTTPException as e:
        await interaction.response.send_message(f"霈?晷?株??臬仃??{e}", ephemeral=True)
        return

    try:
        await message.delete()
    except discord.Forbidden:
        await interaction.response.send_message("Bot 甈?銝雲嚗瘜?方府瘣曉閮??, ephemeral=True)
        return
    except discord.HTTPException as e:
        await interaction.response.send_message(f"?芷瘣曉閮憭望?嚗e}", ephemeral=True)
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
        f"撌脣?斗晷?桅?選?銝行????格摮????航??殷?{removed_order_links} 蝑?,
        ephemeral=True
    )

    await send_order_log(
        interaction.guild,
        "?芷瘣曉?Ｘ",
        (
            f"??鈭箏嚗interaction.user.mention}\n"
            f"瘣曉?駁?嚗target_channel.mention}\n"
            f"閮 ID嚗target_message_id}\n"
            f"?閮嚗removed_order_links} 蝑?
        ),
        color=discord.Color.red()
    )

bot.run(TOKEN)

def _sync_dispatch_claims_to_web_from_bot(dispatch_message_id, claim_data, guild):
    """Discord 瘣曉閮??????亙敺??郊撖怠?蝬脩?鞈?摨怒?""
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
        print(f"[web-sync] Discord ?亙?郊蝬脩?憭望? dispatch_message_id={dispatch_message_id}: {exc}")


