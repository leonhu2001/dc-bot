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
    upsert_vip_voice_room,
    get_vip_voice_room_by_owner,
    get_vip_voice_room_by_channel,
    list_vip_voice_rooms,
    delete_vip_voice_room_record,
    add_hidden_vip_user,
    remove_hidden_vip_user,
    list_hidden_vip_users,
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
    correct_customer_reward_amount,
    sync_reward_counted_order_amount,
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

from services.smart_dispatch import (
    create_smart_dispatch_plan,
    ensure_smart_dispatch_tables,
    get_smart_dispatch_plan,
    set_specified_dm_results,
)

from services.web_sync.event_store import (
    claim_pending_events as _web_sync_fetch_pending_events,
    fetch_order_created_retry_events as _web_order_created_fetch_retry_events,
    get_assignments as _web_sync_get_assignments,
    load_order_created_bundle as _web_order_created_load_bundle,
    mark_event_done as _web_sync_mark_event_done,
    mark_event_failed as _web_sync_mark_event_failed,
    mark_order_created_processing as _web_order_created_mark_processing,
    update_order_created_links as _web_order_created_update_links,
)
from services.web_sync.presentation import (
    build_order_created_details as _web_order_created_details,
    build_receiver_text as _web_sync_build_receiver_text,
)
from services.web_sync.discord_helpers import (
    embed_without_receiver_fields as _web_sync_embed_without_receiver_fields,
    find_ticket as _web_order_created_find_ticket,
    get_channel as _web_order_created_get_channel,
    get_member as _web_order_created_get_member,
    has_footer as _web_order_created_has_footer,
    normalize_dispatch_embed_field_order as _normalize_dispatch_embed_field_order,
)
from services.acceptance.runtime import (
    configure_acceptance_runtime,
    _member_role_id_texts,
    _member_display_name,
    _ticket_overwrite_has_values,
    grant_order_ticket_access,
    revoke_order_ticket_access,
    sync_acceptance_ticket_access_from_state,
    _acceptance_staff_display_text,
    _apply_acceptance_state_to_claim_data,
    refresh_acceptance_dispatch_from_web_order,
    repair_pending_acceptance_dispatch_panels_once,
    process_acceptance_sync_events_once,
    acceptance_sync_event_worker,
    send_acceptance_payment_panel_if_ready,
    restore_acceptance_payment_panel_for_order,
    repair_pending_acceptance_payment_panels_once,
    repair_pending_acceptance_ticket_access_once,
    _build_receiver_text_from_claim_data,
)
from services.web_sync.runtime import (
    configure_web_sync_runtime,
    _web_dashboard_db_path_for_bot,
    _web_order_created_ensure_ticket,
    _web_order_created_find_dispatch_message,
    _web_order_created_ensure_dispatch,
    _web_order_created_seed_state,
    _web_cs_order_id_from_channel,
    _web_cs_set_status,
    _web_cs_ensure_review_panel,
    WebsiteOrderCsConfirmView,
    WebsitePendingCancelConfirmView,
    _r13_seed_website_order_into_self_service,
    _r13_ensure_website_unified_panels,
    _process_web_order_created_event,
)
from services.order_runtime import (
    configure_order_runtime,
    OrderControlSelect,
    SelfServiceOrderCategorySelect,
    SelfServiceOrderItemSelect,
    SelfServiceOrderDetailSelect,
    _get_order_rule_by_item_label,
    normalize_self_service_staff_count,
    _self_service_quantity_meta,
    get_self_service_quantity_limit,
    get_self_service_quantity_unit,
    get_self_service_quantity_options,
    SelfServiceOrderQuantitySelect,
    log_self_service_proxy_action,
    DispatchCancelClaimButton,
    sync_single_discord_claim_event_to_web,
    _get_pending_order_point_benefit_info,
    precheck_order_point_benefit_for_payment,
    redeem_order_point_benefit_on_payment,
    _order_requires_credentials,
    _credential_user_for_id,
    _credential_display_name,
    _resolve_credential_owner,
    revoke_order_credential_messages,
    ensure_order_credential_request,
    OrderCredentialModal,
    OrderCredentialEntryView,
    finalize_accepted_pending_payment,
    maybe_handle_prepay_acceptance_claim,
    maybe_handle_prepay_acceptance_unclaim,
    DispatchClaimView,
    delete_dispatch_claim_panel_for_order,
    lock_dispatch_claim_panel,
    sync_web_order_status_from_bot,
    store_dispatch_claim_panel,
    resume_stored_order,
    StoreOrderModal,
    finalize_payment_and_dispatch,
    PaymentMethodSelect,
    PaymentMethodView,
)
from services.self_service_runtime import (
    configure_self_service_runtime,
    _format_plain_amount,
    _extract_discord_ids_from_text,
    _get_rule_from_self_service_data,
    _is_specify_preference,
    _role_key_for_member,
    _resolve_specified_roles_for_price,
    _defer_and_refresh_self_service_panel,
    SelfServicePlayerCountModal,
    _price_int,
    _price_rate,
    _price_snapshot,
    add_self_service_financial_breakdown_fields,
    create_waiting_acceptance_order_from_self_service,
    _format_percent_value,
    _parse_discount_percent_text,
    _parse_cash_amount_text,
    _resolve_manual_discount_rate_percent,
    _resolve_self_service_discount_rate,
    calculate_manual_price_adjustment,
    apply_manual_price_adjustment_to_order_data,
    _quote_preview_lines_for_self_service,
    add_self_service_quote_preview,
    build_self_service_panel_embed,
    _truncate_select_text,
    get_specified_staff_entries_for_rule,
    _acknowledge_component_interaction,
    _edit_component_message,
    SelfServiceSpecifiedStaffDropdown,
    SelfServiceSpecifiedStaffPageButton,
    SelfServiceSpecifiedStaffClearButton,
    SelfServiceSpecifiedStaffDoneButton,
    _format_point_hours,
    get_order_point_item,
    get_customer_point_balance_for_order,
    is_order_point_benefit_allowed_for_rule,
    _adapt_order_point_benefit_for_rule,
    get_selected_order_point_benefit,
    calculate_self_service_financials,
    apply_self_service_financials_to_order_data,
    SelfServicePointBenefitSelect,
    SelfServicePointBenefitView,
    SelfServiceSpecifiedStaffDropdownView,
    is_self_service_staff_price_required,
    get_self_service_staff_price,
    SelfServiceStaffPriceModal,
    SelfServiceStaffDiscountCouponModal,
    SelfServiceSubmitNoteModal,
    SelfServiceOrderView,
    _reorder_order_value,
    _reorder_json_dict,
    build_reorder_self_service_draft,
    _reorder_message_has_component,
    _find_reorder_panel_message,
    ensure_reorder_ticket_panels,
    create_reorder_ticket_from_closed_order,
)

from services.support_calls import (
    ensure_support_call_tables,
    close_support_calls_for_ticket,
)

from services.web_support_chat import ensure_web_support_tables

from services.orders import (
    _to_int,
    configure_order_helpers,
    ORDER_CATEGORY_LABELS,
    ORDER_ITEMS_BY_CATEGORY,
    ORDER_ITEM_TO_CATEGORY,
    ORDER_ITEM_GROUPS_BY_CATEGORY,
    SELF_SERVICE_ACTIVE_CATEGORIES,
    get_order_item_details_for_group,
    get_order_item_group_label,
    get_order_item_detail_label,
    get_order_item_detail_for_selection,
    get_self_service_quantity_meta,
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
from services.order_discounts import (
    allocate_store_absorbed_fixed_discount,
)

from services.game_roles import GAME_ROLES

from views.review import (
    configure_review_views,
    ReviewButtonView,
    configure_reorder_ticket_creator,
    configure_worker_tip_callbacks,
    get_pending_worker_tip_confirmations,
    build_post_close_status_embed,
    WorkerTipPaymentConfirmView,
)

from views.staff_profiles import (
    ensure_staff_profile_tables,
    find_profile_card_image_url,
    upsert_staff_profile,
    get_staff_profile,
    get_staff_profile_panel_rows,
    save_staff_profile_panel_message,
    build_staff_profile_embed,
    list_customer_favorites,
    build_customer_favorites_embed,
    CustomerFavoritesView,
    PublicStaffProfileBrowseView,
    StaffProfilePanelView,
    refresh_staff_profile_panels_for_order,
    configure_staff_profile_order_ticket_creator,
)

from views.support import (
    configure_support_views,
    RecruitControlView,
    ComplaintPanelView,
    ComplaintResolveView,
    FeedbackPanelView,
)

from views.support_calls import (
    configure_support_call_views,
    SupportCallButton,
    SupportCallActionView,
    refresh_existing_order_ticket_support_buttons,
    support_call_sla_loop,
)

from views.smart_dispatch import (
    prepare_initial_smart_dispatch,
    send_initial_smart_dispatch_alert,
    send_specified_staff_dispatch_dms,
    smart_dispatch_escalation_loop,
)
from views.dispatch_presence import (
    dispatch_presence_channel_loop,
    dispatch_support_presence_channel_loop,
)

from views.web_support_bridge import (
    WebSupportActionView,
    configure_web_support_bridge,
    handle_web_support_thread_message,
    web_support_bridge_loop,
)

from core.vip_levels import (
    BASE_MEMBER_LEVELS,
    SILVER_MEMBER_ROLE_ID as DEFAULT_SILVER_MEMBER_ROLE_ID,
    VIP_ROLE_IDS,
    VIP_ROLE_TIERS,
    get_vip_discount_pay_rate,
)
from views.voice import (
    configure_voice_helpers,
    set_hidden_vip_user_ids,
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
    refresh_vip_voice_control_panel_if_needed,
    VoiceRoomControlView,
    sync_voice_control_panel_state_from_channel,
    grant_play_voice_room_chat_access,
    revoke_play_voice_room_chat_access,
    sync_vip_whitelist_permissions,
)

from views.panels import (
    build_main_panel_embed,
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
PLAY_VOICE_LOBBY_CATEGORY_ID = 1508550586696597604
VIP_VOICE_LOBBY_CATEGORY_ID = 1508550977169526784

# 陪玩語音入口頻道名稱
PLAY_VOICE_CREATE_CHANNEL_NAME = "➕┃點我創建陪玩頻道"
PLAY_VOICE_CREATE_CHANNEL_ID = 1508550586696597604
OLD_PLAY_VOICE_CREATE_CHANNEL_NAMES = ["🎮┃陪玩點我創建頻道"]

# VIP 語音入口頻道名稱
VIP_VOICE_CREATE_CHANNEL_NAME = "➕┃點我創建VIP頻道"
VIP_VOICE_CREATE_CHANNEL_ID = 1508550977169526784
OLD_VIP_VOICE_CREATE_CHANNEL_NAMES = ["👑┃𝙑𝙄𝙋專用點我創建頻道"]

# 公共語音入口頻道名稱
PUBLIC_VOICE_CREATE_CHANNEL_NAME = "➕┃點我創建公共頻道"

# VIP / 會員制度設定
# 單一來源在 core/vip_levels.py，這裡只轉成 bot 既有邏輯需要的格式。
VIP_MEMBER_ROLE_TIERS = [dict(level) for level in VIP_ROLE_TIERS]
MEMBER_LEVELS = [dict(level) for level in BASE_MEMBER_LEVELS]
SILVER_MEMBER_ROLE_ID = DEFAULT_SILVER_MEMBER_ROLE_ID

# VIP 語音入口可見 / 可進入身分組 ID
VIP_VOICE_LOBBY_ROLE_ID = DEFAULT_SILVER_MEMBER_ROLE_ID
VIP_VOICE_LOBBY_ROLE_IDS = list(VIP_ROLE_IDS)

# 不公開 VIP 身分組、但語音系統仍視為 VIP 的指定會員。
# 實際可管理白名單存於 bot.db；此清單只保留給環境設定的固定例外。
HIDDEN_VIP_USER_IDS = []

# 身分組 ID
CUSTOMER_ROLE_ID = 1482084782031638548
EXAMINER_ROLE_ID = 1482084782031638548  # 已轉移：原考官權限改由客服身分組持有
MANAGER_ROLE_ID = 1482084782031638548  # 已轉移：原店長權限改由客服身分組持有
RECRUIT_APPLICANT_ROLE_ID = 1498829171042943057  # 入職票口開啟期間身分組

REWARD_POINT_DIVISOR = 100

# 訂單日誌 / 備份設定
ORDER_LOG_CATEGORY_ID = 1483895536938651809
ORDER_LOG_CHANNEL_NAME = "🤖┃機器人日誌"
LOTTERY_ANNOUNCE_CHANNEL_ID = 1482079302739693739
BACKUP_KEEP_DAYS = 30
ORDER_ID_PREFIX = "MO"
CREDENTIAL_OWNER_USER_ID = 0  # 0 = 自動使用 Discord Bot 應用程式擁有者

# 接單身分組 ID
# 多身分組版：單一 ID 保留給舊邏輯相容，實際權限判斷使用 *_ROLE_IDS。
COMPANION_RECEIVER_ROLE_IDS = [1500751059239440575,1482080315798192210]  # 陪玩接單
BOOSTER_RECEIVER_ROLE_IDS = [1500234130871550004,1500234170943934544,1500751039060643990]      # 打手接單
COMPANION_RECEIVER_ROLE_ID = COMPANION_RECEIVER_ROLE_IDS[0]
BOOSTER_RECEIVER_ROLE_ID = BOOSTER_RECEIVER_ROLE_IDS[0]

# 遊戲身分組彙整給語音權限使用；是否能接單仍由訂單規則決定。
# Delta Force 的頂護 / 女護 / 男護同時也是既有打手接單身分組，因此這裡先去重。
GAME_VOICE_ROLE_IDS = list(dict.fromkeys(
    int(role.role_id)
    for role in GAME_ROLES
))

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

# 網站真人客服通知頻道；預設沿用客訴/客服接收頻道，可由 config.json 覆蓋。
WEB_SUPPORT_CHANNEL_ID = COMPLAINT_RECEIVE_CHANNEL_ID

# 派單頻道 ID
DISPATCH_CHANNEL_ID = 1483868763446186036

# 接單大廳在線人數顯示頻道；0 代表停用。
DISPATCH_ONLINE_CHANNEL_ID = 1483183532330455040

# 客服 / 總管在線狀態顯示頻道；0 代表停用。
DISPATCH_SUPPORT_ONLINE_CHANNEL_ID = 1497622678138519572

# 服務大廳主 Panel 訊息 ID；0 代表不自動校正既有 Panel。
MAIN_SERVICE_PANEL_MESSAGE_ID = 1537533276884045856

# 評價頻道 ID
REVIEW_CHANNEL_ID = 1482998033091268691

# 歡迎頻道 ID
WELCOME_CHANNEL_ID = 1482080953353375752

# 新成員自動給予身分組 ID
NEW_MEMBER_ROLE_ID = 1483872591457550494

# 陪玩語音入口 / 陪玩語音房可見與可進入身分組 ID
# 目前只開放：陪玩接單、打手接單、客服
PLAY_VOICE_ALLOWED_ROLE_IDS = list(dict.fromkeys([
    1500751059239440575,
    1482080315798192210,
    1500234130871550004,
    1500234170943934544,
    1500751039060643990,
    *GAME_VOICE_ROLE_IDS,
    1482084782031638548,
    1507204925766242425,
]))

# 語音房按「隱藏」後，仍可看見房間的身分組 ID
VOICE_ROOM_HIDDEN_VISIBLE_ROLE_IDS = list(dict.fromkeys([
    1500751059239440575,
    1482080315798192210,
    1500234130871550004,
    1500234170943934544,
    1500751039060643990,
    *GAME_VOICE_ROLE_IDS,
    1482084782031638548,
    1507204925766242425,
]))


# 可看見創建後陪玩 / VIP 語音房，但不可連接的身分組 ID
VOICE_VIEW_ONLY_ROLE_IDS = [
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
ORDER_LOG_CATEGORY_ID = _config_int("ORDER_LOG_CATEGORY_ID", ORDER_LOG_CATEGORY_ID)

# 頻道
LOTTERY_ANNOUNCE_CHANNEL_ID = _config_int("LOTTERY_ANNOUNCE_CHANNEL_ID", LOTTERY_ANNOUNCE_CHANNEL_ID)
RECEIPT_CHANNEL_ID = _config_int("RECEIPT_CHANNEL_ID", RECEIPT_CHANNEL_ID)
EXAM_NOTICE_CHANNEL_ID = _config_int("EXAM_NOTICE_CHANNEL_ID", EXAM_NOTICE_CHANNEL_ID)
COMPLAINT_PANEL_CHANNEL_ID = _config_int("COMPLAINT_PANEL_CHANNEL_ID", COMPLAINT_PANEL_CHANNEL_ID)
FEEDBACK_PANEL_CHANNEL_ID = _config_int("FEEDBACK_PANEL_CHANNEL_ID", FEEDBACK_PANEL_CHANNEL_ID)
COMPLAINT_RECEIVE_CHANNEL_ID = _config_int("COMPLAINT_RECEIVE_CHANNEL_ID", COMPLAINT_RECEIVE_CHANNEL_ID)
WEB_SUPPORT_CHANNEL_ID = _config_int("WEB_SUPPORT_CHANNEL_ID", COMPLAINT_RECEIVE_CHANNEL_ID)
DISPATCH_CHANNEL_ID = _config_int("DISPATCH_CHANNEL_ID", DISPATCH_CHANNEL_ID)
DISPATCH_ONLINE_CHANNEL_ID = _config_int(
    "DISPATCH_ONLINE_CHANNEL_ID",
    DISPATCH_ONLINE_CHANNEL_ID,
)
DISPATCH_SUPPORT_ONLINE_CHANNEL_ID = _config_int(
    "DISPATCH_SUPPORT_ONLINE_CHANNEL_ID",
    DISPATCH_SUPPORT_ONLINE_CHANNEL_ID,
)
MAIN_SERVICE_PANEL_MESSAGE_ID = _config_int(
    "MAIN_SERVICE_PANEL_MESSAGE_ID",
    MAIN_SERVICE_PANEL_MESSAGE_ID,
)
REVIEW_CHANNEL_ID = _config_int("REVIEW_CHANNEL_ID", REVIEW_CHANNEL_ID)
WELCOME_CHANNEL_ID = _config_int("WELCOME_CHANNEL_ID", WELCOME_CHANNEL_ID)
CREDENTIAL_OWNER_USER_ID = _config_int("CREDENTIAL_OWNER_USER_ID", CREDENTIAL_OWNER_USER_ID)

# 身分組
VIP_VOICE_LOBBY_ROLE_ID = _config_int("VIP_VOICE_LOBBY_ROLE_ID", VIP_VOICE_LOBBY_ROLE_ID)
CUSTOMER_ROLE_ID = _config_int("CUSTOMER_ROLE_ID", CUSTOMER_ROLE_ID)
EXAMINER_ROLE_ID = _config_int("EXAMINER_ROLE_ID", CUSTOMER_ROLE_ID)
MANAGER_ROLE_ID = _config_int("MANAGER_ROLE_ID", CUSTOMER_ROLE_ID)

# 考官 / 店長身分組已移除，權限統一轉移給客服身分組。
EXAMINER_ROLE_ID = CUSTOMER_ROLE_ID
MANAGER_ROLE_ID = CUSTOMER_ROLE_ID
RECRUIT_APPLICANT_ROLE_ID = _config_int("RECRUIT_APPLICANT_ROLE_ID", RECRUIT_APPLICANT_ROLE_ID)
SILVER_MEMBER_ROLE_ID = _config_int("SILVER_MEMBER_ROLE_ID", SILVER_MEMBER_ROLE_ID)
COMPANION_RECEIVER_ROLE_IDS = _config_int_list("COMPANION_RECEIVER_ROLE_IDS", COMPANION_RECEIVER_ROLE_IDS)
BOOSTER_RECEIVER_ROLE_IDS = _config_int_list("BOOSTER_RECEIVER_ROLE_IDS", BOOSTER_RECEIVER_ROLE_IDS)
COMPANION_RECEIVER_ROLE_ID = _config_int("COMPANION_RECEIVER_ROLE_ID", COMPANION_RECEIVER_ROLE_IDS[0])
BOOSTER_RECEIVER_ROLE_ID = _config_int("BOOSTER_RECEIVER_ROLE_ID", BOOSTER_RECEIVER_ROLE_IDS[0])
if COMPANION_RECEIVER_ROLE_ID not in COMPANION_RECEIVER_ROLE_IDS:
    COMPANION_RECEIVER_ROLE_IDS.insert(0, COMPANION_RECEIVER_ROLE_ID)
if BOOSTER_RECEIVER_ROLE_ID not in BOOSTER_RECEIVER_ROLE_IDS:
    BOOSTER_RECEIVER_ROLE_IDS.insert(0, BOOSTER_RECEIVER_ROLE_ID)
NEW_MEMBER_ROLE_ID = _config_int("NEW_MEMBER_ROLE_ID", NEW_MEMBER_ROLE_ID)
PLAY_VOICE_ALLOWED_ROLE_IDS = _config_int_list("PLAY_VOICE_ALLOWED_ROLE_IDS", PLAY_VOICE_ALLOWED_ROLE_IDS)
VOICE_ROOM_HIDDEN_VISIBLE_ROLE_IDS = _config_int_list("VOICE_ROOM_HIDDEN_VISIBLE_ROLE_IDS", VOICE_ROOM_HIDDEN_VISIBLE_ROLE_IDS)
VOICE_VIEW_ONLY_ROLE_IDS = _config_int_list("VOICE_VIEW_ONLY_ROLE_IDS", VOICE_VIEW_ONLY_ROLE_IDS)
HIDDEN_VIP_USER_IDS = _config_int_list("HIDDEN_VIP_USER_IDS", HIDDEN_VIP_USER_IDS)
CONFIG_HIDDEN_VIP_USER_IDS = list(HIDDEN_VIP_USER_IDS)

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
    vip_voice_lobby_role_ids=VIP_VOICE_LOBBY_ROLE_IDS,
    hidden_vip_user_ids=HIDDEN_VIP_USER_IDS,
    play_voice_allowed_role_ids=PLAY_VOICE_ALLOWED_ROLE_IDS,
    voice_room_hidden_visible_role_ids=VOICE_ROOM_HIDDEN_VISIBLE_ROLE_IDS,
    voice_move_member_role_ids=list(dict.fromkeys([
        *COMPANION_RECEIVER_ROLE_IDS,
        *BOOSTER_RECEIVER_ROLE_IDS,
        *GAME_VOICE_ROLE_IDS,
        CUSTOMER_ROLE_ID,
    ])),
    temp_voice_control_panels=TEMP_VOICE_CONTROL_PANELS,
)


def refresh_hidden_vip_runtime_ids() -> list[int]:
    """把環境固定名單 + bot.db 可管理名單同步到 runtime 與語音入口權限模組。"""
    global HIDDEN_VIP_USER_IDS

    db_user_ids = {
        int(row.get("user_id") or 0)
        for row in list_hidden_vip_users()
        if int(row.get("user_id") or 0)
    }
    configured_user_ids = {
        int(user_id)
        for user_id in CONFIG_HIDDEN_VIP_USER_IDS
        if int(user_id)
    }

    HIDDEN_VIP_USER_IDS = sorted(db_user_ids | configured_user_ids)
    set_hidden_vip_user_ids(HIDDEN_VIP_USER_IDS)
    return list(HIDDEN_VIP_USER_IDS)


configure_rewards(
    member_levels=MEMBER_LEVELS,
    reward_point_divisor=REWARD_POINT_DIVISOR,
)

configure_reward_benefits(
    silver_member_role_id=SILVER_MEMBER_ROLE_ID,
    vip_role_tiers=VIP_MEMBER_ROLE_TIERS,
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
bot.customer_service_role_id_value = CUSTOMER_ROLE_ID
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


configure_support_call_views(
    customer_service_role_id=CUSTOMER_ROLE_ID,
    manager_role_id=MANAGER_ROLE_ID,
    send_order_log_callback=send_order_log,
)


configure_web_support_bridge(
    channel_id=WEB_SUPPORT_CHANNEL_ID,
    customer_service_role_id=CUSTOMER_ROLE_ID,
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
    pre_message: str | None = None,
    mention_roles_in_intro: bool = True,
    order_log_status: str = "已確認詳閱規章內容",
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

    role_mentions = " ".join(
        role.mention
        for role in allowed_roles
        if role is not None
    )

    # profile_direct_order_pre_message_v1
    if pre_message:
        await channel.send(
            content=str(pre_message),
            allowed_mentions=discord.AllowedMentions(
                roles=True,
                users=True,
                everyone=False,
            ),
        )

    intro_content = str(intro_message)

    if (
        mention_roles_in_intro
        and role_mentions
    ):
        intro_content = (
            f"{role_mentions}\n"
            f"{intro_content}"
        )

    await channel.send(
        content=intro_content,
        view=view,
        allowed_mentions=discord.AllowedMentions(
            roles=True,
            users=True,
            everyone=False,
        ),
    )

    if topic and "order_customer_id=" in topic:
        await send_order_log(
            guild,
            title="新票口已建立",
            fields=[
                ("開單人", member.mention, True),
                ("票口", channel.mention, True),
                ("狀態", str(order_log_status), False),
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

def sync_web_order_closed_from_bot(ticket_channel_id, dispatch_message_id=None) -> None:
    """DC bot 結單後，把網站訂單狀態同步成 closed，並同步付款前接單 lifecycle。"""
    try:
        close_support_calls_for_ticket(
            ticket_channel_id,
            reason="order_closed",
        )
    except Exception as exc:
        print(
            f"[support-call] close cleanup failed "
            f"ticket_channel_id={ticket_channel_id}: {exc}",
            flush=True,
        )
    try:
        from datetime import datetime, timedelta

        from shared.web_order_sync import update_web_order_status_by_ticket_channel

        ok = update_web_order_status_by_ticket_channel(
            ticket_channel_id=ticket_channel_id,
            status="closed",
            dispatch_message_id=dispatch_message_id,
            note="由 DC bot 結單同步。",
        )
        print(f"[web-sync] close order ticket_channel_id={ticket_channel_id} dispatch_message_id={dispatch_message_id} ok={ok}")

        if not ok:
            return

        order_id = None

        try:
            from shared.db import SessionLocal
            from shared.models import WebOrder
            from web.app.services.order_service import recalculate_order_payouts

            db = SessionLocal()

            try:
                order = (
                    db.query(WebOrder)
                    .filter(WebOrder.ticket_channel_id == str(ticket_channel_id))
                    .first()
                )

                if order is None and ticket_channel_id is not None:
                    order = (
                        db.query(WebOrder)
                        .filter(WebOrder.ticket_channel_id == ticket_channel_id)
                        .first()
                    )

                if order is None and dispatch_message_id is not None:
                    order = (
                        db.query(WebOrder)
                        .filter(WebOrder.dispatch_message_id == str(dispatch_message_id))
                        .first()
                    )

                if order is None and dispatch_message_id is not None:
                    order = (
                        db.query(WebOrder)
                        .filter(WebOrder.dispatch_message_id == dispatch_message_id)
                        .first()
                    )

                if order is None:
                    print(
                        f"[web-sync] payout skipped: web order not found "
                        f"ticket_channel_id={ticket_channel_id} dispatch_message_id={dispatch_message_id}"
                    )
                else:
                    order_id = int(order.id)

                    if not getattr(order, "closed_at", None):
                        order.closed_at = datetime.utcnow() + timedelta(hours=8)

                    recalculate_order_payouts(db, order.id)
                    db.commit()

                    print(
                        f"[web-sync] payout recalculated WEB-{order.id} "
                        f"ticket_channel_id={ticket_channel_id} dispatch_message_id={dispatch_message_id} "
                        f"closed_at={order.closed_at}"
                    )

            finally:
                db.close()

        except Exception as exc:
            print(f"[web-sync] payout recalculate failed ticket_channel_id={ticket_channel_id}: {exc}")

        if order_id is not None:
            try:
                from shared.order_acceptance import close_acceptance_order, has_acceptance_meta

                if has_acceptance_meta(order_id):
                    close_acceptance_order(order_id, source="discord_close")
                    print(f"[acceptance] closed order_id={order_id} source=discord_close")
            except Exception as exc:
                print(f"[acceptance] 結單同步付款前接單狀態失敗 order_id={order_id}: {exc}")

            try:
                credential_ticket_channel = bot.get_channel(_to_int(ticket_channel_id, 0) or 0)
                if not isinstance(credential_ticket_channel, discord.TextChannel):
                    credential_ticket_channel = None
                bot.loop.create_task(
                    revoke_order_credential_messages(
                        order_id,
                        reason="closed",
                        ticket_channel=credential_ticket_channel,
                        notify_customer=True,
                    )
                )
            except Exception as exc:
                print(f"[credentials] 結單撤回排程失敗 order_id={order_id}: {exc}")

    except Exception as exc:
        print(f"[web-sync] 結單同步網站失敗 ticket_channel_id={ticket_channel_id}: {exc}")



async def ensure_payment_submit_receipt(
    *,
    guild: discord.Guild,
    order_channel: discord.TextChannel,
    customer_id: int,
    customer_member: discord.Member | None,
    staff_member: discord.Member | discord.User,
    category_label: str,
    item: str,
    quantity: int,
    amount: int,
    payment_method: str,
    companion_preference: str | None = None,
) -> tuple[str | None, discord.Message | None]:
    """在付款方式 panel 按下送出後產生交易收據。

    重要：
    - 已經有 receipt_id 的訂單不重複產生。
    - 舊單如果沒有 receipt_id，仍可保留原本已結單 ReceiptModal 補開收據。
    """
    receipt_channel = guild.get_channel(RECEIPT_CHANNEL_ID)

    if receipt_channel is None or not isinstance(receipt_channel, discord.TextChannel):
        raise ValueError("找不到收據頻道，請確認 RECEIPT_CHANNEL_ID 是否正確。")

    order_data = SELF_SERVICE_ORDER_SELECTIONS.setdefault(order_channel.id, {})

    existing_receipt_id = str(order_data.get("receipt_id") or order_data.get("order_no") or "").strip()
    existing_message_id = _to_int(order_data.get("receipt_message_id"))

    if existing_receipt_id:
        return existing_receipt_id, None

    receipt_id = generate_order_receipt_id()
    created_at_iso = get_taipei_now_iso()
    created_at_text = get_taipei_now_text()

    payer_name = (
        getattr(customer_member, "display_name", None)
        or getattr(customer_member, "name", None)
        or str(customer_id)
    )

    staff_name = (
        getattr(staff_member, "display_name", None)
        or getattr(staff_member, "name", None)
        or str(getattr(staff_member, "id", "未紀錄"))
    )

    amount_text = format_t_amount(amount)
    payment_status_text = (
        "已確認收款"
        if payment_method == WALLET_PAYMENT_METHOD
        or bool(order_data.get("payment_review_approved"))
        else "已送出，待客服確認"
    )
    order_content = f"{category_label}｜{item}｜數量：{quantity} 單"
    if companion_preference:
        order_content += f"｜{companion_preference}"

    receipt_text = (
        "```text\n"
        "【魔丸娛樂｜交易收據】\n"
        "\n"
        f"收據編號：{receipt_id}\n"
        f"訂單編號：{receipt_id}\n"
        f"開立時間：{created_at_text}\n"
        "\n"
        f"顧客：{payer_name}\n"
        f"顧客 ID：{customer_id}\n"
        "\n"
        f"服務類別：{category_label}\n"
        f"服務項目：{item}\n"
        f"數量：{quantity} 單\n"
        f"金額：{amount_text}\n"
        f"付款方式：{payment_method}\n"
        f"付款狀態：{payment_status_text}\n"
        "\n"
        f"客服人員：{staff_name}\n"
        "\n"
        "備註：\n"
        "此收據為魔丸娛樂服務交易紀錄，非統一發票。\n"
        "如需正式報帳憑證，請先與客服確認。\n"
        "```"
    )

    embed = discord.Embed(
        title="魔丸娛樂｜交易收據",
        description=receipt_text,
        color=discord.Color.green(),
        timestamp=get_taipei_now(),
    )
    embed.add_field(name="收據編號", value=receipt_id, inline=True)
    embed.add_field(name="顧客", value=f"<@{customer_id}>", inline=True)
    embed.add_field(name="金額", value=amount_text, inline=True)
    embed.add_field(name="付款方式", value=payment_method, inline=True)
    embed.add_field(name="付款狀態", value=payment_status_text, inline=True)
    embed.add_field(name="票口", value=order_channel.mention, inline=False)
    embed.set_footer(text="此收據為交易紀錄，非統一發票。")

    receipt_message = await receipt_channel.send(
        embed=embed,
        allowed_mentions=discord.AllowedMentions(
            users=True,
            roles=False,
            everyone=False,
        ),
    )

    order_data["receipt_id"] = receipt_id
    order_data["order_no"] = receipt_id
    order_data["receipt_created_at"] = created_at_iso
    order_data["receipt_created_by"] = getattr(staff_member, "id", None)
    order_data["receipt_message_id"] = receipt_message.id
    order_data["receipt_channel_id"] = receipt_channel.id
    order_data["receipt_status"] = "payment_submitted"
    order_data["receipt_note"] = "付款方式送出後自動產生，非統一發票。"
    order_data["amount"] = int(amount)
    order_data["total_amount"] = int(amount)
    order_data["amount_text"] = amount_text
    order_data["payment_method"] = payment_method
    order_data["quantity"] = int(quantity)
    remember_order_data(order_channel.id, order_data)

    await send_order_log(
        guild,
        title="交易收據已產生",
        fields=[
            ("收據編號", receipt_id, True),
            ("顧客", f"<@{customer_id}>", True),
            ("金額", amount_text, True),
            ("付款方式", payment_method, True),
            ("付款狀態", payment_status_text, True),
            ("客服人員", getattr(staff_member, "mention", staff_name), True),
            ("票口", order_channel.mention, False),
            ("收據訊息", receipt_message.jump_url, False),
        ],
        color=discord.Color.green(),
    )

    return receipt_id, receipt_message



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
        if parsed_amount < 0:
            await interaction.response.send_message(
                "這張單還沒有訂單價格，請先在付款面板按「填寫訂單價格」讓客服輸入金額。",
                ephemeral=True
            )
            return

        # legacy_receipt_close_ack_v1
        await interaction.response.defer()

        amount_text = str(order_data.get("amount_text") or format_t_amount(parsed_amount))

        existing_receipt_id = str(order_data.get("receipt_id") or order_data.get("order_no") or "").strip()
        receipt_already_created = bool(existing_receipt_id)
        receipt_id = existing_receipt_id or generate_order_receipt_id()
        closed_at_text = get_taipei_now_iso()

        order_data["receipt_id"] = receipt_id
        order_data["order_no"] = receipt_id
        order_data.setdefault("receipt_created_at", closed_at_text)
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

        await refresh_staff_profile_panels_for_order(
            guild,
            ticket_channel_id=order_channel.id,
            reason="order_closed",
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

        if not receipt_already_created:
            receipt_message = await receipt_channel.send(
                embed=embed,
                allowed_mentions=discord.AllowedMentions(
                    users=True,
                    roles=False,
                    everyone=False
                )
            )
            order_data["receipt_message_id"] = receipt_message.id
            order_data["receipt_channel_id"] = receipt_channel.id
            remember_order_data(order_channel.id, order_data)

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

        close_receipt_text = "收據已於付款送出時產生，本次不重複送出。" if receipt_already_created else "收據已送出。"

        await interaction.followup.send(
            f"此單已由 {interaction.user.mention} 結單，{close_receipt_text}\n\n"
            f"{reward_result}\n\n"
            f"可以選擇評價本次服務、加雞腿、不留評價，或關閉票口。",
            embed=build_post_close_status_embed(order_channel.id, customer_id),
            view=ReviewButtonView(customer_id=customer_id, order_content=order_content),
            allowed_mentions=discord.AllowedMentions(
                users=True,
                roles=False,
                everyone=False
            )
        )


def get_stored_order_amount_or_none(order_data: dict) -> int | None:
    for key in ("amount", "total_amount", "amount_text"):
        raw = order_data.get(key)
        if raw is None or str(raw).strip() == "":
            continue

        if isinstance(raw, int):
            return raw

        parsed = parse_receipt_amount(str(raw))
        if parsed is not None:
            return parsed

    return None


async def close_order_without_receipt_modal(interaction: discord.Interaction) -> None:
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

    order_channel = interaction.channel
    customer_id = get_order_customer_id_from_channel(order_channel)

    if customer_id is None:
        await interaction.response.send_message(
            "無法辨識這張票口的下單顧客，因此無法結單。",
            ephemeral=True,
        )
        return

    customer_member = guild.get_member(customer_id)
    order_data = SELF_SERVICE_ORDER_SELECTIONS.setdefault(order_channel.id, {})

    parsed_amount = get_stored_order_amount_or_none(order_data)
    if parsed_amount is None:
        await interaction.response.send_message(
            "這張單還沒有訂單價格，請先讓客服填寫金額；贈送單請填 0。",
            ephemeral=True,
        )
        return

    if parsed_amount < 0:
        await interaction.response.send_message(
            "訂單金額不可為負數，請先修正金額後再結單。",
            ephemeral=True,
        )
        return

    # close_interaction_ack_v1
    await interaction.response.defer()

    order_content, detected_payment_method = get_order_summary_from_channel(order_channel.id)
    payment_method = str(
        order_data.get("payment_method")
        or detected_payment_method
        or "未填寫"
    ).strip()

    amount_text = str(order_data.get("amount_text") or format_t_amount(parsed_amount))
    existing_receipt_id = str(order_data.get("receipt_id") or order_data.get("order_no") or "").strip()
    receipt_already_created = bool(existing_receipt_id)

    receipt_id = existing_receipt_id

    # 新流程通常在付款送出時已產生收據；如果舊單沒有收據，這裡自動補一張，不再要求客服填 Modal。
    if not receipt_id:
        category = order_data.get("category")
        item = order_data.get("item")
        quantity = _to_int(order_data.get("quantity"), 1) or 1
        category_label = str(order_data.get("category_label") or ORDER_CATEGORY_LABELS.get(category, str(category or "訂單")))

        if category is not None and item is not None:
            try:
                receipt_id, _receipt_message = await ensure_payment_submit_receipt(
                    guild=guild,
                    order_channel=order_channel,
                    customer_id=customer_id,
                    customer_member=customer_member,
                    staff_member=interaction.user,
                    category_label=category_label,
                    item=str(item),
                    quantity=quantity,
                    amount=parsed_amount,
                    payment_method=payment_method,
                    companion_preference=order_data.get("companion_preference"),
                )
                order_data = SELF_SERVICE_ORDER_SELECTIONS.setdefault(order_channel.id, {})
            except ValueError as exc:
                await interaction.followup.send(str(exc), ephemeral=True)
                return
        else:
            receipt_id = generate_order_receipt_id()
            order_data["receipt_id"] = receipt_id
            order_data["order_no"] = receipt_id

    closed_at_text = get_taipei_now_iso()
    order_data["receipt_id"] = receipt_id
    order_data["order_no"] = receipt_id
    order_data.setdefault("receipt_created_at", closed_at_text)
    order_data["closed_at"] = closed_at_text
    order_data["closed"] = True
    order_data["status"] = "closed"
    order_data["amount"] = parsed_amount
    order_data["total_amount"] = parsed_amount
    order_data["amount_text"] = amount_text
    order_data["payment_method"] = payment_method
    remember_order_data(order_channel.id, order_data)

    sync_web_order_closed_from_bot(
        ticket_channel_id=order_channel.id,
        dispatch_message_id=order_data.get("dispatch_message_id"),
    )

    await refresh_staff_profile_panels_for_order(
        guild,
        ticket_channel_id=order_channel.id,
        reason="order_closed",
    )

    await lock_dispatch_claim_panel(guild, order_channel.id)
    await rename_ticket_channel(order_channel, "已結單", member=customer_member)

    reward_result = (
        "會員累積已在顧客送出付款方式時處理。"
        if order_data.get("reward_counted")
        else "提醒：這張單尚未標記會員累積，請確認顧客是否已送出付款方式。"
    )

    await send_order_log(
        guild,
        title="訂單已結單",
        fields=[
            ("訂單編號", receipt_id or "未產生", True),
            ("顧客", f"<@{customer_id}>", True),
            ("客服", interaction.user.mention, True),
            ("金額", amount_text, True),
            ("付款方式", payment_method, True),
            ("票口", order_channel.mention, False),
            ("內容", order_content, False),
        ],
        color=discord.Color.green(),
    )

    close_receipt_text = "收據已於付款送出時產生，本次不重複送出。" if receipt_already_created else "收據已自動產生或補登。"

    await interaction.followup.send(
        f"此單已由 {interaction.user.mention} 結單，{close_receipt_text}\n\n"
        f"{reward_result}\n\n"
        f"可以選擇評價本次服務、加雞腿、不留評價，或關閉票口。",
        embed=build_post_close_status_embed(order_channel.id, customer_id),
        view=ReviewButtonView(customer_id=customer_id, order_content=order_content),
        allowed_mentions=discord.AllowedMentions(
            users=True,
            roles=False,
            everyone=False,
        ),
    )


class ConfirmCloseOrderView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=60)

    @discord.ui.button(
        label="是，確認結單",
        style=discord.ButtonStyle.success,
        custom_id="confirm_close_order_yes",
    )
    async def confirm_close(self, interaction: discord.Interaction, button: discord.ui.Button):
        await close_order_without_receipt_modal(interaction)

    @discord.ui.button(
        label="否，保留訂單",
        style=discord.ButtonStyle.secondary,
        custom_id="confirm_close_order_no",
    )
    async def keep_order(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not isinstance(interaction.user, discord.Member):
            await interaction.response.send_message("無法確認你的身分組。", ephemeral=True)
            return

        if not is_customer_staff(interaction.user):
            await interaction.response.send_message("只有客服可以操作。", ephemeral=True)
            return

        await interaction.response.send_message("已保留訂單。", ephemeral=True)



# ========= 下單操作按鈕 =========

CANCEL_REASON_OPTIONS = [
    ("customer_changed_mind", "客人取消／改變需求"),
    ("schedule_conflict", "時間無法配合"),
    ("no_staff", "缺少可接人員"),
    ("payment_issue", "未付款／付款問題"),
    ("price_issue", "價格／預算問題"),
    ("duplicate_order", "重複／誤下單"),
    ("service_unavailable", "服務無法提供"),
    ("internal_correction", "店內修正"),
    ("other", "其他"),
]


class OrderCancellationReasonSelect(discord.ui.Select):
    def __init__(self):
        super().__init__(
            placeholder="先選擇取消原因",
            min_values=1,
            max_values=1,
            options=[
                discord.SelectOption(label=label, value=code)
                for code, label in CANCEL_REASON_OPTIONS
            ],
            row=1,
        )

    async def callback(self, interaction: discord.Interaction):
        parent = self.view
        if parent is None:
            await interaction.response.send_message(
                "取消原因面板已失效，請重新操作。",
                ephemeral=True,
            )
            return

        setattr(parent, "cancellation_reason_code", self.values[0])
        selected_label = dict(CANCEL_REASON_OPTIONS).get(
            self.values[0],
            self.values[0],
        )
        await interaction.response.send_message(
            f"已選擇取消原因：{selected_label}",
            ephemeral=True,
        )


class ConfirmCancelOrderView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=60)
        self.cancellation_reason_code = "unspecified"
        self.add_item(OrderCancellationReasonSelect())

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

        if self.cancellation_reason_code == "unspecified":
            await interaction.response.send_message(
                "請先從下拉選單選擇取消原因。",
                ephemeral=True,
            )
            return

        channel = interaction.channel

        # MAWAN_R13_CANCEL_SYNC
        if isinstance(channel, discord.TextChannel):
            order_data = SELF_SERVICE_ORDER_SELECTIONS.get(channel.id, {})
            dispatch_message_id = _to_int(order_data.get("dispatch_message_id"), None)
            sync_web_order_cancelled_from_bot(
                channel.id,
                dispatch_message_id=dispatch_message_id,
                note="由 DC bot 客服取消訂單同步。",
                actor_discord_id=interaction.user.id,
                cancellation_reason_code=self.cancellation_reason_code,
            )

        if interaction.guild is not None and isinstance(channel, discord.TextChannel):
            await delete_dispatch_claim_panel_for_order(
                guild=interaction.guild,
                order_channel_id=channel.id,
                actor_discord_id=interaction.user.id,
                cancellation_reason_code=self.cancellation_reason_code,
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

    if _is_final_dispatch_claim_status(data):
        parsed_message_id = _to_int(message_id)

        if parsed_message_id is not None:
            ORDER_CLAIMS.pop(parsed_message_id, None)

            try:
                delete_claim_row_from_db(message_id=parsed_message_id)
            except Exception as exc:
                print(f"[claims] cleanup final dispatch claim on restore failed message_id={parsed_message_id}: {exc}")

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

_raw_remember_claim_data = remember_claim_data


def _is_final_dispatch_claim_status(data: dict | None) -> bool:
    if not isinstance(data, dict):
        return False

    status = str(data.get("status") or "").lower().strip()

    return bool(data.get("closed")) or status in {"closed", "cancelled", "canceled"}


def remember_claim_data(message_id: int, data: dict) -> None:
    """保存派單 claim；closed/cancelled 不再持久化，避免重啟恢復舊接單面板。"""
    parsed_message_id = _to_int(message_id)

    if _is_final_dispatch_claim_status(data):
        if parsed_message_id is not None:
            ORDER_CLAIMS.pop(parsed_message_id, None)
            try:
                delete_claim_row_from_db(message_id=parsed_message_id)
            except Exception as exc:
                print(f"[claims] delete final dispatch claim failed message_id={parsed_message_id}: {exc}")

        return

    _raw_remember_claim_data(message_id, data)



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
refresh_hidden_vip_runtime_ids()
cleanup_old_closed_orders()

COMPANION_PREFERENCE_OPTIONS = [
    "不指定陪玩/打手",
    "指定陪玩/打手",
]

PAYMENT_METHOD_OPTIONS = [
    "街口",
    "轉帳",
    "我的錢包",
]

WALLET_PAYMENT_METHOD = "我的錢包"



# ========= 顧客錢包系統 =========

def ensure_wallet_tables() -> None:
    """建立顧客錢包與錢包流水表。"""
    conn = sqlite3.connect(DB_FILE)
    try:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS customer_wallets (
                customer_discord_id TEXT PRIMARY KEY,
                balance INTEGER NOT NULL DEFAULT 0,
                updated_at TEXT
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS wallet_transactions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                customer_discord_id TEXT NOT NULL,
                amount INTEGER NOT NULL,
                balance_before INTEGER NOT NULL,
                balance_after INTEGER NOT NULL,
                type TEXT NOT NULL,
                order_channel_id TEXT,
                order_no TEXT,
                operator_discord_id TEXT,
                operator_display_name TEXT,
                note TEXT,
                created_at TEXT NOT NULL
            )
        """)
        conn.commit()
    finally:
        conn.close()


def get_wallet_balance(customer_id) -> int:
    ensure_wallet_tables()
    customer_id_text = str(customer_id)

    conn = sqlite3.connect(DB_FILE)
    try:
        row = conn.execute(
            "SELECT balance FROM customer_wallets WHERE customer_discord_id = ?",
            (customer_id_text,),
        ).fetchone()

        if row is None:
            return 0

        return int(row[0] or 0)
    finally:
        conn.close()


def adjust_customer_wallet_balance(
    *,
    customer_id,
    amount: int,
    tx_type: str,
    operator=None,
    order_channel_id=None,
    order_no=None,
    note: str | None = None,
    allow_negative: bool = False,
) -> dict:
    """基於目前餘額加減，並寫入流水。amount 可正可負。"""
    ensure_wallet_tables()

    customer_id_text = str(customer_id)
    amount = int(amount or 0)

    if amount == 0:
        raise ValueError("異動金額不能為 0。")

    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row

    try:
        conn.execute("BEGIN IMMEDIATE")

        normalized_order_no = str(order_no or "").strip() or None
        normalized_type = str(tx_type or "adjustment").strip() or "adjustment"

        # 同一交易識別碼重送時必須保持冪等，避免 Discord 重送造成二次扣款；
        # 也避免把資料庫 trigger 的英文錯誤直接丟給顧客。
        if normalized_order_no:
            existing = conn.execute(
                """
                SELECT *
                FROM wallet_transactions
                WHERE customer_discord_id = ?
                  AND order_no = ?
                  AND type = ?
                ORDER BY id ASC
                LIMIT 1
                """,
                (customer_id_text, normalized_order_no, normalized_type),
            ).fetchone()

            if existing is not None:
                if int(existing["amount"] or 0) != amount:
                    raise ValueError(
                        "同一錢包交易識別碼已存在，但金額不同；已拒絕重複入帳。"
                    )

                conn.rollback()
                return dict(existing)

        row = conn.execute(
            "SELECT balance FROM customer_wallets WHERE customer_discord_id = ?",
            (customer_id_text,),
        ).fetchone()

        balance_before = int(row["balance"] or 0) if row is not None else 0
        balance_after = balance_before + amount

        if balance_after < 0 and not allow_negative:
            raise ValueError(
                f"錢包餘額不足，目前餘額 {format_t_amount(balance_before)}，"
                f"無法扣除 {format_t_amount(abs(amount))}。"
            )

        now_text = get_taipei_now_iso()
        operator_id = str(getattr(operator, "id", "") or "")
        operator_name = (
            getattr(operator, "display_name", None)
            or getattr(operator, "name", None)
            or operator_id
            or None
        )

        conn.execute(
            """
            INSERT INTO customer_wallets (customer_discord_id, balance, updated_at)
            VALUES (?, ?, ?)
            ON CONFLICT(customer_discord_id)
            DO UPDATE SET balance = excluded.balance, updated_at = excluded.updated_at
            """,
            (customer_id_text, balance_after, now_text),
        )

        cur = conn.execute(
            """
            INSERT INTO wallet_transactions (
                customer_discord_id,
                amount,
                balance_before,
                balance_after,
                type,
                order_channel_id,
                order_no,
                operator_discord_id,
                operator_display_name,
                note,
                created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                customer_id_text,
                amount,
                balance_before,
                balance_after,
                normalized_type,
                str(order_channel_id) if order_channel_id is not None else None,
                normalized_order_no,
                operator_id or None,
                operator_name,
                str(note or "").strip() or None,
                now_text,
            ),
        )

        tx_id = int(cur.lastrowid)
        conn.commit()

        return {
            "id": tx_id,
            "customer_discord_id": customer_id_text,
            "amount": amount,
            "balance_before": balance_before,
            "balance_after": balance_after,
            "type": tx_type,
            "note": note,
            "created_at": now_text,
        }

    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


async def process_worker_tip_wallet_payment(
    *,
    customer_id: int,
    amount: int,
    order_channel_id: int,
    order_no: str,
    worker_id: str,
    worker_name: str,
    operator,
) -> dict:
    """雞腿使用我的錢包付款：只扣顧客錢包，不計 VIP / 點數 / 原單金額。"""
    amount = int(amount or 0)

    if amount <= 0:
        raise ValueError("雞腿金額必須大於 0。")

    return adjust_customer_wallet_balance(
        customer_id=customer_id,
        amount=-amount,
        tx_type="tip_payment",
        operator=operator,
        order_channel_id=order_channel_id,
        order_no=order_no,
        note=f"雞腿給 {worker_name or worker_id}（100% 給指定成員）",
        allow_negative=False,
    )


async def log_worker_tip_event(*, event: str, interaction: discord.Interaction, tip: dict) -> None:
    guild = interaction.guild
    if guild is None:
        return

    event_labels = {
        "pending": "雞腿待付款確認",
        "paid": "雞腿付款完成",
        "cancelled": "雞腿已取消",
    }
    color_map = {
        "pending": discord.Color.gold(),
        "paid": discord.Color.green(),
        "cancelled": discord.Color.red(),
    }

    await send_order_log(
        guild,
        title=event_labels.get(str(event), "雞腿紀錄更新"),
        fields=[
            ("雞腿編號", f"TIP-{tip.get('id')}", True),
            ("老闆", f"<@{tip.get('customer_discord_id')}>", True),
            ("指定成員", f"<@{tip.get('worker_discord_id')}>", True),
            ("金額", format_t_amount(int(tip.get("amount") or 0)), True),
            ("付款方式", str(tip.get("payment_method") or "未紀錄"), True),
            ("付款狀態", str(tip.get("payment_status") or "未紀錄"), True),
            ("原訂單", str(tip.get("receipt_id") or tip.get("order_id") or "未紀錄"), True),
            ("規則", "100% 給指定成員；不計原單抽成 / VIP / 點數", False),
        ],
        color=color_map.get(str(event), discord.Color.gold()),
    )


configure_worker_tip_callbacks(
    wallet_handler=process_worker_tip_wallet_payment,
    log_handler=log_worker_tip_event,
)


def build_customer_info_with_wallet_embed(member: discord.Member, *, show_staff_notes: bool = True) -> discord.Embed:
    """顧客資訊 Embed：會員資訊 + 錢包餘額。"""
    data = get_customer_reward_data(member.id)
    embed = build_member_info_embed(member, data, show_points=True)

    wallet_balance = get_wallet_balance(member.id)
    embed.add_field(
        name="錢包餘額",
        value=format_t_amount(wallet_balance),
        inline=True,
    )

    if show_staff_notes:
        note_text = format_customer_notes_for_staff(member.id)
        if note_text:
            embed.add_field(
                name="客服備註",
                value=note_text[:1024],
                inline=False,
            )

    return embed


async def send_wallet_log(
    guild: discord.Guild | None,
    *,
    title: str,
    customer: discord.Member,
    operator: discord.Member | discord.User,
    tx: dict,
) -> None:
    try:
        await send_order_log(
            guild,
            title=title,
            fields=[
                ("顧客", customer.mention, True),
                ("操作人員", getattr(operator, "mention", str(getattr(operator, "id", "未知"))), True),
                ("異動金額", format_t_amount(int(tx["amount"])), True),
                ("原餘額", format_t_amount(int(tx["balance_before"])), True),
                ("新餘額", format_t_amount(int(tx["balance_after"])), True),
                ("備註", str(tx.get("note") or "未填寫"), False),
            ],
            color=discord.Color.gold(),
        )
    except Exception as exc:
        print(f"錢包日誌送出失敗：{exc}")



def get_wallet_transactions(customer_id, limit: int = 10) -> list[dict]:
    ensure_wallet_tables()

    safe_limit = max(1, min(int(limit or 10), 25))

    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row

    try:
        rows = conn.execute(
            """
            SELECT
                id,
                customer_discord_id,
                amount,
                balance_before,
                balance_after,
                type,
                order_channel_id,
                order_no,
                operator_discord_id,
                operator_display_name,
                note,
                created_at
            FROM wallet_transactions
            WHERE customer_discord_id = ?
            ORDER BY id DESC
            LIMIT ?
            """,
            (str(customer_id), safe_limit),
        ).fetchall()

        return [dict(row) for row in rows]
    finally:
        conn.close()


def wallet_transaction_type_label(tx_type: str) -> str:
    mapping = {
        "topup": "儲值",
        "payment": "訂單扣款",
        "tip_payment": "雞腿扣款",
        "refund": "退款",
        "adjustment": "修正",
    }
    return mapping.get(str(tx_type or "").strip(), str(tx_type or "未知"))


def build_wallet_history_embed(
    customer: discord.Member | discord.User,
    *,
    limit: int = 10,
    staff_view: bool = False,
) -> discord.Embed:
    balance = get_wallet_balance(customer.id)
    transactions = get_wallet_transactions(customer.id, limit=limit)

    embed = discord.Embed(
        title=f"錢包流水｜{getattr(customer, 'display_name', getattr(customer, 'name', customer.id))}",
        color=discord.Color.gold(),
    )

    embed.add_field(name="顧客", value=getattr(customer, "mention", f"<@{customer.id}>"), inline=True)
    embed.add_field(name="目前餘額", value=format_t_amount(balance), inline=True)

    if not transactions:
        embed.add_field(name="最近流水", value="目前沒有錢包流水。", inline=False)
        return embed

    blocks: list[str] = []

    for index, tx in enumerate(transactions, start=1):
        amount = int(tx.get("amount") or 0)
        sign = "+" if amount > 0 else "-"
        tx_type = wallet_transaction_type_label(str(tx.get("type") or ""))
        before = int(tx.get("balance_before") or 0)
        after = int(tx.get("balance_after") or 0)
        created_at = str(tx.get("created_at") or "未紀錄時間")
        order_no = str(tx.get("order_no") or "").strip()
        note = str(tx.get("note") or "").strip()
        operator_id = str(tx.get("operator_discord_id") or "").strip()
        operator_name = str(tx.get("operator_display_name") or "").strip()

        if len(note) > 300:
            note = note[:297] + "…"

        block = [
            f"**{index}. {tx_type}｜{sign}{format_t_amount(abs(amount))}**",
            f"{format_t_amount(before)} → {format_t_amount(after)}",
        ]

        if order_no:
            block.append(f"訂單：`{order_no}`")

        if staff_view and operator_id:
            block.append(f"操作人：<@{operator_id}>")
        elif staff_view and operator_name:
            block.append(f"操作人：{operator_name}")

        if note:
            block.append(f"備註：{note}")

        block.append(f"時間：{created_at}")
        blocks.append("\n".join(block))

    # Discord 每個 embed field 的 value 上限是 1024 字元。
    # 將流水依完整交易區塊分段，避免整批 10～25 筆塞進同一個 field 導致 400。
    chunks: list[str] = []
    current = ""

    for block in blocks:
        if len(block) > 1000:
            block = block[:997] + "…"

        candidate = block if not current else current + "\n\n" + block
        if len(candidate) <= 1000:
            current = candidate
        else:
            if current:
                chunks.append(current)
            current = block

    if current:
        chunks.append(current)

    for page, chunk in enumerate(chunks, start=1):
        field_name = f"最近 {len(transactions)} 筆流水"
        if len(chunks) > 1:
            field_name += f"（{page}/{len(chunks)}）"
        embed.add_field(name=field_name, value=chunk, inline=False)

    return embed



class StaffOrderOperationSelect(discord.ui.Select):
    def __init__(self):
        options = [
            discord.SelectOption(
                label="已結單",
                value="done",
                description="二次確認後直接結單並送出評論按鈕"
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
            await interaction.response.send_message(
                "是否確定要將這筆訂單標記為已結單？",
                view=ConfirmCloseOrderView(),
                ephemeral=True,
            )
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
        self.add_item(SupportCallButton())
        self.add_item(
            discord.ui.Button(
                label="我的訂單",
                emoji="📋",
                style=discord.ButtonStyle.link,
                url="https://mowanentertainment.com/me/orders",
                row=1,
            )
        )

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
                "請下單用戶依序選擇訂單類別、訂單項目、指定選項與數量。\n"
                "畫面會即時顯示試算金額、可接職位與接單需求。\n"
                "送出後會先派單等待接單，人數滿後才會開放付款。"
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

# profile_direct_order_ticket_creator_v1
async def create_staff_profile_order_ticket(
    *,
    interaction: discord.Interaction,
    staff_id: str,
):
    guild = interaction.guild
    member = interaction.user

    if (
        guild is None
        or not isinstance(
            member,
            discord.Member,
        )
    ):
        raise ValueError(
            "這個功能只能在伺服器內使用。"
        )

    try:
        target_id = int(
            str(staff_id)
        )
    except (TypeError, ValueError):
        raise ValueError(
            "指定成員 ID 無效，請通知客服。"
        )

    target_member = guild.get_member(
        target_id
    )

    if target_member is None:
        try:
            target_member = (
                await guild.fetch_member(
                    target_id
                )
            )
        except Exception:
            target_member = None

    if target_member is None:
        raise ValueError(
            "目前找不到這位指定成員，"
            "可能已離開伺服器或身分資料失效。"
        )

    customer_role = guild.get_role(
        CUSTOMER_ROLE_ID
    )

    if customer_role is None:
        raise ValueError(
            "找不到客服身分組，"
            "請通知管理員確認設定。"
        )

    # 只做「指定意向」通知，
    # 不預先寫 specified_staff_ids。
    # 真正指定仍由後面的訂單規則判斷，
    # 避免選到不可指定品項造成衝突。
    pre_message = (
        f"{customer_role.mention} "
        f"老闆想要指定 "
        f"{target_member.mention}"
    )

    intro = (
        f"這裡有闆闆開單。\n\n"
        f"開單人：{member.mention}\n"
        f"狀態：由個人牆指定下單建立"
        f"{format_customer_notes_for_ticket(member.id)}"
    )

    topic = (
        f"order_customer_id={member.id};"
        f"profile_specified_staff_id={target_id}"
    )

    await create_private_channel(
        interaction=interaction,
        category_id=CUSTOMER_CATEGORY_ID,
        channel_name=safe_channel_name(
            "下單",
            member,
        ),
        allowed_roles=[
            customer_role,
        ],
        intro_message=intro,
        view=OrderControlView(),
        topic=topic,
        pre_message=pre_message,
        mention_roles_in_intro=False,
        order_log_status=(
            "個人牆指定下單｜"
            f"指定 {target_member.display_name}"
        ),
    )


configure_staff_profile_order_ticket_creator(
    create_staff_profile_order_ticket
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


async def refresh_main_service_panel() -> bool:
    if not (
        DISPATCH_SUPPORT_ONLINE_CHANNEL_ID
        and MAIN_SERVICE_PANEL_MESSAGE_ID
    ):
        return False

    channel = bot.get_channel(DISPATCH_SUPPORT_ONLINE_CHANNEL_ID)
    if not isinstance(channel, discord.TextChannel):
        try:
            fetched_channel = await bot.fetch_channel(
                DISPATCH_SUPPORT_ONLINE_CHANNEL_ID
            )
        except (discord.Forbidden, discord.NotFound, discord.HTTPException):
            return False
        channel = (
            fetched_channel
            if isinstance(fetched_channel, discord.TextChannel)
            else None
        )

    if channel is None:
        return False

    try:
        message = await channel.fetch_message(
            MAIN_SERVICE_PANEL_MESSAGE_ID
        )
        await message.edit(
            embed=build_main_panel_embed(),
            view=MainPanelView(),
        )
    except (discord.Forbidden, discord.NotFound, discord.HTTPException) as exc:
        print(
            "[service-lobby] panel refresh failed: "
            f"{type(exc).__name__}: {exc}",
            flush=True,
        )
        return False

    print(
        "[service-lobby] main panel refreshed",
        flush=True,
    )
    return True


# ========= Bot 事件 =========


def member_has_vip_voice_role(member: discord.Member | None) -> bool:
    if member is None:
        return False

    # 隱藏 VIP 不需要公開 VIP role，但在語音房生命週期中等同有效 VIP。
    if int(member.id) in {int(user_id) for user_id in HIDDEN_VIP_USER_IDS}:
        return True

    vip_role_ids = {int(role_id) for role_id in VIP_VOICE_LOBBY_ROLE_IDS}
    return any(int(role.id) in vip_role_ids for role in getattr(member, "roles", []))


@vip_group.command(
    name="hidden_add",
    description="管理員把成員加入 Hidden VIP 白名單",
)
@app_commands.describe(member="要加入 Hidden VIP 白名單的成員")
@app_commands.default_permissions(administrator=True)
async def vip_hidden_add(interaction: discord.Interaction, member: discord.Member):
    if interaction.guild is None or not isinstance(interaction.user, discord.Member):
        await interaction.response.send_message("這個指令只能在伺服器內使用。", ephemeral=True)
        return

    if not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message("只有管理員可以管理 Hidden VIP 白名單。", ephemeral=True)
        return

    await interaction.response.defer(ephemeral=True)

    already_active = int(member.id) in {int(user_id) for user_id in HIDDEN_VIP_USER_IDS}
    added = add_hidden_vip_user(member.id, added_by=interaction.user.id)
    refresh_hidden_vip_runtime_ids()
    now_active = int(member.id) in {int(user_id) for user_id in HIDDEN_VIP_USER_IDS}

    if not now_active:
        await interaction.followup.send(
            "Hidden VIP 白名單寫入失敗，沒有套用任何權限變更。",
            ephemeral=True,
        )
        return

    lobby_warning = None
    try:
        await get_or_create_vip_voice_lobby(interaction.guild)
    except (discord.Forbidden, discord.HTTPException) as exc:
        lobby_warning = f"；但刷新 VIP 建立入口權限失敗：{exc}"

    if already_active and not added:
        await interaction.followup.send(
            f"{member.mention} 已經在 Hidden VIP 白名單內。",
            ephemeral=True,
        )
        return

    await interaction.followup.send(
        f"已將 {member.mention} 加入 Hidden VIP 白名單。\n"
        f"不需要公開 VIP 身分組，也會被系統視為有效 VIP{lobby_warning or '。'}",
        ephemeral=True,
    )


@vip_group.command(
    name="hidden_remove",
    description="管理員把成員移出 Hidden VIP 白名單",
)
@app_commands.describe(member="要移出 Hidden VIP 白名單的成員")
@app_commands.default_permissions(administrator=True)
async def vip_hidden_remove(interaction: discord.Interaction, member: discord.Member):
    if interaction.guild is None or not isinstance(interaction.user, discord.Member):
        await interaction.response.send_message("這個指令只能在伺服器內使用。", ephemeral=True)
        return

    if not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message("只有管理員可以管理 Hidden VIP 白名單。", ephemeral=True)
        return

    if int(member.id) in {int(user_id) for user_id in CONFIG_HIDDEN_VIP_USER_IDS}:
        await interaction.response.send_message(
            "這位成員是由 HIDDEN_VIP_USER_IDS 環境設定固定加入，無法用指令移除。",
            ephemeral=True,
        )
        return

    await interaction.response.defer(ephemeral=True)

    removed = remove_hidden_vip_user(member.id)
    refresh_hidden_vip_runtime_ids()

    lobby_warning = None
    try:
        await get_or_create_vip_voice_lobby(interaction.guild)
    except (discord.Forbidden, discord.HTTPException) as exc:
        lobby_warning = f"；但刷新 VIP 建立入口權限失敗：{exc}"

    if not removed:
        await interaction.followup.send(
            f"{member.mention} 原本就不在可管理的 Hidden VIP 白名單內。",
            ephemeral=True,
        )
        return

    vip_role_ids = {int(role_id) for role_id in VIP_VOICE_LOBBY_ROLE_IDS}
    has_public_vip_role = any(
        int(role.id) in vip_role_ids
        for role in getattr(member, "roles", [])
    )

    room_deleted = False
    if not has_public_vip_role:
        room_deleted = await delete_vip_voice_room_for_owner(
            interaction.guild,
            member.id,
            reason=f"Hidden VIP whitelist removed by {interaction.user}",
        )

    suffix = (
        "；因為他沒有正式 VIP 身分組，原本的 VIP 房也已刪除"
        if room_deleted
        else ""
    )

    await interaction.followup.send(
        f"已將 {member.mention} 移出 Hidden VIP 白名單{suffix}{lobby_warning or '。'}",
        ephemeral=True,
    )


@vip_group.command(
    name="hidden_list",
    description="管理員查看目前 Hidden VIP 白名單",
)
@app_commands.default_permissions(administrator=True)
async def vip_hidden_list(interaction: discord.Interaction):
    if interaction.guild is None or not isinstance(interaction.user, discord.Member):
        await interaction.response.send_message("這個指令只能在伺服器內使用。", ephemeral=True)
        return

    if not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message("只有管理員可以查看 Hidden VIP 白名單。", ephemeral=True)
        return

    rows = list_hidden_vip_users()
    configured_ids = {
        int(user_id)
        for user_id in CONFIG_HIDDEN_VIP_USER_IDS
        if int(user_id)
    }
    db_by_id = {
        int(row.get("user_id") or 0): row
        for row in rows
        if int(row.get("user_id") or 0)
    }

    all_ids = sorted(set(db_by_id) | configured_ids)
    if not all_ids:
        await interaction.response.send_message(
            "目前 Hidden VIP 白名單是空的。",
            ephemeral=True,
        )
        return

    lines: list[str] = []
    for user_id in all_ids[:40]:
        member = interaction.guild.get_member(user_id)
        label = member.mention if member is not None else f"<@{user_id}>"
        source = "設定檔" if user_id in configured_ids else "指令新增"
        lines.append(f"• {label} — {user_id}（{source}）")

    if len(all_ids) > 40:
        lines.append(f"…另有 {len(all_ids) - 40} 位未顯示")

    await interaction.response.send_message(
        "Hidden VIP 白名單：\n" + "\n".join(lines),
        ephemeral=True,
        allowed_mentions=discord.AllowedMentions.none(),
    )


@vip_group.command(
    name="create_voice",
    description="管理員直接替有效 VIP 建立永久 VIP 語音房",
)
@app_commands.describe(user_id="要建立 VIP 語音房的 Discord 使用者 ID")
@app_commands.default_permissions(administrator=True)
async def vip_create_voice(interaction: discord.Interaction, user_id: str):
    if interaction.guild is None or not isinstance(interaction.user, discord.Member):
        await interaction.response.send_message("這個指令只能在伺服器內使用。", ephemeral=True)
        return

    if not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message("只有管理員可以使用這個指令。", ephemeral=True)
        return

    try:
        owner_id = int(str(user_id).strip())
    except (TypeError, ValueError):
        await interaction.response.send_message("Discord 使用者 ID 格式錯誤。", ephemeral=True)
        return

    await interaction.response.defer(ephemeral=True)

    member = await fetch_member_safely(interaction.guild, owner_id)
    if member is None:
        await interaction.followup.send("找不到這位伺服器成員，請確認使用者 ID。", ephemeral=True)
        return

    if not member_has_vip_voice_role(member):
        await interaction.followup.send(
            "這位成員目前不是有效 VIP，也不在 Hidden VIP 白名單內，因此沒有建立房間。",
            ephemeral=True,
        )
        return

    existing_room = get_vip_voice_room_by_owner(owner_id)
    if existing_room:
        existing_channel_id = int(existing_room.get("channel_id") or 0)
        existing_channel = interaction.guild.get_channel(existing_channel_id)

        if isinstance(existing_channel, discord.VoiceChannel):
            TEMP_VIP_VOICE_CHANNEL_IDS.add(existing_channel.id)
            await interaction.followup.send(
                f"{member.mention} 已有永久 VIP 房：{existing_channel.mention}",
                ephemeral=True,
            )
            return

        delete_vip_voice_room_record(
            owner_id=owner_id,
            channel_id=existing_channel_id or None,
        )

    category = interaction.guild.get_channel(VIP_VOICE_LOBBY_CATEGORY_ID)
    if not isinstance(category, discord.CategoryChannel):
        await interaction.followup.send(
            "找不到 VIP 語音類別，請確認 VIP_VOICE_LOBBY_CATEGORY_ID。",
            ephemeral=True,
        )
        return

    new_channel: discord.VoiceChannel | None = None

    try:
        new_channel = await interaction.guild.create_voice_channel(
            name=safe_vip_voice_channel_name(member),
            category=category,
            overwrites=build_vip_room_overwrites(interaction.guild, member),
            reason=f"Permanent VIP voice room manually created by {interaction.user}",
        )

        TEMP_VIP_VOICE_CHANNEL_IDS.add(new_channel.id)
        upsert_vip_voice_room(owner_id, new_channel.id, None)

        panel_message = await create_voice_control_panel(
            guild=interaction.guild,
            category=category,
            member=member,
            voice_channel=new_channel,
            room_type="vip",
        )

        upsert_vip_voice_room(owner_id, new_channel.id, panel_message.id)

    except (discord.Forbidden, discord.HTTPException) as exc:
        if new_channel is not None:
            TEMP_VIP_VOICE_CHANNEL_IDS.discard(new_channel.id)
            delete_vip_voice_room_record(owner_id=owner_id, channel_id=new_channel.id)
            try:
                await new_channel.delete(reason="Rollback failed manual VIP room creation")
            except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                pass

        await interaction.followup.send(
            f"建立 VIP 語音房失敗：{exc}",
            ephemeral=True,
        )
        return

    await interaction.followup.send(
        f"已替 {member.mention} 建立永久 VIP 房：{new_channel.mention}\n"
        "Panel 已建立並綁定，房主不需要先進入建立入口。",
        ephemeral=True,
    )


async def delete_vip_voice_room_for_owner(
    guild: discord.Guild,
    owner_id: int,
    *,
    reason: str,
    verify_vip_inactive: bool = False,
    verify_delay_seconds: float = 0,
) -> bool:
    row = get_vip_voice_room_by_owner(int(owner_id))
    if not row:
        return False

    channel_id = int(row.get("channel_id") or 0)

    # VIP 失效刪房一定做最後一次 Discord 即時驗證。
    # 任何暫時性的 member_update / 身分組同步事件都不能直接刪永久房。
    if verify_vip_inactive:
        if verify_delay_seconds > 0:
            await asyncio.sleep(float(verify_delay_seconds))

        latest_member = await fetch_member_safely(guild, int(owner_id))

        if latest_member is None:
            print(
                f"[vip-voice] skip delete: unable to verify member "
                f"owner={owner_id} channel={channel_id} reason={reason}"
            )
            return False

        if member_has_vip_voice_role(latest_member):
            print(
                f"[vip-voice] skip delete: VIP still active "
                f"owner={owner_id} channel={channel_id} reason={reason}"
            )
            return False

    channel = guild.get_channel(channel_id) if channel_id else None

    print(
        f"[vip-voice] deleting room "
        f"owner={owner_id} channel={channel_id} reason={reason}"
    )

    if isinstance(channel, discord.VoiceChannel):
        try:
            await channel.delete(reason=reason)
        except discord.NotFound:
            pass
        except discord.Forbidden:
            print(f"Bot 權限不足，無法刪除 VIP 語音房：{channel_id}")
            return False
        except discord.HTTPException as e:
            print(f"刪除 VIP 語音房失敗：{channel_id}：{e}")
            return False

    TEMP_VIP_VOICE_CHANNEL_IDS.discard(channel_id)
    await delete_voice_control_panel(guild, channel_id)
    delete_vip_voice_room_record(owner_id=int(owner_id), channel_id=channel_id)
    return True


async def restore_persistent_vip_voice_rooms(guild: discord.Guild) -> int:
    # 先接管更新前已存在、但還沒寫入資料庫的 VIP 房。
    known_channel_ids = {
        int(row.get("channel_id") or 0)
        for row in list_vip_voice_rooms()
        if int(row.get("channel_id") or 0)
    }
    vip_category = guild.get_channel(VIP_VOICE_LOBBY_CATEGORY_ID)

    if isinstance(vip_category, discord.CategoryChannel):
        for channel in vip_category.voice_channels:
            if channel.id in known_channel_ids or channel.name == VIP_VOICE_CREATE_CHANNEL_NAME:
                continue

            owner_id = 0
            panel_message_id = 0

            try:
                async for message in channel.history(limit=100):
                    if bot.user is not None and message.author.id != bot.user.id:
                        continue
                    if not message.embeds:
                        continue

                    embed = message.embeds[0]
                    if str(embed.title or "") != "專屬語音房":
                        continue

                    match = re.search(r"<@!?(\d+)>", str(embed.description or ""))
                    if match is None:
                        continue

                    owner_id = int(match.group(1))
                    panel_message_id = int(message.id)
                    break
            except (discord.Forbidden, discord.HTTPException):
                continue

            owner = await fetch_member_safely(guild, owner_id) if owner_id else None
            if owner is None or not member_has_vip_voice_role(owner):
                continue

            upsert_vip_voice_room(owner_id, channel.id, panel_message_id or None)
            known_channel_ids.add(channel.id)

    restored = 0

    for row in list_vip_voice_rooms():
        owner_id = int(row.get("owner_id") or 0)
        channel_id = int(row.get("channel_id") or 0)
        panel_message_id = int(row.get("panel_message_id") or 0)

        if not owner_id or not channel_id:
            delete_vip_voice_room_record(owner_id=owner_id or None, channel_id=channel_id or None)
            continue

        channel = guild.get_channel(channel_id)
        owner = await fetch_member_safely(guild, owner_id)

        if not isinstance(channel, discord.VoiceChannel):
            delete_vip_voice_room_record(owner_id=owner_id, channel_id=channel_id)
            continue

        # 成員資料暫時抓不到時不要誤刪永久房；真的離開伺服器會由 on_member_remove 清理。
        if owner is None:
            continue

        if not member_has_vip_voice_role(owner):
            await delete_vip_voice_room_for_owner(
                guild,
                owner_id,
                reason="VIP membership is no longer active",
                verify_vip_inactive=True,
            )
            continue

        TEMP_VIP_VOICE_CHANNEL_IDS.add(channel_id)
        TEMP_VOICE_CONTROL_PANELS[channel_id] = {
            "owner_id": owner_id,
            "panel_channel_id": channel_id,
            "panel_message_id": panel_message_id or None,
            "room_type": "vip",
            "locked": False,
            "hidden": False,
        }
        sync_voice_control_panel_state_from_channel(channel)

        try:
            await sync_vip_whitelist_permissions(
                channel,
                owner_id,
            )
        except discord.Forbidden:
            print(
                f"Bot 權限不足，無法恢復 VIP 白名單權限："
                f"owner={owner_id} channel={channel_id}"
            )
        except discord.HTTPException as exc:
            print(
                f"恢復 VIP 白名單權限失敗："
                f"owner={owner_id} channel={channel_id}: {exc}"
            )

        if panel_message_id:
            control_view = VoiceRoomControlView(
                voice_channel_id=channel_id,
                owner_id=owner_id,
                room_type="vip",
            )

            try:
                bot.add_view(
                    control_view,
                    message_id=panel_message_id,
                )
            except ValueError:
                pass

            # Persistent view registration only restores callbacks; it does not
            # change the buttons already rendered on an old Discord message.
            # Edit the existing panel so pre-existing VIP rooms immediately get
            # newly-added controls such as the whitelist button after deploy.
            try:
                panel_message = await channel.fetch_message(panel_message_id)
                await panel_message.edit(
                    view=control_view,
                    allowed_mentions=discord.AllowedMentions(
                        users=True,
                        roles=False,
                        everyone=False,
                    ),
                )
            except discord.NotFound:
                pass
            except discord.Forbidden:
                print(
                    f"Bot 權限不足，無法更新既有 VIP Panel："
                    f"owner={owner_id} channel={channel_id}"
                )
            except discord.HTTPException as exc:
                print(
                    f"更新既有 VIP Panel 失敗："
                    f"owner={owner_id} channel={channel_id}: {exc}"
                )

        restored += 1

    return restored


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
async def on_member_update(before: discord.Member, after: discord.Member):
    had_vip = member_has_vip_voice_role(before)
    has_vip = member_has_vip_voice_role(after)

    if had_vip and not has_vip:
        await delete_vip_voice_room_for_owner(
            after.guild,
            after.id,
            reason="VIP membership expired",
            verify_vip_inactive=True,
            verify_delay_seconds=3,
        )


@bot.event
async def on_member_remove(member: discord.Member):
    await delete_vip_voice_room_for_owner(
        member.guild,
        member.id,
        reason="VIP member left the server",
    )


@bot.event
async def on_guild_channel_delete(channel: discord.abc.GuildChannel):
    # 如果入職票口被手動刪除，也嘗試收回申請人暫時身分組。
    await remove_recruit_applicant_role(channel.guild, channel)

    if isinstance(channel, discord.VoiceChannel):
        row = get_vip_voice_room_by_channel(channel.id)
        if row:
            TEMP_VIP_VOICE_CHANNEL_IDS.discard(channel.id)
            await delete_voice_control_panel(channel.guild, channel.id)
            delete_vip_voice_room_record(channel_id=channel.id)


@bot.event
async def on_voice_state_update(
    member: discord.Member,
    before: discord.VoiceState,
    after: discord.VoiceState
):
    guild = member.guild

    # 離開受管理語音房時先收回訪客的個人權限。
    # 陪玩 / 公共房仍在空房時刪除；VIP 房則持續保留到 VIP 失效。
    if before.channel is not None:
        is_temp_play_voice_room = (
            before.channel.id in TEMP_PLAY_VOICE_CHANNEL_IDS
            or (
                before.channel.category_id in {PLAY_VOICE_CATEGORY_ID, PLAY_VOICE_LOBBY_CATEGORY_ID}
                and before.channel.name.startswith("🎮┃")
                and before.channel.name.endswith("的陪玩頻道")
                and before.channel.name != PLAY_VOICE_CREATE_CHANNEL_NAME
            )
        )

        is_temp_vip_voice_room = (
            before.channel.id in TEMP_VIP_VOICE_CHANNEL_IDS
            or (
                before.channel.category_id in {PLAY_VOICE_CATEGORY_ID, VIP_VOICE_LOBBY_CATEGORY_ID}
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

        if (
            before.channel != after.channel
            and (
                is_temp_play_voice_room
                or is_temp_vip_voice_room
                or is_temp_public_voice_room
            )
        ):
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

        # VIP 房主直接點自己的永久房時，也要檢查 Panel 是否已被聊天訊息埋住。
        vip_room_row = get_vip_voice_room_by_channel(after.channel.id)
        if vip_room_row and int(vip_room_row.get("owner_id") or 0) == member.id:
            try:
                panel_message, panel_refreshed = await refresh_vip_voice_control_panel_if_needed(
                    after.channel,
                    member,
                    message_threshold=10,
                )
                if panel_message is not None:
                    upsert_vip_voice_room(
                        member.id,
                        after.channel.id,
                        panel_message.id,
                    )
                if panel_refreshed:
                    print(
                        f"Refreshed VIP voice control panel: "
                        f"owner={member.id} channel={after.channel.id} message={panel_message.id if panel_message else 0}"
                    )
            except discord.Forbidden:
                print(f"Bot 權限不足，無法刷新 VIP 語音房 Panel：{after.channel.id}")
            except discord.HTTPException as exc:
                print(f"刷新 VIP 語音房 Panel 失敗：{after.channel.id}：{exc}")

    # 進入一般陪玩入口：建立一般陪玩語音房
    if after.channel is not None and play_lobby_channel is not None and after.channel.id == play_lobby_channel.id:
        try:
            category = guild.get_channel(PLAY_VOICE_LOBBY_CATEGORY_ID)
            if category is None or not isinstance(category, discord.CategoryChannel):
                category = play_lobby_channel.category

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

    # 進入 VIP 入口：已有永久包廂就直接送回原房，沒有才建立。
    if after.channel is not None and vip_lobby_channel is not None and after.channel.id == vip_lobby_channel.id:
        try:
            existing_room = get_vip_voice_room_by_owner(member.id)

            if existing_room:
                existing_channel_id = int(existing_room.get("channel_id") or 0)
                existing_channel = guild.get_channel(existing_channel_id)

                if isinstance(existing_channel, discord.VoiceChannel):
                    TEMP_VIP_VOICE_CHANNEL_IDS.add(existing_channel.id)
                    await sync_vip_whitelist_permissions(
                        existing_channel,
                        member.id,
                    )
                    await grant_play_voice_room_chat_access(existing_channel, member)
                    await member.move_to(
                        existing_channel,
                        reason="Move VIP member to existing permanent voice room",
                    )
                    return

                delete_vip_voice_room_record(owner_id=member.id, channel_id=existing_channel_id)

            category = guild.get_channel(VIP_VOICE_LOBBY_CATEGORY_ID)
            if category is None or not isinstance(category, discord.CategoryChannel):
                category = vip_lobby_channel.category

            new_channel = await guild.create_voice_channel(
                name=safe_vip_voice_channel_name(member),
                category=category,
                overwrites=build_vip_room_overwrites(guild, member),
                reason=f"Permanent VIP voice room created by {member}"
            )
            TEMP_VIP_VOICE_CHANNEL_IDS.add(new_channel.id)
            upsert_vip_voice_room(member.id, new_channel.id, None)

            panel_message = await create_voice_control_panel(
                guild=guild,
                category=category,
                member=member,
                voice_channel=new_channel,
                room_type="vip"
            )
            upsert_vip_voice_room(member.id, new_channel.id, panel_message.id)

            await member.move_to(
                new_channel,
                reason="Move member to permanent VIP voice room"
            )
        except discord.Forbidden:
            print("Bot 權限不足，無法建立或移動 VIP 語音房。")
        except discord.HTTPException as e:
            print(f"建立或移動 VIP 語音房失敗：{e}")

        return

    # 進入公共入口：建立所有人可見 / 可加入的公共語音房
    if after.channel is not None and public_lobby_channel is not None and after.channel.id == public_lobby_channel.id:
        try:
            category = guild.get_channel(PLAY_VOICE_CATEGORY_ID)
            if category is None or not isinstance(category, discord.CategoryChannel):
                category = public_lobby_channel.category

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

async def register_core_persistent_views_once() -> None:
    """Register core persistent component views before READY.

    Persistent views must be available even while on_ready is doing network
    restore work (VIP panels, extension loading, command sync, etc.).
    """
    if getattr(bot, "_core_persistent_views_registered", False):
        return

    bot.add_view(MainPanelView())
    bot.add_view(OrderControlView())
    bot.add_view(StaffOrderOperationView())
    bot.add_view(RecruitControlView())
    bot.add_view(ComplaintPanelView())
    bot.add_view(FeedbackPanelView())
    bot.add_view(ComplaintResolveView())
    bot.add_view(SupportCallActionView())
    bot.add_view(WebSupportActionView())

    if not getattr(bot, "_web_support_listener_registered", False):
        bot.add_listener(
            handle_web_support_thread_message,
            "on_message",
        )
        bot._web_support_listener_registered = True

    bot._core_persistent_views_registered = True
    print("[persistent-views] core views registered", flush=True)


async def _bot_setup_hook() -> None:
    await register_core_persistent_views_once()


# discord.py calls setup_hook before READY. Registering persistent views here
# prevents old ticket controls from depending on slow/failing on_ready work.
bot.setup_hook = _bot_setup_hook


@bot.event
async def on_ready():
    # zYao 3C3B2R3 persistent CS view v1
    if not getattr(
        bot,
        "_website_cs_view_v3_registered",
        False,
    ):

        bot.add_view(
            WebsiteOrderCsConfirmView()
        )

        bot._website_cs_view_v3_registered = True
    if not getattr(bot, '_acceptance_sync_worker_started', False):
        bot._acceptance_sync_worker_started = True
        bot.loop.create_task(acceptance_sync_event_worker())
        print('[acceptance-sync] worker started', flush=True)

    if not getattr(bot, "_reward_redeem_view_registered", False):
        bot.add_view(RewardRedeemView())
        bot._reward_redeem_view_registered = True

    if not getattr(bot, "_main_service_panel_refreshed", False):
        if await refresh_main_service_panel():
            bot._main_service_panel_refreshed = True

    ensure_wallet_tables()
    ensure_support_call_tables()
    ensure_smart_dispatch_tables()
    ensure_web_support_tables()

    if not getattr(bot, "_support_call_sla_worker_started", False):
        bot._support_call_sla_worker_started = True
        bot.loop.create_task(support_call_sla_loop(bot))
        print("[support-call] SLA worker started", flush=True)

    if not getattr(bot, "_web_support_bridge_worker_started", False):
        bot._web_support_bridge_worker_started = True
        bot.loop.create_task(web_support_bridge_loop(bot))
        print("[web-support] Discord bridge worker started", flush=True)


    if not getattr(bot, "_smart_dispatch_worker_started", False):
        bot._smart_dispatch_worker_started = True
        bot.loop.create_task(smart_dispatch_escalation_loop(bot))
        print("[smart-dispatch] escalation worker started", flush=True)

    if (
        DISPATCH_ONLINE_CHANNEL_ID
        and not getattr(bot, "_dispatch_presence_worker_started", False)
    ):
        bot._dispatch_presence_worker_started = True
        bot.loop.create_task(
            dispatch_presence_channel_loop(
                bot,
                channel_id=DISPATCH_ONLINE_CHANNEL_ID,
            )
        )
        print(
            "[dispatch-presence] channel sync worker started",
            flush=True,
        )

    if (
        DISPATCH_SUPPORT_ONLINE_CHANNEL_ID
        and not getattr(bot, "_dispatch_support_presence_worker_started", False)
    ):
        bot._dispatch_support_presence_worker_started = True
        bot.loop.create_task(
            dispatch_support_presence_channel_loop(
                bot,
                channel_id=DISPATCH_SUPPORT_ONLINE_CHANNEL_ID,
            )
        )
        print(
            "[dispatch-support-presence] channel sync worker started",
            flush=True,
        )

    if not getattr(bot, "_worker_tip_confirm_views_registered", False):
        restored_worker_tip_views = 0

        for row in get_pending_worker_tip_confirmations():
            try:
                tip_id = int(row.get("id") or 0)
                customer_id = int(str(row.get("customer_discord_id") or "0"))
                message_id = int(str(row.get("confirmation_message_id") or "0"))
            except (TypeError, ValueError):
                continue

            if not tip_id or not customer_id or not message_id:
                continue

            try:
                bot.add_view(
                    WorkerTipPaymentConfirmView(
                        tip_id=tip_id,
                        customer_id=customer_id,
                    ),
                    message_id=message_id,
                )
                restored_worker_tip_views += 1
            except ValueError:
                pass

        bot._worker_tip_confirm_views_registered = True

        if restored_worker_tip_views:
            print(f"Restored worker tip payment views: {restored_worker_tip_views}")

    ensure_web_sync_event_worker_started()
    global BACKUP_TASK_STARTED, STORED_REMINDER_TASK_STARTED, VIP_DOWNGRADE_TASK_STARTED
    # setup_hook normally registers these before READY; keep this as a safe
    # reconnect/fallback path without duplicate registration.
    await register_core_persistent_views_once()

    if not getattr(bot, "_staff_profile_views_registered", False):
        ensure_staff_profile_tables()
        restored_profile_views = 0
        for profile in get_staff_profile_panel_rows():
            try:
                panel_message_id = int(str(profile.get("panel_message_id") or "0"))
            except (TypeError, ValueError):
                panel_message_id = 0

            staff_id = str(profile.get("staff_discord_id") or "").strip()
            if not panel_message_id or not staff_id:
                continue

            try:
                bot.add_view(StaffProfilePanelView(staff_id), message_id=panel_message_id)
                restored_profile_views += 1
            except ValueError:
                pass

        bot._staff_profile_views_registered = True
        if restored_profile_views:
            print(f"Restored staff profile views: {restored_profile_views}")

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

    if not getattr(bot, "_order_credential_view_registered", False):
        try:
            bot.add_view(OrderCredentialEntryView())
            bot._order_credential_view_registered = True
        except ValueError:
            pass

    guild_for_voice = bot.get_guild(GUILD_ID)
    if guild_for_voice is not None:
        if not getattr(bot, "_active_dispatch_panels_refreshed", False):
            try:
                refreshed_active_dispatch_panels = (
                    await repair_active_web_sync_dispatch_panels_once()
                )
                bot._active_dispatch_panels_refreshed = True
                if refreshed_active_dispatch_panels:
                    print(
                        "[web-sync] startup refreshed active/stored dispatch panels: "
                        f"{refreshed_active_dispatch_panels}",
                        flush=True,
                    )
            except Exception as exc:
                print(
                    "[web-sync] startup active/stored dispatch refresh failed: "
                    f"{type(exc).__name__}: {exc}",
                    flush=True,
                )

        try:
            reconciled_acceptance_panels = (
                await repair_pending_acceptance_dispatch_panels_once(
                    guild_for_voice,
                )
            )
            if reconciled_acceptance_panels:
                print(
                    "[acceptance-sync] startup reconciled dispatch panels: "
                    f"{reconciled_acceptance_panels}",
                    flush=True,
                )
        except Exception as exc:
            print(
                "[acceptance-sync] startup reconcile failed: "
                f"{type(exc).__name__}: {exc}",
                flush=True,
            )

        try:
            repaired_payment_panels = await repair_pending_acceptance_payment_panels_once(
                guild_for_voice,
                reason="bot_startup",
            )
            if repaired_payment_panels:
                print(f"[acceptance-repair] restored payment panels: {repaired_payment_panels}", flush=True)
        except Exception as exc:
            print(f"[acceptance-repair] startup repair failed: {type(exc).__name__}: {exc}", flush=True)

        try:
            repaired_ticket_access = await repair_pending_acceptance_ticket_access_once(
                guild_for_voice,
            )
            if repaired_ticket_access:
                print(
                    f"[ticket-access] restored accepted staff ticket access: "
                    f"{repaired_ticket_access}",
                    flush=True,
                )
        except Exception as exc:
            print(
                f"[ticket-access] startup repair failed: "
                f"{type(exc).__name__}: {exc}",
                flush=True,
            )

        if not getattr(bot, "_support_call_ticket_controls_refreshed", False):
            try:
                refreshed_support_buttons = (
                    await refresh_existing_order_ticket_support_buttons(
                        guild_for_voice,
                        category_id=CUSTOMER_CATEGORY_ID,
                        order_control_view_factory=OrderControlView,
                    )
                )
                bot._support_call_ticket_controls_refreshed = True
                if refreshed_support_buttons:
                    print(
                        f"[support-call] refreshed ticket controls: "
                        f"{refreshed_support_buttons}",
                        flush=True,
                    )
            except Exception as exc:
                print(
                    f"[support-call] ticket control refresh failed: "
                    f"{type(exc).__name__}: {exc}",
                    flush=True,
                )

        await get_or_create_order_log_channel(guild_for_voice)
        if not BACKUP_TASK_STARTED:
            BACKUP_TASK_STARTED = True
            asyncio.create_task(daily_backup_loop())
        if not STORED_REMINDER_TASK_STARTED:
            STORED_REMINDER_TASK_STARTED = True
            asyncio.create_task(stored_order_reminder_loop())
        # VIP 自動降階已停用。
        # 保留手動 /vip check_vip_downgrades 指令，但不再由 bot 自動排程執行。
        # if not VIP_DOWNGRADE_TASK_STARTED:
        #     VIP_DOWNGRADE_TASK_STARTED = True
        #     asyncio.create_task(vip_downgrade_loop())
        try:
            await get_or_create_play_voice_lobby(guild_for_voice)
            await get_or_create_vip_voice_lobby(guild_for_voice)
            await get_or_create_public_voice_lobby(guild_for_voice)

            if not getattr(bot, "_vip_voice_views_registered", False):
                restored_vip_rooms = await restore_persistent_vip_voice_rooms(guild_for_voice)
                bot._vip_voice_views_registered = True
                if restored_vip_rooms:
                    print(f"Restored VIP voice rooms: {restored_vip_rooms}")
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
        synced = await asyncio.wait_for(
            bot.tree.sync(guild=guild),
            timeout=30,
        )
        print(f"Slash commands synced: {len(synced)}", flush=True)
    except asyncio.TimeoutError:
        print(
            "Sync timeout: Discord command sync exceeded 30 seconds; "
            "persistent views remain available.",
            flush=True,
        )
    except Exception as e:
        print(f"Sync error: {e}", flush=True)

    print(f"Logged in as {bot.user}", flush=True)


# ========= Slash 指令 =========


@bot.tree.command(
    name="my_favorites",
    description="查看你收藏的成員",
    guild=discord.Object(id=GUILD_ID),
)
async def my_favorites(interaction: discord.Interaction):
    customer_id = str(interaction.user.id)
    favorites = list_customer_favorites(customer_id, limit=25)
    embed = build_customer_favorites_embed(customer_id, favorites)

    if favorites:
        await interaction.response.send_message(
            embed=embed,
            view=CustomerFavoritesView(customer_id, favorites),
            ephemeral=True,
        )
    else:
        await interaction.response.send_message(
            embed=embed,
            ephemeral=True,
        )




@bot.tree.command(
    name="browse_staff_profiles",
    description="瀏覽公開成員個人牆",
    guild=discord.Object(id=GUILD_ID),
)
@app_commands.describe(
    keyword="可搜尋名稱、遊戲、服務或階級，可不填"
)
async def browse_staff_profiles(
    interaction: discord.Interaction,
    keyword: str | None = None,
):
    keyword_text = str(keyword or "").strip()[:60]
    view = PublicStaffProfileBrowseView(
        interaction.user.id,
        keyword=keyword_text,
        page=0,
        page_size=10,
    )

    if view.children:
        await interaction.response.send_message(
            embed=view.build_embed(),
            view=view,
            ephemeral=True,
            allowed_mentions=discord.AllowedMentions(users=False, roles=False, everyone=False),
        )
    else:
        await interaction.response.send_message(
            embed=view.build_embed(),
            ephemeral=True,
            allowed_mentions=discord.AllowedMentions(users=False, roles=False, everyone=False),
        )



@bot.tree.command(
    name="fix_acceptance_payment_panel",
    description="客服補送等待接單滿人後的付款 panel",
    guild=discord.Object(id=GUILD_ID),
)
@app_commands.describe(
    order_id="WEB 訂單 ID，可不填；不填時會使用目前票口最新等待付款訂單"
)
@app_commands.default_permissions(manage_messages=True)
async def fix_acceptance_payment_panel(
    interaction: discord.Interaction,
    order_id: int | None = None,
):
    if not _require_customer_staff_or_manager(interaction):
        await interaction.response.send_message("只有客服、店長或管理員可以補送付款 panel。", ephemeral=True)
        return

    if interaction.guild is None:
        await interaction.response.send_message("這個功能只能在伺服器內使用。", ephemeral=True)
        return

    target_order_id = order_id

    if target_order_id is None:
        if not isinstance(interaction.channel, discord.TextChannel):
            await interaction.response.send_message("請在票口內使用，或手動輸入 WEB 訂單 ID。", ephemeral=True)
            return

        import sqlite3
        db_path = Path(__file__).parent / "web_dashboard.db"
        conn = sqlite3.connect(db_path, timeout=15)
        conn.row_factory = sqlite3.Row
        try:
            row = conn.execute(
                """
                SELECT id
                FROM web_orders
                WHERE ticket_channel_id = ?
                  AND status IN ('accepted_pending_pay', 'waiting_acceptance')
                ORDER BY id DESC
                LIMIT 1
                """,
                (str(interaction.channel.id),),
            ).fetchone()
        finally:
            conn.close()

        if row is None:
            await interaction.response.send_message(
                "目前票口找不到等待接單 / 等待付款的 WEB 訂單，請手動輸入 order_id。",
                ephemeral=True,
            )
            return

        target_order_id = int(row["id"])

    await interaction.response.defer(ephemeral=True)

    ok, message = await restore_acceptance_payment_panel_for_order(
        interaction.guild,
        int(target_order_id),
        reason=f"manual_by_{interaction.user.id}",
    )

    await interaction.followup.send(message, ephemeral=True)




@bot.tree.command(
    name="staff_profile_panel",
    description="客服在成員個人牆貼文內生成或更新成員 panel",
    guild=discord.Object(id=GUILD_ID),
)
@app_commands.describe(
    member="這個個人牆對應的成員",
    role_title="階級，例如：護航、女護、頂護",
    games="主要遊戲，例如：三角洲",
    services="服務類型，例如：護航 / 技術陪",
    bio="個人特色，例如：穩定、報點清楚、耐心",
    profile_type="類型，例如：打手、陪玩、主播",
    display_name="顯示名稱，可不填，預設使用 Discord 暱稱",
)
@app_commands.default_permissions(manage_messages=True)
async def staff_profile_panel(
    interaction: discord.Interaction,
    member: discord.Member,
    role_title: str,
    games: str,
    services: str,
    bio: str,
    profile_type: str = "打手",
    display_name: str | None = None,
):
    if not _require_customer_staff_or_manager(interaction):
        await interaction.response.send_message("只有客服、店長或管理員可以建立個人牆 panel。", ephemeral=True)
        return

    channel = interaction.channel
    if channel is None or not hasattr(channel, "send"):
        await interaction.response.send_message("請在成員個人牆貼文或文字頻道內使用此指令。", ephemeral=True)
        return

    await interaction.response.defer(ephemeral=True)

    parent_id = None
    if isinstance(channel, discord.Thread):
        parent_id = getattr(channel.parent, "id", None)

    image_url = await find_profile_card_image_url(channel)
    profile = upsert_staff_profile(
        staff_id=member.id,
        display_name=display_name or member.display_name,
        profile_type=profile_type,
        role_title=role_title,
        main_games=games,
        service_tags=services,
        bio=bio,
        card_image_url=image_url,
        forum_thread_id=getattr(channel, "id", None),
        forum_channel_id=parent_id or getattr(channel, "id", None),
        is_public=True,
    )

    old_message_id = 0
    try:
        old_message_id = int(str(profile.get("panel_message_id") or "0"))
    except (TypeError, ValueError):
        old_message_id = 0

    view = StaffProfilePanelView(member.id)
    embed = build_staff_profile_embed(profile)
    panel_message = None
    action_text = "已生成"

    if old_message_id and hasattr(channel, "fetch_message"):
        try:
            panel_message = await channel.fetch_message(old_message_id)
            await panel_message.edit(
                embed=embed,
                view=view,
                allowed_mentions=discord.AllowedMentions(users=False, roles=False, everyone=False),
            )
            action_text = "已更新"
        except (discord.NotFound, discord.Forbidden, discord.HTTPException):
            panel_message = None

    if panel_message is None:
        panel_message = await channel.send(
            embed=embed,
            view=view,
            allowed_mentions=discord.AllowedMentions(users=False, roles=False, everyone=False),
        )
        action_text = "已生成"

    save_staff_profile_panel_message(
        staff_id=member.id,
        panel_message_id=panel_message.id,
        forum_thread_id=getattr(channel, "id", None),
        forum_channel_id=parent_id or getattr(channel, "id", None),
    )

    try:
        bot.add_view(StaffProfilePanelView(member.id), message_id=panel_message.id)
    except ValueError:
        pass

    image_note = "已抓到貼文圖片作為名片圖。" if image_url else "沒有抓到圖片；panel 仍已建立，可之後重新執行指令更新。"
    await interaction.followup.send(
        f"{action_text} {member.mention} 的個人牆 panel。\n{image_note}",
        ephemeral=True,
        allowed_mentions=discord.AllowedMentions(users=False, roles=False, everyone=False),
    )









async def _fetch_staff_profile_panel_target(guild: discord.Guild, profile: dict):
    channel_id_text = str(
        profile.get("forum_thread_id")
        or profile.get("forum_channel_id")
        or ""
    ).strip()
    message_id_text = str(profile.get("panel_message_id") or "").strip()

    if not channel_id_text or not message_id_text:
        return None, None, "這位成員還沒有記錄個人牆 panel 位置，請先在個人牆貼文內使用 /staff_profile_panel。"

    try:
        channel_id = int(channel_id_text)
        message_id = int(message_id_text)
    except (TypeError, ValueError):
        return None, None, "個人牆 panel 位置資料格式錯誤，請重新使用 /staff_profile_panel 生成一次。"

    channel = None

    try:
        get_thread = getattr(guild, "get_thread", None)
        if callable(get_thread):
            channel = get_thread(channel_id)

        if channel is None:
            channel = guild.get_channel(channel_id)

        if channel is None:
            channel = await guild.fetch_channel(channel_id)
    except (discord.NotFound, discord.Forbidden, discord.HTTPException):
        channel = None

    if channel is None or not hasattr(channel, "fetch_message"):
        return None, None, "找不到原本的個人牆頻道或貼文，請確認貼文是否還存在。"

    try:
        message = await channel.fetch_message(message_id)
    except discord.NotFound:
        return channel, None, "找不到原本的個人牆 panel 訊息，請重新使用 /staff_profile_panel 生成一次。"
    except discord.Forbidden:
        return channel, None, "Bot 沒有權限讀取或編輯原本的個人牆 panel。"
    except discord.HTTPException as e:
        return channel, None, f"讀取個人牆 panel 失敗：{e}"

    return channel, message, None


@bot.tree.command(
    name="refresh_staff_profile_panel",
    description="將後台個人牆資料同步到 Discord panel",
    guild=discord.Object(id=GUILD_ID),
)
@app_commands.describe(
    member="要同步個人牆 panel 的成員"
)
@app_commands.default_permissions(manage_messages=True)
async def refresh_staff_profile_panel(
    interaction: discord.Interaction,
    member: discord.Member,
):
    if not _require_customer_staff_or_manager(interaction):
        await interaction.response.send_message("只有客服、店長或管理員可以同步個人牆 panel。", ephemeral=True)
        return

    if interaction.guild is None:
        await interaction.response.send_message("這個指令只能在伺服器內使用。", ephemeral=True)
        return

    await interaction.response.defer(ephemeral=True)

    profile = get_staff_profile(member.id)

    if profile is None:
        await interaction.followup.send(
            "找不到這位成員的個人牆資料，請先建立 /staff_profile_panel。",
            ephemeral=True,
        )
        return

    channel, panel_message, error_message = await _fetch_staff_profile_panel_target(
        interaction.guild,
        profile,
    )

    if error_message:
        await interaction.followup.send(error_message, ephemeral=True)
        return

    view = StaffProfilePanelView(member.id)
    embed = build_staff_profile_embed(profile)

    try:
        await panel_message.edit(
            embed=embed,
            view=view,
            allowed_mentions=discord.AllowedMentions(users=False, roles=False, everyone=False),
        )
    except discord.Forbidden:
        await interaction.followup.send("Bot 沒有權限編輯這則個人牆 panel。", ephemeral=True)
        return
    except discord.HTTPException as e:
        await interaction.followup.send(f"同步個人牆 panel 失敗：{e}", ephemeral=True)
        return

    parent_id = None
    if isinstance(channel, discord.Thread):
        parent_id = getattr(channel.parent, "id", None)

    save_staff_profile_panel_message(
        staff_id=member.id,
        panel_message_id=panel_message.id,
        forum_thread_id=getattr(channel, "id", None),
        forum_channel_id=parent_id or getattr(channel, "id", None),
    )

    try:
        bot.add_view(StaffProfilePanelView(member.id), message_id=panel_message.id)
    except ValueError:
        pass

    await interaction.followup.send(
        f"已同步 {member.mention} 的個人牆 panel。\n"
        "後台資料已更新到 Discord 訊息；收藏、指定下單、查看評價按鈕也已重新掛上。",
        ephemeral=True,
        allowed_mentions=discord.AllowedMentions(users=False, roles=False, everyone=False),
    )


# ========= 點數兌換面板 =========

POINT_REDEEM_ITEMS = [
    {"key": "discount_20", "cost": 5, "name": "20 元折價券"},
    {"key": "discount_30", "cost": 10, "name": "30 元折價券"},
    {"key": "extra_10", "cost": 15, "name": "加時 30 分鐘"},
    {"key": "extra_15", "cost": 20, "name": "加場一場保撤"},
    {"key": "free_specify_fee", "cost": 25, "name": "免指定費 1 次"},
    {"key": "discount_100", "cost": 30, "name": "100 元折價券"},
    {"key": "extra_30", "cost": 40, "name": "加時一小時"},
]

POINT_REDEEM_ITEMS_BY_KEY = {
    item["key"]: item
    for item in POINT_REDEEM_ITEMS
}

POINT_REDEEM_ITEMS_BY_KEY.setdefault(
    "free_play_1h",
    dict(
        key="free_play_1h",
        cost=80,
        name="免費陪玩 1 小時",
    ),
)

_REWARD_REDEEM_SELECTIONS: dict[tuple[int, int], str] = {}


def build_reward_redeem_embed() -> discord.Embed:
    lines = [
        f"**{item['cost']} 點**｜{item['name']}"
        for item in POINT_REDEEM_ITEMS
    ]

    embed = discord.Embed(
        title="🎁 魔丸點數兌換",
        description=(
            "請先使用下拉式清單選擇要兌換的項目，再按下「兌換」。\n\n"
            + "\n".join(lines)
        ),
        color=discord.Color.gold(),
    )
    embed.set_footer(text="兌換成功後會自動扣除點數，並寫入顧客備註。")
    return embed


def append_reward_redeem_customer_note(
    data: dict,
    *,
    user_id: int,
    cost: int,
    reward_name: str,
    before_points: int,
    after_points: int,
) -> None:
    now_text = get_taipei_now_iso()
    note_text = (
        f"點數兌換：{cost} 點，{reward_name} "
        f"｜兌換前 {before_points} 點，兌換後 {after_points} 點"
    )

    notes = data.setdefault("notes", [])

    if not isinstance(notes, list):
        notes = []
        data["notes"] = notes

    notes.append(
        {
            "created_at": now_text,
            "created_by": int(user_id),
            "author_id": int(user_id),
            "operator_id": int(user_id),
            "content": note_text,
            "note": note_text,
            "source": "point_redeem",
        }
    )


class RewardRedeemSelect(discord.ui.Select):
    def __init__(self):
        options = [
            discord.SelectOption(
                label=f"{item['cost']} 點｜{item['name']}",
                value=item["key"],
                description=f"兌換 {item['name']}",
            )
            for item in POINT_REDEEM_ITEMS
        ]

        super().__init__(
            placeholder="選擇要兌換的項目",
            min_values=1,
            max_values=1,
            options=options,
            custom_id="reward_redeem_select",
        )

    async def callback(self, interaction: discord.Interaction):
        selected_key = self.values[0]
        item = POINT_REDEEM_ITEMS_BY_KEY.get(selected_key)

        if item is None:
            await interaction.response.send_message("找不到這個兌換項目，請重新選擇。", ephemeral=True)
            return

        message_id = interaction.message.id if interaction.message else 0
        _REWARD_REDEEM_SELECTIONS[(int(message_id), int(interaction.user.id))] = selected_key

        await interaction.response.send_message(
            f"已選擇：**{item['cost']} 點｜{item['name']}**\n確認後請按「兌換」。",
            ephemeral=True,
        )


class RewardRedeemView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(RewardRedeemSelect())

    @discord.ui.button(
        label="兌換",
        style=discord.ButtonStyle.success,
        custom_id="reward_redeem_confirm_button",
    )
    async def redeem_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not isinstance(interaction.user, discord.Member):
            await interaction.response.send_message("這個功能只能在伺服器內使用。", ephemeral=True)
            return

        message_id = interaction.message.id if interaction.message else 0
        selected_key = _REWARD_REDEEM_SELECTIONS.get((int(message_id), int(interaction.user.id)))

        if not selected_key:
            await interaction.response.send_message("請先用下拉式清單選擇要兌換的項目。", ephemeral=True)
            return

        item = POINT_REDEEM_ITEMS_BY_KEY.get(selected_key)

        if item is None:
            await interaction.response.send_message("找不到這個兌換項目，請重新選擇。", ephemeral=True)
            return

        cost = int(item["cost"])
        reward_name = str(item["name"])

        data = get_customer_reward_data(interaction.user.id)
        before_points = int(get_current_reward_points(data))

        if before_points < cost:
            await interaction.response.send_message(
                f"你的點數不足。\n目前點數：**{before_points} 點**\n需要點數：**{cost} 點**",
                ephemeral=True,
            )
            return

        data["point_adjustment"] = int(data.get("point_adjustment", 0) or 0) - cost
        after_points = int(get_current_reward_points(data))
        data["points"] = after_points

        point_logs = data.setdefault("point_adjustment_logs", [])

        if not isinstance(point_logs, list):
            point_logs = []
            data["point_adjustment_logs"] = point_logs

        point_logs.append(
            {
                "created_at": get_taipei_now_iso(),
                "operator_id": int(interaction.user.id),
                "operator_name": str(interaction.user),
                "delta": -cost,
                "reason": f"點數兌換：{reward_name}",
                "before_points": before_points,
                "after_points": after_points,
            }
        )

        append_reward_redeem_customer_note(
            data,
            user_id=interaction.user.id,
            cost=cost,
            reward_name=reward_name,
            before_points=before_points,
            after_points=after_points,
        )

        save_bot_data()
        _REWARD_REDEEM_SELECTIONS.pop((int(message_id), int(interaction.user.id)), None)

        await interaction.response.send_message(
            (
                f"兌換成功：**{reward_name}**\n"
                f"已扣除：**{cost} 點**\n"
                f"剩餘點數：**{after_points} 點**\n"
                "兌換紀錄已寫入你的顧客備註。"
            ),
            ephemeral=True,
        )


@bot.tree.command(name="reward_redeem_panel", description="發送會員點數兌換面板")
async def reward_redeem_panel(interaction: discord.Interaction):
    if not isinstance(interaction.user, discord.Member) or not is_customer_staff(interaction.user):
        await interaction.response.send_message("只有客服可以發送點數兌換面板。", ephemeral=True)
        return

    if interaction.channel is None or not hasattr(interaction.channel, "send"):
        await interaction.response.send_message("請在文字頻道使用這個指令。", ephemeral=True)
        return

    await interaction.response.defer(ephemeral=True)

    await interaction.channel.send(
        embed=build_reward_redeem_embed(),
        view=RewardRedeemView(),
        allowed_mentions=discord.AllowedMentions(
            users=False,
            roles=False,
            everyone=False,
        ),
    )

    await interaction.followup.send("已發送點數兌換面板。", ephemeral=True)

# ========= end 點數兌換面板 =========


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



@bot.tree.command(
    name="wallet_add",
    description="客服幫顧客錢包儲值",
    guild=discord.Object(id=GUILD_ID)
)
@app_commands.describe(
    customer="要儲值的顧客",
    amount="儲值金額，只能輸入正數",
    note="備註，例如街口儲值、轉帳儲值"
)
@app_commands.default_permissions(manage_messages=True)
async def wallet_add(
    interaction: discord.Interaction,
    customer: discord.Member,
    amount: int,
    note: str | None = None,
):
    if not _require_customer_staff_or_manager(interaction):
        await interaction.response.send_message("只有客服、店長或管理員可以操作錢包。", ephemeral=True)
        return

    if amount <= 0:
        await interaction.response.send_message("儲值金額必須大於 0。", ephemeral=True)
        return

    tx = adjust_customer_wallet_balance(
        customer_id=customer.id,
        amount=amount,
        tx_type="topup",
        operator=interaction.user,
        note=note or "客服儲值",
    )

    embed = build_customer_info_with_wallet_embed(customer, show_staff_notes=True)
    embed.title = "錢包儲值完成"

    await interaction.response.send_message(embed=embed, ephemeral=True)
    await send_wallet_log(interaction.guild, title="錢包儲值", customer=customer, operator=interaction.user, tx=tx)


@bot.tree.command(
    name="wallet_adjust",
    description="客服修正顧客錢包餘額，基於目前餘額加減",
    guild=discord.Object(id=GUILD_ID)
)
@app_commands.describe(
    customer="要修正錢包的顧客",
    amount="異動金額，可正可負，例如 500 或 -300",
    note="修正原因"
)
@app_commands.default_permissions(manage_messages=True)
async def wallet_adjust(
    interaction: discord.Interaction,
    customer: discord.Member,
    amount: int,
    note: str | None = None,
):
    if not _require_customer_staff_or_manager(interaction):
        await interaction.response.send_message("只有客服、店長或管理員可以操作錢包。", ephemeral=True)
        return

    if amount == 0:
        await interaction.response.send_message("異動金額不能為 0。", ephemeral=True)
        return

    try:
        tx = adjust_customer_wallet_balance(
            customer_id=customer.id,
            amount=amount,
            tx_type="adjustment",
            operator=interaction.user,
            note=note or "客服修正",
        )
    except ValueError as e:
        await interaction.response.send_message(str(e), ephemeral=True)
        return

    embed = build_customer_info_with_wallet_embed(customer, show_staff_notes=True)
    embed.title = "錢包餘額已修正"

    await interaction.response.send_message(embed=embed, ephemeral=True)
    await send_wallet_log(interaction.guild, title="錢包餘額修正", customer=customer, operator=interaction.user, tx=tx)


@bot.tree.command(
    name="wallet_refund",
    description="客服手動退回顧客錢包餘額",
    guild=discord.Object(id=GUILD_ID)
)
@app_commands.describe(
    customer="要退款的顧客",
    amount="退款金額，只能輸入正數",
    note="退款原因"
)
@app_commands.default_permissions(manage_messages=True)
async def wallet_refund(
    interaction: discord.Interaction,
    customer: discord.Member,
    amount: int,
    note: str | None = None,
):
    if not _require_customer_staff_or_manager(interaction):
        await interaction.response.send_message("只有客服、店長或管理員可以操作錢包。", ephemeral=True)
        return

    if amount <= 0:
        await interaction.response.send_message("退款金額必須大於 0。", ephemeral=True)
        return

    tx = adjust_customer_wallet_balance(
        customer_id=customer.id,
        amount=amount,
        tx_type="refund",
        operator=interaction.user,
        note=note or "客服退款",
    )

    embed = build_customer_info_with_wallet_embed(customer, show_staff_notes=True)
    embed.title = "錢包退款完成"

    await interaction.response.send_message(embed=embed, ephemeral=True)
    await send_wallet_log(interaction.guild, title="錢包退款", customer=customer, operator=interaction.user, tx=tx)



@bot.tree.command(
    name="wallet_history",
    description="客服查詢顧客錢包流水",
    guild=discord.Object(id=GUILD_ID)
)
@app_commands.describe(
    customer="要查詢的顧客",
    limit="顯示最近幾筆，最多 25 筆"
)
@app_commands.default_permissions(manage_messages=True)
async def wallet_history(
    interaction: discord.Interaction,
    customer: discord.Member,
    limit: int = 10,
):
    if not _require_customer_staff_or_manager(interaction):
        await interaction.response.send_message("只有客服、店長或管理員可以查詢錢包流水。", ephemeral=True)
        return

    embed = build_wallet_history_embed(customer, limit=limit, staff_view=True)
    await interaction.response.send_message(embed=embed, ephemeral=True)


@bot.tree.command(
    name="my_wallet_history",
    description="查詢自己的錢包流水",
    guild=discord.Object(id=GUILD_ID)
)
@app_commands.describe(limit="顯示最近幾筆，最多 25 筆")
async def my_wallet_history(
    interaction: discord.Interaction,
    limit: int = 10,
):
    if not isinstance(interaction.user, discord.Member):
        await interaction.response.send_message("無法確認你的伺服器身分。", ephemeral=True)
        return

    embed = build_wallet_history_embed(interaction.user, limit=limit, staff_view=False)
    await interaction.response.send_message(embed=embed, ephemeral=True)


@bot.tree.command(
    name="wallet_refund_order",
    description="客服針對指定訂單手動退款到顧客錢包",
    guild=discord.Object(id=GUILD_ID)
)
@app_commands.describe(
    customer="要退款的顧客",
    order_no="訂單編號，例如 MO20260610001",
    amount="退款金額，只能輸入正數",
    note="退款原因"
)
@app_commands.default_permissions(manage_messages=True)
async def wallet_refund_order(
    interaction: discord.Interaction,
    customer: discord.Member,
    order_no: str,
    amount: int,
    note: str | None = None,
):
    if not _require_customer_staff_or_manager(interaction):
        await interaction.response.send_message("只有客服、店長或管理員可以操作錢包退款。", ephemeral=True)
        return

    order_no = str(order_no or "").strip()

    if not order_no:
        await interaction.response.send_message("請填寫訂單編號。", ephemeral=True)
        return

    if amount <= 0:
        await interaction.response.send_message("退款金額必須大於 0。", ephemeral=True)
        return

    refund_note = str(note or "").strip() or f"訂單 {order_no} 手動退款"

    tx = adjust_customer_wallet_balance(
        customer_id=customer.id,
        amount=amount,
        tx_type="refund",
        operator=interaction.user,
        order_no=order_no,
        note=refund_note,
    )

    embed = build_wallet_history_embed(customer, limit=5, staff_view=True)
    embed.title = "訂單退款已加回錢包"
    embed.add_field(name="退款訂單", value=f"`{order_no}`", inline=True)
    embed.add_field(name="退款金額", value=format_t_amount(amount), inline=True)

    await interaction.response.send_message(embed=embed, ephemeral=True)
    await send_wallet_log(
        interaction.guild,
        title="錢包訂單退款",
        customer=customer,
        operator=interaction.user,
        tx=tx,
    )



@bot.tree.command(
    name="my_info",
    description="查詢自己的會員資訊、點數與錢包餘額",
    guild=discord.Object(id=GUILD_ID)
)
async def my_info(interaction: discord.Interaction):
    if not isinstance(interaction.user, discord.Member):
        await interaction.response.send_message("無法確認你的伺服器身分。", ephemeral=True)
        return

    embed = build_customer_info_with_wallet_embed(interaction.user, show_staff_notes=False)
    await interaction.response.send_message(embed=embed, ephemeral=True)



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




def sync_web_order_cancelled_from_bot(
    ticket_channel_id,
    dispatch_message_id=None,
    note: str | None = None,
    *,
    actor_discord_id: str | int | None = None,
    cancellation_reason_code: str | None = None,
    cancellation_reason_text: str | None = None,
) -> None:
    """DC bot 刪除/取消訂單後，把網站訂單狀態同步成 cancelled，並同步付款前接單 lifecycle。"""
    try:
        close_support_calls_for_ticket(
            ticket_channel_id,
            reason="order_cancelled",
        )
    except Exception as exc:
        print(
            f"[support-call] cancel cleanup failed "
            f"ticket_channel_id={ticket_channel_id}: {exc}",
            flush=True,
        )
    try:
        from shared.web_order_sync import update_web_order_status_by_ticket_channel

        ok = update_web_order_status_by_ticket_channel(
            ticket_channel_id=ticket_channel_id,
            status="cancelled",
            dispatch_message_id=dispatch_message_id,
            note=note or "由 DC bot 刪除/取消訂單同步。",
            actor_discord_id=actor_discord_id,
            cancellation_reason_code=cancellation_reason_code,
            cancellation_reason_text=cancellation_reason_text,
        )
        print(
            f"[web-sync] cancel order "
            f"ticket_channel_id={ticket_channel_id} "
            f"dispatch_message_id={dispatch_message_id} ok={ok}"
        )

        if not ok:
            return

        order_id = None

        try:
            from shared.db import SessionLocal
            from shared.models import WebOrder

            db = SessionLocal()

            try:
                order = (
                    db.query(WebOrder)
                    .filter(WebOrder.ticket_channel_id == str(ticket_channel_id))
                    .first()
                )

                if order is None and ticket_channel_id is not None:
                    order = (
                        db.query(WebOrder)
                        .filter(WebOrder.ticket_channel_id == ticket_channel_id)
                        .first()
                    )

                if order is None and dispatch_message_id is not None:
                    order = (
                        db.query(WebOrder)
                        .filter(WebOrder.dispatch_message_id == str(dispatch_message_id))
                        .first()
                    )

                if order is None and dispatch_message_id is not None:
                    order = (
                        db.query(WebOrder)
                        .filter(WebOrder.dispatch_message_id == dispatch_message_id)
                        .first()
                    )

                if order is not None:
                    order_id = int(order.id)

            finally:
                db.close()

        except Exception as exc:
            print(f"[web-sync] cancel order lookup failed ticket_channel_id={ticket_channel_id}: {exc}")

        if order_id is not None:
            try:
                from shared.order_acceptance import cancel_acceptance_order, has_acceptance_meta

                if has_acceptance_meta(order_id):
                    cancel_acceptance_order(
                        order_id,
                        source="discord_cancel",
                        actor_discord_id=actor_discord_id,
                        cancellation_reason_code=cancellation_reason_code,
                        cancellation_reason_text=cancellation_reason_text,
                    )
                    print(f"[acceptance] cancelled order_id={order_id} source=discord_cancel")
            except Exception as exc:
                print(f"[acceptance] 取消訂單同步付款前接單狀態失敗 order_id={order_id}: {exc}")

            try:
                credential_ticket_channel = bot.get_channel(_to_int(ticket_channel_id, 0) or 0)
                if not isinstance(credential_ticket_channel, discord.TextChannel):
                    credential_ticket_channel = None
                bot.loop.create_task(
                    revoke_order_credential_messages(
                        order_id,
                        reason="cancelled",
                        ticket_channel=credential_ticket_channel,
                        notify_customer=True,
                    )
                )
            except Exception as exc:
                print(f"[credentials] 取消訂單撤回排程失敗 order_id={order_id}: {exc}")

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
        item_name = str(data.get("item") or "").strip()
        reward_excluded = bool(data.get("reward_excluded")) or item_name == "幣號" or int(data.get("reward_amount", amount) or 0) <= 0
        should_adjust_customer = adjust_customer and is_order_closed_for_rewards(data) and not reward_excluded
        order_count_delta = -1 if should_adjust_customer else 0

        if should_adjust_customer:
            adjust_customer_totals_for_order(customer_id, -amount, order_count_delta)

        dispatch_deleted = False
        if delete_dispatch_panel:
            dispatch_deleted = await delete_dispatch_message_for_order(interaction.guild, data)

        dispatch_message_id = _to_int(data.get("dispatch_message_id"))
        if dispatch_message_id is not None:
            ORDER_CLAIMS.pop(dispatch_message_id, None)
            delete_claim_row_from_db(message_id=dispatch_message_id)

        if _order_requires_credentials(data):
            try:
                from services.order_credentials import get_order_id_by_ticket_channel
                credential_order_id = _to_int(data.get("web_order_id")) or get_order_id_by_ticket_channel(channel_id)
                if credential_order_id is not None:
                    original_ticket_channel = interaction.guild.get_channel(channel_id) if interaction.guild is not None else None
                    await revoke_order_credential_messages(
                        credential_order_id,
                        reason="deleted",
                        ticket_channel=original_ticket_channel if isinstance(original_ticket_channel, discord.TextChannel) else None,
                        notify_customer=True,
                    )
            except Exception as exc:
                print(f"[credentials] 手動刪單撤回失敗 channel_id={channel_id}: {exc}")

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
            f"會員同步：{'已扣回' if should_adjust_customer else ('不扣回，因為此訂單未累積 VIP' if reward_excluded else '未扣回 / 不適用')}\n"
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

    resend_status = "active"
    resend_order_id = _to_int(
        data.get("web_order_id"),
        None,
    )
    resend_acceptance_state = None
    resend_smart_dispatch = None
    resend_allowed_role_ids: list[str] = []
    resend_required_game_role_ids: list[str] = []
    resend_specified_staff_ids = [
        str(item)
        for item in data.get("specified_staff_ids") or []
        if str(item).strip()
    ]
    resend_unresolved_specified_ids = list(
        resend_specified_staff_ids
    )

    if (
        str(data.get("status") or "").lower()
        == "waiting_acceptance"
        and resend_order_id is not None
    ):
        try:
            from shared.order_acceptance import (
                WAITING_ACCEPTANCE,
                get_acceptance_state,
            )
            from services.order_rules import (
                get_allowed_role_ids,
                get_required_game_role_ids,
            )

            resend_acceptance_state = get_acceptance_state(
                int(resend_order_id)
            )

            if (
                str(resend_acceptance_state.status)
                == WAITING_ACCEPTANCE
            ):
                resend_status = WAITING_ACCEPTANCE
                resend_rule = _get_rule_from_self_service_data(
                    data
                )
                resend_allowed_role_ids = get_allowed_role_ids(
                    resend_rule
                )
                resend_required_game_role_ids = get_required_game_role_ids(
                    resend_rule
                )
                accepted_ids = {
                    str(claim.staff_discord_id)
                    for claim in resend_acceptance_state.claims
                }
                resend_unresolved_specified_ids = [
                    staff_id
                    for staff_id in resend_specified_staff_ids
                    if staff_id not in accepted_ids
                ]
                remaining_count = max(
                    1,
                    int(
                        resend_acceptance_state.required_staff_count
                        or 1
                    )
                    - int(
                        resend_acceptance_state.accepted_count
                        or 0
                    ),
                )
                resend_smart_dispatch = (
                    prepare_initial_smart_dispatch(
                        guild,
                        customer_id=customer_id,
                        allowed_role_ids=resend_allowed_role_ids,
                        specified_staff_ids=resend_unresolved_specified_ids,
                        required_staff_count=remaining_count,
                        required_game_role_ids=resend_required_game_role_ids,
                        excluded_staff_ids=accepted_ids,
                    )
                )
        except Exception as exc:
            print(
                f"[smart-dispatch] resend prepare failed "
                f"order_id={resend_order_id}: "
                f"{type(exc).__name__}: {exc}",
                flush=True,
            )

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
        status=resend_status,
    )

    dispatch_message = await dispatch_channel.send(
        content=None,
        embed=embed,
        view=view,
        allowed_mentions=discord.AllowedMentions(
            users=True,
            roles=resend_smart_dispatch is not None,
            everyone=False,
        ),
    )

    if resend_smart_dispatch is not None:
        try:
            await send_initial_smart_dispatch_alert(
                guild,
                content=resend_smart_dispatch["content"],
                dispatch_jump_url=dispatch_message.jump_url,
            )
        except (discord.Forbidden, discord.HTTPException) as exc:
            print(f"[smart-dispatch] resend initial alert failed: {exc}", flush=True)

    claim_data = {
        "companion": set(),
        "booster": set(),
        "locked": False,
        "status": resend_status,
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
    data["status"] = resend_status
    data["closed_at"] = None
    data["stored_at"] = None
    data["stored_by"] = None
    data["stored_reason"] = None
    data["stored_expected_time"] = None
    data["stored_note"] = None
    data["dispatch_channel_id"] = dispatch_channel.id
    data["dispatch_message_id"] = dispatch_message.id

    if (
        resend_smart_dispatch is not None
        and resend_order_id is not None
        and resend_acceptance_state is not None
    ):
        try:
            create_smart_dispatch_plan(
                order_id=int(resend_order_id),
                dispatch_channel_id=dispatch_channel.id,
                dispatch_message_id=dispatch_message.id,
                required_staff_count=int(
                    resend_acceptance_state.required_staff_count
                    or 1
                ),
                allowed_role_ids=resend_allowed_role_ids,
                specified_staff_ids=resend_specified_staff_ids,
                required_game_role_ids=resend_required_game_role_ids,
                ranked_candidate_ids=resend_smart_dispatch[
                    "ranked_candidate_ids"
                ],
                notified_candidate_ids=resend_smart_dispatch[
                    "initial_notified_ids"
                ],
                reset_existing=True,
            )

            if resend_unresolved_specified_ids:
                dm_sent_ids, dm_failed_ids = (
                    await send_specified_staff_dispatch_dms(
                        guild,
                        specified_staff_ids=resend_unresolved_specified_ids,
                        category_label=str(category_label),
                        item_label=item,
                        required_staff_count=int(
                            resend_acceptance_state.required_staff_count
                            or 1
                        ),
                        dispatch_jump_url=dispatch_message.jump_url,
                        allowed_role_ids=resend_allowed_role_ids,
                        required_game_role_ids=resend_required_game_role_ids,
                    )
                )
                set_specified_dm_results(
                    int(resend_order_id),
                    sent_ids=dm_sent_ids,
                    failed_ids=dm_failed_ids,
                )
        except Exception as exc:
            print(
                f"[smart-dispatch] resend lifecycle failed "
                f"order_id={resend_order_id}: "
                f"{type(exc).__name__}: {exc}",
                flush=True,
            )

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


def _apply_web_order_wallet_amount_adjustment(
    event: dict,
    payload: dict,
) -> dict | None:
    required_payload_keys = {
        "old_customer_pay_amount",
        "new_customer_pay_amount",
        "old_payment_method",
        "new_payment_method",
        "old_customer_discord_id",
        "new_customer_discord_id",
    }

    # Events created before this rollout did not include enough information to
    # safely reconstruct wallet deltas. Leave them untouched.
    if not required_payload_keys.issubset(payload.keys()):
        return None

    from services.order_wallet_reconciliation import (
        build_wallet_payment_adjustment_plan,
        validate_wallet_net_before_adjustment,
    )
    from services.wallet_service import (
        adjust_wallet_balance,
        find_wallet_transaction,
    )

    plan = build_wallet_payment_adjustment_plan(
        old_amount=int(payload.get("old_customer_pay_amount") or 0),
        new_amount=int(payload.get("new_customer_pay_amount") or 0),
        old_payment_method=payload.get("old_payment_method"),
        new_payment_method=payload.get("new_payment_method"),
        old_customer_id=payload.get("old_customer_discord_id"),
        new_customer_id=payload.get("new_customer_discord_id"),
    )

    if plan is None:
        return None

    event_id = int(event["event_id"])
    order_id = int(
        event.get("order_id")
        or event.get("web_order_id")
        or payload.get("order_id")
        or 0
    )
    if order_id <= 0:
        raise RuntimeError("wallet amount adjustment is missing order_id")

    reference = f"WEB-{order_id}:AMOUNT-ADJ:{event_id}"

    existing = find_wallet_transaction(
        customer_id=plan["customer_id"],
        order_no=reference,
        tx_type="payment_adjustment",
        db_file=DB_FILE,
    )
    if existing is not None:
        if int(existing.get("amount") or 0) != int(plan["amount"]):
            raise RuntimeError(
                "既有 payment_adjustment reference 金額不同，禁止覆寫。"
            )

        print(
            "[amount-sync] wallet adjustment reuse "
            f"event_id={event_id} order=WEB-{order_id} "
            f"tx_id={existing.get('id')}",
            flush=True,
        )
        return existing

    ticket_channel_id = _to_int(
        event.get("ticket_channel_id"),
        None,
    )

    if ticket_channel_id is None:
        raise RuntimeError(
            "錢包訂單金額調整缺少 ticket_channel_id，禁止自動補扣 / 退款。"
        )

    import sqlite3

    net_customer_id = str(
        payload.get("old_customer_discord_id")
        if str(payload.get("old_payment_method") or "").strip() == WALLET_PAYMENT_METHOD
        else plan["customer_id"]
    ).strip()

    with sqlite3.connect(DB_FILE, timeout=15) as conn:
        row = conn.execute(
            """
            SELECT COALESCE(SUM(amount), 0)
            FROM wallet_transactions
            WHERE customer_discord_id = ?
              AND order_channel_id = ?
              AND type IN ('payment', 'payment_adjustment')
            """,
            (
                net_customer_id,
                str(ticket_channel_id),
            ),
        ).fetchone()
        actual_wallet_net = int(row[0] or 0) if row else 0

    validate_wallet_net_before_adjustment(
        old_amount=int(payload.get("old_customer_pay_amount") or 0),
        old_payment_method=payload.get("old_payment_method"),
        actual_wallet_net=actual_wallet_net,
    )

    tx = adjust_wallet_balance(
        customer_id=plan["customer_id"],
        amount=int(plan["amount"]),
        tx_type="payment_adjustment",
        operator_discord_id=payload.get("admin_discord_id"),
        operator_display_name=payload.get("admin_display_name"),
        order_channel_id=ticket_channel_id,
        order_no=reference,
        note=(
            f"後台訂單付款差額調整｜WEB-{order_id}｜"
            f"{plan['old_payment_method'] or '未紀錄'} "
            f"{plan['old_amount']}T → "
            f"{plan['new_payment_method'] or '未紀錄'} "
            f"{plan['new_amount']}T"
        ),
        allow_negative=False,
        db_file=DB_FILE,
    )

    print(
        "[amount-sync] wallet adjustment "
        f"event_id={event_id} order=WEB-{order_id} "
        f"customer={plan['customer_id']} "
        f"delta={plan['amount']} tx_id={tx.get('id')}",
        flush=True,
    )

    return tx


async def _process_web_wallet_reconciliation_event(event: dict) -> None:
    event_id = int(event["event_id"])
    retry_count = int(event.get("retry_count") or 0)

    try:
        try:
            payload = json.loads(event.get("payload_json") or "{}")
        except Exception:
            payload = {}

        tx = _apply_web_order_wallet_amount_adjustment(
            event,
            payload,
        )
        if tx is None:
            raise RuntimeError(
                "wallet reconciliation event did not produce an adjustment"
            )

        _web_sync_mark_event_done(event_id)
        print(
            "[wallet-reconciliation] "
            f"event_id={event_id} order_id={event.get('order_id')} "
            f"tx_id={tx.get('id')} done",
            flush=True,
        )

    except Exception as exc:
        _web_sync_mark_event_failed(
            event_id,
            str(exc),
            retry_count,
        )
        print(
            "[wallet-reconciliation] "
            f"event_id={event_id} failed: "
            f"{type(exc).__name__}: {exc}",
            flush=True,
        )


async def _process_web_order_amount_correction_event(event: dict) -> None:
    event_id = int(event["event_id"])
    retry_count = int(event.get("retry_count") or 0)

    try:
        payload = {}
        try:
            payload = json.loads(event.get("payload_json") or "{}")
        except Exception:
            payload = {}

        # Wallet reconciliation must run even if the Discord-side order state
        # has already been cleaned up. The event reference makes this idempotent.
        _apply_web_order_wallet_amount_adjustment(
            event,
            payload,
        )

        ticket_channel_id = _to_int(event.get("ticket_channel_id"), None)
        new_amount = max(0, int(event.get("amount") or 0))

        # Website-only orders may be edited before the Discord ticket/state exists.
        # Their latest amount will be read when the bot seeds the order later.
        if ticket_channel_id is None:
            _web_sync_mark_event_done(event_id)
            print(
                f"[amount-sync] event_id={event_id} skipped: no ticket channel yet",
                flush=True,
            )
            return

        order_data = SELF_SERVICE_ORDER_SELECTIONS.get(int(ticket_channel_id))

        if not isinstance(order_data, dict):
            _web_sync_mark_event_done(event_id)
            print(
                f"[amount-sync] event_id={event_id} skipped: "
                f"bot order state not found ticket={ticket_channel_id}",
                flush=True,
            )
            return

        reward_result = sync_reward_counted_order_amount(
            order_data,
            new_amount,
        )

        # Keep bot.db / monthly VIP spend / statistics aligned with the web order.
        remember_order_data(int(ticket_channel_id), order_data)

        if (
            reward_result
            and not reward_result.get("reset_preserved")
            and reward_result.get("old_level") != reward_result.get("new_level")
        ):
            guild = bot.get_guild(GUILD_ID)

            if guild is not None:
                member = await fetch_member_safely(
                    guild,
                    int(reward_result["customer_id"]),
                )
                await ensure_reward_member_benefits(
                    guild,
                    member,
                    get_customer_reward_data(
                        int(reward_result["customer_id"])
                    ),
                )

        _web_sync_mark_event_done(event_id)

        if reward_result:
            print(
                "[amount-sync] "
                f"event_id={event_id} ticket={ticket_channel_id} "
                f"amount {reward_result['old_amount']}->{reward_result['new_amount']} "
                f"vip_total {reward_result['old_total_spent']}->{reward_result['new_total_spent']} "
                f"points {reward_result['old_points']}->{reward_result['new_points']} "
                f"level {reward_result['old_level']}->{reward_result['new_level']}",
                flush=True,
            )
        else:
            print(
                "[amount-sync] "
                f"event_id={event_id} ticket={ticket_channel_id} "
                f"order amount {old_order_amount}->{new_amount}; "
                "reward not previously counted",
                flush=True,
            )

    except Exception as exc:
        _web_sync_mark_event_failed(
            event_id,
            str(exc),
            retry_count,
        )
        print(
            f"[amount-sync] event_id={event_id} failed: {type(exc).__name__}: {exc}",
            flush=True,
        )


async def process_one_web_sync_event(
    event: dict,
) -> None:
    event_type = str(
        event.get("event_type")
        or ""
    ).strip().lower()

    if event_type == "order_created":
        await _process_web_order_created_event(
            event
        )
        return

    payload = {}
    try:
        payload = json.loads(event.get("payload_json") or "{}")
    except Exception:
        payload = {}

    from web.app.services.order_service import (
        is_prepay_acceptance_sync_event,
    )

    # 付款前接單有自己的 acceptance worker；一般 web-sync 不得先吃掉事件。
    if is_prepay_acceptance_sync_event(
        event_type,
        payload,
    ):
        return

    if (
        event_type == "order_updated"
        and str(payload.get("sync_kind") or "") == "wallet_reconciliation"
    ):
        await _process_web_wallet_reconciliation_event(
            event
        )
        return

    if (
        event_type == "order_updated"
        and str(payload.get("sync_kind") or "") == "order_amount_correction"
    ):
        await _process_web_order_amount_correction_event(
            event
        )
        return

    await _process_existing_web_sync_event(
        event
    )

async def _refresh_existing_web_sync_dispatch(event: dict) -> None:
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

    # 網頁接單同步到 DC bot 記憶體，讓 Discord 的取消接單按鈕也認得。
    claim_data = ORDER_CLAIMS.setdefault(dispatch_message_id, {})
    claim_data["booster"] = set()
    claim_data["companion"] = set()

    for row in assignments:
        user_id = str(row.get("worker_discord_id") or "").strip()
        role_type = str(row.get("role_type") or "booster").strip()

        if not user_id:
            continue

        try:
            parsed_user_id = int(user_id)
        except Exception:
            continue

        if role_type == "companion":
            claim_data["companion"].add(parsed_user_id)
        else:
            claim_data["booster"].add(parsed_user_id)

    try:
        remember_claim_data(dispatch_message_id, claim_data)
    except Exception as exc:
        print(
            "[web-sync] remember claim data failed "
            f"dispatch_message_id={dispatch_message_id}: {exc}"
        )

    if message.embeds:
        embed = message.embeds[0].copy()
    else:
        embed = discord.Embed(
            title="派單訊息",
            color=discord.Color.blue(),
        )

    embed = _web_sync_embed_without_receiver_fields(embed)
    embed.add_field(
        name="目前接單",
        value=receiver_text,
        inline=False,
    )

    embed = _normalize_dispatch_embed_field_order(embed)

    await message.edit(
        embed=embed,
        allowed_mentions=discord.AllowedMentions(
            users=True,
            roles=False,
            everyone=False,
        ),
    )


async def repair_active_web_sync_dispatch_panels_once(
    *,
    limit: int = 100,
) -> int:
    """Refresh existing active/stored dispatch panels from canonical assignments.

    This is intentionally run once on Bot startup so older messages are rewritten
    with the current receiver presentation instead of keeping stale raw mentions.
    """
    db_path = _web_dashboard_db_path_for_bot()
    conn = sqlite3.connect(db_path, timeout=15)
    conn.row_factory = sqlite3.Row

    try:
        rows = conn.execute(
            """
            SELECT
                id AS order_id,
                dispatch_channel_id,
                dispatch_message_id
            FROM web_orders
            WHERE status IN ('active', 'stored')
              AND dispatch_channel_id IS NOT NULL
              AND TRIM(dispatch_channel_id) <> ''
              AND dispatch_message_id IS NOT NULL
              AND TRIM(dispatch_message_id) <> ''
            ORDER BY id DESC
            LIMIT ?
            """,
            (max(1, int(limit or 100)),),
        ).fetchall()
    finally:
        conn.close()

    repaired = 0

    for row in rows:
        event = dict(row)

        try:
            await _refresh_existing_web_sync_dispatch(event)
            repaired += 1
        except discord.NotFound:
            print(
                "[web-sync] startup active dispatch refresh skipped missing message "
                f"order_id={event.get('order_id')} "
                f"message_id={event.get('dispatch_message_id')}",
                flush=True,
            )
        except discord.Forbidden:
            print(
                "[web-sync] startup active dispatch refresh missing permission "
                f"order_id={event.get('order_id')} "
                f"message_id={event.get('dispatch_message_id')}",
                flush=True,
            )
        except Exception as exc:
            print(
                "[web-sync] startup active dispatch refresh failed "
                f"order_id={event.get('order_id')}: "
                f"{type(exc).__name__}: {exc}",
                flush=True,
            )

    return repaired


async def _process_existing_web_sync_event(event: dict) -> None:
    event_id = int(event["event_id"])
    retry_count = int(event.get("retry_count") or 0)

    try:
        await _refresh_existing_web_sync_dispatch(event)
        _web_sync_mark_event_done(event_id)
        print(f"[web-sync] event_id={event_id} done order_id={event.get('order_id')}")
    except Exception as exc:
        _web_sync_mark_event_failed(event_id, str(exc), retry_count)
        print(f"處理網站同步事件失敗 event_id={event_id}：{exc}")



async def web_sync_event_worker() -> None:
    await bot.wait_until_ready()

    print(
        "[web-sync] worker loop running",
        flush=True,
    )

    while not bot.is_closed():
        try:
            events = (
                _web_sync_fetch_pending_events(
                    limit=10
                )
            )

            seen_event_ids = set()

            for event in events:
                event_id = int(
                    event.get(
                        "event_id"
                    )
                    or 0
                )

                if event_id:
                    seen_event_ids.add(
                        event_id
                    )

                await process_one_web_sync_event(
                    event
                )

            # 3C-3A 測試期間可能已有
            # ORDER_CREATED 被舊 worker 標成 failed。
            # 只恢復 created event，不動其他 failed event。
            retry_events = (
                _web_order_created_fetch_retry_events(
                    limit=10
                )
            )

            for event in retry_events:
                event_id = int(
                    event.get(
                        "event_id"
                    )
                    or 0
                )

                if (
                    event_id
                    and event_id
                    in seen_event_ids
                ):
                    continue

                await process_one_web_sync_event(
                    event
                )

        except Exception as exc:
            print(
                "[web-sync] 背景處理器失敗："
                f"{type(exc).__name__}: {exc}",
                flush=True,
            )

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
        receiver_lines.extend(f"<@{user_id}>" for user_id in companion_ids)
    if booster_ids:
        receiver_lines.extend(f"<@{user_id}>" for user_id in booster_ids)

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
        name="狀態",
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
        self.cancellation_reason_code = "unspecified"
        self.add_item(OrderCancellationReasonSelect())

    @discord.ui.button(label="確認取消存單", style=discord.ButtonStyle.danger)
    async def confirm_cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not _require_customer_staff_or_manager(interaction):
            await interaction.response.send_message("只有客服、店長或管理員可以取消存單。", ephemeral=True)
            return
        if interaction.guild is None:
            await interaction.response.send_message("這個功能只能在伺服器內使用。", ephemeral=True)
            return

        if self.cancellation_reason_code == "unspecified":
            await interaction.response.send_message(
                "請先從下拉選單選擇取消原因。",
                ephemeral=True,
            )
            return

        channel = interaction.guild.get_channel(self.order_channel_id)
        await interaction.response.defer(ephemeral=True)

        await delete_dispatch_claim_panel_for_order(
            interaction.guild,
            self.order_channel_id,
            actor_discord_id=interaction.user.id,
            cancellation_reason_code=self.cancellation_reason_code,
        )

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


# 註冊 bot.py 裡的 top-level slash 指令群組
try:
    bot.tree.add_command(order_group)
except app_commands.CommandAlreadyRegistered:
    pass
try:
    bot.tree.add_command(vip_group)
except app_commands.CommandAlreadyRegistered:
    pass


# Bind extracted legacy runtime adapters only after bot.py has defined all
# remaining Views/callbacks they depend on. The extracted modules never import
# bot.py directly, avoiding a circular import during startup.
configure_acceptance_runtime(globals())
configure_web_sync_runtime(globals())
configure_order_runtime(globals())
configure_self_service_runtime(globals())

bot.run(TOKEN)
