from __future__ import annotations

from services.loyalty_benefits import (
    get_coupon,
    list_available_coupons,
    reserve_coupon,
    validate_coupon_for_order,
)

from typing import Any, Mapping

import discord


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

    _CONFIGURED = True


def _format_plain_amount(amount: int | None) -> str:
    if amount is None:
        return "客服待填價"
    return f"{int(amount or 0):,}"


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



def _price_int(
    src: dict,
    *keys,
    default=0,
):
    for key in keys:
        value = src.get(key)

        if (
            value is None
            or str(value).strip() == ""
        ):
            continue

        value = _to_int(
            value,
            None,
        )

        if value is not None:
            return int(value)

    return int(default)


def _price_rate(
    src: dict,
) -> float:
    try:
        value = float(
            src.get(
                "discount_rate_percent",
                src.get(
                    "manual_discount_percent",
                    100,
                ),
            )
        )
    except (TypeError, ValueError):
        value = 100.0

    value = max(
        0.0,
        min(
            100.0,
            value,
        ),
    )

    mode = str(
        src.get(
            "manual_discount_mode"
        )
        or ""
    ).strip().lower()

    if (
        mode == "pay_rate"
        or _price_int(
            src,
            "price_formula_version",
            default=0,
        )
        >= 2
    ):
        return value

    return 100.0 - value


def _price_snapshot(
    value,
) -> dict:
    if isinstance(
        value,
        dict,
    ):
        return dict(value)

    try:
        parsed = json.loads(
            str(
                value
                or ""
            )
        )
    except Exception:
        return {}

    return (
        parsed
        if isinstance(
            parsed,
            dict,
        )
        else {}
    )


def add_self_service_financial_breakdown_fields(
    embed: discord.Embed,
    src: dict,
    final_label="顧客應付",
):
    src = dict(
        src
        or {}
    )

    original = max(
        0,
        _price_int(
            src,
            "service_original_amount",
            "original_amount",
            default=0,
        ),
    )

    percent_off = max(
        0,
        _price_int(
            src,
            "percent_discount_amount",
            "manual_discount_amount",
            default=0,
        ),
    )

    fixed = max(
        0,
        _price_int(
            src,
            "fixed_discount_amount",
            "cash_coupon_amount",
            default=0,
        ),
    )

    point_cash = max(
        0,
        _price_int(
            src,
            "point_discount_coupon_amount",
            default=0,
        ),
    )

    specify_before = max(
        0,
        _price_int(
            src,
            "specified_fee_before_waiver",
            default=0,
        ),
    )

    point_specify = max(
        0,
        _price_int(
            src,
            "point_waived_specify_fee",
            default=0,
        ),
    )

    specify_effective = src.get(
        "effective_specify_fee"
    )

    if specify_effective is None:
        specify_effective = max(
            0,
            specify_before
            - point_specify,
        )
    else:
        specify_effective = max(
            0,
            _to_int(
                specify_effective,
                0,
            )
            or 0,
        )

    final = max(
        0,
        _price_int(
            src,
            "customer_pay_amount",
            "amount",
            "total_amount",
            default=0,
        ),
    )

    payout = max(
        0,
        _price_int(
            src,
            "payout_base_amount",
            default=0,
        ),
    )

    rate = _price_rate(
        src
    )

    embed.add_field(
        name="商品原價",
        value=_format_plain_amount(
            original
        ),
        inline=True,
    )

    if (
        rate < 100
        or percent_off
    ):
        embed.add_field(
            name="百分比折扣",
            value=(
                "折後 "
                f"{_format_percent_value(rate)}%"
                "\n"
                f"-{_format_plain_amount(percent_off)}"
            ),
            inline=True,
        )

    if fixed:
        reason = str(
            src.get(
                "cash_coupon_reason"
            )
            or ""
        ).strip()

        text = (
            f"-{_format_plain_amount(fixed)}"
        )

        if reason:
            text += (
                f"\n{reason}"
            )

        text += (
            "\n店內吸收，不影響打手分潤"
        )

        embed.add_field(
            name="固定折扣",
            value=text,
            inline=True,
        )

    if point_cash:
        embed.add_field(
            name="點數折價",
            value=(
                f"-{_format_plain_amount(point_cash)}"
                "\n店內吸收，不扣打手分潤"
            ),
            inline=True,
        )

    if specify_before:
        if specify_effective == 0:
            text = (
                f"原 {_format_plain_amount(specify_before)}"
                "\n已免除"
            )

        else:
            text = (
                "+"
                f"{_format_plain_amount(specify_effective)}"
            )

        embed.add_field(
            name="指定費",
            value=text,
            inline=True,
        )

    embed.add_field(
        name=final_label,
        value=_format_plain_amount(
            final
        ),
        inline=True,
    )

    embed.add_field(
        name="打手分潤基準",
        value=_format_plain_amount(
            payout
        ),
        inline=True,
    )

    benefit_name = str(
        src.get(
            "point_benefit_name"
        )
        or ""
    ).strip()

    bonus = str(
        src.get(
            "service_bonus_text"
        )
        or ""
    ).strip()

    if benefit_name:
        lines = [
            (
                f"{_price_int(src, 'point_benefit_cost', default=0)} "
                f"點｜{benefit_name}"
            )
        ]

        if point_cash:
            lines.append(
                "已直接折抵價格："
                f"-{_format_plain_amount(point_cash)}"
            )

        if bonus:
            lines.append(
                f"訂單備註：{bonus}"
            )

        embed.add_field(
            name="點數福利",
            value="\n".join(
                lines
            ),
            inline=False,
        )

    elif bonus:
        embed.add_field(
            name="訂單福利備註",
            value=bonus,
            inline=False,
        )

    # service_promotion_financial_embed_v1
    service_promotion_text = str(
        src.get(
            "service_promotion_text"
        )
        or ""
    ).strip()

    if service_promotion_text:
        embed.add_field(
            name="活動加贈",
            value=service_promotion_text,
            inline=False,
        )

    return embed


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
    data["point_service_value"] = price_adjustment.get("point_service_value", 0)
    data["selected_loyalty_coupon_id"] = price_adjustment.get("loyalty_coupon_id")
    data["loyalty_coupon_name"] = price_adjustment.get("loyalty_coupon_name")
    data["loyalty_service_units"] = price_adjustment.get("loyalty_service_units", 0)
    data["loyalty_service_value"] = price_adjustment.get("loyalty_service_value", 0)
    data["service_bonus_text"] = price_adjustment["service_bonus_text"]
    data["store_absorbed_amount"] = price_adjustment["store_absorbed_amount"]
    data["customer_pay_amount"] = price_adjustment["customer_pay_amount"]
    data["amount"] = amount
    data["total_amount"] = amount
    data["amount_text"] = _format_plain_amount(amount)
    data["payment_method"] = "待付款"
    data["dispatch_message_id"] = dispatch_message.id
    data["dispatch_channel_id"] = dispatch_channel.id
    data["web_order_id"] = int(web_order.id)
    if data.get("selected_loyalty_coupon_id"):
        coupon = reserve_coupon(
            int(data["selected_loyalty_coupon_id"]),
            customer_id=customer_id,
            rule_key=str(rule.key),
            player_count=player_count,
            reservation_key=f"WEB-{int(web_order.id)}",
        )
        data["loyalty_coupon_name"] = str(coupon.get("display_name") or data.get("loyalty_coupon_name") or "累積福利")
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

def _format_percent_value(value) -> str:
    try:
        number = float(value or 0)
    except (TypeError, ValueError):
        number = 0.0

    if number.is_integer():
        return str(int(number))

    return f"{number:.2f}".rstrip("0").rstrip(".")


def _parse_discount_percent_text(value: str | None) -> float:
    raw = str(value or "").strip().replace("%", "")

    if not raw:
        return 100.0

    try:
        value = float(raw)
    except ValueError as exc:
        raise ValueError(
            "折後比例請輸入數字，例如 90 代表 9 折。"
        ) from exc

    if value < 0 or value > 100:
        raise ValueError(
            "折後比例只能輸入 0～100。"
        )

    return value


def _parse_cash_amount_text(value: str | None) -> int:
    raw = str(value or "").strip().replace(",", "")

    if not raw:
        return 0

    try:
        amount = int(float(raw))
    except ValueError as exc:
        raise ValueError(
            "固定折扣金額請輸入數字，例如 100。"
        ) from exc

    if amount < 0:
        raise ValueError(
            "固定折扣金額不能小於 0。"
        )

    return amount


PRICE_FORMULA_VERSION = 2


def _resolve_manual_discount_rate_percent(data: dict) -> float:
    raw = data.get("manual_discount_percent")

    if raw is None or str(raw).strip() == "":
        return 100.0

    try:
        value = float(raw)
    except (TypeError, ValueError):
        value = 0.0

    value = max(
        0.0,
        min(100.0, value),
    )

    if (
        str(
            data.get("manual_discount_mode")
            or ""
        ).strip().lower()
        == "pay_rate"
    ):
        return value

    # legacy：
    # 舊資料 10 = 折掉 10%
    # 新制等同折後 90%
    return 100.0 - value


def _resolve_self_service_discount_rate(
    rule,
    data: dict,
) -> tuple[float, str, str, str]:
    """統一解析 DC 訂單百分比折扣。

    客服有明確輸入百分比時，以客服設定覆蓋 VIP，避免雙重疊加；
    否則依顧客目前有效 VIP 等級自動套用。
    """
    raw = data.get("manual_discount_percent")
    override = data.get("manual_discount_percent_override")

    if override is None:
        # 相容更新前已存在的客服折扣草稿：
        # 舊版 modal 會留下 set_by，但空白也會被寫成 100。
        override = (
            data.get("manual_price_adjustment_set_by") is not None
            and raw is not None
            and str(raw).strip() != ""
            and _resolve_manual_discount_rate_percent(data) < 100
        )

    if bool(override):
        rate = _resolve_manual_discount_rate_percent(data)
        reason = str(
            data.get("manual_discount_reason")
            or ""
        ).strip()
        return (
            rate,
            reason,
            "manual",
            "",
        )

    customer_id = _to_int(
        data.get("customer_id")
    )
    vip_name = "普通魔丸"

    if customer_id is not None:
        try:
            reward_data = get_customer_reward_data(
                int(customer_id)
            )
            vip_name = str(
                get_effective_member_level(
                    reward_data
                ).get("name")
                or "普通魔丸"
            )
        except Exception:
            vip_name = "普通魔丸"

    rate = float(
        get_vip_discount_pay_rate(
            vip_name,
            category=str(
                getattr(
                    rule,
                    "category",
                    "",
                )
                or ""
            ),
            rule_key=str(
                getattr(
                    rule,
                    "key",
                    "",
                )
                or ""
            ),
        )
    )

    reason = (
        f"{vip_name} 自動 VIP 折扣"
        if rate < 100
        else ""
    )

    return (
        rate,
        reason,
        (
            "vip"
            if rate < 100
            else "none"
        ),
        vip_name,
    )


def calculate_manual_price_adjustment(
    base_amount: int,
    data: dict,
) -> dict:
    original = max(
        0,
        int(base_amount or 0),
    )

    rate = (
        _resolve_manual_discount_rate_percent(
            data
        )
    )

    after_percent = max(
        0,
        min(
            original,
            int(
                round(
                    original
                    * rate
                    / 100
                )
            ),
        ),
    )

    percent_off = (
        original
        - after_percent
    )

    raw_fixed = data.get(
        "fixed_discount_amount"
    )

    if raw_fixed is None:
        raw_fixed = data.get(
            "cash_coupon_amount"
        )

    fixed = max(
        0,
        min(
            after_percent,
            _to_int(
                raw_fixed,
                0,
            )
            or 0,
        ),
    )

    allocation = allocate_store_absorbed_fixed_discount(
        after_percent_amount=after_percent,
        fixed_discount_amount=fixed,
    )

    return {
        "price_formula_version": 2,
        "manual_discount_mode": "pay_rate",

        "service_original_amount": original,
        "original_amount": original,

        "manual_discount_percent": rate,
        "discount_rate_percent": rate,

        "manual_discount_amount": percent_off,
        "percent_discount_amount": percent_off,

        # 百分比折扣仍會降低分潤基準；客服固定金額折扣由店內全額吸收。
        "payout_base_amount": allocation.payout_base_amount,

        # 舊 DB 欄位仍保留相容，
        # 但畫面統一叫固定折扣。
        "cash_coupon_amount": fixed,
        "fixed_discount_amount": fixed,

        "store_absorbed_amount": allocation.store_absorbed_amount,

        "customer_pay_amount": allocation.customer_pay_amount,

        "manual_discount_reason": str(
            data.get(
                "manual_discount_reason"
            )
            or ""
        ).strip(),

        "cash_coupon_reason": str(
            data.get(
                "cash_coupon_reason"
            )
            or ""
        ).strip(),
    }


def apply_manual_price_adjustment_to_order_data(data: dict, base_amount: int) -> dict:
    adjustment = calculate_manual_price_adjustment(base_amount, data)

    for key, value in adjustment.items():
        data[key] = value

    data["amount"] = adjustment["customer_pay_amount"]
    data["total_amount"] = adjustment["customer_pay_amount"]
    data["amount_text"] = _format_plain_amount(adjustment["customer_pay_amount"])

    return adjustment

def _quote_preview_lines_for_self_service(data: dict, guild: discord.Guild | None = None) -> list[tuple[str, str]]:
    if not data.get("item"):
        return []

    try:
        rule = _get_rule_from_self_service_data(data)
        from services.order_rules import calculate_price, get_required_staff_count, rule_role_labels
    except Exception:
        return []

    quantity = _to_int(data.get("quantity"), 1) or 1
    companion_preference = str(data.get("companion_preference") or "不指定陪玩/打手").strip()
    player_count = _to_int(data.get("player_count"), 1) or 1
    specified_staff_ids = [str(item) for item in data.get("specified_staff_ids") or []]

    specified_roles = []
    specified_mentions = []

    if guild is not None and specified_staff_ids:
        for staff_id in specified_staff_ids:
            member = None
            try:
                member = guild.get_member(int(staff_id))
            except Exception:
                member = None

            if member is not None:
                role_key = _role_key_for_member(rule, member)
                if role_key:
                    specified_roles.append(role_key)
                specified_mentions.append(member.mention)
            else:
                specified_mentions.append(f"<@{staff_id}>")

    try:
        price = calculate_price(
            rule,
            quantity=quantity,
            player_count=player_count,
            specified_roles=specified_roles,
        )
    except Exception:
        price = None

    required_staff_count = get_required_staff_count(rule, player_count)

    lines: list[tuple[str, str]] = []

    if price is None:
        lines.append(("預估金額", "客服待填價"))
    else:
        adjustment = calculate_self_service_financials(rule, price, data)

        if adjustment.get("manual_price_missing"):
            lines.append(("顧客應付", "客服待填價"))
        else:
            lines.append(("顧客應付", _format_plain_amount(adjustment["customer_pay_amount"])))

        detail_parts = [
            (
                "客服待填價格"
                if adjustment.get("manual_price_missing")
                else f"商品原價 {_format_plain_amount(adjustment['service_original_amount'])}"
            ),
        ]

        if int(price.specify_fee or 0) > 0:
            detail_parts.append(f"指定費原本 {_format_plain_amount(price.specify_fee)}")

        if adjustment["point_waived_specify_fee"] > 0:
            detail_parts.append(f"點數免指定費 -{_format_plain_amount(adjustment['point_waived_specify_fee'])}")

        if adjustment.get("point_free_first_hour_amount", 0) > 0:
            detail_parts.append(f"首小時免費 -{_format_plain_amount(adjustment['point_free_first_hour_amount'])}")

        if getattr(price, "free_specify_fee", False):
            detail_parts.append("2 小時以上免指定費")

        if adjustment["manual_discount_amount"] > 0:
            reason = adjustment["manual_discount_reason"] or "未填原因"
            detail_parts.append(
                f"百分比折扣｜折後 {_format_percent_value(adjustment['manual_discount_percent'])}%"
                f" -{_format_plain_amount(adjustment['manual_discount_amount'])}"
                f"（{reason}）"
            )

        detail_parts.append(f"打手分潤基準 {_format_plain_amount(adjustment['payout_base_amount'])}")

        if adjustment["point_discount_coupon_amount"] > 0:
            detail_parts.append(
                f"點數折價 -{_format_plain_amount(adjustment['point_discount_coupon_amount'])}"
                "（店內吸收）"
            )

        if adjustment["cash_coupon_amount"] > 0:
            reason = adjustment["cash_coupon_reason"] or "未填原因"
            detail_parts.append(
                f"固定折扣 -{_format_plain_amount(adjustment['cash_coupon_amount'])}"
                f"（{reason}，店內吸收，不影響打手分潤）"
            )

        lines.append(("金額明細", "｜".join(detail_parts)))

        if adjustment["point_benefit_name"]:
            point_text = f"{adjustment['point_benefit_cost']} 點｜{adjustment['point_benefit_name']}"
            if adjustment["service_bonus_text"]:
                point_text += f"｜{adjustment['service_bonus_text']}"
            lines.append(("點數福利", point_text))

    # service_promotion_quote_preview_v2
    if price is not None:
        promotion_text = str(
            adjustment.get(
                "service_promotion_text"
            )
            or ""
        ).strip()

        if promotion_text:
            lines.append(
                (
                    "活動加贈",
                    promotion_text,
                )
            )

    unit = get_self_service_quantity_unit(rule.label, data)
    lines.append(("數量", f"{quantity} {unit}"))

    if getattr(rule, "player_count_enabled", False):
        lines.append(("陪玩人數", f"{player_count} 位"))

    lines.append(("接單需求", f"{required_staff_count} 位"))
    lines.append(("可接職位", rule_role_labels(rule)))

    can_specify_item = bool(getattr(rule, "allow_specify", False))

    if can_specify_item:
        max_spec = rule.max_specified_count or required_staff_count

        if _is_specify_preference(companion_preference):
            if specified_mentions:
                lines.append(("指定狀態", "已選擇指定"))
                lines.append(("指定人員", "、".join(specified_mentions)))
            else:
                lines.append(("指定狀態", f"已選擇指定，尚未選擇成員\n可指定人數：最多 {max_spec} 位"))
        else:
            lines.append(("指定狀態", "目前不指定"))
            lines.append(("可指定人數", f"此項目可指定，最多 {max_spec} 位"))
    else:
        lines.append(("指定狀態", "不可指定"))

    if not rule.point_benefits_allowed:
        lines.append(("點數福利", "此分類不可使用點數福利"))

    if rule.min_quantity and int(rule.min_quantity) > 1:
        lines.append(("最低數量", f"{rule.min_quantity} {unit}"))

    return lines


def add_self_service_quote_preview(embed: discord.Embed, data: dict, guild: discord.Guild | None = None) -> discord.Embed:
    lines = _quote_preview_lines_for_self_service(data, guild)

    if not lines:
        return embed

    preview_text = "\n".join(
        f"**{name}：** {value}"
        for name, value in lines
    )

    embed.add_field(
        name="訂單試算",
        value=preview_text[:1024],
        inline=False,
    )

    return embed


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
    "discount_20": {"kind": "cash_discount", "amount": 20, "summary": "20T 折價券，由店內吸收，不影響陪玩分潤"},
    "discount_30": {"kind": "cash_discount", "amount": 30, "summary": "30T 折價券，由店內吸收，不影響陪玩分潤"},
    "discount_100": {"kind": "cash_discount", "amount": 100, "summary": "100T 折價券，由店內吸收，不影響陪玩分潤"},
    "free_specify_fee": {"kind": "free_specify_fee", "summary": "免指定費；顧客免付，由店內吸收，陪玩仍照原指定費計薪"},
    "extra_hour_30m": {"kind": "extra_hours", "hours": 0.5, "summary": "服務時間 +30 分鐘，由店內按原價服務價值吸收"},
    "extra_hour_1h": {"kind": "extra_hours", "hours": 1, "summary": "服務時間 +1 小時，由店內按原價服務價值吸收"},
    "extra_game_1": {"kind": "extra_games", "games": 1, "summary": "服務局數 +1 局，由店內按原價服務價值吸收"},
    "extra_game_2": {"kind": "extra_games", "games": 2, "summary": "服務局數 +2 局，由店內按原價服務價值吸收"},
    # Hidden compatibility only: old unsettled orders may still carry this key.
    "free_play_1h": {"kind": "free_first_hour", "hours": 1, "summary": "舊版首小時免費"},
}


def _format_point_hours(hours) -> str:
    try:
        value = float(hours or 0)
    except (TypeError, ValueError):
        value = 0.0
    if value <= 0:
        return "0H"
    if value == 0.5:
        return "30 分鐘"
    if value.is_integer():
        return f"{int(value)}H"
    return f"{value:g}H"


def get_order_point_item(key: str | None) -> dict | None:
    if not key:
        return None
    try:
        return POINT_REDEEM_ITEMS_BY_KEY.get(str(key))
    except Exception:
        return None


def get_customer_point_balance_for_order(customer_id: int) -> int:
    try:
        reward_data = get_customer_reward_data(int(customer_id))
        return int(get_current_reward_points(reward_data))
    except Exception:
        return 0


def is_order_point_benefit_allowed_for_rule(rule, key: str, data: dict | None = None) -> tuple[bool, str]:
    data = data or {}
    key = str(key or "")
    spec = ORDER_POINT_BENEFIT_SPECS.get(key)
    if not spec:
        return False, "這個點數福利不支援新下單流程。"
    if not getattr(rule, "point_benefits_allowed", False):
        return False, "此分類不可使用點數福利。"
    category = str(getattr(rule, "category", "")).lower()
    rule_key = str(getattr(rule, "key", "") or "")
    rule_label = str(getattr(rule, "label", "") or "")
    if category == "steam":
        return False, "Steam遊戲目前不可使用點數福利。"
    if category in {"fun", "delta_desktop_fun", "title"}:
        return False, "趣味單 / 高難度稱號不可使用點數福利。"
    if rule_key.startswith("basic_trial_") or rule_label.startswith("體驗單"):
        return False, "體驗單不可使用點數福利。"
    kind = str(spec.get("kind") or "")
    pricing_type = str(getattr(rule, "pricing_type", "") or "")
    if kind == "free_specify_fee":
        if not getattr(rule, "allow_specify", False):
            return False, "此項目不開放指定，因此不能使用免指定費。"
        if not data.get("specified_staff_ids"):
            return False, "請先指定人員，再使用免指定費。"
        if pricing_type == "hourly" and (_to_int(data.get("quantity"), 1) or 1) >= 2:
            return False, "2 小時以上本來就免指定費，不需要再花 30 點兌換。"
    if kind == "free_first_hour":
        if rule_key not in FREE_PLAY_FIRST_HOUR_RULE_KEYS or pricing_type != "hourly":
            return False, "這是舊版相容福利，不能用於目前這個品項。"
    if kind == "extra_hours" and pricing_type != "hourly":
        return False, "加時福利只適用計時方案。"
    if kind == "extra_games" and pricing_type != "game":
        return False, "加局福利只適用計局方案。"
    return True, ""


def _adapt_order_point_benefit_for_rule(rule, benefit: dict) -> dict:
    return dict(benefit or {})


def get_selected_order_point_benefit(data: dict, rule=None) -> dict | None:
    key = data.get("selected_point_benefit_key")
    item = get_order_point_item(key)

    if item is None:
        return None

    spec = ORDER_POINT_BENEFIT_SPECS.get(str(key))

    if spec is None:
        return None

    if rule is not None:
        allowed, _ = is_order_point_benefit_allowed_for_rule(rule, str(key), data)
        if not allowed:
            return None

    merged = dict(item)
    merged.update(spec)

    if rule is not None:
        merged = _adapt_order_point_benefit_for_rule(
            rule,
            merged,
        )

    return merged


def calculate_self_service_financials(
    rule,
    price_result,
    data: dict,
) -> dict:
    manual_price = (
        get_self_service_staff_price(
            data
        )
    )

    specify_before = max(
        0,
        int(
            getattr(
                price_result,
                "specify_fee",
                0,
            )
            or 0
        ),
    )

    staff_adjust = int(
        getattr(
            price_result,
            "staff_adjustment_amount",
            0,
        )
        or 0
    )

    if is_self_service_staff_price_required(
        rule
    ):
        service_original = max(
            0,
            int(
                manual_price
                or 0
            ),
        )

    else:
        service_original = max(
            0,
            int(
                getattr(
                    price_result,
                    "base_amount",
                    0,
                )
                or 0
            )
            + staff_adjust,
        )

    benefit = (
        get_selected_order_point_benefit(
            data,
            rule,
        )
    )

    bkey = (
        str(
            benefit.get("key")
        )
        if benefit
        else None
    )

    bname = (
        str(
            benefit.get("name")
        )
        if benefit
        else ""
    )

    bcost = (
        int(
            benefit.get("cost")
            or 0
        )
        if benefit
        else 0
    )

    bkind = (
        str(
            benefit.get("kind")
            or ""
        )
        if benefit
        else ""
    )

    point_specify = 0
    point_cash = 0

    legacy_free_hour = 0

    extra_hours = 0.0
    extra_games = 0

    if bkind == "free_specify_fee":
        point_specify = (
            specify_before
        )

    elif bkind == "cash_discount":
        point_cash = max(
            0,
            int(
                benefit.get(
                    "amount"
                )
                or 0
            ),
        )

    elif bkind == "extra_hours":
        extra_hours = max(
            0.0,
            float(
                benefit.get(
                    "hours"
                )
                or 0
            ),
        )

    elif bkind == "extra_games":
        extra_games = max(
            0,
            int(
                benefit.get(
                    "games"
                )
                or 0
            ),
        )

    elif bkind == "extra_game":
        extra_games = max(
            0,
            int(
                benefit.get(
                    "games"
                )
                or 0
            ),
        )

    elif bkind == "free_first_hour":
        # 80 點已從新清單下架。
        # 只相容舊未結單。
        try:
            from services.order_rules import (
                calculate_price
            )

            pc = (
                _to_int(
                    data.get(
                        "player_count"
                    ),
                    1,
                )
                or 1
            )

            first = calculate_price(
                rule,
                quantity=1,
                player_count=pc,
                specified_roles=[],
            )

            legacy_free_hour = max(
                0,
                int(
                    getattr(
                        first,
                        "base_amount",
                        0,
                    )
                    or 0
                ),
            )

        except Exception:
            qty = max(
                1,
                _to_int(
                    data.get(
                        "quantity"
                    ),
                    1,
                )
                or 1,
            )

            legacy_free_hour = max(
                0,
                int(
                    getattr(
                        price_result,
                        "base_amount",
                        0,
                    )
                    or 0
                )
                // qty,
            )

    selected_loyalty = None
    selected_loyalty_id = _to_int(data.get("selected_loyalty_coupon_id"), None)
    if selected_loyalty_id is not None:
        selected_loyalty = validate_coupon_for_order(
            selected_loyalty_id,
            customer_id=data.get("customer_id") or 0,
            rule_key=str(getattr(rule, "key", "") or ""),
            player_count=_to_int(data.get("player_count"), 1) or 1,
            allow_reserved=True,
        )
        if bkind in {"extra_hours", "extra_games"}:
            raise ValueError("累積加時／加局券不能和點數加時／加局同張訂單使用。")

    point_specify = min(
        point_specify,
        specify_before,
    )

    specify_effective = max(
        0,
        specify_before
        - point_specify,
    )

    legacy_free_hour = min(
        legacy_free_hour,
        service_original,
    )

    discountable = max(
        0,
        service_original
        - legacy_free_hour,
    )

    (
        rate,
        discount_reason,
        discount_source,
        vip_level_name,
    ) = _resolve_self_service_discount_rate(
        rule,
        data,
    )

    after_percent = max(
        0,
        min(
            discountable,
            int(
                round(
                    discountable
                    * rate
                    / 100
                )
            ),
        ),
    )

    percent_off = max(
        0,
        discountable
        - after_percent,
    )

    raw_fixed = data.get(
        "fixed_discount_amount"
    )

    if raw_fixed is None:
        raw_fixed = data.get(
            "cash_coupon_amount"
        )

    fixed = max(
        0,
        min(
            after_percent,
            _to_int(
                raw_fixed,
                0,
            )
            or 0,
        ),
    )

    after_fixed = max(
        0,
        after_percent
        - fixed,
    )

    point_cash = max(
        0,
        min(
            point_cash,
            after_fixed,
        ),
    )

    allocation = allocate_store_absorbed_fixed_discount(
        after_percent_amount=after_percent,
        fixed_discount_amount=fixed,
        additional_store_discount_amount=point_cash,
        extra_customer_charge_amount=specify_effective,
    )

    # 百分比折扣只影響顧客購買的基礎服務。店家承諾的免費服務／免指定
    # 都用原價單位價值補進陪玩分潤，不跟著 VIP 折扣縮水。
    purchased_service_quantity = max(1, _to_int(data.get("quantity"), 1) or 1)
    original_unit_value = (service_original / purchased_service_quantity) if purchased_service_quantity else 0
    point_service_value = int(round(original_unit_value * (extra_hours or extra_games or 0)))
    loyalty_units = float(selected_loyalty.get("reward_units") or 0) if selected_loyalty else 0.0
    loyalty_service_value = int(round(original_unit_value * loyalty_units)) if loyalty_units > 0 else 0

    payout_base = max(
        0,
        allocation.payout_base_amount + point_specify + point_service_value + loyalty_service_value,
    )
    customer_pay = allocation.customer_pay_amount
    store_absorbed = max(
        0,
        allocation.store_absorbed_amount + point_specify + point_service_value + loyalty_service_value,
    )

    notes = []

    if legacy_free_hour:
        notes.append(
            "舊版福利：首小時免費 "
            f"-{_format_plain_amount(legacy_free_hour)}"
        )

    if extra_hours:
        notes.append(
            "服務時間 +"
            f"{_format_point_hours(extra_hours)}"
        )

    if extra_games:
        if bkind == "extra_games":
            notes.append(
                f"服務局數 +{extra_games} 局"
            )
        else:
            notes.append(
                f"加場 {extra_games} 場保撤"
            )

    if point_specify:
        notes.append(
            "免指定費 "
            f"-{_format_plain_amount(point_specify)}"
        )

    if selected_loyalty:
        if str(selected_loyalty.get("pricing_type") or "") == "hourly":
            loyalty_label = "30 分鐘" if loyalty_units == 0.5 else f"{loyalty_units:g}H"
            notes.append(f"累積福利：服務時間 +{loyalty_label}")
        else:
            notes.append(f"累積福利：服務局數 +{loyalty_units:g} 局")

    # service_promotion_calc_v1

    actual_service_quantity = max(
        purchased_service_quantity,
        int(
            getattr(
                price_result,
                "service_quantity",
                purchased_service_quantity,
            )
            or purchased_service_quantity
        ),
    )

    automatic_service_bonus_quantity = max(
        0,
        actual_service_quantity
        - purchased_service_quantity,
    )

    service_unit_text = str(
        getattr(
            rule,
            "unit_label",
            "單",
        )
        or "單"
    ).strip()

    service_promotion_text = ""

    if automatic_service_bonus_quantity > 0:
        service_promotion_text = (
            f"活動加贈：購買 {purchased_service_quantity}{service_unit_text}，"
            f"額外贈送 {automatic_service_bonus_quantity}{service_unit_text}"
            f"｜活動後共 {actual_service_quantity}{service_unit_text}"
        )

    return {
        "price_formula_version": 2,
        "manual_discount_mode": "pay_rate",

        "manual_price_missing": bool(
            is_self_service_staff_price_required(
                rule
            )
            and manual_price is None
        ),

        "manual_staff_amount": manual_price,

        "manual_staff_price_reason": str(
            data.get(
                "manual_staff_price_reason"
            )
            or ""
        ).strip(),

        "rule_original_amount": (
            service_original
            + specify_before
        ),

        "service_original_amount": service_original,
        "original_amount": service_original,
        "priced_amount": discountable,

        "manual_discount_percent": rate,
        "discount_rate_percent": rate,

        "manual_discount_amount": percent_off,
        "percent_discount_amount": percent_off,

        "manual_discount_reason": (
            discount_reason
        ),

        "discount_source": (
            discount_source
        ),

        "vip_level_name": (
            vip_level_name
        ),

        "cash_coupon_amount": fixed,
        "fixed_discount_amount": fixed,

        "cash_coupon_reason": str(
            data.get(
                "cash_coupon_reason"
            )
            or ""
        ).strip(),

        "point_discount_coupon_amount": (
            point_cash
        ),

        "specified_fee_before_waiver": (
            specify_before
        ),

        "effective_specify_fee": (
            specify_effective
        ),

        "point_waived_specify_fee": (
            point_specify
        ),

        "point_free_first_hour_amount": (
            legacy_free_hour
        ),

        "point_extra_hours": extra_hours,
        "point_extra_games": extra_games,
        "point_service_value": point_service_value,
        "loyalty_coupon_id": int(selected_loyalty["id"]) if selected_loyalty else None,
        "loyalty_coupon_name": str(selected_loyalty.get("display_name") or "") if selected_loyalty else "",
        "loyalty_service_units": loyalty_units,
        "loyalty_service_value": loyalty_service_value,

        "point_benefit_key": bkey,
        "point_benefit_name": bname,
        "point_benefit_cost": bcost,

        "point_benefit_summary": (
            str(
                benefit.get(
                    "summary"
                )
                or ""
            )
            if benefit
            else ""
        ),

        # 非折價福利直接顯示在訂單備註。
        "service_bonus_text": (
            "｜".join(notes)
        ),

        "service_quantity": (
            actual_service_quantity
        ),

        "service_bonus_quantity": (
            automatic_service_bonus_quantity
        ),

        "service_promotion_text": service_promotion_text,

        "payout_base_amount": (
            payout_base
        ),

        "store_absorbed_amount": (
            store_absorbed
        ),

        "customer_pay_amount": (
            customer_pay
        ),
    }


def apply_self_service_financials_to_order_data(data: dict, rule, price_result) -> dict:
    adjustment = calculate_self_service_financials(rule, price_result, data)

    for key, value in adjustment.items():
        data[key] = value

    data["amount"] = adjustment["customer_pay_amount"]
    data["total_amount"] = adjustment["customer_pay_amount"]
    data["amount_text"] = _format_plain_amount(adjustment["customer_pay_amount"])

    return adjustment


class SelfServicePointBenefitSelect(discord.ui.Select):
    def __init__(self, parent_view: "SelfServicePointBenefitView"):
        options = [
            discord.SelectOption(
                label="不使用點數福利",
                value="none",
                description="清除這張單目前選擇的點數福利",
                default=parent_view.selected_key is None,
            )
        ]

        for item in parent_view.available_items:
            options.append(
                discord.SelectOption(
                    label=_truncate_select_text(f"{item['cost']} 點｜{item['name']}"),
                    value=str(item["key"]),
                    description=_truncate_select_text(item.get("summary") or f"兌換 {item['name']}"),
                    default=str(item["key"]) == str(parent_view.selected_key),
                )
            )

        if len(options) == 1:
            options[0].description = "目前沒有符合點數與訂單條件的福利"

        super().__init__(
            placeholder="選擇這張單要使用的點數福利",
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

        if selected == "none":
            for key in (
                "selected_point_benefit_key",
                "point_benefit_key",
                "point_benefit_name",
                "point_benefit_cost",
                "point_discount_coupon_amount",
                "point_waived_specify_fee",
                "point_extra_hours",
                "point_extra_games",
                "service_bonus_text",
            ):
                data.pop(key, None)
        else:
            item = get_order_point_item(selected)

            if item is None:
                await interaction.response.send_message("找不到這個點數福利，請重新選擇。", ephemeral=True)
                return

            spec = ORDER_POINT_BENEFIT_SPECS.get(str(selected)) or {}
            if data.get("selected_loyalty_coupon_id") and str(spec.get("kind") or "") in {"extra_hours", "extra_games"}:
                await interaction.response.send_message(
                    "累積加時／加局券不能和點數加時／加局同張使用；折價券與免指定費仍可一起用。",
                    ephemeral=True,
                )
                return
            data["selected_point_benefit_key"] = str(selected)
            data["point_benefit_key"] = str(selected)
            data["point_benefit_name"] = str(item.get("name") or selected)
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
        self.selected_loyalty_id = _to_int(data.get("selected_loyalty_coupon_id"), None)
        self.point_balance = get_customer_point_balance_for_order(customer_id)
        self.available_items = self.build_available_items(data)
        self.available_loyalty_items = list_available_coupons(
            customer_id,
            rule_key=str(getattr(rule, "key", "") or ""),
            player_count=_to_int(data.get("player_count"), 1) or 1,
        )

        self.add_item(SelfServicePointBenefitSelect(self))
        self.add_item(SelfServiceLoyaltyBenefitSelect(self))

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

        if benefit:
            selected_text = f"{benefit['cost']} 點｜{benefit['name']}"

        loyalty_text = str(data.get("loyalty_coupon_name") or "尚未使用")
        return (
            f"請選擇這張單要使用的會員福利。\n"
            f"目前可用點數：{self.point_balance} 點\n"
            f"點數福利：{selected_text}\n"
            f"累積福利：{loyalty_text}\n\n"
            "加時／加局類的點數福利與累積福利不能同張疊加；折價與免指定費可以。"
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

class SelfServiceLoyaltyBenefitSelect(discord.ui.Select):
    def __init__(self, parent_view: "SelfServicePointBenefitView"):
        options = [discord.SelectOption(
            label="不使用累積福利", value="none",
            description="清除這張單目前選擇的累積福利券",
            default=parent_view.selected_loyalty_id is None,
        )]
        for item in parent_view.available_loyalty_items[:24]:
            options.append(discord.SelectOption(
                label=_truncate_select_text(str(item.get("display_name") or "累積福利")),
                value=str(item["id"]),
                description="同商品、同人數規格；可重新選陪玩",
                default=int(item["id"]) == int(parent_view.selected_loyalty_id or 0),
            ))
        super().__init__(
            placeholder="選擇累積福利券", min_values=1, max_values=1,
            options=options, row=1,
        )

    async def callback(self, interaction: discord.Interaction):
        view = self.view
        if not isinstance(view, SelfServicePointBenefitView):
            await interaction.response.send_message("會員福利選單狀態異常。", ephemeral=True)
            return
        data = SELF_SERVICE_ORDER_SELECTIONS.setdefault(view.channel_id, {})
        selected = self.values[0]
        if selected == "none":
            data.pop("selected_loyalty_coupon_id", None)
            data.pop("loyalty_coupon_name", None)
        else:
            coupon = validate_coupon_for_order(
                int(selected), customer_id=view.customer_id,
                rule_key=str(getattr(view.rule, "key", "") or ""),
                player_count=_to_int(data.get("player_count"), 1) or 1,
                allow_reserved=True,
            )
            point = get_selected_order_point_benefit(data, view.rule)
            if point and str(point.get("kind") or "") in {"extra_hours", "extra_games"}:
                await interaction.response.send_message(
                    "累積加時／加局券不能和點數加時／加局同張使用；折價券與免指定費仍可一起用。",
                    ephemeral=True,
                )
                return
            data["selected_loyalty_coupon_id"] = int(coupon["id"])
            data["loyalty_coupon_name"] = str(coupon.get("display_name") or "累積福利")
        data.pop("payment_method", None)
        remember_order_data(view.channel_id, data)
        await view.refresh_source_panel(interaction)
        await interaction.response.edit_message(
            content=view.build_message_content(data),
            view=SelfServicePointBenefitView(
                customer_id=view.customer_id, channel_id=view.channel_id,
                panel_message_id=view.panel_message_id, rule=view.rule,
            ),
        )


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
        label="會員福利",
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


def _reorder_order_value(
    order,
    key: str,
    default=None,
):
    if order is None:
        return default

    try:
        value = order[key]
    except (
        KeyError,
        IndexError,
        TypeError,
    ):
        value = getattr(
            order,
            key,
            default,
        )

    return (
        default
        if value is None
        else value
    )


def _reorder_json_dict(value) -> dict:
    if isinstance(value, dict):
        return dict(value)

    try:
        parsed = json.loads(
            str(value or "")
        )
    except Exception:
        return {}

    return (
        parsed
        if isinstance(parsed, dict)
        else {}
    )


async def build_reorder_self_service_draft(
    *,
    guild: discord.Guild,
    order,
    targets: list[dict],
    customer_id: int,
) -> tuple[dict, list[str]]:
    """
    從已結單 WebOrder 建立一份新的自助下單草稿。

    不繼承：
    - 舊付款方式
    - 舊折扣
    - 舊點數福利
    - 舊客服手動報價

    自動價會由目前規則重新試算。
    """

    source_order_id = _to_int(
        _reorder_order_value(
            order,
            "id",
        )
    )

    source_ticket_channel_id = _to_int(
        _reorder_order_value(
            order,
            "ticket_channel_id",
        )
    )

    source_dispatch_message_id = _to_int(
        _reorder_order_value(
            order,
            "dispatch_message_id",
        )
    )

    old_category_label = str(
        _reorder_order_value(
            order,
            "category",
            "",
        )
        or ""
    ).strip()

    old_item = str(
        _reorder_order_value(
            order,
            "item",
            "",
        )
        or ""
    ).strip()

    stored_rule_key = str(
        _reorder_order_value(
            order,
            "order_rule_key",
            "",
        )
        or ""
    ).strip()

    price_snapshot = _reorder_json_dict(
        _reorder_order_value(
            order,
            "price_snapshot_json",
            None,
        )
    )

    rule_snapshot = _reorder_json_dict(
        _reorder_order_value(
            order,
            "rule_snapshot_json",
            None,
        )
    )

    warnings = []

    data = {
        "customer_id": int(customer_id),
        "status": "draft",
        "closed": False,

        "reorder_source_order_id": (
            source_order_id
        ),

        "reorder_source_ticket_channel_id": (
            source_ticket_channel_id
        ),

        "reorder_source_dispatch_message_id": (
            source_dispatch_message_id
        ),

        "reorder_source_category": (
            old_category_label
        ),

        "reorder_source_item": (
            old_item
        ),

        "reorder_created_at": (
            get_taipei_now_iso()
        ),

        "reorder_draft_version": 2,

        "companion_preference": (
            "不指定陪玩/打手"
        ),
    }

    try:
        from services.order_rules import (
            ORDER_RULES,
            get_required_staff_count,
        )
    except Exception as exc:
        warnings.append(
            f"讀取目前訂單規則失敗：{exc}"
        )

        return data, warnings

    rule = None

    if stored_rule_key:
        rule = ORDER_RULES.get(
            stored_rule_key
        )

    if (
        rule is None
        and old_item
    ):
        rule = _get_order_rule_by_item_label(
            old_item
        )

    category_key = None

    if rule is not None:
        category_key = str(
            getattr(
                rule,
                "category",
                "",
            )
            or ""
        )

        old_item = str(
            getattr(
                rule,
                "label",
                old_item,
            )
            or old_item
        )

        stored_rule_key = str(
            getattr(
                rule,
                "key",
                stored_rule_key,
            )
            or stored_rule_key
        )

    if not category_key:
        for key, label in (
            ORDER_CATEGORY_LABELS.items()
        ):
            if (
                str(label).strip()
                == old_category_label
            ):
                category_key = str(key)
                break

    if (
        category_key
        and category_key
        in ORDER_CATEGORY_LABELS
    ):
        data["category"] = (
            category_key
        )

    item_group = None

    if old_item:
        try:
            item_group = (
                get_order_item_group_label(
                    old_item
                )
            )
        except Exception:
            item_group = None

    valid_groups = (
        ORDER_ITEM_GROUPS_BY_CATEGORY.get(
            category_key,
            [],
        )
        if category_key
        else []
    )

    if (
        item_group
        and item_group in valid_groups
    ):
        data["item_group"] = (
            item_group
        )
    else:
        item_group = None

    detail = None

    if (
        category_key
        and item_group
    ):
        details = (
            get_order_item_details_for_group(
                category_key,
                item_group,
            )
        )

        for candidate in details:
            candidate_rule_key = str(
                candidate.get(
                    "rule_key"
                )
                or ""
            )

            candidate_item = str(
                candidate.get(
                    "item"
                )
                or ""
            )

            if (
                stored_rule_key
                and candidate_rule_key
                == stored_rule_key
            ):
                detail = candidate
                break

            if (
                old_item
                and candidate_item
                == old_item
            ):
                detail = candidate
                break

    if detail is not None:
        data["item_detail_value"] = str(
            detail.get("value")
            or ""
        )

        data["item"] = str(
            detail.get("item")
            or old_item
        )

        data["order_rule_key"] = str(
            detail.get("rule_key")
            or stored_rule_key
        )

        if (
            detail.get(
                "player_count"
            )
            is not None
        ):
            data["player_count"] = int(
                detail["player_count"]
            )

        try:
            rule = ORDER_RULES.get(
                data["order_rule_key"]
            ) or rule
        except Exception:
            pass

        old_quantity = (
            _to_int(
                _reorder_order_value(
                    order,
                    "quantity",
                    1,
                ),
                1,
            )
            or 1
        )

        meta = (
            get_self_service_quantity_meta(
                category_key,
                item_group,
                data[
                    "item_detail_value"
                ],
            )
        )

        if meta:
            minimum = int(
                meta.get(
                    "min",
                    1,
                )
                or 1
            )

            maximum = int(
                meta.get(
                    "max",
                    minimum,
                )
                or minimum
            )

            old_quantity = max(
                minimum,
                min(
                    maximum,
                    old_quantity,
                ),
            )

        data["quantity"] = (
            old_quantity
        )

    elif category_key:
        warnings.append(
            "上一張單的品項目前無法完整對應新版自助下單，"
            "已先帶入可辨識的類別，請重新確認品項與規格。"
        )

    else:
        warnings.append(
            "上一張單的類別目前已不在自助下單清單，"
            "請在新票口重新選擇。"
        )

    # 非把 player_count 寫在第三欄的項目，
    # 從上一單 snapshot 嘗試還原。
    if (
        rule is not None
        and bool(
            getattr(
                rule,
                "player_count_enabled",
                False,
            )
        )
        and not data.get(
            "player_count"
        )
    ):
        old_player_count = (
            _to_int(
                price_snapshot.get(
                    "player_count"
                ),
                None,
            )
        )

        if old_player_count is None:
            old_player_count = (
                _to_int(
                    rule_snapshot.get(
                        "player_count"
                    ),
                    None,
                )
            )

        if old_player_count is not None:
            minimum = max(
                1,
                int(
                    getattr(
                        rule,
                        "min_player_count",
                        1,
                    )
                    or 1
                ),
            )

            maximum_raw = getattr(
                rule,
                "max_player_count",
                None,
            )

            maximum = (
                int(maximum_raw)
                if maximum_raw
                is not None
                else None
            )

            old_player_count = max(
                minimum,
                old_player_count,
            )

            if maximum is not None:
                old_player_count = min(
                    maximum,
                    old_player_count,
                )

            data["player_count"] = (
                old_player_count
            )

    # 上一張單的接單成員：
    # 只有「現在仍符合這個品項可指定資格」的人才帶入。
    if (
        rule is not None
        and bool(
            getattr(
                rule,
                "allow_specify",
                False,
            )
        )
        and targets
    ):
        player_count = (
            _to_int(
                data.get(
                    "player_count"
                ),
                1,
            )
            or 1
        )

        try:
            required_staff_count = int(
                get_required_staff_count(
                    rule,
                    player_count,
                )
                or 1
            )
        except Exception:
            required_staff_count = 1

        max_specified = int(
            getattr(
                rule,
                "max_specified_count",
                None,
            )
            or required_staff_count
            or 1
        )

        max_specified = max(
            1,
            min(
                max_specified,
                required_staff_count,
            ),
        )

        valid_staff_ids = []
        rejected_staff_count = 0

        for target in targets:
            staff_id = str(
                target.get(
                    "staff_id"
                )
                or ""
            ).strip()

            if not staff_id:
                continue

            try:
                member_id = int(
                    staff_id
                )
            except ValueError:
                rejected_staff_count += 1
                continue

            member = guild.get_member(
                member_id
            )

            if member is None:
                try:
                    member = (
                        await guild.fetch_member(
                            member_id
                        )
                    )
                except Exception:
                    member = None

            if (
                member is None
                or _role_key_for_member(
                    rule,
                    member,
                )
                is None
            ):
                rejected_staff_count += 1
                continue

            if (
                staff_id
                not in valid_staff_ids
            ):
                valid_staff_ids.append(
                    staff_id
                )

        if len(
            valid_staff_ids
        ) > max_specified:
            rejected_staff_count += (
                len(valid_staff_ids)
                - max_specified
            )

            valid_staff_ids = (
                valid_staff_ids[
                    :max_specified
                ]
            )

        if valid_staff_ids:
            data[
                "specified_staff_ids"
            ] = valid_staff_ids

            data[
                "companion_preference"
            ] = "指定陪玩/打手"

        if rejected_staff_count:
            warnings.append(
                "上一單部分接單成員目前不符合這個品項的指定資格，"
                "因此沒有自動帶入。"
            )

    # 手動報價單絕對不沿用舊價格。
    if (
        rule is not None
        and is_self_service_staff_price_required(
            rule
        )
    ):
        warnings.append(
            "此品項需要客服重新報價，上一張單的舊報價不會沿用。"
        )

    return data, warnings


def _reorder_message_has_component(
    message: discord.Message,
    custom_id: str,
) -> bool:
    for row in getattr(message, "components", []) or []:
        for child in getattr(row, "children", []) or []:
            if str(getattr(child, "custom_id", "") or "") == str(custom_id):
                return True
    return False


async def _find_reorder_panel_message(
    channel: discord.TextChannel,
    custom_id: str,
) -> discord.Message | None:
    try:
        async for message in channel.history(limit=80):
            if _reorder_message_has_component(message, custom_id):
                return message
    except (discord.Forbidden, discord.HTTPException):
        return None
    return None


async def ensure_reorder_ticket_panels(
    *,
    guild: discord.Guild,
    channel: discord.TextChannel,
    customer_id: int,
    data: dict,
    source_order_id: int | None,
) -> tuple[discord.Message, discord.Message]:
    """
    再約票口固定維持兩個正式面板：
    1. 客服操作：填寫自助下單 / 取消訂單
    2. 已預填的自助下單面板

    重複按「再約」時會修復缺少的面板，不會一直重複建立。
    """

    support_role = guild.get_role(CUSTOMER_ROLE_ID)
    support_mention = support_role.mention if support_role is not None else "客服"
    source_text = (
        f"WEB-{source_order_id}"
        if source_order_id is not None
        else "上一張訂單"
    )

    control_message = await _find_reorder_panel_message(
        channel,
        "order_control_select",
    )

    control_embed = discord.Embed(
        title="客服操作選項",
        description=(
            f"這是由 {source_text} 建立的再約草稿。\n"
            "下方使用一般訂單控制：客服可開啟／更新自助下單，"
            "或直接取消這張再約訂單。"
        ),
        color=discord.Color.gold(),
    )
    control_embed.set_footer(
        text=(
            f"REORDER-{source_order_id or channel.id}"
            "｜客服操作"
        )
    )

    if control_message is None:
        control_message = await channel.send(
            content=f"{support_mention} 再約草稿待確認。",
            embed=control_embed,
            view=OrderControlView(),
            allowed_mentions=discord.AllowedMentions(
                users=False,
                roles=True,
                everyone=False,
            ),
        )
    else:
        try:
            await control_message.edit(
                embed=control_embed,
                view=OrderControlView(),
                allowed_mentions=discord.AllowedMentions(
                    users=False,
                    roles=True,
                    everyone=False,
                ),
            )
        except discord.HTTPException:
            pass

    self_service_message = await _find_reorder_panel_message(
        channel,
        "self_service_order_category_select",
    )

    panel_embed = build_self_service_panel_embed(
        customer_id,
        data,
        guild,
    )
    panel_embed.set_footer(
        text=(
            f"REORDER-{source_order_id or channel.id}"
            "｜再約預填自助下單"
        )
    )
    panel_view = SelfServiceOrderView(
        customer_id=customer_id,
        channel_id=channel.id,
        selected_category=data.get("category"),
    )

    if self_service_message is None:
        self_service_message = await channel.send(
            content=(
                f"<@{customer_id}> "
                "這張是你的再約草稿，系統已帶入上一單可沿用內容，"
                "你可以直接修改。"
            ),
            embed=panel_embed,
            view=panel_view,
            allowed_mentions=discord.AllowedMentions(
                users=True,
                roles=False,
                everyone=False,
            ),
        )
    else:
        try:
            await self_service_message.edit(
                embed=panel_embed,
                view=panel_view,
                allowed_mentions=discord.AllowedMentions(
                    users=True,
                    roles=False,
                    everyone=False,
                ),
            )
        except discord.HTTPException:
            pass

    data["reorder_control_message_id"] = control_message.id
    data["self_service_panel_message_id"] = self_service_message.id
    remember_order_data(channel.id, data)
    save_bot_data()

    return control_message, self_service_message


async def create_reorder_ticket_from_closed_order(
    *,
    interaction: discord.Interaction,
    order,
    targets: list[dict],
    order_content: str | None = None,
) -> dict:
    """
    再約 v2：
    已結單票口按再約
    -> 建立全新票口
    -> 預填自助下單
    -> 老闆可修改
    -> 客服確認送出
    """

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

    source_order_id = _to_int(
        _reorder_order_value(
            order,
            "id",
        )
    )

    source_ticket_channel_id = _to_int(
        _reorder_order_value(
            order,
            "ticket_channel_id",
        )
    )

    old_item = str(
        _reorder_order_value(
            order,
            "item",
            "未紀錄",
        )
        or "未紀錄"
    )

    # 防止同一筆來源訂單連點建立很多草稿。
    if source_order_id is not None:
        marker = (
            f"reorder_source_order_id="
            f"{source_order_id}"
        )

        customer_marker = (
            f"order_customer_id="
            f"{member.id}"
        )

        for possible_channel in (
            guild.text_channels
        ):
            topic = str(
                possible_channel.topic
                or ""
            )

            if (
                marker not in topic
                or customer_marker
                not in topic
            ):
                continue

            existing_data = (
                SELF_SERVICE_ORDER_SELECTIONS.get(
                    possible_channel.id,
                    {},
                )
            )

            existing_status = str(
                existing_data.get(
                    "status"
                )
                or "draft"
            ).lower()

            if (
                not existing_data.get(
                    "closed"
                )
                and existing_status
                not in {
                    "closed",
                    "cancelled",
                    "canceled",
                }
            ):
                repair_warnings: list[str] = []

                # 舊版再約草稿可能只建立了文字訊息，
                # 或 Bot 重啟後缺少 panel message id。
                # 只有資料真的不存在時才重新從來源單建立草稿；
                # 已經被老闆修改過的草稿絕不覆蓋。
                if not existing_data:
                    existing_data, repair_warnings = (
                        await build_reorder_self_service_draft(
                            guild=guild,
                            order=order,
                            targets=targets,
                            customer_id=member.id,
                        )
                    )
                    SELF_SERVICE_ORDER_SELECTIONS[
                        possible_channel.id
                    ] = existing_data
                    remember_order_data(
                        possible_channel.id,
                        existing_data,
                    )

                await ensure_reorder_ticket_panels(
                    guild=guild,
                    channel=possible_channel,
                    customer_id=member.id,
                    data=existing_data,
                    source_order_id=source_order_id,
                )

                return {
                    "channel": (
                        possible_channel
                    ),
                    "created": False,
                    "warning": "；".join(repair_warnings),
                }

    category = guild.get_channel(
        CUSTOMER_CATEGORY_ID
    )

    if (
        category is None
        or not isinstance(
            category,
            discord.CategoryChannel,
        )
    ):
        raise ValueError(
            "找不到下單票口類別。"
        )

    customer_staff_role = (
        guild.get_role(
            CUSTOMER_ROLE_ID
        )
    )

    overwrites = {
        guild.default_role:
            discord.PermissionOverwrite(
                view_channel=False,
                send_messages=False,
                read_message_history=False,
            ),

        member:
            discord.PermissionOverwrite(
                view_channel=True,
                send_messages=True,
                read_message_history=True,
                attach_files=True,
            ),

        guild.me:
            discord.PermissionOverwrite(
                view_channel=True,
                send_messages=True,
                manage_channels=True,
                read_message_history=True,
                attach_files=True,
            ),
    }

    if customer_staff_role is not None:
        overwrites[
            customer_staff_role
        ] = discord.PermissionOverwrite(
            view_channel=True,
            send_messages=True,
            read_message_history=True,
            attach_files=True,
        )

    topic_parts = [
        f"order_customer_id={member.id}",
    ]

    if source_order_id is not None:
        topic_parts.append(
            "reorder_source_order_id="
            f"{source_order_id}"
        )

    if source_ticket_channel_id is not None:
        topic_parts.append(
            "reorder_source_ticket_channel_id="
            f"{source_ticket_channel_id}"
        )

    new_channel = (
        await guild.create_text_channel(
            name=build_ticket_channel_name(
                "再約",
                member,
            ),
            category=category,
            overwrites=overwrites,
            topic=";".join(
                topic_parts
            ),
            reason=(
                f"{member} created reorder "
                f"from WEB-{source_order_id}"
            ),
        )
    )

    try:
        data, warnings = (
            await build_reorder_self_service_draft(
                guild=guild,
                order=order,
                targets=targets,
                customer_id=member.id,
            )
        )

        SELF_SERVICE_ORDER_SELECTIONS[
            new_channel.id
        ] = data

        remember_order_data(
            new_channel.id,
            data,
        )

        support_mention = (
            customer_staff_role.mention
            if customer_staff_role
            is not None
            else ""
        )

        source_text = (
            f"WEB-{source_order_id}"
            if source_order_id
            is not None
            else "上一張訂單"
        )

        intro_lines = [
            support_mention,
            "🔁 **再約訂單已建立**",
            "",
            f"老闆：{member.mention}",
            f"來源：{source_text}",
            f"上一單項目：{old_item}",
            "",
            "系統已先把上一張單可沿用的內容填入下方自助下單。",
            "老闆可以直接修改類別、品項、規格、數量、指定成員與點數福利。",
            "折扣、付款方式、舊點數福利與舊客服報價不會沿用。",
            "",
            "內容確認完成後，由客服按 **「客服確認送出」**。",
        ]

        if warnings:
            intro_lines.extend(
                [
                    "",
                    "⚠️ **系統提醒**",
                    *[
                        f"・{warning}"
                        for warning
                        in warnings
                    ],
                ]
            )

        await new_channel.send(
            content="\n".join(
                line
                for line in intro_lines
                if line is not None
            ),
            allowed_mentions=(
                discord.AllowedMentions(
                    users=True,
                    roles=True,
                    everyone=False,
                )
            ),
        )

        await ensure_reorder_ticket_panels(
            guild=guild,
            channel=new_channel,
            customer_id=member.id,
            data=data,
            source_order_id=source_order_id,
        )

        try:
            await send_order_log(
                guild,
                title="再約草稿已建立",
                fields=[
                    (
                        "顧客",
                        member.mention,
                        True,
                    ),
                    (
                        "來源訂單",
                        (
                            f"WEB-{source_order_id}"
                            if source_order_id
                            is not None
                            else "未紀錄"
                        ),
                        True,
                    ),
                    (
                        "新票口",
                        new_channel.mention,
                        False,
                    ),
                    (
                        "上一單項目",
                        old_item,
                        False,
                    ),
                    (
                        "流程",
                        (
                            "系統預填 → "
                            "顧客可修改 → "
                            "客服確認送出"
                        ),
                        False,
                    ),
                ],
                color=discord.Color.blue(),
            )
        except Exception as exc:
            print(
                "[reorder] log failed "
                f"channel_id="
                f"{new_channel.id}: {exc}"
            )

        return {
            "channel": new_channel,
            "created": True,
            "warning": (
                "；".join(warnings)
            ),
        }

    except Exception:
        # 草稿初始化失敗時不要留下空白垃圾票口。
        try:
            await new_channel.delete(
                reason=(
                    "Reorder draft initialization failed"
                )
            )
        except Exception:
            pass

        SELF_SERVICE_ORDER_SELECTIONS.pop(
            new_channel.id,
            None,
        )

        try:
            delete_order_row_from_db(
                new_channel.id
            )
        except Exception:
            pass

        raise


