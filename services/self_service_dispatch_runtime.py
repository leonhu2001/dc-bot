from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Callable, Mapping

import discord

from services.self_service_dispatch_cleanup import cleanup_failed_self_service_dispatch


@dataclass(frozen=True)
class SelfServiceDispatchDeps:
    dispatch_channel_id: int
    order_selections: dict
    order_claims: dict
    to_int: Callable[..., Any]
    get_rule_from_data: Callable[[dict], Any]
    normalize_staff_count: Callable[[dict], Any]
    resolve_specified_roles: Callable[..., Any]
    apply_financials: Callable[..., dict]
    category_labels: Mapping[str, str]
    member_display_name: Callable[..., str]
    build_order_embed: Callable[..., discord.Embed]
    format_amount: Callable[..., str]
    add_financial_fields: Callable[..., Any]
    prepare_initial_dispatch: Callable[..., dict]
    dispatch_claim_view: Callable[..., discord.ui.View]
    remember_order: Callable[..., Any]
    is_customer_staff: Callable[..., bool]
    create_dispatch_plan: Callable[..., Any]
    send_specified_dms: Callable[..., Any]
    set_specified_dm_results: Callable[..., Any]
    now_iso: Callable[[], str]
    remember_claim: Callable[..., Any]
    save_data: Callable[[], Any]
    send_initial_alert: Callable[..., Any]
    order_log_sender: Callable[..., Any]
    quantity_unit: Callable[..., str]
    proxy_logger: Callable[..., Any]


async def create_waiting_acceptance_order(
    interaction: discord.Interaction,
    *,
    customer_id: int,
    channel_id: int,
    deps: SelfServiceDispatchDeps,
) -> str:
    """Create a self-service dispatch with a runtime-owned compensation boundary.

    The Discord dispatch stays inert until canonical WebOrder/acceptance/local
    state is ready. Any failure before the claim panel is activated is rolled
    back here rather than relying on a UI caller to remember compensation.
    """
    data = deps.order_selections.setdefault(channel_id, {})

    if data.get("dispatch_rollback_pending"):
        try:
            warnings = await cleanup_failed_self_service_dispatch(
                interaction,
                channel_id=channel_id,
                data=data,
                order_claims=deps.order_claims,
                default_dispatch_channel_id=int(deps.dispatch_channel_id),
                remember_order=deps.remember_order,
                save_data=deps.save_data,
            )
        except Exception as cleanup_exc:
            raise RuntimeError(
                "上一次派單回滾尚未完成，暫時不能建立新派單，請通知客服主管確認。"
            ) from cleanup_exc

        if warnings:
            raise RuntimeError(
                "上一次派單回滾尚未完成，暫時不能建立新派單，請通知客服主管確認。"
            )

    try:
        return await _create_waiting_acceptance_order_once(
            interaction,
            customer_id=customer_id,
            channel_id=channel_id,
            deps=deps,
        )
    except Exception:
        failed_data = deps.order_selections.setdefault(channel_id, {})
        provisional_started = (
            deps.to_int(
                failed_data.get("provisional_dispatch_message_id"),
                None,
            )
            is not None
        )

        if provisional_started:
            try:
                warnings = await cleanup_failed_self_service_dispatch(
                    interaction,
                    channel_id=channel_id,
                    data=failed_data,
                    order_claims=deps.order_claims,
                    default_dispatch_channel_id=int(deps.dispatch_channel_id),
                    remember_order=deps.remember_order,
                    save_data=deps.save_data,
                )
                if warnings:
                    print(
                        f"[self-service-dispatch] rollback pending channel_id={channel_id}: "
                        + "；".join(warnings),
                        flush=True,
                    )
            except Exception as cleanup_exc:
                print(
                    f"[self-service-dispatch] rollback crashed channel_id={channel_id}: "
                    f"{type(cleanup_exc).__name__}: {cleanup_exc}",
                    flush=True,
                )

        raise


async def _create_waiting_acceptance_order_once(
    interaction: discord.Interaction,
    *,
    customer_id: int,
    channel_id: int,
    deps: SelfServiceDispatchDeps,
) -> str:
    DISPATCH_CHANNEL_ID = int(deps.dispatch_channel_id)
    SELF_SERVICE_ORDER_SELECTIONS = deps.order_selections
    ORDER_CLAIMS = deps.order_claims
    _to_int = deps.to_int
    _get_rule_from_self_service_data = deps.get_rule_from_data
    normalize_self_service_staff_count = deps.normalize_staff_count
    _resolve_specified_roles_for_price = deps.resolve_specified_roles
    apply_self_service_financials_to_order_data = deps.apply_financials
    ORDER_CATEGORY_LABELS = deps.category_labels
    _member_display_name = deps.member_display_name
    build_self_service_order_embed = deps.build_order_embed
    _format_plain_amount = deps.format_amount
    add_self_service_financial_breakdown_fields = deps.add_financial_fields
    prepare_initial_smart_dispatch = deps.prepare_initial_dispatch
    DispatchClaimView = deps.dispatch_claim_view
    remember_order_data = deps.remember_order
    is_customer_staff = deps.is_customer_staff
    create_smart_dispatch_plan = deps.create_dispatch_plan
    send_specified_staff_dispatch_dms = deps.send_specified_dms
    set_specified_dm_results = deps.set_specified_dm_results
    get_taipei_now_iso = deps.now_iso
    remember_claim_data = deps.remember_claim
    save_bot_data = deps.save_data
    send_initial_smart_dispatch_alert = deps.send_initial_alert
    send_order_log = deps.order_log_sender
    get_self_service_quantity_unit = deps.quantity_unit
    log_self_service_proxy_action = deps.proxy_logger
    guild = interaction.guild

    if guild is None:
        raise ValueError("這個功能只能在伺服器內使用。")

    if not isinstance(interaction.channel, discord.TextChannel):
        raise ValueError("無法確認目前票口頻道。")

    data = SELF_SERVICE_ORDER_SELECTIONS.setdefault(channel_id, {})
    data["customer_id"] = int(customer_id)

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
        "vip_monthly_benefit_id": price_adjustment.get("vip_monthly_benefit_id"),
        "vip_monthly_benefit_key": price_adjustment.get("vip_monthly_benefit_key"),
        "vip_monthly_benefit_title": price_adjustment.get("vip_monthly_benefit_title"),
        "vip_monthly_cash_amount": price_adjustment.get("vip_monthly_cash_amount"),
        "point_waived_specify_fee": price_adjustment.get("point_waived_specify_fee"),
        "point_free_first_hour_amount": price_adjustment.get("point_free_first_hour_amount"),
        "point_extra_hours": price_adjustment.get("point_extra_hours"),
        "point_extra_games": price_adjustment.get("point_extra_games"),
        "benefit_coupon_id": price_adjustment.get("benefit_coupon_id"),
        "benefit_coupon_title": price_adjustment.get("benefit_coupon_title"),
        "benefit_coupon": price_adjustment.get("benefit_coupon"),
        "benefit_service_value": price_adjustment.get("benefit_service_value"),
        "benefit_discount_amount": price_adjustment.get("benefit_discount_amount"),
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
        view=None,
        allowed_mentions=discord.AllowedMentions(
            users=True,
            roles=True,
            everyone=False,
        ),
    )

    data["provisional_dispatch_message_id"] = dispatch_message.id
    data["provisional_dispatch_channel_id"] = dispatch_channel.id
    remember_order_data(interaction.channel.id, data)

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

    if price_adjustment.get("vip_monthly_benefit_title"):
        web_note_parts.append(
            "VIP 月福利："
            f"{price_adjustment['vip_monthly_benefit_title']}"
            f"｜折抵 {int(price_adjustment.get('vip_monthly_cash_amount') or 0)}T"
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

    if price_adjustment.get("vip_monthly_benefit_id"):
        from services.vip_monthly_benefits import reserve_cash_benefit_for_channel
        reserve_cash_benefit_for_channel(
            benefit_id=int(price_adjustment["vip_monthly_benefit_id"]),
            customer_id=customer_id,
            channel_id=interaction.channel.id,
        )

    try:
        from shared.db import engine as _rule_snapshot_engine
        from sqlalchemy import text as _rule_snapshot_sql_text

        with _rule_snapshot_engine.begin() as _rule_snapshot_conn:
            result = _rule_snapshot_conn.execute(
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
            if result.rowcount != 1:
                raise RuntimeError(
                    f"WebOrder snapshot update rowcount={result.rowcount}"
                )
    except Exception as exc:
        raise RuntimeError("WebOrder 規則／價格快照寫入失敗。") from exc

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
        raise RuntimeError("智慧派單計畫建立失敗。") from exc

    try:
        from shared.db import engine as _rule_snapshot_engine
        from sqlalchemy import text as _rule_snapshot_sql_text

        with _rule_snapshot_engine.begin() as _rule_snapshot_conn:
            result = _rule_snapshot_conn.execute(
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
            if result.rowcount != 1:
                raise RuntimeError(
                    f"acceptance snapshot update rowcount={result.rowcount}"
                )
    except Exception as exc:
        raise RuntimeError("接單規則／價格快照寫入失敗。") from exc

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
    data["benefit_coupon"] = price_adjustment.get("benefit_coupon")
    data["benefit_service_value"] = price_adjustment.get("benefit_service_value")
    data["benefit_discount_amount"] = price_adjustment.get("benefit_discount_amount")
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

    try:
        await dispatch_message.edit(
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
    except (discord.Forbidden, discord.HTTPException) as exc:
        raise RuntimeError("派單訊息建立完成，但接單 Panel 啟用失敗。") from exc

    # From this point the panel is public and may be claimed immediately. Do not
    # compensate later notification/log failures back into a deleted order.
    data.pop("provisional_dispatch_message_id", None)
    data.pop("provisional_dispatch_channel_id", None)
    remember_order_data(interaction.channel.id, data)
    save_bot_data()

    try:
        await send_initial_smart_dispatch_alert(
            guild,
            content=smart_dispatch["content"],
            dispatch_jump_url=dispatch_message.jump_url,
        )
    except Exception as exc:
        print(
            f"[smart-dispatch] initial alert failed: {type(exc).__name__}: {exc}",
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
    except Exception as exc:
        print(
            f"[self-service-dispatch] order log failed channel_id={channel_id}: "
            f"{type(exc).__name__}: {exc}",
            flush=True,
        )

    try:
        await log_self_service_proxy_action(
            interaction,
            customer_id,
            "送出等待接單",
            f"{category_label}｜{rule.label}｜{quantity} {get_self_service_quantity_unit(rule.label)}｜{_format_plain_amount(amount)}",
        )
    except Exception as exc:
        print(
            f"[self-service-dispatch] proxy log failed channel_id={channel_id}: "
            f"{type(exc).__name__}: {exc}",
            flush=True,
        )

    return f"已送出等待接單：{dispatch_message.jump_url}"
