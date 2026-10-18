from __future__ import annotations

from typing import Any

import discord

from core.database import remember_order_data, save_bot_data
from services.orders import (
    ORDER_CATEGORY_LABELS,
    ORDER_ITEM_GROUPS_BY_CATEGORY,
    _to_int,
    get_order_item_details_for_group,
    get_order_item_group_label,
)
from services.self_service_ui_runtime import (
    SelfServiceOrderView,
    build_self_service_panel_embed,
)
from services.web_sync.discord_helpers import (
    has_footer as _web_order_created_has_footer,
)
from services.web_sync.presentation import (
    build_order_created_details as _web_order_created_details,
)
from shared.order_state import (
    PENDING_CS_DISPATCH as WEB_ORDER_PENDING_CS_DISPATCH,
)


_CONFIGURED = False

CUSTOMER_ROLE_ID: int
OrderControlView: type[discord.ui.View]
SELF_SERVICE_ORDER_SELECTIONS: dict[int, dict[str, Any]]


def configure_web_sync_self_service_bridge(
    *,
    customer_role_id: int,
    order_control_view_type: type[discord.ui.View],
    order_selections: dict[int, dict[str, Any]],
) -> None:
    """Bind only bot-owned state needed by the website self-service bridge."""
    global _CONFIGURED
    global CUSTOMER_ROLE_ID, OrderControlView, SELF_SERVICE_ORDER_SELECTIONS

    CUSTOMER_ROLE_ID = int(customer_role_id)
    OrderControlView = order_control_view_type
    SELF_SERVICE_ORDER_SELECTIONS = order_selections
    _CONFIGURED = True


# BEGIN MAWAN_R13_UNIFIED_WEBSITE_ORDER_FLOW

def _r13_seed_website_order_into_self_service(
    order_id: int,
    bundle: dict,
    ticket_channel: discord.TextChannel,
) -> tuple[int, dict]:
    """Seed a website order into the existing Discord self-service state without creating a second order."""
    order = bundle.get("order") or {}
    details = _web_order_created_details(bundle)

    customer_id = _to_int(order.get("customer_discord_id"), None)
    if customer_id is None:
        raise RuntimeError(f"WEB-{order_id} 缺少 customer_discord_id，無法建立統一自助下單面板")

    category_key = str(details.get("category_key") or "").strip()
    category_label = str(details.get("category_label") or order.get("category") or "").strip()

    if category_key not in ORDER_ITEM_GROUPS_BY_CATEGORY:
        raw_category = str(order.get("category") or category_label or "").strip()
        resolved_category = None
        for key, label in ORDER_CATEGORY_LABELS.items():
            if raw_category in {str(key), str(label)} or category_label == str(label):
                resolved_category = str(key)
                break
        if resolved_category:
            category_key = resolved_category

    if category_key not in ORDER_ITEM_GROUPS_BY_CATEGORY:
        raise RuntimeError(
            f"WEB-{order_id} 無法把網站類別映射到 Discord 自助下單："
            f"category={order.get('category')!r} category_key={category_key!r}"
        )

    item = str(details.get("item") or order.get("item") or "").strip()
    rule_snapshot = details.get("rule_snapshot") or {}
    price_snapshot = details.get("price_snapshot") or {}
    submission_payload = details.get("submission_payload") or {}
    rule_key = str(
        order.get("order_rule_key")
        or rule_snapshot.get("key")
        or rule_snapshot.get("order_rule_key")
        or price_snapshot.get("order_rule_key")
        or submission_payload.get("order_rule_key")
        or ""
    ).strip()

    item_group = get_order_item_group_label(item) if item else None
    matched_detail = None

    def _match_detail(detail: dict) -> bool:
        detail_item = str(detail.get("item") or "").strip()
        detail_label = str(detail.get("label") or "").strip()
        detail_rule = str(detail.get("rule_key") or "").strip()
        if rule_key and detail_rule == rule_key:
            return True
        return bool(item and item in {detail_item, detail_label})

    if item_group:
        candidate_details = get_order_item_details_for_group(category_key, item_group)
        matched_detail = next((row for row in candidate_details if _match_detail(row)), None)
        if matched_detail is None and len(candidate_details) == 1:
            matched_detail = candidate_details[0]

    if matched_detail is None:
        for candidate_group in ORDER_ITEM_GROUPS_BY_CATEGORY.get(category_key, []):
            candidate_details = get_order_item_details_for_group(category_key, candidate_group)
            candidate = next((row for row in candidate_details if _match_detail(row)), None)
            if candidate is not None:
                item_group = str(candidate_group)
                matched_detail = candidate
                break

    if not item_group or matched_detail is None:
        raise RuntimeError(
            f"WEB-{order_id} 無法把網站品項映射到 Discord 自助下單："
            f"item={item!r} rule_key={rule_key!r} category={category_key!r}"
        )

    data = SELF_SERVICE_ORDER_SELECTIONS.setdefault(ticket_channel.id, {})

    data["customer_id"] = int(customer_id)
    seeded_customer_display_name = str(
        order.get("customer_display_name")
        or ""
    ).strip()
    if seeded_customer_display_name and seeded_customer_display_name != str(customer_id):
        data["customer_display_name"] = seeded_customer_display_name
    data["category"] = category_key
    data["category_label"] = ORDER_CATEGORY_LABELS.get(category_key, category_label or category_key)
    data["item_group"] = str(item_group)
    data["item_detail_value"] = str(matched_detail.get("value") or "")
    data["item"] = str(matched_detail.get("item") or item)
    data["order_rule_key"] = str(matched_detail.get("rule_key") or rule_key)
    data["quantity"] = max(1, int(_to_int(details.get("quantity"), 1) or 1))
    data["player_count"] = max(1, int(_to_int(details.get("player_count"), 1) or 1))

    specified_staff_ids = [
        str(value).strip()
        for value in (details.get("specified_staff_ids") or [])
        if str(value).strip()
    ]
    data["specified_staff_ids"] = specified_staff_ids
    data["companion_preference"] = (
        "指定陪玩/打手" if specified_staff_ids else "不指定陪玩/打手"
    )

    extra_requirements = str(details.get("extra_requirements") or "").strip()
    data["extra_requirements"] = extra_requirements or None
    if extra_requirements:
        data["staff_note"] = extra_requirements
        data["staff_order_note"] = extra_requirements

    data["service_terms_version"] = str(details.get("service_terms_version") or "").strip() or None
    data["website_terms_accepted_at"] = str(details.get("terms_accepted_at") or "").strip() or None
    data["web_submission_request_key"] = str(details.get("request_key") or "").strip() or None
    data["web_order_note"] = order.get("note")

    # Carry forward financial selections so the existing self-service preview reconstructs the
    # same website quote. website_finance_settled prevents a second point deduction at payment.
    for key in (
        "manual_staff_amount",
        "manual_staff_price_reason",
        "manual_discount_percent",
        "manual_discount_reason",
        "cash_coupon_amount",
        "cash_coupon_reason",
        "point_benefit_key",
        "point_benefit_name",
        "point_benefit_cost",
        "point_discount_coupon_amount",
        "point_waived_specify_fee",
        "point_free_first_hour_amount",
        "point_extra_hours",
        "point_extra_games",
        "service_bonus_text",
        "service_promotion_text",
        "original_amount",
        "payout_base_amount",
        "customer_pay_amount",
        "store_absorbed_amount",
    ):
        value = price_snapshot.get(key)
        if value is None:
            value = order.get(key)
        if value is not None:
            data[key] = value

    point_key = str(price_snapshot.get("point_benefit_key") or "").strip()
    if point_key:
        data["selected_point_benefit_key"] = point_key
        data["point_benefit_key"] = point_key

    data["website_finance_settled"] = True
    data["web_order_source"] = "website"
    data["web_order_id"] = int(order_id)
    data["status"] = WEB_ORDER_PENDING_CS_DISPATCH
    data["closed"] = False

    # Website checkout never decides the Discord payment method and has not dispatched yet.
    for key in (
        "payment_method",
        "website_payment_method",
        "dispatch_channel_id",
        "dispatch_message_id",
        "payment_channel_id",
        "payment_message_id",
        "payment_finalizing",
        "dispatch_submitting",
    ):
        data.pop(key, None)

    remember_order_data(ticket_channel.id, data)
    save_bot_data()
    return int(customer_id), data


async def _r13_ensure_website_unified_panels(
    guild: discord.Guild,
    order_id: int,
    bundle: dict,
    ticket_channel: discord.TextChannel,
) -> None:
    """Use the exact normal Discord OrderControlView + SelfServiceOrderView for website orders."""
    customer_id, data = _r13_seed_website_order_into_self_service(
        order_id,
        bundle,
        ticket_channel,
    )

    control_footer = f"WEB-{order_id}｜客服操作"
    self_service_footer = f"WEB-{order_id}｜官網預填自助下單"

    support_role = guild.get_role(CUSTOMER_ROLE_ID)
    support_mention = support_role.mention if support_role is not None else "客服"

    if not await _web_order_created_has_footer(ticket_channel, control_footer, limit=60):
        control_embed = discord.Embed(
            title="客服操作選項",
            description=(
                f"官網訂單 WEB-{order_id} 已建立。\n"
                "下方直接使用一般 Discord 訂單的操作流程；"
                "訂單內容已自動帶入自助下單面板，客服確認後再送出等待接單。"
            ),
            color=discord.Color.gold(),
        )
        control_embed.set_footer(text=control_footer)
        await ticket_channel.send(
            content=f"{support_mention} 官網新訂單待確認。",
            embed=control_embed,
            view=OrderControlView(),
            allowed_mentions=discord.AllowedMentions(
                users=False,
                roles=True,
                everyone=False,
            ),
        )

    if not await _web_order_created_has_footer(ticket_channel, self_service_footer, limit=60):
        panel_embed = build_self_service_panel_embed(customer_id, data, guild)
        panel_embed.set_footer(text=self_service_footer)
        await ticket_channel.send(
            embed=panel_embed,
            view=SelfServiceOrderView(
                customer_id=customer_id,
                channel_id=ticket_channel.id,
                selected_category=data.get("category"),
            ),
            allowed_mentions=discord.AllowedMentions(
                users=True,
                roles=False,
                everyone=False,
            ),
        )

# END MAWAN_R13_UNIFIED_WEBSITE_ORDER_FLOW
