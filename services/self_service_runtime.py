from __future__ import annotations

from dataclasses import dataclass
import json

import discord

from core.database import (
    delete_claim_row_from_db,
    delete_order_row_from_db,
    remember_claim_data,
    remember_order_data,
    save_bot_data,
)
from core.permissions import can_operate_self_service_order, is_customer_staff
from core.time_utils import get_taipei_now_iso
from core.vip_levels import get_vip_discount_pay_rate
from services.acceptance.runtime import _member_display_name
from services.logging_service import send_order_log
from services.order_discounts import allocate_store_absorbed_fixed_discount
from services.order_dispatch_runtime import DispatchClaimView
from services.order_runtime import (
    SelfServiceOrderCategorySelect,
    SelfServiceOrderDetailSelect,
    SelfServiceOrderItemSelect,
    SelfServiceOrderQuantitySelect,
    _get_order_rule_by_item_label,
    _self_service_quantity_meta,
    get_self_service_quantity_unit,
    log_self_service_proxy_action,
    normalize_self_service_staff_count,
)
from services.orders import (
    ORDER_CATEGORY_LABELS,
    ORDER_ITEM_GROUPS_BY_CATEGORY,
    ORDER_ITEM_TO_CATEGORY,
    _to_int,
    build_self_service_order_embed,
    get_order_item_detail_for_selection,
    get_order_item_details_for_group,
    get_order_item_group_label,
    get_self_service_quantity_meta,
)
from services.rewards import (
    get_current_reward_points,
    get_customer_reward_data,
    get_effective_member_level,
)
from services.smart_dispatch import create_smart_dispatch_plan, set_specified_dm_results
from services.ticket_identity import build_ticket_channel_name
from views.review import configure_reorder_ticket_creator
from views.smart_dispatch import (
    prepare_initial_smart_dispatch,
    send_initial_smart_dispatch_alert,
    send_specified_staff_dispatch_dms,
)
from services.self_service_retract import (
    SelfServiceDispatchedView,
    retract_self_service_dispatch,
)
from services.self_service_dispatch_cleanup import cleanup_failed_self_service_dispatch
from services.self_service_dispatch_runtime import (
    SelfServiceDispatchDeps,
    create_waiting_acceptance_order as create_self_service_waiting_acceptance_order,
)

from services.self_service_financials import (
    configure_self_service_financials,
    _adapt_order_point_benefit_for_rule,
    _format_percent_value,
    _format_plain_amount,
    _format_point_hours,
    _parse_cash_amount_text,
    _parse_discount_percent_text,
    _price_int,
    _price_rate,
    _price_snapshot,
    _quote_preview_lines_for_self_service,
    _resolve_manual_discount_rate_percent,
    _resolve_self_service_discount_rate,
    add_self_service_financial_breakdown_fields,
    add_self_service_quote_preview,
    apply_manual_price_adjustment_to_order_data,
    apply_self_service_financials_to_order_data,
    calculate_manual_price_adjustment,
    calculate_self_service_financials,
    get_customer_point_balance_for_order,
    get_order_point_item,
    get_selected_order_point_benefit,
    get_self_service_staff_price,
    is_order_point_benefit_allowed_for_rule,
    is_self_service_staff_price_required,
)

from services.self_service_selection_runtime import (
    configure_self_service_selection_runtime,
    FREE_PLAY_FIRST_HOUR_RULE_KEYS,
    ORDER_POINT_BENEFIT_SPECS,
    get_specified_staff_entries_for_rule,
    SelfServicePointBenefitView,
    SelfServiceSpecifiedStaffDropdownView,
)

from services.self_service_reorder import (
    configure_self_service_reorder,
    _reorder_order_value,
    _reorder_json_dict,
    build_reorder_self_service_draft,
    _reorder_message_has_component,
    _find_reorder_panel_message,
    ensure_reorder_ticket_panels,
    create_reorder_ticket_from_closed_order,
)

from services.self_service_ui_runtime import (
    PRICE_FORMULA_VERSION,
    SelfServiceOrderView,
    SelfServicePlayerCountModal,
    SelfServiceStaffDiscountCouponModal,
    SelfServiceStaffPriceModal,
    SelfServiceSubmitNoteModal,
    build_self_service_panel_embed,
    configure_self_service_ui_runtime,
)

# Dependencies with a stable owning module are imported directly above and must not
# be replaced by bot.py namespace injection. Keeping this allow-list explicit lets
# us catch future regressions where a module-owned dependency leaks back into the
# startup boundary.
_MODULE_OWNED_RUNTIME_NAMES = frozenset(
    {
        "discord",
        "json",
        "ORDER_CATEGORY_LABELS",
        "ORDER_ITEM_GROUPS_BY_CATEGORY",
        "ORDER_ITEM_TO_CATEGORY",
        "_to_int",
        "build_self_service_order_embed",
        "get_order_item_detail_for_selection",
        "get_order_item_details_for_group",
        "get_order_item_group_label",
        "get_self_service_quantity_meta",
        "delete_claim_row_from_db",
        "delete_order_row_from_db",
        "remember_claim_data",
        "remember_order_data",
        "save_bot_data",
        "can_operate_self_service_order",
        "is_customer_staff",
        "get_taipei_now_iso",
        "get_vip_discount_pay_rate",
        "_member_display_name",
        "send_order_log",
        "allocate_store_absorbed_fixed_discount",
        "DispatchClaimView",
        "SelfServiceOrderCategorySelect",
        "SelfServiceOrderDetailSelect",
        "SelfServiceOrderItemSelect",
        "SelfServiceOrderQuantitySelect",
        "_get_order_rule_by_item_label",
        "_self_service_quantity_meta",
        "get_self_service_quantity_unit",
        "log_self_service_proxy_action",
        "normalize_self_service_staff_count",
        "get_current_reward_points",
        "get_customer_reward_data",
        "get_effective_member_level",
        "build_ticket_channel_name",
        "configure_reorder_ticket_creator",
        "create_smart_dispatch_plan",
        "set_specified_dm_results",
        "prepare_initial_smart_dispatch",
        "send_initial_smart_dispatch_alert",
        "send_specified_staff_dispatch_dms",
        "SelfServiceDispatchedView",
        "retract_self_service_dispatch",
        "cleanup_failed_self_service_dispatch",
        "SelfServiceDispatchDeps",
        "create_self_service_waiting_acceptance_order",
    }
)


@dataclass(frozen=True)
class _SelfServiceRuntimeState:
    customer_category_id: int
    customer_role_id: int
    dispatch_channel_id: int
    order_claims: dict
    point_redeem_items: object
    point_redeem_items_by_key: object
    order_selections: dict
    order_control_view_type: object


_CONFIGURED = False
_RUNTIME_STATE: _SelfServiceRuntimeState | None = None


def _require_runtime_state() -> _SelfServiceRuntimeState:
    state = _RUNTIME_STATE
    if state is None:
        raise RuntimeError("self-service runtime is not configured")
    return state


def configure_self_service_runtime_explicit(
    *,
    customer_category_id: int,
    customer_role_id: int,
    dispatch_channel_id: int,
    order_claims: dict,
    point_redeem_items,
    point_redeem_items_by_key,
    order_selections: dict,
    order_control_view_type,
) -> None:
    """Bind the remaining bot-owned self-service dependencies explicitly."""
    global _CONFIGURED, _RUNTIME_STATE

    state = _SelfServiceRuntimeState(
        customer_category_id=customer_category_id,
        customer_role_id=customer_role_id,
        dispatch_channel_id=dispatch_channel_id,
        order_claims=order_claims,
        point_redeem_items=point_redeem_items,
        point_redeem_items_by_key=point_redeem_items_by_key,
        order_selections=order_selections,
        order_control_view_type=order_control_view_type,
    )
    _RUNTIME_STATE = state

    configure_reorder_ticket_creator(create_reorder_ticket_from_closed_order)

    configure_self_service_financials(
        order_point_benefit_specs=ORDER_POINT_BENEFIT_SPECS,
        point_redeem_items_by_key=state.point_redeem_items_by_key,
        get_rule_from_data=_get_rule_from_self_service_data,
        is_specify_preference=_is_specify_preference,
        role_key_for_member=_role_key_for_member,
        to_int=_to_int,
        store_absorbed_discount_allocator=allocate_store_absorbed_fixed_discount,
        current_reward_points=get_current_reward_points,
        customer_reward_data=get_customer_reward_data,
        effective_member_level=get_effective_member_level,
        self_service_quantity_unit=get_self_service_quantity_unit,
        vip_discount_pay_rate=get_vip_discount_pay_rate,
    )

    configure_self_service_reorder(
        order_category_labels=ORDER_CATEGORY_LABELS,
        order_item_groups_by_category=ORDER_ITEM_GROUPS_BY_CATEGORY,
        get_order_rule_by_item_label=_get_order_rule_by_item_label,
        role_key_for_member=_role_key_for_member,
        to_int=_to_int,
        order_item_details_for_group=get_order_item_details_for_group,
        order_item_group_label=get_order_item_group_label,
        self_service_quantity_meta=get_self_service_quantity_meta,
        taipei_now_iso=get_taipei_now_iso,
        staff_price_required=is_self_service_staff_price_required,
        customer_role_id=state.customer_role_id,
        customer_category_id=state.customer_category_id,
        order_control_view=state.order_control_view_type,
        self_service_order_view=SelfServiceOrderView,
        panel_embed_builder=build_self_service_panel_embed,
        self_service_order_selections=state.order_selections,
        remember_data=remember_order_data,
        save_data=save_bot_data,
        ticket_channel_name_builder=build_ticket_channel_name,
        delete_order_row=delete_order_row_from_db,
        order_log_sender=send_order_log,
    )

    configure_self_service_selection_runtime(
        order_selections=state.order_selections,
        point_redeem_items=state.point_redeem_items,
        role_key_for_member=_role_key_for_member,
        remember_data=remember_order_data,
        panel_embed_builder=build_self_service_panel_embed,
        order_view_type=SelfServiceOrderView,
        to_int=_to_int,
        order_point_item_getter=get_order_point_item,
        customer_point_balance_getter=get_customer_point_balance_for_order,
        point_benefit_allowed_for_rule=is_order_point_benefit_allowed_for_rule,
        point_benefit_adapter=_adapt_order_point_benefit_for_rule,
        selected_point_benefit_getter=get_selected_order_point_benefit,
    )

    configure_self_service_ui_runtime(
        order_selections=state.order_selections,
        order_claims=state.order_claims,
        dispatch_channel_id=state.dispatch_channel_id,
        get_rule_from_data=_get_rule_from_self_service_data,
        is_specify_preference=_is_specify_preference,
        create_waiting_order=create_waiting_acceptance_order_from_self_service,
    )

    _CONFIGURED = True


def _extract_discord_ids_from_text(text_value: str) -> list[str]:
    import re

    ids = re.findall(r"\d{15,25}", str(text_value or ""))
    return list(dict.fromkeys(ids))


def _get_rule_from_self_service_data(data: dict):
    try:
        from services.order_rules import ORDER_RULES, get_rule
        from services.orders import ORDER_RULE_KEY_BY_LABEL
    except Exception as exc:
        raise ValueError(f"讀取訂單規則失敗：{exc}") from exc

    rule_key = str(data.get("order_rule_key") or "").strip()
    if rule_key:
        try:
            return get_rule(rule_key)
        except Exception:
            pass

    item_text = str(data.get("item") or "").strip()
    alias_rule_key = ORDER_RULE_KEY_BY_LABEL.get(item_text)
    if alias_rule_key:
        try:
            rule = get_rule(alias_rule_key)
            data["order_rule_key"] = rule.key
            return rule
        except Exception:
            pass

    for rule in ORDER_RULES.values():
        if str(rule.label) == item_text:
            data["order_rule_key"] = rule.key
            return rule

    raise ValueError("找不到這個訂單項目的規則，請重新選擇品項。")


def _is_specify_preference(value: str | None) -> bool:
    text = str(value or "").strip()
    return text in {"指定陪玩/打手", "指定打手"}


def _role_key_for_member(rule, member: discord.Member):
    from services.order_rules import (
        ALL_ROLE_IDS,
        get_allowed_role_ids,
        get_allowed_role_keys,
        get_required_game_role_ids,
        role_ids_match_requirements,
    )

    member_role_ids = {
        str(role.id)
        for role in getattr(member, "roles", [])
        if getattr(role, "id", None) is not None
    }

    if not role_ids_match_requirements(
        member_role_ids,
        get_allowed_role_ids(rule),
        get_required_game_role_ids(rule),
    ):
        return None

    matched = [
        role_key
        for role_key in get_allowed_role_keys(rule)
        if str(ALL_ROLE_IDS.get(role_key)) in member_role_ids
    ]

    if not matched:
        return None

    fee_map = {
        **(getattr(rule, "specify_fee_by_role", {}) or {}),
        **(getattr(rule, "specify_fee_by_game_role", {}) or {}),
    }
    matched.sort(
        key=lambda role_key: int(
            fee_map.get(
                role_key,
                getattr(rule, "specify_fee_default", 0) or 0,
            )
        ),
        reverse=True,
    )
    return matched[0]


async def _resolve_specified_roles_for_price(
    guild: discord.Guild,
    rule,
    specified_staff_ids: list[str],
):
    specified_roles = []
    resolved_mentions = []

    for staff_id in specified_staff_ids:
        try:
            member_id = int(staff_id)
        except (TypeError, ValueError):
            raise ValueError(f"指定人員 ID 無效：{staff_id}")

        member = guild.get_member(member_id)

        if member is None:
            try:
                member = await guild.fetch_member(member_id)
            except Exception:
                member = None

        if member is None:
            raise ValueError(f"找不到指定人員：{staff_id}")

        role_key = _role_key_for_member(rule, member)

        if role_key is None:
            raise ValueError(f"{member.mention} 的職位不符合這張單的可指定 / 可接條件。")

        specified_roles.append(role_key)
        resolved_mentions.append(member.mention)

    return specified_roles, resolved_mentions


async def _defer_and_refresh_self_service_panel(
    interaction: discord.Interaction,
    *,
    customer_id: int,
    channel_id: int,
    data: dict,
):
    try:
        if not interaction.response.is_done():
            await interaction.response.defer()
    except discord.HTTPException:
        pass

    if interaction.message is None:
        try:
            await interaction.followup.send("已更新自助下單選項。", ephemeral=True)
        except discord.HTTPException:
            pass
        return

    try:
        await interaction.message.edit(
            embed=build_self_service_panel_embed(customer_id, data, interaction.guild),
            view=SelfServiceOrderView(
                customer_id=customer_id,
                channel_id=channel_id,
                selected_category=data.get("category"),
            ),
            allowed_mentions=discord.AllowedMentions(users=False, roles=False, everyone=False),
        )
    except Exception as exc:
        print(
            f"[self-service] panel refresh failed channel_id={channel_id}: "
            f"{type(exc).__name__}: {exc}",
            flush=True,
        )
        try:
            await interaction.followup.send(
                "訂單選項已儲存，但面板更新失敗。請再操作一次；若仍發生請通知客服。"
                f"（{type(exc).__name__}）",
                ephemeral=True,
            )
        except discord.HTTPException:
            pass


async def create_waiting_acceptance_order_from_self_service(
    interaction: discord.Interaction,
    *,
    customer_id: int,
    channel_id: int,
) -> str:
    state = _require_runtime_state()
    return await create_self_service_waiting_acceptance_order(
        interaction,
        customer_id=customer_id,
        channel_id=channel_id,
        deps=SelfServiceDispatchDeps(
            dispatch_channel_id=state.dispatch_channel_id,
            order_selections=state.order_selections,
            order_claims=state.order_claims,
            to_int=_to_int,
            get_rule_from_data=_get_rule_from_self_service_data,
            normalize_staff_count=normalize_self_service_staff_count,
            resolve_specified_roles=_resolve_specified_roles_for_price,
            apply_financials=apply_self_service_financials_to_order_data,
            category_labels=ORDER_CATEGORY_LABELS,
            member_display_name=_member_display_name,
            build_order_embed=build_self_service_order_embed,
            format_amount=_format_plain_amount,
            add_financial_fields=add_self_service_financial_breakdown_fields,
            prepare_initial_dispatch=prepare_initial_smart_dispatch,
            dispatch_claim_view=DispatchClaimView,
            remember_order=remember_order_data,
            is_customer_staff=is_customer_staff,
            create_dispatch_plan=create_smart_dispatch_plan,
            send_specified_dms=send_specified_staff_dispatch_dms,
            set_specified_dm_results=set_specified_dm_results,
            now_iso=get_taipei_now_iso,
            remember_claim=remember_claim_data,
            save_data=save_bot_data,
            send_initial_alert=send_initial_smart_dispatch_alert,
            order_log_sender=send_order_log,
            quantity_unit=get_self_service_quantity_unit,
            proxy_logger=log_self_service_proxy_action,
        ),
    )


async def retract_waiting_acceptance_order_from_self_service(
    interaction: discord.Interaction,
    *,
    channel_id: int,
) -> str:
    """Adapter from the legacy self-service runtime into the retract lifecycle."""
    state = _require_runtime_state()
    return await retract_self_service_dispatch(
        interaction,
        channel_id=channel_id,
        order_selections=state.order_selections,
        order_claims=state.order_claims,
        dispatch_channel_id=state.dispatch_channel_id,
        remember_order=remember_order_data,
        save_data=save_bot_data,
        delete_claim_row=delete_claim_row_from_db,
        order_log_sender=send_order_log,
        now_iso=get_taipei_now_iso,
    )