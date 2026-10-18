from __future__ import annotations

from typing import Any

import discord

from core.database import (
    remember_claim_data,
    remember_order_data,
    save_bot_data,
)
from core.time_utils import get_taipei_now_iso
from services.acceptance.runtime import _apply_acceptance_state_to_claim_data
from services.logging_service import send_order_log
from services.orders import _to_int
from services.self_service_financials import _format_plain_amount
from services.smart_dispatch import (
    create_smart_dispatch_plan,
    get_smart_dispatch_plan,
    set_specified_dm_results,
)
from services.ticket_identity import build_ticket_channel_name
from services.web_sync.discord_helpers import (
    find_ticket as _web_order_created_find_ticket,
    get_channel as _web_order_created_get_channel,
    get_member as _web_order_created_get_member,
    has_footer as _web_order_created_has_footer,
)
from services.web_sync.event_store import (
    load_order_created_bundle as _web_order_created_load_bundle,
    mark_order_created_processing as _web_order_created_mark_processing,
    update_order_created_links as _web_order_created_update_links,
    mark_event_done as _web_sync_mark_event_done,
    mark_event_failed as _web_sync_mark_event_failed,
)
from services.web_sync.presentation import (
    build_order_created_details as _web_order_created_details,
)
from services.web_sync.cs_review import (
    WEB_ORDER_PENDING_CS_DISPATCH,
    WebsiteOrderCsConfirmView,
    WebsitePendingCancelConfirmView,
    configure_web_sync_cs_review,
    _web_dashboard_db_path_for_bot,
    _web_cs_order_id_from_channel,
    _web_cs_set_status,
    _web_cs_ensure_review_panel,
)
from services.web_sync.self_service_bridge import (
    configure_web_sync_self_service_bridge,
    _r13_ensure_website_unified_panels,
    _r13_seed_website_order_into_self_service,
)
from views.smart_dispatch import (
    prepare_initial_smart_dispatch,
    send_initial_smart_dispatch_alert,
    send_specified_staff_dispatch_dms,
)


_CONFIGURED = False

CUSTOMER_CATEGORY_ID: int
CUSTOMER_ROLE_ID: int
DISPATCH_CHANNEL_ID: int
GUILD_ID: int
ORDER_CLAIMS: dict[int, dict[str, Any]]
SELF_SERVICE_ORDER_SELECTIONS: dict[int, dict[str, Any]]
bot: discord.Client


def configure_web_sync_runtime_explicit(
    *,
    customer_category_id: int,
    customer_role_id: int,
    dispatch_channel_id: int,
    guild_id: int,
    order_claims: dict[int, dict[str, Any]],
    order_control_view_type: type[discord.ui.View],
    order_selections: dict[int, dict[str, Any]],
    bot_instance: discord.Client,
) -> None:
    """Bind only the entrypoint-owned state required by Web sync."""
    global _CONFIGURED
    global CUSTOMER_CATEGORY_ID, CUSTOMER_ROLE_ID, DISPATCH_CHANNEL_ID, GUILD_ID
    global ORDER_CLAIMS, SELF_SERVICE_ORDER_SELECTIONS, bot

    CUSTOMER_CATEGORY_ID = int(customer_category_id)
    CUSTOMER_ROLE_ID = int(customer_role_id)
    DISPATCH_CHANNEL_ID = int(dispatch_channel_id)
    GUILD_ID = int(guild_id)
    ORDER_CLAIMS = order_claims
    SELF_SERVICE_ORDER_SELECTIONS = order_selections
    bot = bot_instance
    configure_web_sync_self_service_bridge(
        customer_role_id=CUSTOMER_ROLE_ID,
        order_control_view_type=order_control_view_type,
        order_selections=SELF_SERVICE_ORDER_SELECTIONS,
    )
    configure_web_sync_cs_review(
    order_selections=SELF_SERVICE_ORDER_SELECTIONS,
    ensure_dispatch=lambda *args, **kwargs: _web_order_created_ensure_dispatch(
        *args, **kwargs
    ),
    seed_state=lambda *args, **kwargs: _web_order_created_seed_state(
        *args, **kwargs
    ),
)
    _CONFIGURED = True


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
        amount_text = _format_plain_amount(
            details["amount"]
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

    amount = int(
        details["amount"]
    )

    data["amount"] = amount
    data["total_amount"] = amount

    data["amount_text"] = _format_plain_amount(
        amount
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
