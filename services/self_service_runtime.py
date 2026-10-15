from __future__ import annotations

import json
from typing import Any, Mapping

import discord

from core.database import (
    delete_claim_row_from_db,
    remember_claim_data,
    remember_order_data,
    save_bot_data,
)
from core.permissions import is_customer_staff
from core.time_utils import get_taipei_now_iso
from services.acceptance.runtime import _member_display_name
from services.orders import (
    ORDER_CATEGORY_LABELS,
    _to_int,
    build_self_service_order_embed,
)
from services.smart_dispatch import create_smart_dispatch_plan, set_specified_dm_results
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

# Dependencies with a stable owning module are imported directly above and must not
# be replaced by the legacy bot.py namespace injection. Keeping this allow-list
# explicit lets us shrink the remaining runtime surface incrementally without
# changing the public Discord self-service entry points.
_MODULE_OWNED_RUNTIME_NAMES = frozenset(
    {
        "Any",
        "Mapping",
        "discord",
        "json",
        "ORDER_CATEGORY_LABELS",
        "_to_int",
        "build_self_service_order_embed",
        "delete_claim_row_from_db",
        "remember_claim_data",
        "remember_order_data",
        "save_bot_data",
        "is_customer_staff",
        "get_taipei_now_iso",
        "_member_display_name",
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

_CONFIGURED = False


def configure_self_service_runtime(namespace: Mapping[str, Any]) -> None:
    """Bind only the remaining bot-owned legacy dependencies after bot.py is loaded."""
    global _CONFIGURED

    for name, value in namespace.items():
        if name.startswith("__"):
            continue
        if name == "configure_self_service_runtime":
            continue
        if name in _MODULE_OWNED_RUNTIME_NAMES:
            continue
        globals()[name] = value

    reorder_configurator = globals().get("configure_reorder_ticket_creator")
    if callable(reorder_configurator):
        reorder_configurator(create_reorder_ticket_from_closed_order)

    # ORDER_POINT_BENEFIT_SPECS is owned by self_service_selection_runtime,
    # so bot.py must not be required to re-export it just to configure
    # the financial runtime.
    financial_keys = {
        "POINT_REDEEM_ITEMS_BY_KEY",
        "allocate_store_absorbed_fixed_discount",
        "get_current_reward_points",
        "get_customer_reward_data",
        "get_effective_member_level",
        "get_self_service_quantity_unit",
        "get_vip_discount_pay_rate",
    }
    present_financial_keys = financial_keys.intersection(namespace)
    missing_financial_keys = sorted(financial_keys.difference(namespace))

    if present_financial_keys and missing_financial_keys:
        raise RuntimeError(
            "self-service financial runtime missing dependencies: "
            + ", ".join(missing_financial_keys)
        )

    if not missing_financial_keys:
        configure_self_service_financials(
            order_point_benefit_specs=ORDER_POINT_BENEFIT_SPECS,
            point_redeem_items_by_key=namespace["POINT_REDEEM_ITEMS_BY_KEY"],
            get_rule_from_data=_get_rule_from_self_service_data,
            is_specify_preference=_is_specify_preference,
            role_key_for_member=_role_key_for_member,
            to_int=_to_int,
            store_absorbed_discount_allocator=namespace["allocate_store_absorbed_fixed_discount"],
            current_reward_points=namespace["get_current_reward_points"],
            customer_reward_data=namespace["get_customer_reward_data"],
            effective_member_level=namespace["get_effective_member_level"],
            self_service_quantity_unit=namespace["get_self_service_quantity_unit"],
            vip_discount_pay_rate=namespace["get_vip_discount_pay_rate"],
        )

    reorder_keys = {
        "ORDER_ITEM_GROUPS_BY_CATEGORY",
        "CUSTOMER_ROLE_ID",
        "CUSTOMER_CATEGORY_ID",
        "SELF_SERVICE_ORDER_SELECTIONS",
        "OrderControlView",
        "_get_order_rule_by_item_label",
        "build_ticket_channel_name",
        "delete_order_row_from_db",
        "get_order_item_details_for_group",
        "get_order_item_group_label",
        "get_self_service_quantity_meta",
        "send_order_log",
    }
    if reorder_keys.issubset(namespace):
        configure_self_service_reorder(
            order_category_labels=ORDER_CATEGORY_LABELS,
            order_item_groups_by_category=namespace["ORDER_ITEM_GROUPS_BY_CATEGORY"],
            get_order_rule_by_item_label=namespace["_get_order_rule_by_item_label"],
            role_key_for_member=_role_key_for_member,
            to_int=_to_int,
            order_item_details_for_group=namespace["get_order_item_details_for_group"],
            order_item_group_label=namespace["get_order_item_group_label"],
            self_service_quantity_meta=namespace["get_self_service_quantity_meta"],
            taipei_now_iso=get_taipei_now_iso,
            staff_price_required=is_self_service_staff_price_required,
            customer_role_id=namespace["CUSTOMER_ROLE_ID"],
            customer_category_id=namespace["CUSTOMER_CATEGORY_ID"],
            order_control_view=namespace["OrderControlView"],
            self_service_order_view=SelfServiceOrderView,
            panel_embed_builder=build_self_service_panel_embed,
            self_service_order_selections=namespace["SELF_SERVICE_ORDER_SELECTIONS"],
            remember_data=remember_order_data,
            save_data=save_bot_data,
            ticket_channel_name_builder=namespace["build_ticket_channel_name"],
            delete_order_row=namespace["delete_order_row_from_db"],
            order_log_sender=namespace["send_order_log"],
        )


    selection_keys = {
        "SELF_SERVICE_ORDER_SELECTIONS",
        "POINT_REDEEM_ITEMS",
    }
    if selection_keys.issubset(namespace):
        configure_self_service_selection_runtime(
            order_selections=namespace["SELF_SERVICE_ORDER_SELECTIONS"],
            point_redeem_items=namespace["POINT_REDEEM_ITEMS"],
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
    matched.sort(key=lambda role_key: int(fee_map.get(role_key, getattr(rule, "specify_fee_default", 0) or 0)), reverse=True)
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




class SelfServicePlayerCountModal(discord.ui.Modal, title="填寫陪玩人數"):
    player_count = discord.ui.TextInput(
        label="陪玩人數",
        placeholder="例如：1、2、3、4",
        required=True,
        max_length=3,
    )

    def __init__(self, customer_id: int, channel_id: int):
        super().__init__()
        self.customer_id = customer_id
        self.channel_id = channel_id

    async def on_submit(self, interaction: discord.Interaction):
        if not can_operate_self_service_order(interaction.user, self.customer_id):
            await interaction.response.send_message("只有開這張票口的用戶或客服可以操作訂單。", ephemeral=True)
            return

        data = SELF_SERVICE_ORDER_SELECTIONS.setdefault(self.channel_id, {})

        try:
            rule = _get_rule_from_self_service_data(data)
            value = int(str(self.player_count.value).strip())
        except ValueError:
            await interaction.response.send_message("陪玩人數請輸入數字。", ephemeral=True)
            return

        if value < int(rule.min_player_count or 1):
            await interaction.response.send_message(f"陪玩人數至少需要 {rule.min_player_count} 位。", ephemeral=True)
            return

        if rule.max_player_count is not None and value > int(rule.max_player_count):
            await interaction.response.send_message(f"{rule.label} 最多只能點 {rule.max_player_count} 位。", ephemeral=True)
            return

        data["player_count"] = value
        data.pop("payment_method", None)
        remember_order_data(self.channel_id, data)

        await interaction.response.send_message(
            f"已填寫陪玩人數：**{value} 位**。\n請再按一次「送出等待接單」。",
            ephemeral=True,
        )











async def create_waiting_acceptance_order_from_self_service(
    interaction: discord.Interaction,
    *,
    customer_id: int,
    channel_id: int,
) -> str:
    return await create_self_service_waiting_acceptance_order(
        interaction,
        customer_id=customer_id,
        channel_id=channel_id,
        deps=SelfServiceDispatchDeps(
            dispatch_channel_id=DISPATCH_CHANNEL_ID,
            order_selections=SELF_SERVICE_ORDER_SELECTIONS,
            order_claims=ORDER_CLAIMS,
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
    return await retract_self_service_dispatch(
        interaction,
        channel_id=channel_id,
        order_selections=SELF_SERVICE_ORDER_SELECTIONS,
        order_claims=ORDER_CLAIMS,
        dispatch_channel_id=DISPATCH_CHANNEL_ID,
        remember_order=remember_order_data,
        save_data=save_bot_data,
        delete_claim_row=delete_claim_row_from_db,
        order_log_sender=send_order_log,
        now_iso=get_taipei_now_iso,
    )


PRICE_FORMULA_VERSION = 2













def build_self_service_panel_embed(
    customer_id: int,
    data: dict,
    guild: discord.Guild | None = None,
) -> discord.Embed:
    category = data.get("category")
    category_label = ORDER_CATEGORY_LABELS.get(category, "尚未選擇")
    item_group = str(data.get("item_group") or "尚未選擇")

    detail = get_order_item_detail_for_selection(
        category,
        data.get("item_group"),
        data.get("item_detail_value"),
    )
    detail_label = str((detail or {}).get("label") or "尚未選擇")

    quantity = _to_int(data.get("quantity"), 1) or 1
    quantity_unit = get_self_service_quantity_unit(data.get("item"), data) if data.get("item") else "單"

    embed = discord.Embed(
        title="自助下單",
        description=(
            f"下單用戶：<@{customer_id}>\n\n"
            "請依序選擇：類別 → 訂單項目 → 具體規格 → 單數。\n"
            "可指定的品項才會開放指定成員；2 小時以上免指定費。\n"
            "送出後先進入等待接單，人數滿後才開放付款。"
        ),
        color=discord.Color.purple(),
    )

    embed.add_field(name="第一欄｜類別", value=str(category_label), inline=True)
    embed.add_field(name="第二欄｜項目", value=item_group, inline=True)
    embed.add_field(name="第三欄｜規格", value=detail_label, inline=True)

    if data.get("item"):
        embed.add_field(
            name="第四欄｜單數",
            value=f"{quantity} {quantity_unit}",
            inline=True,
        )

    try:
        rule = _get_rule_from_self_service_data(data) if data.get("item") else None
    except Exception:
        rule = None

    if rule is not None:
        if getattr(rule, "allow_specify", False):
            specified_ids = [str(item) for item in data.get("specified_staff_ids") or []]
            specify_text = "未指定" if not specified_ids else f"已指定 {len(specified_ids)} 位"
        else:
            specify_text = "此品項不可指定"
        embed.add_field(name="指定", value=specify_text, inline=True)

    return add_self_service_quote_preview(embed, data, guild)

# 指定陪玩 / 點數福利選擇 UI 已移至 services/self_service_selection_runtime.py
# 客服手動價格規則由 services/self_service_financials.py 單一維護。


class SelfServiceStaffPriceModal(discord.ui.Modal, title="客服填寫訂單價格"):
    amount = discord.ui.TextInput(
        label="訂單價格",
        placeholder="請輸入實收前原價，例如 3000",
        required=True,
        max_length=10,
    )

    reason = discord.ui.TextInput(
        label="價格備註",
        placeholder="例如 自訂單報價、部門任務報價",
        required=False,
        max_length=100,
    )

    def __init__(self, customer_id: int, channel_id: int, panel_message_id: int | None = None):
        super().__init__()
        self.customer_id = int(customer_id)
        self.channel_id = int(channel_id)
        self.panel_message_id = panel_message_id

    async def on_submit(self, interaction: discord.Interaction):
        if not isinstance(interaction.user, discord.Member) or not is_customer_staff(interaction.user):
            await interaction.response.send_message("只有客服可以填寫訂單價格。", ephemeral=True)
            return

        raw_amount = str(self.amount.value or "").strip().replace(",", "")

        try:
            amount = int(float(raw_amount))
        except ValueError:
            await interaction.response.send_message("價格請輸入數字，例如 3000。", ephemeral=True)
            return

        if amount < 0:
            await interaction.response.send_message("價格不能小於 0。", ephemeral=True)
            return

        data = SELF_SERVICE_ORDER_SELECTIONS.setdefault(self.channel_id, {})
        data["manual_staff_amount"] = int(amount)
        data["manual_staff_price_reason"] = str(self.reason.value or "").strip()
        data["manual_staff_price_set_by"] = interaction.user.id
        data["manual_staff_price_set_at"] = get_taipei_now_iso()
        data.pop("payment_method", None)

        remember_order_data(self.channel_id, data)

        await interaction.response.defer(ephemeral=True)

        edited_panel = False

        if isinstance(interaction.channel, discord.TextChannel) and self.panel_message_id:
            try:
                panel_message = await interaction.channel.fetch_message(self.panel_message_id)
                await panel_message.edit(
                    embed=build_self_service_panel_embed(self.customer_id, data, interaction.guild),
                    view=SelfServiceOrderView(
                        customer_id=self.customer_id,
                        channel_id=self.channel_id,
                        selected_category=data.get("category"),
                    ),
                    allowed_mentions=discord.AllowedMentions(users=True, roles=False, everyone=False),
                )
                edited_panel = True
            except discord.HTTPException:
                edited_panel = False

        await interaction.followup.send(
            f"已設定訂單價格：{_format_plain_amount(amount)}"
            + (f"\n備註：{data['manual_staff_price_reason']}" if data.get("manual_staff_price_reason") else "")
            + ("" if edited_panel else "\n\n提醒：面板沒有自動刷新，請重新選一次數量即可刷新試算。"),
            ephemeral=True,
        )

        await log_self_service_proxy_action(
            interaction,
            self.customer_id,
            "客服填寫訂單價格",
            f"{_format_plain_amount(amount)}｜{data.get('manual_staff_price_reason') or '無備註'}",
        )

class SelfServiceStaffDiscountCouponModal(discord.ui.Modal, title="客服設定折扣"):
    discount_percent = discord.ui.TextInput(
        label="折後比例 %",
        placeholder="例如 90 = 9 折；不折扣留空或填 100",
        required=False,
        max_length=10,
    )

    discount_reason = discord.ui.TextInput(
        label="折扣原因",
        placeholder="例如 VIP折扣、店內活動、老客優惠、補償折扣",
        required=False,
        max_length=100,
    )

    cash_coupon_amount = discord.ui.TextInput(
        label="固定折扣金額",
        placeholder="例如 100；沒有固定折扣可留空或填 0",
        required=False,
        max_length=10,
    )

    cash_coupon_reason = discord.ui.TextInput(
        label="固定折扣原因 / 名稱",
        placeholder="例如 VIP優惠、活動優惠、生日優惠",
        required=False,
        max_length=100,
    )

    def __init__(self, customer_id: int, channel_id: int, panel_message_id: int | None = None):
        super().__init__()
        self.customer_id = customer_id
        self.channel_id = channel_id
        self.panel_message_id = panel_message_id

    async def on_submit(self, interaction: discord.Interaction):
        if not isinstance(interaction.user, discord.Member) or not is_customer_staff(interaction.user):
            await interaction.response.send_message("只有客服可以設定折扣。", ephemeral=True)
            return

        data = SELF_SERVICE_ORDER_SELECTIONS.setdefault(self.channel_id, {})

        if not data.get("item"):
            await interaction.response.send_message("請先選擇訂單項目，再設定折扣。", ephemeral=True)
            return

        discount_percent_text = str(
            self.discount_percent.value
            or ""
        ).strip()

        try:
            discount_percent = _parse_discount_percent_text(
                discount_percent_text
            )
            coupon_amount = _parse_cash_amount_text(
                str(
                    self.cash_coupon_amount.value
                    or ""
                )
            )
        except ValueError as exc:
            await interaction.response.send_message(str(exc), ephemeral=True)
            return

        if discount_percent_text:
            data["manual_discount_mode"] = "pay_rate"
            data["manual_discount_percent"] = discount_percent
            data["manual_discount_percent_override"] = True
            data["manual_discount_reason"] = str(
                self.discount_reason.value
                or ""
            ).strip()
        else:
            # 百分比留空 = 清除客服百分比覆蓋，回到 VIP 自動折扣。
            data.pop("manual_discount_mode", None)
            data.pop("manual_discount_percent", None)
            data.pop("manual_discount_reason", None)
            data["manual_discount_percent_override"] = False

        data["cash_coupon_amount"] = coupon_amount
        data["fixed_discount_amount"] = coupon_amount
        data["cash_coupon_reason"] = str(self.cash_coupon_reason.value or "").strip()
        data["manual_price_adjustment_set_by"] = interaction.user.id
        data["manual_price_adjustment_set_at"] = get_taipei_now_iso()

        remember_order_data(self.channel_id, data)

        await interaction.response.defer(ephemeral=True)

        edited_panel = False

        if isinstance(interaction.channel, discord.TextChannel) and self.panel_message_id:
            try:
                panel_message = await interaction.channel.fetch_message(self.panel_message_id)
                await panel_message.edit(
                    embed=build_self_service_panel_embed(self.customer_id, data, interaction.guild),
                    view=SelfServiceOrderView(
                        customer_id=self.customer_id,
                        channel_id=self.channel_id,
                        selected_category=data.get("category"),
                    ),
                    allowed_mentions=discord.AllowedMentions(users=True, roles=False, everyone=False),
                )
                edited_panel = True
            except discord.HTTPException:
                edited_panel = False

        adjustment_note = []
        if discount_percent_text:
            adjustment_note.append(
                "客服百分比：折後 "
                f"{_format_percent_value(discount_percent)}%"
            )
        else:
            adjustment_note.append(
                "客服百分比已清除，改由顧客 VIP 等級自動套用。"
            )

        if coupon_amount > 0:
            adjustment_note.append(
                f"固定折扣：-{_format_plain_amount(coupon_amount)}"
                "（店內吸收，不影響打手分潤）"
            )

        await interaction.followup.send(
            "已設定折扣。"
            + ("\n" + "\n".join(adjustment_note) if adjustment_note else "")
            + ("" if edited_panel else "\n\n提醒：面板沒有自動刷新，請重新選一次數量即可刷新試算。"),
            ephemeral=True,
        )

        await log_self_service_proxy_action(
            interaction,
            self.customer_id,
            "設定折扣",
            "｜".join(adjustment_note) if adjustment_note else "折後100%，無固定折扣",
        )

class SelfServiceSubmitNoteModal(discord.ui.Modal, title="送單前訂單備註"):
    note = discord.ui.TextInput(
        label="訂單備註",
        placeholder="可填可不填，例如：老闆特殊需求、時間、注意事項",
        style=discord.TextStyle.paragraph,
        required=False,
        max_length=800,
    )

    def __init__(self, customer_id: int, channel_id: int, panel_message_id: int | None = None):
        super().__init__()
        self.customer_id = int(customer_id)
        self.channel_id = int(channel_id)
        self.panel_message_id = panel_message_id

    async def on_submit(self, interaction: discord.Interaction):
        if not isinstance(interaction.user, discord.Member) or not is_customer_staff(interaction.user):
            await interaction.response.send_message("請聯繫客服送單。", ephemeral=True)
            return

        data = SELF_SERVICE_ORDER_SELECTIONS.setdefault(self.channel_id, {})
        note_text = str(self.note.value or "").strip()

        if note_text:
            data["staff_order_note"] = note_text
            data["staff_note"] = note_text
        else:
            data.pop("staff_order_note", None)
            data.pop("staff_note", None)

        data["staff_order_note_set_by"] = interaction.user.id
        data["staff_order_note_set_at"] = get_taipei_now_iso()
        remember_order_data(self.channel_id, data)

        await interaction.response.defer(ephemeral=True)

        try:
            response_text = await create_waiting_acceptance_order_from_self_service(
                interaction,
                customer_id=self.customer_id,
                channel_id=self.channel_id,
            )
        except ValueError as exc:
            failed_data = SELF_SERVICE_ORDER_SELECTIONS.setdefault(self.channel_id, {})
            provisional_started = _to_int(
                failed_data.get("provisional_dispatch_message_id"),
                None,
            ) is not None
            if not provisional_started:
                await interaction.followup.send(str(exc), ephemeral=True)
                return

            cleanup_warnings = await cleanup_failed_self_service_dispatch(
                interaction,
                channel_id=self.channel_id,
                data=failed_data,
                order_claims=ORDER_CLAIMS,
                default_dispatch_channel_id=DISPATCH_CHANNEL_ID,
                remember_order=remember_order_data,
                save_data=save_bot_data,
                delete_claim_row=delete_claim_row_from_db,
            )
            warning_text = ""
            if cleanup_warnings:
                warning_text = "\n⚠️ " + "；".join(cleanup_warnings)
            await interaction.followup.send(
                f"{exc}\n\n本次 provisional 派單已回滾，原本填好的草稿仍保留，可以修正後重新送出。"
                + warning_text,
                ephemeral=True,
            )
            return
        except Exception as exc:
            failed_data = SELF_SERVICE_ORDER_SELECTIONS.setdefault(self.channel_id, {})
            provisional_started = _to_int(
                failed_data.get("provisional_dispatch_message_id"),
                None,
            ) is not None
            canonical_ready = (
                _to_int(failed_data.get("dispatch_message_id"), None) is not None
                and _to_int(failed_data.get("web_order_id"), None) is not None
                and str(failed_data.get("status") or "").strip().lower()
                == "waiting_acceptance"
            )
            print(
                f"[acceptance] 備註後建立 waiting_acceptance 自助單失敗 "
                f"channel_id={self.channel_id}: {type(exc).__name__}: {exc}",
                flush=True,
            )

            if provisional_started:
                cleanup_warnings = await cleanup_failed_self_service_dispatch(
                    interaction,
                    channel_id=self.channel_id,
                    data=failed_data,
                    order_claims=ORDER_CLAIMS,
                    default_dispatch_channel_id=DISPATCH_CHANNEL_ID,
                    remember_order=remember_order_data,
                    save_data=save_bot_data,
                    delete_claim_row=delete_claim_row_from_db,
                )
                warning_text = ""
                if cleanup_warnings:
                    warning_text = "\n⚠️ " + "；".join(cleanup_warnings)
                await interaction.followup.send(
                    "送出等待接單失敗；本次 provisional 派單已回滾，原本填好的草稿仍保留，可以修正後重新送出。"
                    + warning_text,
                    ephemeral=True,
                )
                return

            if canonical_ready:
                await interaction.followup.send(
                    "訂單的 WebOrder／接單狀態已建立完成，但送單後續處理發生異常。"
                    "為避免重複派單，請先不要重新送出，通知客服主管確認此張單。",
                    ephemeral=True,
                )
                return

            await interaction.followup.send(
                "送出等待接單失敗；尚未建立可接單的派單，原本填好的草稿仍保留，請修正後再試或通知客服主管。",
                ephemeral=True,
            )
            return

        if isinstance(interaction.channel, discord.TextChannel) and self.panel_message_id:
            try:
                panel_message = await interaction.channel.fetch_message(self.panel_message_id)
                await panel_message.edit(
                    embed=build_self_service_panel_embed(self.customer_id, data, interaction.guild),
                    view=SelfServiceDispatchedView(),
                    allowed_mentions=discord.AllowedMentions(users=True, roles=False, everyone=False),
                )
            except discord.HTTPException:
                pass

        await log_self_service_proxy_action(
            interaction,
            self.customer_id,
            "送出等待接單",
            note_text or "無備註",
        )

        await interaction.followup.send(response_text, ephemeral=True)


class SelfServiceOrderView(discord.ui.View):
    def __init__(self, customer_id: int, channel_id: int, selected_category: str | None = None):
        super().__init__(timeout=86400)

        self.customer_id = customer_id
        self.channel_id = channel_id

        data = SELF_SERVICE_ORDER_SELECTIONS.get(channel_id, {})
        category = selected_category or data.get("category")
        selected_item = data.get("item")
        selected_quantity = _to_int(data.get("quantity"), 1) or 1

        self.add_item(SelfServiceOrderCategorySelect(customer_id, channel_id, category))
        self.add_item(SelfServiceOrderItemSelect(customer_id, channel_id, category, selected_item))
        self.add_item(SelfServiceOrderDetailSelect(customer_id, channel_id))
        self.add_item(SelfServiceOrderQuantitySelect(customer_id, channel_id, selected_item, selected_quantity))

        try:
            current_rule = _get_rule_from_self_service_data(data) if selected_item else None
        except Exception:
            current_rule = None

        for child in self.children:
            custom_id = getattr(child, "custom_id", None)
            if custom_id == "self_service_order_specified_staff_button":
                child.disabled = not bool(current_rule and getattr(current_rule, "allow_specify", False))
            elif custom_id == "self_service_order_staff_price_button":
                child.disabled = not bool(current_rule and is_self_service_staff_price_required(current_rule))
            elif custom_id == "self_service_order_point_benefit_button" and data.get("website_finance_settled"):
                child.disabled = True
            elif custom_id == "self_service_order_go_payment_button":
                child.label = "客服確認送出" if data.get("reorder_source_order_id") else "送出等待接單"


    @discord.ui.button(
        label="選擇指定成員",
        style=discord.ButtonStyle.secondary,
        custom_id="self_service_order_specified_staff_button",
        row=4,
    )
    async def specified_staff(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not can_operate_self_service_order(interaction.user, self.customer_id):
            await interaction.response.send_message("只有開這張票口的用戶或客服可以選擇指定成員。", ephemeral=True)
            return

        if interaction.guild is None:
            await interaction.response.send_message("這個功能只能在伺服器內使用。", ephemeral=True)
            return

        data = SELF_SERVICE_ORDER_SELECTIONS.setdefault(self.channel_id, {})

        if not data.get("item"):
            await interaction.response.send_message("請先選擇訂單項目，再選擇指定成員。", ephemeral=True)
            return

        try:
            rule = _get_rule_from_self_service_data(data)
            from services.order_rules import get_required_staff_count
            player_count = _to_int(data.get("player_count"), 1) or 1
            required_staff_count = get_required_staff_count(rule, player_count)
        except ValueError as exc:
            await interaction.response.send_message(str(exc), ephemeral=True)
            return
        except Exception as exc:
            await interaction.response.send_message(f"讀取指定規則失敗：{exc}", ephemeral=True)
            return

        can_specify_item = bool(getattr(rule, "allow_specify", False))

        if not can_specify_item:
            data.pop("specified_staff_ids", None)
            remember_order_data(self.channel_id, data)
            await interaction.response.send_message("這個項目不開放指定人員。", ephemeral=True)
            return

        if not _is_specify_preference(data.get("companion_preference")):
            data["companion_preference"] = "指定陪玩/打手"
            remember_order_data(self.channel_id, data)


        await interaction.response.defer(ephemeral=True)

        max_specified_count = int(rule.max_specified_count or required_staff_count or 1)
        max_specified_count = min(max_specified_count, int(required_staff_count or 1))
        entries = get_specified_staff_entries_for_rule(interaction.guild, rule)

        if not entries:
            await interaction.followup.send("目前找不到符合這張單可指定職位的人員，請確認打手身分組。", ephemeral=True)
            return

        panel_message_id = interaction.message.id if interaction.message is not None else None

        view = SelfServiceSpecifiedStaffDropdownView(
            customer_id=self.customer_id,
            channel_id=self.channel_id,
            panel_message_id=panel_message_id,
            rule_key=rule.key,
            max_specified_count=max_specified_count,
            entries=entries,
            selected_ids=[str(item) for item in data.get("specified_staff_ids") or []],
        )

        await interaction.followup.send(
            content=view.build_message_content(),
            view=view,
            ephemeral=True,
            allowed_mentions=discord.AllowedMentions(users=True, roles=False, everyone=False),
        )


    @discord.ui.button(
        label="點數 / 會員福利",
        style=discord.ButtonStyle.secondary,
        custom_id="self_service_order_point_benefit_button",
        row=4,
    )
    async def point_benefit(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not can_operate_self_service_order(interaction.user, self.customer_id):
            await interaction.response.send_message("只有開這張票口的用戶或客服可以選擇點數福利。", ephemeral=True)
            return

        if interaction.guild is None:
            await interaction.response.send_message("這個功能只能在伺服器內使用。", ephemeral=True)
            return

        data = SELF_SERVICE_ORDER_SELECTIONS.setdefault(self.channel_id, {})

        if not data.get("item"):
            await interaction.response.send_message("請先選擇訂單項目，再選擇點數福利。", ephemeral=True)
            return

        try:
            rule = _get_rule_from_self_service_data(data)
        except ValueError as exc:
            await interaction.response.send_message(str(exc), ephemeral=True)
            return

        allowed, reason = is_order_point_benefit_allowed_for_rule(rule, "discount_20", data)
        if not allowed:
            await interaction.response.send_message(reason or "這個分類不可使用點數福利。", ephemeral=True)
            return

        panel_message_id = interaction.message.id if interaction.message is not None else None

        view = SelfServicePointBenefitView(
            customer_id=self.customer_id,
            channel_id=self.channel_id,
            panel_message_id=panel_message_id,
            rule=rule,
        )

        await interaction.response.send_message(
            content=view.build_message_content(data),
            view=view,
            ephemeral=True,
            allowed_mentions=discord.AllowedMentions(users=True, roles=False, everyone=False),
        )


    @discord.ui.button(
        label="客服填價格",
        style=discord.ButtonStyle.secondary,
        custom_id="self_service_order_staff_price_button",
        row=4,
    )
    async def staff_price(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not isinstance(interaction.user, discord.Member) or not is_customer_staff(interaction.user):
            await interaction.response.send_message("只有客服可以填寫訂單價格。", ephemeral=True)
            return

        data = SELF_SERVICE_ORDER_SELECTIONS.setdefault(self.channel_id, {})

        if not data.get("item"):
            await interaction.response.send_message("請先選擇訂單項目，再填寫價格。", ephemeral=True)
            return

        try:
            rule = _get_rule_from_self_service_data(data)
        except ValueError as exc:
            await interaction.response.send_message(str(exc), ephemeral=True)
            return

        if not is_self_service_staff_price_required(rule):
            await interaction.response.send_message("這個項目會自動試算價格，不需要客服手動填價格。", ephemeral=True)
            return

        panel_message_id = interaction.message.id if interaction.message is not None else None
        await interaction.response.send_modal(
            SelfServiceStaffPriceModal(
                customer_id=self.customer_id,
                channel_id=self.channel_id,
                panel_message_id=panel_message_id,
            )
        )


    @discord.ui.button(
        label="客服設定折扣",
        style=discord.ButtonStyle.secondary,
        custom_id="self_service_order_staff_discount_coupon_button",
        row=4,
    )
    async def staff_discount_coupon(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not isinstance(interaction.user, discord.Member) or not is_customer_staff(interaction.user):
            await interaction.response.send_message("只有客服可以設定折扣。", ephemeral=True)
            return

        data = SELF_SERVICE_ORDER_SELECTIONS.get(self.channel_id, {})

        if not data.get("item"):
            await interaction.response.send_message("請先選擇訂單項目，再設定折扣。", ephemeral=True)
            return

        panel_message_id = interaction.message.id if interaction.message is not None else None
        await interaction.response.send_modal(
            SelfServiceStaffDiscountCouponModal(
                customer_id=self.customer_id,
                channel_id=self.channel_id,
                panel_message_id=panel_message_id,
            )
        )


    @discord.ui.button(
        label="送出等待接單",
        style=discord.ButtonStyle.success,
        custom_id="self_service_order_go_payment_button",
        row=4
    )
    async def go_payment(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not isinstance(interaction.user, discord.Member) or not is_customer_staff(interaction.user):
            await interaction.response.send_message("請聯繫客服送單。", ephemeral=True)
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

        try:
            selected_rule = _get_rule_from_self_service_data(data)
            item_category = str(getattr(selected_rule, "category", "") or "")
        except ValueError:
            item_category = ORDER_ITEM_TO_CATEGORY.get(item)

        if item_category != category:
            await interaction.response.send_message(
                "你選擇的訂單類別與訂單項目不一致，請重新選擇。",
                ephemeral=True,
            )
            return


        quantity_meta = _self_service_quantity_meta(data, item)
        min_quantity = int(quantity_meta["min"])
        max_quantity = int(quantity_meta["max"])
        quantity_unit = str(quantity_meta["unit"])

        if min_quantity == max_quantity:
            quantity = min_quantity
            data["quantity"] = quantity
            remember_order_data(self.channel_id, data)
        elif quantity < min_quantity or quantity > max_quantity:
            await interaction.response.send_message(
                f"單數請選擇 {min_quantity}～{max_quantity} {quantity_unit}。",
                ephemeral=True,
            )
            return

        if companion_preference is None:
            companion_preference = "不指定陪玩/打手"
            data["companion_preference"] = companion_preference
            remember_order_data(self.channel_id, data)

        try:
            rule = _get_rule_from_self_service_data(data)
        except ValueError as exc:
            await interaction.response.send_message(str(exc), ephemeral=True)
            return

        normalize_self_service_staff_count(data)

        if getattr(rule, "player_count_enabled", False) and not _to_int(data.get("player_count")):
            await interaction.response.send_modal(SelfServicePlayerCountModal(self.customer_id, self.channel_id))
            return

        if getattr(rule, "allow_specify", False) and _is_specify_preference(companion_preference) and not data.get("specified_staff_ids"):
            panel_message_id = interaction.message.id if interaction.message is not None else None
            await interaction.response.send_message(
                "老闆已選擇指定，但尚未完成指定成員選擇。請老闆先點「選擇指定成員」並按「完成」後，再送出等待接單。",
                ephemeral=True,
            )
            return

        if is_self_service_staff_price_required(rule) and get_self_service_staff_price(data) is None:
            await interaction.response.send_message("這張單需要客服先按「客服填價格」填寫價格，才能送出等待接單。", ephemeral=True)
            return

        panel_message_id = interaction.message.id if interaction.message is not None else None
        await interaction.response.send_modal(
            SelfServiceSubmitNoteModal(
                customer_id=self.customer_id,
                channel_id=self.channel_id,
                panel_message_id=panel_message_id,
            )
        )
















