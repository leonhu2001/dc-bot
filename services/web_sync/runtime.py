from __future__ import annotations

from typing import Any, Mapping

import discord


_CONFIGURED = False


def configure_web_sync_runtime(namespace: Mapping[str, Any]) -> None:
    """Bind bot-owned runtime dependencies without importing bot.py.

    The Web sync runtime remains behavior-compatible while legacy bot globals
    are progressively replaced with explicit service/view dependencies.
    """
    global _CONFIGURED

    for name, value in namespace.items():
        if name.startswith("__"):
            continue
        if name == "configure_web_sync_runtime":
            continue
        globals()[name] = value

    _CONFIGURED = True


def _web_dashboard_db_path_for_bot() -> str:
    from pathlib import Path

    return str(Path(__file__).resolve().parents[2] / "web_dashboard.db")


# zYao 3C3B web order created bridge v1

async def _web_order_created_ensure_ticket(
    guild: discord.Guild,
    event_id: int,
    order_id: int,
    bundle: dict,
):
    order = bundle["order"]
    details = _web_order_created_details(
        bundle
    )

    details["website_payment_method"] = ""

    customer_id = _to_int(
        order.get(
            "customer_discord_id"
        ),
        None,
    )

    if customer_id is None:
        raise RuntimeError(
            f"WEB-{order_id} 缺少 customer_discord_id"
        )

    member = await _web_order_created_get_member(
        guild,
        customer_id,
    )

    ticket_channel = (
        await _web_order_created_find_ticket(
            guild,
            order_id,
            order.get(
                "ticket_channel_id"
            ),
        )
    )

    created = False

    if ticket_channel is None:
        category = (
            await _web_order_created_get_channel(
                guild,
                CUSTOMER_CATEGORY_ID,
            )
        )

        if not isinstance(
            category,
            discord.CategoryChannel,
        ):
            raise RuntimeError(
                "找不到網站訂單票口類別。"
            )

        support_role = guild.get_role(
            CUSTOMER_ROLE_ID
        )

        bot_member = guild.me

        if (
            bot_member is None
            and bot.user is not None
        ):
            bot_member = guild.get_member(
                bot.user.id
            )

        if bot_member is None:
            raise RuntimeError(
                "無法取得 Bot guild member。"
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
            bot_member:
                discord.PermissionOverwrite(
                    view_channel=True,
                    send_messages=True,
                    manage_channels=True,
                    read_message_history=True,
                    attach_files=True,
                ),
        }

        if support_role is not None:
            overwrites[
                support_role
            ] = (
                discord.PermissionOverwrite(
                    view_channel=True,
                    send_messages=True,
                    read_message_history=True,
                    attach_files=True,
                )
            )

        topic = (
            f"order_customer_id={customer_id};"
            f"web_order_id={order_id};"
            f"web_order_event_id={event_id}"
        )

        channel_name = (
            build_ticket_channel_name(
                "下單",
                member,
                display_name=(
                    order.get(
                        "customer_display_name"
                    )
                    or getattr(
                        member,
                        "display_name",
                        None,
                    )
                ),
            )
        )

        ticket_channel = (
            await guild.create_text_channel(
                name=channel_name,
                category=category,
                overwrites=overwrites,
                topic=topic,
                reason=(
                    f"WEB-{order_id} "
                    "website order"
                ),
            )
        )

        created = True

    _web_order_created_update_links(
        order_id,
        ticket_channel_id=(
            ticket_channel.id
        ),
    )

    intro_footer = (
        f"WEB-{order_id}｜網站訂單票口"
    )

    has_intro = (
        await _web_order_created_has_footer(
            ticket_channel,
            intro_footer,
            limit=25,
        )
    )

    if not has_intro:
        amount_text = (
            _format_plain_amount(
                details["amount"]
            )
            if "_format_plain_amount"
            in globals()
            else format_t_amount(
                details["amount"]
            )
        )

        embed = discord.Embed(
            title="網站訂單已建立｜等待客服確認",
            description=(
                "此訂單已由官網正式送出，"
                "目前等待客服確認送單。\n"
                "客服確認後才會派單，之後沿用原本"
                " Discord 接單與付款流程。"
            ),
            color=discord.Color.gold(),
        )

        embed.add_field(
            name="訂單",
            value=(
                f"WEB-{order_id}\n"
                f"{details['category_label']}｜"
                f"{details['item']}"
            ),
            inline=False,
        )

        embed.add_field(
            name="顧客",
            value=f"<@{customer_id}>",
            inline=True,
        )

        embed.add_field(
            name="數量",
            value=str(
                details["quantity"]
            ),
            inline=True,
        )

        embed.add_field(
            name="顧客應付",
            value=amount_text,
            inline=True,
        )

        if details[
            "website_payment_method"
        ]:
            embed.add_field(
                name="網站預選付款方式",
                value=details[
                    "website_payment_method"
                ][:1024],
                inline=False,
            )

        if details[
            "service_terms_version"
        ]:
            terms_value = (
                "已同意"
                f"｜{details['service_terms_version']}"
            )

            if details[
                "terms_accepted_at"
            ]:
                terms_value += (
                    "\n"
                    + details[
                        "terms_accepted_at"
                    ]
                )

            embed.add_field(
                name="服務規章",
                value=terms_value[:1024],
                inline=False,
            )

        if details[
            "specified_staff_ids"
        ]:
            embed.add_field(
                name="指定人員",
                value="、".join(
                    f"<@{staff_id}>"
                    for staff_id
                    in details[
                        "specified_staff_ids"
                    ]
                )[:1024],
                inline=False,
            )

        if details[
            "extra_requirements"
        ]:
            embed.add_field(
                name="附加需求",
                value=details[
                    "extra_requirements"
                ][:1024],
                inline=False,
            )

        embed.set_footer(
            text=intro_footer
        )

        await ticket_channel.send(
            content=(
                f"<@{customer_id}> "
                "您的網站訂單已建立。"
            ),
            embed=embed,
            allowed_mentions=(
                discord.AllowedMentions(
                    users=True,
                    roles=False,
                    everyone=False,
                )
            ),
        )

    if created:
        try:
            await send_order_log(
                guild,
                title="網站新票口已建立",
                fields=[
                    (
                        "顧客",
                        f"<@{customer_id}>",
                        True,
                    ),
                    (
                        "網站訂單",
                        f"WEB-{order_id}",
                        True,
                    ),
                    (
                        "票口",
                        ticket_channel.mention,
                        False,
                    ),
                ],
                color=discord.Color.purple(),
            )
        except Exception as exc:
            print(
                "[web-order-create] "
                "ticket log failed "
                f"WEB-{order_id}: {exc}"
            )

    return ticket_channel




async def _web_order_created_find_dispatch_message(
    guild: discord.Guild,
    order_id: int,
    order: dict,
):
    dispatch_channel_id = _to_int(
        order.get(
            "dispatch_channel_id"
        ),
        DISPATCH_CHANNEL_ID,
    ) or DISPATCH_CHANNEL_ID

    dispatch_channel = (
        await _web_order_created_get_channel(
            guild,
            dispatch_channel_id,
        )
    )

    if not isinstance(
        dispatch_channel,
        discord.TextChannel,
    ):
        dispatch_channel = (
            await _web_order_created_get_channel(
                guild,
                DISPATCH_CHANNEL_ID,
            )
        )

    if not isinstance(
        dispatch_channel,
        discord.TextChannel,
    ):
        raise RuntimeError(
            "找不到派單頻道。"
        )

    stored_message_id = _to_int(
        order.get(
            "dispatch_message_id"
        ),
        None,
    )

    if stored_message_id is not None:
        try:
            existing = (
                await dispatch_channel.fetch_message(
                    stored_message_id
                )
            )

            return (
                dispatch_channel,
                existing,
            )

        except (
            discord.NotFound,
            discord.Forbidden,
            discord.HTTPException,
        ):
            pass

    marker = (
        f"WEB-{order_id}｜網站訂單"
    )

    try:
        async for message in dispatch_channel.history(
            limit=100,
        ):
            for embed in message.embeds:
                footer = getattr(
                    embed,
                    "footer",
                    None,
                )

                footer_text = str(
                    getattr(
                        footer,
                        "text",
                        "",
                    )
                    or ""
                )

                if marker in footer_text:
                    return (
                        dispatch_channel,
                        message,
                    )

    except discord.HTTPException:
        pass

    return (
        dispatch_channel,
        None,
    )


async def _web_order_created_ensure_dispatch(
    guild: discord.Guild,
    order_id: int,
    bundle: dict,
    ticket_channel: discord.TextChannel,
):
    order = bundle["order"]
    details = _web_order_created_details(
        bundle
    )
    customer_id = _to_int(
        order.get(
            "customer_discord_id"
        ),
        None,
    )

    smart_dispatch = prepare_initial_smart_dispatch(
        guild,
        customer_id=customer_id,
        allowed_role_ids=list(
            details.get("allowed_role_ids")
            or []
        ),
        specified_staff_ids=list(
            details.get("specified_staff_ids")
            or []
        ),
        required_staff_count=int(
            details.get("required_staff_count")
            or 1
        ),
        required_game_role_ids=list(
            details.get("required_game_role_ids")
            or []
        ),
    )

    (
        dispatch_channel,
        dispatch_message,
    ) = (
        await _web_order_created_find_dispatch_message(
            guild,
            order_id,
            order,
        )
    )

    if dispatch_message is None:
        placeholder = discord.Embed(
            title="網站訂單｜等待接單",
            description=(
                f"網站訂單：WEB-{order_id}\n"
                f"顧客：<@{customer_id}>\n"
                f"項目：{details['category_label']}｜"
                f"{details['item']}\n"
                "正在建立正式接單面板。"
            ),
            color=discord.Color.gold(),
        )

        placeholder.set_footer(
            text=(
                f"WEB-{order_id}｜網站訂單"
            )
        )

        dispatch_message = (
            await dispatch_channel.send(
                content=None,
                embed=placeholder,
                allowed_mentions=(
                    discord.AllowedMentions(
                        users=True,
                        roles=True,
                        everyone=False,
                    )
                ),
            )
        )

    existing_plan = get_smart_dispatch_plan(
        int(order_id)
    )

    if existing_plan is None:
        try:
            await send_initial_smart_dispatch_alert(
                guild,
                content=smart_dispatch["content"],
                dispatch_jump_url=dispatch_message.jump_url,
            )
        except (discord.Forbidden, discord.HTTPException) as exc:
            print(
                f"[smart-dispatch] website initial alert failed "
                f"order_id={order_id}: {exc}",
                flush=True,
            )

    if existing_plan is None:
        try:
            create_smart_dispatch_plan(
                order_id=int(order_id),
                dispatch_channel_id=dispatch_channel.id,
                dispatch_message_id=dispatch_message.id,
                required_staff_count=int(
                    details.get("required_staff_count")
                    or 1
                ),
                allowed_role_ids=list(
                    details.get("allowed_role_ids")
                    or []
                ),
                specified_staff_ids=list(
                    details.get("specified_staff_ids")
                    or []
                ),
                required_game_role_ids=list(
                    details.get("required_game_role_ids")
                    or []
                ),
                ranked_candidate_ids=smart_dispatch[
                    "ranked_candidate_ids"
                ],
                notified_candidate_ids=smart_dispatch[
                    "initial_notified_ids"
                ],
            )
        except Exception as exc:
            print(
                f"[smart-dispatch] website plan create failed "
                f"order_id={order_id}: {type(exc).__name__}: {exc}",
                flush=True,
            )

    plan = get_smart_dispatch_plan(
        int(order_id)
    )

    specified_ids = list(
        details.get("specified_staff_ids")
        or []
    )

    if (
        specified_ids
        and plan is not None
        and not plan.get("specified_dm_sent_ids")
        and not plan.get("specified_dm_failed_ids")
    ):
        try:
            dm_sent_ids, dm_failed_ids = (
                await send_specified_staff_dispatch_dms(
                    guild,
                    specified_staff_ids=specified_ids,
                    category_label=str(
                        details.get("category_label")
                        or order.get("category")
                        or "未紀錄"
                    ),
                    item_label=str(
                        details.get("item")
                        or order.get("item")
                        or "未紀錄"
                    ),
                    required_staff_count=int(
                        details.get("required_staff_count")
                        or 1
                    ),
                    dispatch_jump_url=dispatch_message.jump_url,
                    allowed_role_ids=list(
                        details.get("allowed_role_ids")
                        or []
                    ),
                    required_game_role_ids=list(
                        details.get("required_game_role_ids")
                        or []
                    ),
                )
            )

            set_specified_dm_results(
                int(order_id),
                sent_ids=dm_sent_ids,
                failed_ids=dm_failed_ids,
            )
        except Exception as exc:
            print(
                f"[smart-dispatch] website specified DM failed "
                f"order_id={order_id}: {type(exc).__name__}: {exc}",
                flush=True,
            )

    _web_order_created_update_links(
        order_id,
        ticket_channel_id=(
            ticket_channel.id
        ),
        dispatch_channel_id=(
            dispatch_channel.id
        ),
        dispatch_message_id=(
            dispatch_message.id
        ),
    )

    return (
        dispatch_channel,
        dispatch_message,
    )


def _web_order_created_seed_state(
    order_id: int,
    bundle: dict,
    ticket_channel: discord.TextChannel,
    dispatch_channel: discord.TextChannel,
    dispatch_message: discord.Message,
):
    order = bundle["order"]
    acceptance = (
        bundle.get("acceptance")
        or {}
    )

    if not acceptance:
        raise RuntimeError(
            f"WEB-{order_id} 缺少付款前接單 meta"
        )

    details = (
        _web_order_created_details(
            bundle
        )
    )

    customer_id = _to_int(
        order.get(
            "customer_discord_id"
        ),
        None,
    )

    if customer_id is None:
        raise RuntimeError(
            f"WEB-{order_id} 缺少顧客 ID"
        )

    data = (
        SELF_SERVICE_ORDER_SELECTIONS
        .setdefault(
            ticket_channel.id,
            {},
        )
    )

    data["customer_id"] = (
        customer_id
    )

    data["category"] = (
        details["category_key"]
        or order.get("category")
    )

    data["category_label"] = (
        details["category_label"]
    )

    data["item"] = (
        details["item"]
    )

    data["quantity"] = (
        details["quantity"]
    )

    data["player_count"] = (
        details["player_count"]
    )

    data["order_rule_key"] = (
        order.get(
            "order_rule_key"
        )
    )

    data["rule_version"] = (
        order.get(
            "rule_version"
        )
    )

    data["rule_snapshot_json"] = (
        order.get(
            "rule_snapshot_json"
        )
    )

    data["price_snapshot_json"] = (
        order.get(
            "price_snapshot_json"
        )
    )

    try:
        import json as _json
        _price_snapshot = _json.loads(str(data.get("price_snapshot_json") or "{}"))
        _preview = _price_snapshot.get("preview") if isinstance(_price_snapshot, dict) else {}
        _preview = _preview if isinstance(_preview, dict) else {}
        _loyalty = _preview.get("loyalty") if isinstance(_preview.get("loyalty"), dict) else {}
        _finance = _preview.get("finance") if isinstance(_preview.get("finance"), dict) else {}
        if _loyalty.get("id"):
            data["selected_loyalty_coupon_id"] = int(_loyalty["id"])
            data["loyalty_coupon_name"] = str(_loyalty.get("name") or "累積福利")
            data["loyalty_service_units"] = float(_loyalty.get("reward_units") or 0)
            data["loyalty_service_value"] = int(_finance.get("loyalty_service_value") or 0)
            data["service_bonus_text"] = "｜".join(
                part for part in (
                    str(_finance.get("point_service_note") or "").strip(),
                    str(_finance.get("loyalty_service_note") or "").strip(),
                ) if part
            )
    except Exception as exc:
        print(f"[loyalty] website snapshot parse skipped WEB-{order_id}: {exc}")

    amount = int(
        details["amount"]
    )

    data["amount"] = amount
    data["total_amount"] = amount

    data["amount_text"] = (
        _format_plain_amount(
            amount
        )
        if "_format_plain_amount"
        in globals()
        else format_t_amount(
            amount
        )
    )

    for key in (
        "original_amount",
        "payout_base_amount",
        "customer_pay_amount",
        "manual_discount_amount",
        "cash_coupon_amount",
        "store_absorbed_amount",
    ):
        value = order.get(key)

        if value is not None:
            data[key] = value

    data[
        "website_payment_method"
    ] = details[
        "website_payment_method"
    ] or None

    # 網站預選不代表 Discord 已正式付款。
    data.pop(
        "payment_method",
        None,
    )

    data[
        "specified_staff_ids"
    ] = list(
        details[
            "specified_staff_ids"
        ]
    )

    data[
        "companion_preference"
    ] = (
        "指定陪玩/打手"
        if details[
            "specified_staff_ids"
        ]
        else "不指定陪玩/打手"
    )

    extra_requirements = (
        details[
            "extra_requirements"
        ]
    )

    data[
        "extra_requirements"
    ] = (
        extra_requirements
        or None
    )

    if extra_requirements:
        data["staff_note"] = (
            extra_requirements
        )
        data[
            "staff_order_note"
        ] = extra_requirements

    data[
        "service_terms_version"
    ] = (
        details[
            "service_terms_version"
        ]
        or None
    )

    data[
        "website_terms_accepted_at"
    ] = (
        details[
            "terms_accepted_at"
        ]
        or None
    )

    data[
        "web_submission_request_key"
    ] = (
        details[
            "request_key"
        ]
        or None
    )

    data["web_order_note"] = (
        order.get("note")
    )

    data[
        "website_finance_settled"
    ] = True

    data[
        "web_order_source"
    ] = "website"

    data[
        "web_order_id"
    ] = int(order_id)

    data[
        "dispatch_channel_id"
    ] = dispatch_channel.id

    data[
        "dispatch_message_id"
    ] = dispatch_message.id

    data[
        "closed"
    ] = False

    data[
        "status"
    ] = str(
        acceptance.get(
            "status"
        )
        or order.get(
            "status"
        )
        or "waiting_acceptance"
    )

    data[
        "waiting_acceptance_created_at"
    ] = (
        data.get(
            "waiting_acceptance_created_at"
        )
        or get_taipei_now_iso()
    )

    # 防止網站已扣的點數福利，
    # 又被 Bot 付款流程視為尚未扣除。
    for unsafe_key in (
        "point_benefit_key",
        "selected_point_benefit_key",
        "point_benefit_name",
        "point_benefit_cost",
        "point_discount_coupon_amount",
        "point_waived_specify_fee",
        "point_free_first_hour_amount",
        "point_extra_hours",
        "point_extra_games",
        "point_benefit_redeemed",
        "point_benefit_redeemed_at",
        "point_benefit_before_points",
        "point_benefit_after_points",
        "point_benefit_redeemed_by",
    ):
        data.pop(
            unsafe_key,
            None,
        )

    from shared.order_acceptance import (
        get_acceptance_state,
    )

    state = get_acceptance_state(
        int(order_id)
    )

    claim_data = (
        ORDER_CLAIMS.setdefault(
            dispatch_message.id,
            {
                "companion": set(),
                "booster": set(),
                "locked": False,
            },
        )
    )

    _apply_acceptance_state_to_claim_data(
        claim_data,
        state,
    )

    claim_data[
        "locked"
    ] = False

    claim_data[
        "customer_id"
    ] = customer_id

    claim_data[
        "category_label"
    ] = details[
        "category_label"
    ]

    claim_data[
        "item"
    ] = details[
        "item"
    ]

    claim_data[
        "quantity"
    ] = details[
        "quantity"
    ]

    claim_data[
        "payment_method"
    ] = "待付款"

    claim_data[
        "amount"
    ] = amount

    claim_data[
        "total_amount"
    ] = amount

    claim_data[
        "source_channel_id"
    ] = ticket_channel.id

    claim_data[
        "dispatch_channel_id"
    ] = dispatch_channel.id

    claim_data[
        "companion_preference"
    ] = data[
        "companion_preference"
    ]

    claim_data[
        "specified_staff_ids"
    ] = list(
        details[
            "specified_staff_ids"
        ]
    )

    claim_data[
        "website_order"
    ] = True

    ORDER_CLAIMS[
        dispatch_message.id
    ] = claim_data

    remember_order_data(
        ticket_channel.id,
        data,
    )

    remember_claim_data(
        dispatch_message.id,
        claim_data,
    )

    save_bot_data()



# zYao 3C3B2R3 CS review gate v1

WEB_ORDER_PENDING_CS_DISPATCH = (
    "pending_cs_dispatch"
)


def _web_cs_order_id_from_channel(
    channel,
):

    topic = str(
        getattr(
            channel,
            "topic",
            "",
        )
        or ""
    )


    match = re.search(
        r"(?:^|;)"
        r"web_order_id="
        r"(\d+)"
        r"(?:;|$)",
        topic,
    )


    if not match:

        return None


    return int(
        match.group(1)
    )


def _web_cs_set_status(
    order_id: int,
    status: str,
    *,
    cs_user=None,
):
    """更新官網訂單 bridge 狀態；所有 lifecycle 變更統一走中央狀態機。"""
    from sqlalchemy import text

    from shared.db import engine
    from shared.order_state import transition_order_state_in_connection

    cs_id = ""
    cs_name = ""

    if cs_user is not None:
        cs_id = str(
            getattr(
                cs_user,
                "id",
                "",
            )
            or ""
        ).strip()

        cs_name = str(
            getattr(
                cs_user,
                "display_name",
                None,
            )
            or getattr(
                cs_user,
                "global_name",
                None,
            )
            or getattr(
                cs_user,
                "name",
                None,
            )
            or cs_id
        ).strip()

    with engine.begin() as conn:
        transition_order_state_in_connection(
            conn,
            order_id=int(order_id),
            target_status=str(status),
            source=(
                "website_cs_dispatch"
                if cs_user is not None
                else "website_cs_lifecycle"
            ),
            reason=f"客服流程更新狀態為 {status}",
            actor_discord_id=cs_id or None,
        )

        if cs_user is not None:
            conn.execute(
                text(
                    """
                    UPDATE web_orders
                    SET customer_service_discord_id = :cs_id,
                        customer_service_display_name = :cs_name,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE id = :order_id
                    """
                ),
                {
                    "cs_id": cs_id or None,
                    "cs_name": cs_name or None,
                    "order_id": int(order_id),
                },
            )


async def _web_cs_ensure_review_panel(
    order_id: int,
    bundle: dict,
    ticket_channel:
        discord.TextChannel,
):

    footer_text = (
        f"WEB-{order_id}"
        "｜客服送單前"
    )


    if await _web_order_created_has_footer(
        ticket_channel,
        footer_text,
        limit=40,
    ):

        return


    order = (
        bundle.get(
            "order"
        )
        or {}
    )


    details = (
        _web_order_created_details(
            bundle
        )
    )


    customer_id = _to_int(
        order.get(
            "customer_discord_id"
        ),
        None,
    )


    amount = _to_int(
        order.get(
            "customer_pay_amount"
        ),
        details.get(
            "amount"
        )
        or 0,
    )


    amount = int(
        amount
        or 0
    )


    embed = discord.Embed(
        title=(
            "網站訂單｜"
            "等待客服確認"
        ),
        description=(
            "官網訂單已建立完成。\n\n"
            "目前尚未送到派單頻道，"
            "也尚未開放任何人接單。\n"
            "請客服確認內容後再送單。"
        ),
        color=discord.Color.gold(),
    )


    embed.add_field(
        name="網站訂單",
        value=f"WEB-{order_id}",
        inline=True,
    )


    embed.add_field(
        name="顧客",
        value=(
            f"<@{customer_id}>"
            if customer_id
            else "未紀錄"
        ),
        inline=True,
    )


    embed.add_field(
        name="項目",
        value=(
            f"{details.get('category_label') or '未紀錄'}"
            f"｜"
            f"{details.get('item') or '未紀錄'}"
        ),
        inline=False,
    )


    embed.add_field(
        name="數量",
        value=str(
            details.get(
                "quantity"
            )
            or 1
        ),
        inline=True,
    )


    amount_text = (
        _format_plain_amount(
            amount
        )
        if "_format_plain_amount"
        in globals()
        else format_t_amount(
            amount
        )
    )


    embed.add_field(
        name="顧客應付",
        value=amount_text,
        inline=True,
    )


    embed.add_field(
        name="付款方式",
        value=(
            "尚未選擇\n"
            "人員接滿後於 Discord 選擇"
        ),
        inline=False,
    )


    specified = (
        details.get(
            "specified_staff_ids"
        )
        or []
    )


    if specified:

        embed.add_field(
            name="指定人員",
            value="、".join(
                f"<@{staff_id}>"
                for staff_id
                in specified
            )[:1024],
            inline=False,
        )


    extra = str(
        details.get(
            "extra_requirements"
        )
        or ""
    ).strip()


    if extra:

        embed.add_field(
            name="附加需求",
            value=extra[:1024],
            inline=False,
        )


    terms = str(
        details.get(
            "service_terms_version"
        )
        or ""
    ).strip()


    if terms:

        embed.add_field(
            name="服務規章",
            value=(
                f"已同意｜{terms}"
            ),
            inline=False,
        )


    embed.set_footer(
        text=footer_text
    )


    await ticket_channel.send(
        embed=embed,
        view=WebsiteOrderCsConfirmView(),
        allowed_mentions=(
            discord.AllowedMentions(
                users=True,
                roles=False,
                everyone=False,
            )
        ),
    )


class WebsiteOrderCsConfirmView(
    discord.ui.View
):

    def __init__(
        self,
    ):

        super().__init__(
            timeout=None
        )


    @discord.ui.button(
        label="客服確認送單",
        style=(
            discord.ButtonStyle.success
        ),
        custom_id=(
            "website_order_"
            "cs_confirm_dispatch_v3"
        ),
    )
    async def confirm(
        self,
        interaction:
            discord.Interaction,
        button:
            discord.ui.Button,
    ):

        if (
            not isinstance(
                interaction.user,
                discord.Member,
            )
            or not is_customer_staff(
                interaction.user
            )
        ):

            await interaction.response.send_message(
                "只有客服可以確認送單。",
                ephemeral=True,
            )

            return


        if not isinstance(
            interaction.channel,
            discord.TextChannel,
        ):

            await interaction.response.send_message(
                "目前不是有效訂單票口。",
                ephemeral=True,
            )

            return


        order_id = (
            _web_cs_order_id_from_channel(
                interaction.channel
            )
        )


        if order_id is None:

            await interaction.response.send_message(
                "找不到網站訂單編號。",
                ephemeral=True,
            )

            return


        bundle = (
            _web_order_created_load_bundle(
                order_id
            )
        )


        order = (
            bundle.get(
                "order"
            )
            or {}
        )


        current_status = str(
            order.get(
                "status"
            )
            or ""
        ).lower()


        if (
            current_status
            != WEB_ORDER_PENDING_CS_DISPATCH
        ):

            await interaction.response.send_message(
                (
                    "這張訂單目前不是"
                    "等待客服確認狀態。"
                ),
                ephemeral=True,
            )

            return


        await interaction.response.defer(
            ephemeral=True
        )


        try:

            # 先放行為正式等待接單。
            _web_cs_set_status(
                order_id,
                "waiting_acceptance",
                cs_user=interaction.user,
            )


            bundle = (
                _web_order_created_load_bundle(
                    order_id
                )
            )


            guild = interaction.guild


            if guild is None:

                raise RuntimeError(
                    "找不到 Discord guild"
                )


            (
                dispatch_channel,
                dispatch_message,
            ) = (
                await _web_order_created_ensure_dispatch(
                    guild,
                    order_id,
                    bundle,
                    interaction.channel,
                )
            )


            # 接回原本 3C-3B seed。
            _web_order_created_seed_state(
                order_id,
                bundle,
                interaction.channel,
                dispatch_channel,
                dispatch_message,
            )


            # 官網沒有付款方式。
            data = (
                SELF_SERVICE_ORDER_SELECTIONS
                .setdefault(
                    interaction.channel.id,
                    {},
                )
            )


            data.pop(
                "payment_method",
                None,
            )


            data.pop(
                "website_payment_method",
                None,
            )


            data[
                "web_order_no_payment_selection"
            ] = True


            remember_order_data(
                interaction.channel.id,
                data,
            )


            save_bot_data()


            await (
                refresh_acceptance_dispatch_from_web_order(
                    guild,
                    order_id,
                )
            )


            await interaction.channel.send(
                (
                    "✅ "
                    f"{interaction.user.mention} "
                    "已確認訂單並送出等待接單。"
                ),
                allowed_mentions=(
                    discord.AllowedMentions(
                        users=True,
                        roles=False,
                        everyone=False,
                    )
                ),
            )


            if interaction.message:

                try:

                    await interaction.message.edit(
                        view=None
                    )

                except discord.HTTPException:

                    pass


            await interaction.followup.send(
                "已確認並送出等待接單。",
                ephemeral=True,
            )


        except Exception as exc:

            # 派單失敗就恢復客服確認狀態，
            # 讓客服可以重試。恢復失敗時不可再對客服宣稱已恢復。
            rollback_error = None

            try:

                _web_cs_set_status(
                    order_id,
                    WEB_ORDER_PENDING_CS_DISPATCH,
                )

            except Exception as rollback_exc:

                rollback_error = rollback_exc

                print(
                    "[web-order-create] "
                    f"CS dispatch rollback failed "
                    f"WEB-{order_id}: "
                    f"{type(rollback_exc).__name__}: "
                    f"{rollback_exc}",
                    flush=True,
                )


            print(
                "[web-order-create] "
                f"CS dispatch failed "
                f"WEB-{order_id}: "
                f"{type(exc).__name__}: "
                f"{exc}",
                flush=True,
            )


            if rollback_error is None:

                followup_message = (
                    "送單失敗，"
                    "訂單已恢復等待客服確認。"
                )

            else:

                followup_message = (
                    "送單失敗，而且訂單狀態沒有成功恢復。"
                    f"請先不要重複操作 WEB-{order_id}，"
                    "通知總管檢查訂單狀態。"
                )


            await interaction.followup.send(
                followup_message,
                ephemeral=True,
            )


    # MAWAN_R12_WEBSITE_PENDING_CANCEL

    @discord.ui.button(
        label="取消訂單",
        style=discord.ButtonStyle.danger,
        custom_id="website_order_pending_cancel",
        row=1,
    )
    async def cancel_pending_order(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ):
        # MAWAN_R12_1_PENDING_CANCEL_DB_FALLBACK
        if (
            not isinstance(interaction.user, discord.Member)
            or not is_customer_staff(interaction.user)
        ):
            await interaction.response.send_message(
                "只有客服可以取消網站訂單。",
                ephemeral=True,
            )
            return

        if not isinstance(interaction.channel, discord.TextChannel):
            await interaction.response.send_message(
                "目前不是有效的訂單票口。",
                ephemeral=True,
            )
            return

        channel = interaction.channel
        channel_id = channel.id
        data = SELF_SERVICE_ORDER_SELECTIONS.setdefault(channel_id, {})

        # 待客服確認階段尚未建立派單資料，不能只依賴 Bot 記憶體。
        # 依序使用：Bot state -> 頻道 topic -> web_orders.ticket_channel_id。
        order_id = _to_int(data.get("web_order_id"), None)

        if order_id is None:
            try:
                order_id = _web_cs_order_id_from_channel(channel)
            except Exception:
                order_id = None

        conn = sqlite3.connect(
            _web_dashboard_db_path_for_bot(),
            timeout=15,
        )
        conn.row_factory = sqlite3.Row

        try:
            row = None

            if order_id is not None:
                row = conn.execute(
                    """
                    SELECT id, status, dispatch_message_id, ticket_channel_id
                    FROM web_orders
                    WHERE id = ?
                    LIMIT 1
                    """,
                    (int(order_id),),
                ).fetchone()

            if row is None:
                row = conn.execute(
                    """
                    SELECT id, status, dispatch_message_id, ticket_channel_id
                    FROM web_orders
                    WHERE ticket_channel_id = ?
                    ORDER BY id DESC
                    LIMIT 1
                    """,
                    (str(channel_id),),
                ).fetchone()
        finally:
            conn.close()

        if row is None:
            await interaction.response.send_message(
                "找不到這張票口對應的網站訂單，請通知管理員確認。",
                ephemeral=True,
            )
            return

        order_id = int(row["id"])
        db_status = str(row["status"] or "").strip().lower()
        db_dispatch_message_id = str(row["dispatch_message_id"] or "").strip()

        # 把 canonical DB 身分補回 Bot state，之後同票口都能正常取到 WEB ID。
        data["web_order_id"] = order_id
        data["web_order_source"] = "website"
        data["status"] = db_status
        remember_order_data(channel_id, data)
        save_bot_data()

        if db_status != WEB_ORDER_PENDING_CS_DISPATCH:
            await interaction.response.send_message(
                "這張訂單已經進入後續流程，不能從待確認面板取消。",
                ephemeral=True,
            )
            return

        if db_dispatch_message_id or data.get("dispatch_message_id"):
            await interaction.response.send_message(
                "這張訂單已經送出派單，請使用正式訂單操作取消。",
                ephemeral=True,
            )
            return

        await interaction.response.send_message(
            "請先選擇取消原因，再按「確認取消網站訂單」。",
            view=WebsitePendingCancelConfirmView(
                order_id=int(order_id),
                order_channel_id=int(channel_id),
            ),
            ephemeral=True,
        )




class WebsitePendingCancelConfirmView(discord.ui.View):
    def __init__(
        self,
        *,
        order_id: int,
        order_channel_id: int,
    ):
        super().__init__(timeout=60)
        self.order_id = int(order_id)
        self.order_channel_id = int(order_channel_id)
        self.cancellation_reason_code = "unspecified"
        self.add_item(OrderCancellationReasonSelect())

    @discord.ui.button(
        label="確認取消網站訂單",
        style=discord.ButtonStyle.danger,
        row=0,
    )
    async def confirm_cancel(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ):
        if (
            not isinstance(interaction.user, discord.Member)
            or not is_customer_staff(interaction.user)
        ):
            await interaction.response.send_message(
                "只有客服可以取消網站訂單。",
                ephemeral=True,
            )
            return

        if self.cancellation_reason_code == "unspecified":
            await interaction.response.send_message(
                "請先從下拉選單選擇取消原因。",
                ephemeral=True,
            )
            return

        if interaction.guild is None:
            await interaction.response.send_message(
                "找不到 Discord 伺服器，請重新操作。",
                ephemeral=True,
            )
            return

        channel = interaction.guild.get_channel(
            self.order_channel_id
        )
        if not isinstance(channel, discord.TextChannel):
            await interaction.response.send_message(
                "找不到這張網站訂單票口。",
                ephemeral=True,
            )
            return

        await interaction.response.defer(ephemeral=True)

        reason_label = dict(CANCEL_REASON_OPTIONS).get(
            self.cancellation_reason_code,
            self.cancellation_reason_code,
        )

        try:
            from shared.order_state import (
                CANCELLED,
                PENDING_CS_DISPATCH,
                transition_order_state,
            )

            transition_order_state(
                order_id=self.order_id,
                target_status=CANCELLED,
                source="website_pending_cancel",
                reason=reason_label,
                actor_discord_id=interaction.user.id,
                expected_statuses={PENDING_CS_DISPATCH},
                require_empty_dispatch_message=True,
                cancellation_reason_code=self.cancellation_reason_code,
            )
        except ValueError:
            await interaction.followup.send(
                "取消前訂單狀態已被其他操作更新，或已產生派單訊息，請重新確認目前狀態。",
                ephemeral=True,
            )
            return

        SELF_SERVICE_ORDER_SELECTIONS.pop(
            self.order_channel_id,
            None,
        )

        try:
            delete_order_row_from_db(self.order_channel_id)
        except Exception as exc:
            print(
                "[website-order] cancel local row cleanup failed "
                f"channel_id={self.order_channel_id}: {exc}",
                flush=True,
            )

        save_bot_data()

        try:
            await send_order_log(
                interaction.guild,
                title="網站訂單已取消",
                fields=[
                    ("網站訂單", f"WEB-{self.order_id}", True),
                    ("操作客服", interaction.user.mention, True),
                    ("取消原因", reason_label, True),
                    ("票口", channel.mention, False),
                ],
                color=discord.Color.red(),
            )
        except Exception as exc:
            print(
                "[website-order] "
                f"cancel log failed: {exc}",
                flush=True,
            )

        await interaction.followup.send(
            (
                f"已取消 WEB-{self.order_id}｜"
                f"{reason_label}，票口將在 3 秒後關閉。"
            ),
            ephemeral=False,
        )

        await asyncio.sleep(3)

        try:
            await channel.delete(
                reason=(
                    f"Website order WEB-{self.order_id} "
                    f"cancelled by {interaction.user}"
                )
            )
        except discord.HTTPException as exc:
            print(
                "[website-order] cancel ticket delete failed "
                f"channel_id={self.order_channel_id}: {exc}",
                flush=True,
            )

    @discord.ui.button(
        label="保留訂單",
        style=discord.ButtonStyle.secondary,
        row=0,
    )
    async def keep_order(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ):
        if (
            not isinstance(interaction.user, discord.Member)
            or not is_customer_staff(interaction.user)
        ):
            await interaction.response.send_message(
                "只有客服可以操作。",
                ephemeral=True,
            )
            return

        await interaction.response.edit_message(
            content="已保留網站訂單。",
            view=None,
        )


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

async def _process_web_order_created_event(
    event: dict,
) -> None:

    event_id = int(
        event["event_id"]
    )


    order_id = int(
        event.get(
            "order_id"
        )
        or event.get(
            "web_order_id"
        )
    )


    retry_count = int(
        event.get(
            "retry_count"
        )
        or 0
    )


    _web_order_created_mark_processing(
        event_id
    )


    try:

        bundle = (
            _web_order_created_load_bundle(
                order_id
            )
        )


        order = (
            bundle.get(
                "order"
            )
            or {}
        )


        status = str(
            order.get(
                "status"
            )
            or ""
        ).lower()


        if (
            status
            != WEB_ORDER_PENDING_CS_DISPATCH
        ):

            _web_sync_mark_event_done(
                event_id
            )


            print(
                "[web-order-create] "
                f"skip WEB-{order_id} "
                f"status={status}",
                flush=True,
            )


            return


        guild = bot.get_guild(
            GUILD_ID
        )


        if guild is None:

            raise RuntimeError(
                "Discord guild 尚未 ready"
            )


        ticket_channel = (
            await _web_order_created_ensure_ticket(
                guild,
                event_id,
                order_id,
                bundle,
            )
        )


        await _r13_ensure_website_unified_panels(
            guild,
            order_id,
            bundle,
            ticket_channel,
        )


        _web_sync_mark_event_done(
            event_id
        )


        print(
            "[web-order-create] "
            f"WEB-{order_id} "
            f"ticket={ticket_channel.id} "
            "unified_self_service_ready",
            flush=True,
        )


    except Exception as exc:

        _web_sync_mark_event_failed(
            event_id,
            (
                f"{type(exc).__name__}: "
                f"{exc}"
            ),
            retry_count,
        )


        print(
            "[web-order-create] "
            f"WEB-{order_id} failed: "
            f"{type(exc).__name__}: "
            f"{exc}",
            flush=True,
        )
