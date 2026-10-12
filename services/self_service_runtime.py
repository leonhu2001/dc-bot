from __future__ import annotations

from typing import Any, Mapping

import discord

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
    is_order_point_benefit_allowed_for_rule,
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

_CONFIGURED = False


def configure_self_service_runtime(namespace: Mapping[str, Any]) -> None:
    """Bind remaining bot-owned legacy dependencies after bot.py is loaded."""
    global _CONFIGURED

    for name, value in namespace.items():
        if name.startswith("__"):
            continue
        if name == "configure_self_service_runtime":
            continue
        globals()[name] = value

    reorder_configurator = globals().get("configure_reorder_ticket_creator")
    if callable(reorder_configurator):
        reorder_configurator(create_reorder_ticket_from_closed_order)

    financial_keys = {
        "ORDER_POINT_BENEFIT_SPECS",
        "POINT_REDEEM_ITEMS_BY_KEY",
        "_to_int",
        "allocate_store_absorbed_fixed_discount",
        "get_current_reward_points",
        "get_customer_reward_data",
        "get_effective_member_level",
        "get_self_service_quantity_unit",
        "get_vip_discount_pay_rate",
    }
    if financial_keys.issubset(namespace):
        configure_self_service_financials(
            order_point_benefit_specs=namespace["ORDER_POINT_BENEFIT_SPECS"],
            point_redeem_items_by_key=namespace["POINT_REDEEM_ITEMS_BY_KEY"],
            get_rule_from_data=_get_rule_from_self_service_data,
            is_specify_preference=_is_specify_preference,
            role_key_for_member=_role_key_for_member,
            to_int=namespace["_to_int"],
            store_absorbed_discount_allocator=namespace["allocate_store_absorbed_fixed_discount"],
            current_reward_points=namespace["get_current_reward_points"],
            customer_reward_data=namespace["get_customer_reward_data"],
            effective_member_level=namespace["get_effective_member_level"],
            self_service_quantity_unit=namespace["get_self_service_quantity_unit"],
            self_service_staff_price=get_self_service_staff_price,
            vip_discount_pay_rate=namespace["get_vip_discount_pay_rate"],
            staff_price_required=is_self_service_staff_price_required,
        )

    reorder_keys = {
        "ORDER_CATEGORY_LABELS",
        "ORDER_ITEM_GROUPS_BY_CATEGORY",
        "CUSTOMER_ROLE_ID",
        "CUSTOMER_CATEGORY_ID",
        "SELF_SERVICE_ORDER_SELECTIONS",
        "OrderControlView",
        "_get_order_rule_by_item_label",
        "_to_int",
        "build_ticket_channel_name",
        "delete_order_row_from_db",
        "get_order_item_details_for_group",
        "get_order_item_group_label",
        "get_self_service_quantity_meta",
        "get_taipei_now_iso",
        "remember_order_data",
        "save_bot_data",
        "send_order_log",
    }
    if reorder_keys.issubset(namespace):
        configure_self_service_reorder(
            order_category_labels=namespace["ORDER_CATEGORY_LABELS"],
            order_item_groups_by_category=namespace["ORDER_ITEM_GROUPS_BY_CATEGORY"],
            get_order_rule_by_item_label=namespace["_get_order_rule_by_item_label"],
            role_key_for_member=_role_key_for_member,
            to_int=namespace["_to_int"],
            order_item_details_for_group=namespace["get_order_item_details_for_group"],
            order_item_group_label=namespace["get_order_item_group_label"],
            self_service_quantity_meta=namespace["get_self_service_quantity_meta"],
            taipei_now_iso=namespace["get_taipei_now_iso"],
            staff_price_required=is_self_service_staff_price_required,
            customer_role_id=namespace["CUSTOMER_ROLE_ID"],
            customer_category_id=namespace["CUSTOMER_CATEGORY_ID"],
            order_control_view=namespace["OrderControlView"],
            self_service_order_view=SelfServiceOrderView,
            panel_embed_builder=build_self_service_panel_embed,
            self_service_order_selections=namespace["SELF_SERVICE_ORDER_SELECTIONS"],
            remember_data=namespace["remember_order_data"],
            save_data=namespace["save_bot_data"],
            ticket_channel_name_builder=namespace["build_ticket_channel_name"],
            delete_order_row=namespace["delete_order_row_from_db"],
            order_log_sender=namespace["send_order_log"],
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
    except discord.HTTPException as exc:
        try:
            await interaction.followup.send(f"更新自助下單 panel 失敗：{exc}", ephemeral=True)
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
    guild = interaction.guild

    if guild is None:
        raise ValueError("這個功能只能在伺服器內使用。")

    if not isinstance(interaction.channel, discord.TextChannel):
        raise ValueError("無法確認目前票口頻道。")

    data = SELF_SERVICE_ORDER_SELECTIONS.setdefault(channel_id, {})

    if data.get("dispatch_message_id") is not None:
        dispatch_message_id = _to_int(data.get("dispatch_message_id"))
        dispatch_channel_id = _to_int(data.get("dispatch_channel_id"), DISPATCH_CHANNEL_ID) or DISPATCH_CHANNEL_ID
        if dispatch_message_id:
            return f"這張單已經送出等待接單，請不要重複送出。\n派單訊息：https://discord.com/channels/{guild.id}/{dispatch_channel_id}/{dispatch_message_id}"
        return "這張單已經送出等待接單，請不要重複送出。"

    rule = _get_rule_from_self_service_data(data)

    from services.order_rules import (
        calculate_price,
        get_allowed_role_ids,
        get_required_game_role_ids,
        get_required_staff_count,
        build_order_rule_snapshot,
        rule_role_labels,
    )
    from shared.order_acceptance import WAITING_ACCEPTANCE, create_or_update_acceptance_meta
    from shared.web_order_sync import upsert_web_order_from_dispatch

    quantity = _to_int(data.get("quantity"), 1) or 1
    normalize_self_service_staff_count(data)
    player_count = _to_int(data.get("player_count"), 1) or 1
    specified_staff_ids = [str(item) for item in data.get("specified_staff_ids") or []]

    specified_roles, specified_mentions = await _resolve_specified_roles_for_price(
        guild,
        rule,
        specified_staff_ids,
    )

    price_result = calculate_price(
        rule,
        quantity=quantity,
        player_count=player_count,
        specified_roles=specified_roles,
    )

    required_staff_count = int(getattr(price_result, "required_staff_count", None) or get_required_staff_count(rule, player_count))
    price_adjustment = apply_self_service_financials_to_order_data(data, rule, price_result)
    amount = int(price_adjustment["customer_pay_amount"] or 0)
    payout_base_amount = int(price_adjustment["payout_base_amount"] or amount)
    allowed_role_ids_for_rule = get_allowed_role_ids(rule)
    required_game_role_ids_for_rule = get_required_game_role_ids(rule)

    rule_snapshot = build_order_rule_snapshot(
        rule,
        quantity=quantity,
        player_count=player_count,
        required_staff_count=required_staff_count,
        allowed_role_ids=allowed_role_ids_for_rule,
        required_game_role_ids=required_game_role_ids_for_rule,
        specified_staff_ids=specified_staff_ids,
    )

    rule_version = int(
        rule_snapshot.get("version", 1) or 1
    )

    rule_snapshot_json = json.dumps(
        rule_snapshot,
        ensure_ascii=False,
        sort_keys=True,
    )

    price_snapshot = {
        "version": rule_version,
        "price_formula_version": price_adjustment.get("price_formula_version", 2),
        "manual_discount_mode": price_adjustment.get("manual_discount_mode", "pay_rate"),
        "service_original_amount": price_adjustment.get("service_original_amount"),
        "discount_rate_percent": price_adjustment.get("discount_rate_percent"),
        "percent_discount_amount": price_adjustment.get("percent_discount_amount"),
        "fixed_discount_amount": price_adjustment.get("fixed_discount_amount"),
        "manual_discount_reason": price_adjustment.get("manual_discount_reason"),
        "cash_coupon_reason": price_adjustment.get("cash_coupon_reason"),
        "specified_fee_before_waiver": price_adjustment.get("specified_fee_before_waiver"),
        "effective_specify_fee": price_adjustment.get("effective_specify_fee"),
        "order_rule_key": rule.key,
        "rule_version": rule_version,
        "quantity": quantity,
        "player_count": player_count,
        "required_staff_count": required_staff_count,
        "manual_staff_amount": price_adjustment.get("manual_staff_amount"),
        "rule_original_amount": price_adjustment.get("rule_original_amount"),
        "original_amount": price_adjustment.get("original_amount"),
        "manual_discount_percent": price_adjustment.get("manual_discount_percent"),
        "manual_discount_amount": price_adjustment.get("manual_discount_amount"),
        "payout_base_amount": price_adjustment.get("payout_base_amount"),
        "cash_coupon_amount": price_adjustment.get("cash_coupon_amount"),
        "point_benefit_key": price_adjustment.get("point_benefit_key"),
        "point_benefit_name": price_adjustment.get("point_benefit_name"),
        "point_benefit_cost": price_adjustment.get("point_benefit_cost"),
        "point_discount_coupon_amount": price_adjustment.get("point_discount_coupon_amount"),
        "point_waived_specify_fee": price_adjustment.get("point_waived_specify_fee"),
        "point_free_first_hour_amount": price_adjustment.get("point_free_first_hour_amount"),
        "point_extra_hours": price_adjustment.get("point_extra_hours"),
        "point_extra_games": price_adjustment.get("point_extra_games"),
        "benefit_coupon_id": price_adjustment.get("benefit_coupon_id"),
        "benefit_coupon_title": price_adjustment.get("benefit_coupon_title"),
        "benefit_service_value": price_adjustment.get("benefit_service_value"),
        "benefit_service_note": price_adjustment.get("benefit_service_note"),
        "store_absorbed_amount": price_adjustment.get("store_absorbed_amount"),
        "customer_pay_amount": price_adjustment.get("customer_pay_amount"),
        "service_bonus_text": price_adjustment.get("service_bonus_text"),
        "service_quantity": price_adjustment.get("service_quantity"),
        "service_bonus_quantity": price_adjustment.get("service_bonus_quantity"),
        "service_promotion_text": price_adjustment.get("service_promotion_text"),
        "specified_staff_ids": [
            str(item)
            for item in (specified_staff_ids or [])
        ],
    }

    price_snapshot_json = json.dumps(
        price_snapshot,
        ensure_ascii=False,
        sort_keys=True,
    )

    dispatch_channel = guild.get_channel(DISPATCH_CHANNEL_ID)

    if dispatch_channel is None or not isinstance(dispatch_channel, discord.TextChannel):
        raise ValueError("找不到派單頻道，請確認 DISPATCH_CHANNEL_ID 是否正確。")

    category_label = ORDER_CATEGORY_LABELS.get(rule.category, rule.category)
    customer_member = guild.get_member(customer_id)

    if customer_member is None:
        try:
            customer_member = await guild.fetch_member(customer_id)
        except Exception:
            customer_member = None

    if customer_member is not None:
        data["customer_display_name"] = _member_display_name(customer_member)

    companion_preference = data.get("companion_preference") or "不指定陪玩/打手"
    staff_order_note = str(data.get("staff_order_note") or data.get("staff_note") or "").strip()

    embed = build_self_service_order_embed(
        customer_mention=f"<@{customer_id}>",
        category_label=category_label,
        item=rule.label,
        quantity=quantity,
        payment_method="待付款",
        source_channel=interaction.channel,
        companion_preference=companion_preference,
        receiver_text="尚未接單",
        staff_note=staff_order_note or None,
    )

    if price_adjustment.get("manual_staff_amount") is not None:
        embed.add_field(
            name="客服報價",
            value=(
                f"{_format_plain_amount(price_adjustment['manual_staff_amount'])}"
                + (f"\n備註：{price_adjustment.get('manual_staff_price_reason')}" if price_adjustment.get("manual_staff_price_reason") else "")
            ),
            inline=False,
        )

    add_self_service_financial_breakdown_fields(
        embed,
        price_adjustment,
    )

    embed.add_field(
        name="接單需求",
        value=f"{required_staff_count} 位",
        inline=True,
    )

    embed.add_field(
        name="可接職位",
        value=rule_role_labels(rule),
        inline=False,
    )

    if rule.player_count_enabled:
        embed.add_field(
            name="陪玩人數",
            value=f"{player_count} 位",
            inline=True,
        )

    if specified_mentions:
        embed.add_field(
            name="指定人員",
            value="、".join(
                specified_mentions
            ),
            inline=False,
        )

    if not rule.point_benefits_allowed:
        embed.add_field(name="點數福利", value="此分類不可使用點數福利", inline=False)

    smart_dispatch = prepare_initial_smart_dispatch(
        guild,
        customer_id=customer_id,
        allowed_role_ids=allowed_role_ids_for_rule,
        specified_staff_ids=specified_staff_ids,
        required_staff_count=required_staff_count,
        required_game_role_ids=required_game_role_ids_for_rule,
    )

    dispatch_message = await dispatch_channel.send(
        content=None,
        embed=embed,
        view=DispatchClaimView(
            customer_id=customer_id,
            category_label=category_label,
            item=rule.label,
            quantity=quantity,
            payment_method="待付款",
            source_channel_id=interaction.channel.id,
            companion_preference=companion_preference,
            locked=False,
            status=WAITING_ACCEPTANCE,
        ),
        allowed_mentions=discord.AllowedMentions(
            users=True,
            roles=True,
            everyone=False,
        ),
    )

    try:
        await send_initial_smart_dispatch_alert(
            guild,
            content=smart_dispatch["content"],
            dispatch_jump_url=dispatch_message.jump_url,
        )
    except (discord.Forbidden, discord.HTTPException) as exc:
        print(f"[smart-dispatch] initial alert failed: {exc}", flush=True)

    web_note_parts = []

    if staff_order_note:
        web_note_parts.append(
            f"客服備註：{staff_order_note}"
        )

    if price_adjustment.get(
        "service_bonus_text"
    ):
        web_note_parts.append(
            "點數福利："
            f"{price_adjustment['service_bonus_text']}"
        )

    if price_adjustment.get("benefit_coupon_title"):
        benefit_note = str(price_adjustment.get("benefit_service_note") or "").strip()
        web_note_parts.append(
            "會員福利："
            f"{price_adjustment['benefit_coupon_title']}"
            + (f"｜{benefit_note}" if benefit_note else "")
        )

    # service_promotion_web_note_v1
    if price_adjustment.get(
        "service_promotion_text"
    ):
        web_note_parts.append(
            price_adjustment["service_promotion_text"]
        )

    web_order_note = (
        "｜".join(
            web_note_parts
        )
        if web_note_parts
        else None
    )

    web_order = upsert_web_order_from_dispatch(
        ticket_channel_id=interaction.channel.id,
        dispatch_channel_id=dispatch_channel.id,
        dispatch_message_id=dispatch_message.id,
        customer_discord_id=customer_id,
        customer_display_name=getattr(customer_member, "display_name", None) or str(customer_id),
        category=category_label,
        item=rule.label,
        quantity=quantity,
        amount=amount,
        payment_method="待付款",
        original_amount=price_adjustment["original_amount"],
        payout_base_amount=payout_base_amount,
        customer_pay_amount=price_adjustment["customer_pay_amount"],
        manual_discount_amount=price_adjustment["manual_discount_amount"],
        cash_coupon_amount=price_adjustment["cash_coupon_amount"],
        store_absorbed_amount=price_adjustment["store_absorbed_amount"],
        status=WAITING_ACCEPTANCE,
        customer_service_discord_id=getattr(interaction.user, "id", None) if isinstance(interaction.user, discord.Member) and is_customer_staff(interaction.user) else None,
        customer_service_display_name=getattr(interaction.user, "display_name", None) if isinstance(interaction.user, discord.Member) and is_customer_staff(interaction.user) else None,
        bot_order_no=data.get("order_no") or data.get("receipt_id"),
        note=web_order_note,
    )

    if price_adjustment.get("benefit_coupon_id"):
        from services.loyalty_benefits import reserve_coupon_for_order
        reserve_coupon_for_order(
            coupon_id=int(price_adjustment["benefit_coupon_id"]),
            customer_id=customer_id,
            order_id=int(web_order.id),
            rule_key=str(rule.key),
            player_count=player_count,
        )

    try:
        from shared.db import engine as _rule_snapshot_engine
        from sqlalchemy import text as _rule_snapshot_sql_text

        with _rule_snapshot_engine.begin() as _rule_snapshot_conn:
            _rule_snapshot_conn.execute(
                _rule_snapshot_sql_text("""
                    UPDATE web_orders
                    SET order_rule_key = :order_rule_key,
                        rule_version = :rule_version,
                        rule_snapshot_json = :rule_snapshot_json,
                        price_snapshot_json = :price_snapshot_json,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE id = :order_id
                """),
                {
                    "order_id": int(web_order.id),
                    "order_rule_key": str(rule.key),
                    "rule_version": int(rule_version),
                    "rule_snapshot_json": rule_snapshot_json,
                    "price_snapshot_json": price_snapshot_json,
                },
            )
    except Exception as exc:
        print(f"[rule-snapshot] failed to persist web_order snapshot order_id={getattr(web_order, 'id', None)}: {type(exc).__name__}: {exc}")

    create_or_update_acceptance_meta(
        order_id=int(web_order.id),
        order_rule_key=rule.key,
        required_staff_count=required_staff_count,
        min_protector_count=int(rule.min_protector_count or 0),
        allowed_role_ids=allowed_role_ids_for_rule,
        required_game_role_ids=required_game_role_ids_for_rule,
        specified_staff_ids=specified_staff_ids,
        point_benefits_allowed=bool(rule.point_benefits_allowed),
        status=WAITING_ACCEPTANCE,
    )


    try:
        create_smart_dispatch_plan(
            order_id=int(web_order.id),
            dispatch_channel_id=dispatch_channel.id,
            dispatch_message_id=dispatch_message.id,
            required_staff_count=required_staff_count,
            allowed_role_ids=allowed_role_ids_for_rule,
            specified_staff_ids=specified_staff_ids,
            required_game_role_ids=required_game_role_ids_for_rule,
            ranked_candidate_ids=smart_dispatch["ranked_candidate_ids"],
            notified_candidate_ids=smart_dispatch["initial_notified_ids"],
        )
    except Exception as exc:
        print(
            f"[smart-dispatch] plan create failed "
            f"order_id={int(web_order.id)}: {type(exc).__name__}: {exc}",
            flush=True,
        )

    if specified_staff_ids:
        try:
            dm_sent_ids, dm_failed_ids = await send_specified_staff_dispatch_dms(
                guild,
                specified_staff_ids=specified_staff_ids,
                category_label=category_label,
                item_label=rule.label,
                required_staff_count=required_staff_count,
                dispatch_jump_url=dispatch_message.jump_url,
                allowed_role_ids=allowed_role_ids_for_rule,
                required_game_role_ids=required_game_role_ids_for_rule,
            )

            try:
                set_specified_dm_results(
                    int(web_order.id),
                    sent_ids=dm_sent_ids,
                    failed_ids=dm_failed_ids,
                )
            except Exception as exc:
                print(
                    f"[smart-dispatch] DM result persist failed "
                    f"order_id={int(web_order.id)}: {type(exc).__name__}: {exc}",
                    flush=True,
                )

            if dm_failed_ids:
                print(
                    f"[smart-dispatch] specified DM unavailable "
                    f"order_id={int(web_order.id)} "
                    f"failed={','.join(dm_failed_ids)}",
                    flush=True,
                )
        except Exception as exc:
            print(
                f"[smart-dispatch] specified DM failed "
                f"order_id={int(web_order.id)}: {type(exc).__name__}: {exc}",
                flush=True,
            )

    try:
        from shared.db import engine as _rule_snapshot_engine
        from sqlalchemy import text as _rule_snapshot_sql_text

        with _rule_snapshot_engine.begin() as _rule_snapshot_conn:
            _rule_snapshot_conn.execute(
                _rule_snapshot_sql_text("""
                    UPDATE order_acceptance_meta
                    SET rule_version = :rule_version,
                        rule_snapshot_json = :rule_snapshot_json,
                        price_snapshot_json = :price_snapshot_json,
                        updated_at = :updated_at
                    WHERE order_id = :order_id
                """),
                {
                    "order_id": int(web_order.id),
                    "rule_version": int(rule_version),
                    "rule_snapshot_json": rule_snapshot_json,
                    "price_snapshot_json": price_snapshot_json,
                    "updated_at": get_taipei_now_iso(),
                },
            )
    except Exception as exc:
        print(f"[rule-snapshot] failed to persist acceptance_meta snapshot order_id={getattr(web_order, 'id', None)}: {type(exc).__name__}: {exc}")

    ORDER_CLAIMS[dispatch_message.id] = {
        "companion": set(),
        "booster": set(),
        "locked": False,
        "customer_id": customer_id,
        "category_label": category_label,
        "category": rule.category,
        "item": rule.label,
        "order_rule_key": rule.key,
        "quantity": quantity,
        "player_count": player_count,
        "payment_method": "待付款",
        "amount": amount,
        "total_amount": amount,
        "source_channel_id": interaction.channel.id,
        "companion_preference": companion_preference,
        "dispatch_channel_id": dispatch_channel.id,
        "status": WAITING_ACCEPTANCE,
        "accepted_count": 0,
        "required_staff_count": required_staff_count,
        "min_protector_count": int(rule.min_protector_count or 0),
        "specified_staff_ids": specified_staff_ids,
    }

    data["customer_id"] = customer_id
    data["category"] = rule.category
    data["category_label"] = category_label
    data["item"] = rule.label
    data["order_rule_key"] = rule.key
    data["rule_version"] = rule_version
    data["rule_snapshot_json"] = rule_snapshot_json
    data["price_snapshot_json"] = price_snapshot_json
    data["quantity"] = quantity
    data["player_count"] = player_count
    data["manual_price_missing"] = price_adjustment["manual_price_missing"]
    data["manual_staff_amount"] = price_adjustment["manual_staff_amount"]
    data["manual_staff_price_reason"] = price_adjustment["manual_staff_price_reason"]
    data["rule_original_amount"] = price_adjustment["rule_original_amount"]
    data["original_amount"] = price_adjustment["original_amount"]
    data["manual_discount_percent"] = price_adjustment["manual_discount_percent"]
    data["manual_discount_amount"] = price_adjustment["manual_discount_amount"]
    data["manual_discount_reason"] = price_adjustment["manual_discount_reason"]
    data["payout_base_amount"] = payout_base_amount
    data["cash_coupon_amount"] = price_adjustment["cash_coupon_amount"]
    data["cash_coupon_reason"] = price_adjustment["cash_coupon_reason"]
    data["point_benefit_key"] = price_adjustment["point_benefit_key"]
    data["point_benefit_name"] = price_adjustment["point_benefit_name"]
    data["point_benefit_cost"] = price_adjustment["point_benefit_cost"]
    data["point_discount_coupon_amount"] = price_adjustment["point_discount_coupon_amount"]
    data["point_waived_specify_fee"] = price_adjustment["point_waived_specify_fee"]
    data["point_free_first_hour_amount"] = price_adjustment["point_free_first_hour_amount"]
    data["point_extra_hours"] = price_adjustment["point_extra_hours"]
    data["point_extra_games"] = price_adjustment["point_extra_games"]
    data["service_bonus_text"] = price_adjustment["service_bonus_text"]
    data["benefit_coupon_id"] = price_adjustment.get("benefit_coupon_id")
    data["benefit_coupon_title"] = price_adjustment.get("benefit_coupon_title")
    data["benefit_service_value"] = price_adjustment.get("benefit_service_value")
    data["benefit_service_note"] = price_adjustment.get("benefit_service_note")
    data["store_absorbed_amount"] = price_adjustment["store_absorbed_amount"]
    data["customer_pay_amount"] = price_adjustment["customer_pay_amount"]
    data["amount"] = amount
    data["total_amount"] = amount
    data["amount_text"] = _format_plain_amount(amount)
    data["payment_method"] = "待付款"
    data["dispatch_message_id"] = dispatch_message.id
    data["dispatch_channel_id"] = dispatch_channel.id
    data["web_order_id"] = int(web_order.id)
    data["status"] = WAITING_ACCEPTANCE
    data["closed"] = False
    data["specified_staff_ids"] = specified_staff_ids
    data["waiting_acceptance_created_at"] = get_taipei_now_iso()

    remember_order_data(interaction.channel.id, data)
    remember_claim_data(dispatch_message.id, ORDER_CLAIMS[dispatch_message.id])
    save_bot_data()

    await send_order_log(
        guild,
        title="新自助下單｜等待接單",
        fields=[
            ("顧客", f"<@{customer_id}>", True),
            ("訂單類別", category_label, True),
            ("訂單項目", rule.label, True),
            ("數量", f"{quantity} {get_self_service_quantity_unit(rule.label)}", True),
            ("訂單總價", _format_plain_amount(amount), True),
            ("接單需求", f"{required_staff_count} 位", True),
            ("票口", interaction.channel.mention, False),
            ("派單訊息", dispatch_message.jump_url, False),
        ],
        color=discord.Color.blue(),
    )

    await log_self_service_proxy_action(
        interaction,
        customer_id,
        "送出等待接單",
        f"{category_label}｜{rule.label}｜{quantity} {get_self_service_quantity_unit(rule.label)}｜{_format_plain_amount(amount)}",
    )

    return f"已送出等待接單：{dispatch_message.jump_url}"







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

SPECIFIED_STAFF_SELECT_PAGE_SIZE = 25

SPECIFIED_STAFF_ROLE_LABELS = {
    "top_protector": "魔丸♛頂護",
    "female_protector": "魔丸♝女護",
    "male_protector": "魔丸♜男護",
    "male_companion": "魔丸♞男陪",
    "female_companion": "魔丸♟女陪",
}


def _truncate_select_text(value: str, limit: int = 100) -> str:
    text_value = str(value or "").strip()

    if len(text_value) <= limit:
        return text_value

    return text_value[: limit - 1] + "…"


def get_specified_staff_entries_for_rule(guild: discord.Guild, rule) -> list[dict]:
    from services.order_rules import ALL_ROLE_IDS, ALL_ROLE_LABELS, get_allowed_role_keys

    entries = []
    allowed_role_keys = list(get_allowed_role_keys(rule))

    for member in guild.members:
        if getattr(member, "bot", False):
            continue

        member_role_ids = {
            str(role.id)
            for role in getattr(member, "roles", [])
            if getattr(role, "id", None) is not None
        }

        matched_role_keys = [
            role_key
            for role_key in allowed_role_keys
            if str(ALL_ROLE_IDS.get(role_key)) in member_role_ids
        ]

        if not matched_role_keys:
            continue

        display_role_key = _role_key_for_member(rule, member) or matched_role_keys[0]
        role_label = (
            SPECIFIED_STAFF_ROLE_LABELS.get(display_role_key)
            or ALL_ROLE_LABELS.get(display_role_key, display_role_key)
        )

        entries.append({
            "id": str(member.id),
            "label": _truncate_select_text(getattr(member, "display_name", None) or getattr(member, "name", None) or str(member.id)),
            "description": _truncate_select_text(role_label),
            "role_order": allowed_role_keys.index(display_role_key) if display_role_key in allowed_role_keys else 999,
        })

    entries.sort(key=lambda item: (item["role_order"], item["label"].casefold(), item["id"]))
    return entries



async def _acknowledge_component_interaction(interaction: discord.Interaction) -> None:
    try:
        if not interaction.response.is_done():
            await interaction.response.defer()
    except discord.HTTPException:
        pass


async def _edit_component_message(
    interaction: discord.Interaction,
    *,
    content: str | None = None,
    view: discord.ui.View | None = None,
) -> None:
    try:
        if interaction.response.is_done():
            await interaction.edit_original_response(content=content, view=view)
        else:
            await interaction.response.edit_message(content=content, view=view)
    except discord.NotFound:
        pass
    except discord.HTTPException as exc:
        try:
            await interaction.followup.send(f"更新指定人員選單失敗：{exc}", ephemeral=True)
        except discord.HTTPException:
            pass

class SelfServiceSpecifiedStaffDropdown(discord.ui.Select):
    def __init__(self, parent_view: "SelfServiceSpecifiedStaffDropdownView"):
        entries = parent_view.page_entries()
        selected_ids = set(parent_view.selected_ids)

        if entries:
            options = [
                discord.SelectOption(
                    label=entry["label"],
                    value=entry["id"],
                    description=entry["description"],
                    default=entry["id"] in selected_ids,
                )
                for entry in entries
            ]
            disabled = False
            max_values = min(parent_view.max_specified_count, len(options))
        else:
            options = [
                discord.SelectOption(
                    label="這一頁沒有可指定人員",
                    value="none",
                    description="請換頁或通知客服確認身分組",
                )
            ]
            disabled = True
            max_values = 1

        super().__init__(
            placeholder=f"選擇指定人員，最多 {parent_view.max_specified_count} 位",
            min_values=1,
            max_values=max_values,
            options=options,
            disabled=disabled,
            row=0,
        )

    async def callback(self, interaction: discord.Interaction):
        view = self.view

        if not isinstance(view, SelfServiceSpecifiedStaffDropdownView):
            await interaction.response.send_message("指定人員選單狀態異常，請重新按一次按鈕。", ephemeral=True)
            return

        if "none" in self.values:
            await interaction.response.defer()
            return

        page_ids = {entry["id"] for entry in view.page_entries()}
        current_ids = [
            staff_id
            for staff_id in view.selected_ids
            if staff_id not in page_ids
        ]

        for staff_id in self.values:
            if staff_id not in current_ids:
                current_ids.append(staff_id)

        if len(current_ids) > view.max_specified_count:
            await interaction.response.send_message(
                f"這張單最多只能指定 {view.max_specified_count} 位。",
                ephemeral=True,
            )
            return

        view.selected_ids = current_ids
        await view.save_selection_and_refresh_panel(interaction)

        view.refresh_items()

        await interaction.response.edit_message(
            content=view.build_message_content(),
            view=view,
            allowed_mentions=discord.AllowedMentions(users=True, roles=False, everyone=False),
        )


class SelfServiceSpecifiedStaffPageButton(discord.ui.Button):
    def __init__(self, direction: int):
        self.direction = direction
        label = "上一頁" if direction < 0 else "下一頁"
        super().__init__(
            label=label,
            style=discord.ButtonStyle.secondary,
            row=1,
        )

    async def callback(self, interaction: discord.Interaction):
        view = self.view

        if not isinstance(view, SelfServiceSpecifiedStaffDropdownView):
            await interaction.response.send_message("指定人員選單狀態異常，請重新按一次按鈕。", ephemeral=True)
            return

        view.page = max(0, min(view.max_page, view.page + self.direction))
        view.refresh_items()

        await interaction.response.edit_message(
            content=view.build_message_content(),
            view=view,
            allowed_mentions=discord.AllowedMentions(users=True, roles=False, everyone=False),
        )


class SelfServiceSpecifiedStaffClearButton(discord.ui.Button):
    def __init__(self):
        super().__init__(
            label="清除指定",
            style=discord.ButtonStyle.danger,
            row=1,
        )

    async def callback(self, interaction: discord.Interaction):
        view = self.view

        if not isinstance(view, SelfServiceSpecifiedStaffDropdownView):
            await interaction.response.send_message("指定人員選單狀態異常，請重新按一次按鈕。", ephemeral=True)
            return

        view.selected_ids = []
        await view.save_selection_and_refresh_panel(interaction)
        view.refresh_items()

        await interaction.response.edit_message(
            content=view.build_message_content(),
            view=view,
            allowed_mentions=discord.AllowedMentions(users=True, roles=False, everyone=False),
        )


class SelfServiceSpecifiedStaffDoneButton(discord.ui.Button):
    def __init__(self):
        super().__init__(
            label="完成",
            style=discord.ButtonStyle.success,
            row=1,
        )

    async def callback(self, interaction: discord.Interaction):
        view = self.view

        if not isinstance(view, SelfServiceSpecifiedStaffDropdownView):
            await interaction.response.send_message("指定人員選單狀態異常，請重新按一次按鈕。", ephemeral=True)
            return

        await view.save_selection_and_refresh_panel(interaction)

        await interaction.response.edit_message(
            content="已完成指定人員設定，原本的自助下單面板已更新。",
            view=None,
            allowed_mentions=discord.AllowedMentions(users=True, roles=False, everyone=False),
        )


FREE_PLAY_FIRST_HOUR_RULE_KEYS = {
    "basic_entertain_single",
    "basic_entertain_double",
    "basic_tech_secret_single",
    "basic_tech_secret_double",
}


ORDER_POINT_BENEFIT_SPECS = {
    "discount_20": {"kind": "cash_discount", "amount": 20, "summary": "20T 折價券，店內吸收，不影響陪玩分潤"},
    "discount_30": {"kind": "cash_discount", "amount": 30, "summary": "30T 折價券，店內吸收，不影響陪玩分潤"},
    "free_specify_fee": {"kind": "free_specify_fee", "summary": "免指定費，指定費由店內吸收，陪玩應得不減少"},
    "discount_100": {"kind": "cash_discount", "amount": 100, "summary": "100T 折價券，店內吸收，不影響陪玩分潤"},
    "extra_hour_30m": {"kind": "extra_hours", "hours": 0.5, "pricing_types": ("hourly",), "summary": "服務時間 +30 分鐘，由店內吸收額外服務成本"},
    "extra_hour_1h": {"kind": "extra_hours", "hours": 1, "pricing_types": ("hourly",), "summary": "服務時間 +1 小時，由店內吸收額外服務成本"},
    "extra_game_1": {"kind": "extra_games", "games": 1, "pricing_types": ("game",), "summary": "服務局數 +1 局，由店內吸收額外服務成本"},
    "extra_game_2": {"kind": "extra_games", "games": 2, "pricing_types": ("game",), "summary": "服務局數 +2 局，由店內吸收額外服務成本"},
}


















class SelfServicePointBenefitSelect(discord.ui.Select):
    def __init__(self, parent_view: "SelfServicePointBenefitView"):
        options = [
            discord.SelectOption(
                label="不使用點數福利",
                value="none",
                description="清除這張單目前選擇的點數福利",
                default=(parent_view.selected_key is None and parent_view.selected_coupon_id is None),
            )
        ]

        for coupon in parent_view.available_coupons:
            options.append(
                discord.SelectOption(
                    label=_truncate_select_text(str(coupon.get("title") or "會員福利券")),
                    value=f"coupon:{coupon['id']}",
                    description="使用累積福利券；與點數福利擇一",
                    default=str(coupon.get("id")) == str(parent_view.selected_coupon_id),
                )
            )

        for item in parent_view.available_items:
            options.append(
                discord.SelectOption(
                    label=_truncate_select_text(f"{item['cost']} 點｜{item['name']}"),
                    value=f"point:{item['key']}",
                    description=_truncate_select_text(item.get("summary") or f"兌換 {item['name']}"),
                    default=str(item["key"]) == str(parent_view.selected_key),
                )
            )

        if len(options) == 1:
            options[0].description = "目前沒有符合點數與訂單條件的福利"

        super().__init__(
            placeholder="選擇點數 / 會員福利",
            min_values=1,
            max_values=1,
            options=options[:25],
            row=0,
        )

    async def callback(self, interaction: discord.Interaction):
        view = self.view

        if not isinstance(view, SelfServicePointBenefitView):
            await interaction.response.send_message("點數福利選單狀態異常，請重新按一次按鈕。", ephemeral=True)
            return

        selected = self.values[0]
        data = SELF_SERVICE_ORDER_SELECTIONS.setdefault(view.channel_id, {})

        clear_keys = (
            "selected_point_benefit_key",
            "selected_benefit_coupon_id",
            "point_benefit_key",
            "point_benefit_name",
            "point_benefit_cost",
            "point_discount_coupon_amount",
            "point_waived_specify_fee",
            "point_extra_hours",
            "point_extra_games",
            "service_bonus_text",
            "benefit_coupon_id",
            "benefit_coupon_title",
            "benefit_service_note",
        )
        for key in clear_keys:
            data.pop(key, None)

        if selected.startswith("coupon:"):
            try:
                data["selected_benefit_coupon_id"] = int(selected.split(":", 1)[1])
            except (TypeError, ValueError):
                await interaction.response.send_message("福利券格式錯誤，請重新選擇。", ephemeral=True)
                return
        elif selected.startswith("point:"):
            point_key = selected.split(":", 1)[1]
            item = get_order_point_item(point_key)
            if item is None:
                await interaction.response.send_message("找不到這個點數福利，請重新選擇。", ephemeral=True)
                return
            data["selected_point_benefit_key"] = point_key
            data["point_benefit_key"] = point_key
            data["point_benefit_name"] = str(item.get("name") or point_key)
            data["point_benefit_cost"] = int(item.get("cost") or 0)

        data.pop("payment_method", None)
        remember_order_data(view.channel_id, data)

        await view.refresh_source_panel(interaction)

        await interaction.response.edit_message(
            content=view.build_message_content(data),
            view=SelfServicePointBenefitView(
                customer_id=view.customer_id,
                channel_id=view.channel_id,
                panel_message_id=view.panel_message_id,
                rule=view.rule,
            ),
            allowed_mentions=discord.AllowedMentions(users=True, roles=False, everyone=False),
        )


class SelfServicePointBenefitView(discord.ui.View):
    def __init__(
        self,
        *,
        customer_id: int,
        channel_id: int,
        panel_message_id: int | None,
        rule,
    ):
        super().__init__(timeout=300)
        self.customer_id = int(customer_id)
        self.channel_id = int(channel_id)
        self.panel_message_id = panel_message_id
        self.rule = rule

        data = SELF_SERVICE_ORDER_SELECTIONS.get(channel_id, {})
        self.selected_key = data.get("selected_point_benefit_key")
        self.selected_coupon_id = data.get("selected_benefit_coupon_id")
        self.point_balance = get_customer_point_balance_for_order(customer_id)
        self.available_items = self.build_available_items(data)
        from services.loyalty_benefits import list_applicable_coupons
        self.available_coupons = list_applicable_coupons(
            customer_id,
            rule_key=str(getattr(rule, "key", "")),
            player_count=_to_int(data.get("player_count"), 1) or 1,
        )

        self.add_item(SelfServicePointBenefitSelect(self))

    def build_available_items(self, data: dict) -> list[dict]:
        result = []

        try:
            source_items = POINT_REDEEM_ITEMS
        except Exception:
            source_items = []

        for item in source_items:
            key = str(item.get("key") or "")
            spec = ORDER_POINT_BENEFIT_SPECS.get(key)

            if not spec:
                continue

            cost = int(item.get("cost") or 0)

            if cost > self.point_balance:
                continue

            allowed, _ = is_order_point_benefit_allowed_for_rule(self.rule, key, data)

            if not allowed:
                continue

            merged = dict(item)
            merged.update(spec)
            merged = _adapt_order_point_benefit_for_rule(
                self.rule,
                merged,
            )
            result.append(merged)

        return result

    def build_message_content(self, data: dict | None = None) -> str:
        data = data or SELF_SERVICE_ORDER_SELECTIONS.get(self.channel_id, {})
        benefit = get_selected_order_point_benefit(data, self.rule)
        selected_text = "尚未使用"

        if data.get("selected_benefit_coupon_id"):
            coupon = next(
                (item for item in self.available_coupons if str(item.get("id")) == str(data.get("selected_benefit_coupon_id"))),
                None,
            )
            if coupon:
                selected_text = str(coupon.get("title") or "會員福利券")
        elif benefit:
            selected_text = f"{benefit['cost']} 點｜{benefit['name']}"

        return (
            f"請選擇這張單要使用的點數福利或會員福利券。\n"
            f"目前可用點數：{self.point_balance} 點\n"
            f"可用福利券：{len(self.available_coupons)} 張\n"
            f"目前選擇：{selected_text}\n\n"
            "同張訂單只能擇一；福利券會在訂單建立時先保留，結單後正式核銷。"
        )

    async def refresh_source_panel(self, interaction: discord.Interaction):
        data = SELF_SERVICE_ORDER_SELECTIONS.get(self.channel_id, {})

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
            except discord.HTTPException:
                pass

class SelfServiceSpecifiedStaffDropdownView(discord.ui.View):
    def __init__(
        self,
        *,
        customer_id: int,
        channel_id: int,
        panel_message_id: int | None,
        rule_key: str,
        max_specified_count: int,
        entries: list[dict],
        selected_ids: list[str] | None = None,
    ):
        super().__init__(timeout=300)
        self.customer_id = int(customer_id)
        self.channel_id = int(channel_id)
        self.panel_message_id = panel_message_id
        self.rule_key = str(rule_key)
        self.max_specified_count = max(1, int(max_specified_count or 1))
        self.entries = entries
        self.selected_ids = list(dict.fromkeys(str(item) for item in (selected_ids or []) if str(item).strip()))
        self.page = 0
        self.refresh_items()

    @property
    def max_page(self) -> int:
        if not self.entries:
            return 0
        return max(0, (len(self.entries) - 1) // SPECIFIED_STAFF_SELECT_PAGE_SIZE)

    def page_entries(self) -> list[dict]:
        start = self.page * SPECIFIED_STAFF_SELECT_PAGE_SIZE
        end = start + SPECIFIED_STAFF_SELECT_PAGE_SIZE
        return self.entries[start:end]

    def refresh_items(self):
        self.clear_items()
        self.add_item(SelfServiceSpecifiedStaffDropdown(self))

        previous_button = SelfServiceSpecifiedStaffPageButton(-1)
        previous_button.disabled = self.page <= 0
        self.add_item(previous_button)

        next_button = SelfServiceSpecifiedStaffPageButton(1)
        next_button.disabled = self.page >= self.max_page
        self.add_item(next_button)

        self.add_item(SelfServiceSpecifiedStaffClearButton())
        self.add_item(SelfServiceSpecifiedStaffDoneButton())

    def selected_mentions(self) -> list[str]:
        return [f"<@{staff_id}>" for staff_id in self.selected_ids]

    def build_message_content(self) -> str:
        selected_text = "、".join(self.selected_mentions()) if self.selected_ids else "尚未指定"

        return (
            f"請從下拉式清單選擇指定人員。\n"
            f"目前頁數：{self.page + 1}/{self.max_page + 1}\n"
            f"最多可指定：{self.max_specified_count} 位\n"
            f"目前指定：{selected_text}"
        )

    async def save_selection_and_refresh_panel(self, interaction: discord.Interaction):
        data = SELF_SERVICE_ORDER_SELECTIONS.setdefault(self.channel_id, {})

        data["specified_staff_ids"] = self.selected_ids

        if self.selected_ids:
            data["companion_preference"] = "指定陪玩/打手"
        else:
            data["companion_preference"] = "不指定陪玩/打手"

        data.pop("payment_method", None)
        remember_order_data(self.channel_id, data)

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
            except discord.HTTPException:
                pass

def is_self_service_staff_price_required(rule) -> bool:
    rule_key = str(getattr(rule, "key", "") or "")
    pricing_type = str(getattr(rule, "pricing_type", "") or "").lower()

    return (
        rule_key in {"farm_department_task", "custom_custom_order"}
        or pricing_type in {"manual", "staff", "custom"}
    )


def get_self_service_staff_price(data: dict) -> int | None:
    amount = _to_int(data.get("manual_staff_amount"), None)

    if amount is None:
        return None

    return max(0, int(amount))


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
            await interaction.followup.send(str(exc), ephemeral=True)
            return
        except Exception as exc:
            print(f"[acceptance] 備註後建立 waiting_acceptance 自助單失敗 channel_id={self.channel_id}: {exc}")
            await interaction.followup.send("送出等待接單失敗，請通知客服確認後台紀錄。", ephemeral=True)
            return

        if isinstance(interaction.channel, discord.TextChannel) and self.panel_message_id:
            try:
                panel_message = await interaction.channel.fetch_message(self.panel_message_id)
                await panel_message.edit(view=None)
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
















