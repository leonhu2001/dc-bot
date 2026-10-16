from __future__ import annotations

from core.database import remember_claim_data, remember_order_data, save_bot_data
from core.time_utils import get_taipei_now_iso
from typing import Any, Mapping

import discord

from services.acceptance.repair_runtime import (
    configure_acceptance_repair_runtime,
    repair_pending_acceptance_dispatch_panels_once,
    repair_pending_acceptance_payment_panels_once,
    repair_pending_acceptance_ticket_access_once,
    restore_acceptance_payment_panel_for_order,
)
from services.acceptance.sync_worker import (
    acceptance_sync_event_worker,
    configure_acceptance_sync_worker,
    process_acceptance_sync_events_once,
)
from services.logging_service import send_order_log
from services.order_dispatch_runtime import DispatchClaimView
from services.order_flow import build_payment_method_embed
from services.orders import (
    ORDER_CATEGORY_LABELS,
    _to_int,
    build_self_service_order_embed,
)
from services.self_service_financials import (
    _format_plain_amount,
    _price_int,
    _price_snapshot,
    add_self_service_financial_breakdown_fields,
)


_CONFIGURED = False
_DEPENDENCY_NAMES = (
    "DISPATCH_CHANNEL_ID",
    "ORDER_CLAIMS",
    "PaymentMethodView",
    "SELF_SERVICE_ORDER_SELECTIONS",
)
_SYNC_WORKER_DEPENDENCY_NAMES = (
    "GUILD_ID",
    "_refresh_existing_web_sync_dispatch",
    "bot",
)
_REQUIRED_DEPENDENCY_NAMES = _DEPENDENCY_NAMES + _SYNC_WORKER_DEPENDENCY_NAMES


def configure_acceptance_runtime(namespace: Mapping[str, Any]) -> None:
    """Bind only the bot-owned acceptance adapters that have no stable owner yet."""
    global _CONFIGURED
    global DISPATCH_CHANNEL_ID, ORDER_CLAIMS, PaymentMethodView
    global SELF_SERVICE_ORDER_SELECTIONS

    missing = [name for name in _REQUIRED_DEPENDENCY_NAMES if name not in namespace]
    if missing:
        raise RuntimeError(
            "acceptance runtime missing dependencies: " + ", ".join(missing)
        )

    DISPATCH_CHANNEL_ID = namespace["DISPATCH_CHANNEL_ID"]
    ORDER_CLAIMS = namespace["ORDER_CLAIMS"]
    PaymentMethodView = namespace["PaymentMethodView"]
    SELF_SERVICE_ORDER_SELECTIONS = namespace["SELF_SERVICE_ORDER_SELECTIONS"]

    configure_acceptance_sync_worker(
        bot_instance=namespace["bot"],
        guild_id=namespace["GUILD_ID"],
        refresh_acceptance_dispatch=refresh_acceptance_dispatch_from_web_order,
        refresh_existing_web_sync_dispatch=namespace[
            "_refresh_existing_web_sync_dispatch"
        ],
        grant_ticket_access=grant_order_ticket_access,
        revoke_ticket_access=revoke_order_ticket_access,
        to_int=_to_int,
    )
    configure_acceptance_repair_runtime(
        order_selections=SELF_SERVICE_ORDER_SELECTIONS,
        payment_method_view_type=PaymentMethodView,
        refresh_acceptance_dispatch=refresh_acceptance_dispatch_from_web_order,
        sync_ticket_access_from_state=sync_acceptance_ticket_access_from_state,
        acceptance_staff_display_text=_acceptance_staff_display_text,
    )

    _CONFIGURED = True


def _member_role_id_texts(member: discord.Member) -> list[str]:
    return [
        str(role.id)
        for role in getattr(member, "roles", [])
        if getattr(role, "id", None) is not None
    ]


def _member_display_name(member: discord.Member) -> str:
    return str(
        getattr(member, "display_name", None)
        or getattr(member, "global_name", None)
        or getattr(member, "name", None)
        or getattr(member, "id", None)
        or "未知使用者"
    )


def _ticket_overwrite_has_values(overwrite: discord.PermissionOverwrite) -> bool:
    values = getattr(overwrite, "_values", None)
    if isinstance(values, dict):
        return bool(values)

    return any(
        getattr(overwrite, attr, None) is not None
        for attr in (
            "view_channel",
            "send_messages",
            "read_message_history",
            "attach_files",
            "embed_links",
        )
    )


async def grant_order_ticket_access(
    guild: discord.Guild,
    ticket_channel_id: int,
    member: discord.Member,
) -> bool:
    """接單成功後給接單者票口可見 / 文字互動權限。"""
    channel = guild.get_channel(int(ticket_channel_id))
    if not isinstance(channel, discord.TextChannel):
        return False

    overwrite = channel.overwrites_for(member)
    overwrite.view_channel = True
    overwrite.send_messages = True
    overwrite.read_message_history = True
    overwrite.attach_files = True
    overwrite.embed_links = True

    try:
        await channel.set_permissions(
            member,
            overwrite=overwrite,
            reason="Grant accepted staff ticket access",
        )
        return True
    except discord.Forbidden:
        print(
            f"[ticket-access] Bot 權限不足，無法開放票口 "
            f"channel={ticket_channel_id} member={member.id}"
        )
    except discord.HTTPException as exc:
        print(
            f"[ticket-access] 開放票口失敗 "
            f"channel={ticket_channel_id} member={member.id}: {exc}"
        )

    return False


async def revoke_order_ticket_access(
    guild: discord.Guild,
    ticket_channel_id: int,
    member: discord.Member,
) -> bool:
    """取消接單後只清掉接單流程寫入的票口權限，恢復角色繼承。"""
    channel = guild.get_channel(int(ticket_channel_id))
    if not isinstance(channel, discord.TextChannel):
        return False

    overwrite = channel.overwrites_for(member)
    overwrite.view_channel = None
    overwrite.send_messages = None
    overwrite.read_message_history = None
    overwrite.attach_files = None
    overwrite.embed_links = None

    try:
        await channel.set_permissions(
            member,
            overwrite=overwrite if _ticket_overwrite_has_values(overwrite) else None,
            reason="Revoke unclaimed staff ticket access",
        )
        return True
    except discord.Forbidden:
        print(
            f"[ticket-access] Bot 權限不足，無法收回票口 "
            f"channel={ticket_channel_id} member={member.id}"
        )
    except discord.HTTPException as exc:
        print(
            f"[ticket-access] 收回票口失敗 "
            f"channel={ticket_channel_id} member={member.id}: {exc}"
        )

    return False


async def sync_acceptance_ticket_access_from_state(
    guild: discord.Guild,
    ticket_channel_id: int,
    state,
) -> None:
    """刷新接單狀態時，確保所有目前接單者都能看到票口。"""
    for claim in getattr(state, "claims", ()):
        user_id = _to_int(getattr(claim, "staff_discord_id", None))
        if user_id is None:
            continue

        member = guild.get_member(user_id)
        if member is None:
            try:
                fetched = await guild.fetch_member(user_id)
                member = fetched if isinstance(fetched, discord.Member) else None
            except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                member = None

        if member is not None:
            await grant_order_ticket_access(
                guild,
                int(ticket_channel_id),
                member,
            )


def _acceptance_staff_display_text(
    guild: discord.Guild | None,
    state,
) -> str | None:
    """Use clickable Discord mentions when possible, with a saved-name fallback."""
    values: list[str] = []

    for claim in getattr(state, "claims", ()):
        user_id = _to_int(getattr(claim, "staff_discord_id", None))
        member = guild.get_member(user_id) if guild is not None and user_id is not None else None

        if member is not None:
            display_value = member.mention
        else:
            display_value = str(
                getattr(claim, "staff_display_name", None)
                or ""
            ).strip()

        if display_value and display_value not in values:
            values.append(display_value)

    return "、".join(values) or None


def _apply_acceptance_state_to_claim_data(claim_data: dict, state) -> None:
    receiver_ids: set[int] = set()

    for claim in getattr(state, "claims", ()):
        parsed_id = _to_int(getattr(claim, "staff_discord_id", None))
        if parsed_id is not None:
            receiver_ids.add(parsed_id)

    claim_data["companion"] = set()
    claim_data["booster"] = receiver_ids
    claim_data["acceptance_order_id"] = int(getattr(state, "order_id", 0) or 0)
    claim_data["accepted_count"] = int(getattr(state, "accepted_count", 0) or 0)
    claim_data["required_staff_count"] = int(getattr(state, "required_staff_count", 1) or 1)
    claim_data["protector_count"] = int(getattr(state, "protector_count", 0) or 0)
    claim_data["min_protector_count"] = int(getattr(state, "min_protector_count", 0) or 0)
    claim_data["status"] = str(getattr(state, "status", None) or claim_data.get("status") or "waiting_acceptance")


async def refresh_acceptance_dispatch_from_web_order(guild: discord.Guild, order_id: int) -> None:
    from shared.db import SessionLocal
    from shared.models import WebOrder
    from shared.order_acceptance import ACCEPTED_PENDING_PAY, get_acceptance_state

    db = SessionLocal()

    try:
        order = db.get(WebOrder, int(order_id))

        if order is None:
            raise ValueError(f"找不到網站訂單：{order_id}")

        dispatch_message_id = _to_int(order.dispatch_message_id)
        dispatch_channel_id = _to_int(order.dispatch_channel_id, DISPATCH_CHANNEL_ID) or DISPATCH_CHANNEL_ID
        ticket_channel_id = _to_int(order.ticket_channel_id)
        customer_id = _to_int(order.customer_discord_id)
        customer_display_name = str(
            getattr(order, "customer_display_name", None)
            or ""
        ).strip()
        category_raw = str(order.category or "未紀錄")
        category_label = ORDER_CATEGORY_LABELS.get(category_raw, category_raw)
        item = str(order.item or "未紀錄")
        quantity = _to_int(
            order.quantity,
            1,
        ) or 1

        amount = _to_int(
            getattr(
                order,
                "customer_pay_amount",
                None,
            ),
            None,
        )

        if amount is None:
            amount = _to_int(
                order.amount,
                0,
            ) or 0

        payment_method = str(
            order.payment_method
            or "待付款"
        )

        web_price_data = _price_snapshot(
            getattr(
                order,
                "price_snapshot_json",
                None,
            )
        )

        web_price_data.setdefault(
            "original_amount",
            _to_int(
                getattr(
                    order,
                    "original_amount",
                    None,
                ),
                0,
            )
            or 0,
        )

        web_price_data.setdefault(
            "service_original_amount",
            web_price_data.get(
                "original_amount",
                0,
            ),
        )

        web_price_data.setdefault(
            "manual_discount_amount",
            _to_int(
                getattr(
                    order,
                    "manual_discount_amount",
                    None,
                ),
                0,
            )
            or 0,
        )

        web_price_data.setdefault(
            "cash_coupon_amount",
            _to_int(
                getattr(
                    order,
                    "cash_coupon_amount",
                    None,
                ),
                0,
            )
            or 0,
        )
        web_price_data.setdefault(
            "fixed_discount_amount",
            web_price_data.get(
                "cash_coupon_amount",
                0,
            ),
        )

        web_price_data.setdefault(
            "payout_base_amount",
            _to_int(
                getattr(
                    order,
                    "payout_base_amount",
                    None,
                ),
                amount,
            )
            or 0,
        )

        web_price_data.setdefault(
            "customer_pay_amount",
            amount,
        )

        absorbed = _to_int(
            getattr(
                order,
                "store_absorbed_amount",
                None,
            ),
            0,
        ) or 0

        web_price_data.setdefault(
            "point_discount_coupon_amount",
            max(
                0,
                absorbed
                - _price_int(
                    web_price_data,
                    "cash_coupon_amount",
                    default=0,
                ),
            ),
        )

        web_order_note = str(
            getattr(
                order,
                "note",
                None,
            )
            or ""
        ).strip()
    finally:
        db.close()

    if dispatch_message_id is None or ticket_channel_id is None or customer_id is None:
        raise ValueError(f"網站訂單缺少必要頻道或顧客資料：{order_id}")

    state = get_acceptance_state(int(order_id))
    accepted_staff_display_text = _acceptance_staff_display_text(guild, state)

    dispatch_channel = guild.get_channel(dispatch_channel_id)
    ticket_channel = guild.get_channel(ticket_channel_id)

    if not isinstance(dispatch_channel, discord.TextChannel):
        raise ValueError(f"找不到派單頻道：{dispatch_channel_id}")

    if not isinstance(ticket_channel, discord.TextChannel):
        raise ValueError(f"找不到票口頻道：{ticket_channel_id}")

    await sync_acceptance_ticket_access_from_state(
        guild,
        ticket_channel_id,
        state,
    )

    data = SELF_SERVICE_ORDER_SELECTIONS.setdefault(ticket_channel_id, {})

    if customer_display_name and customer_display_name != str(customer_id):
        data["customer_display_name"] = customer_display_name

    if accepted_staff_display_text:
        data["accepted_staff_display_text"] = accepted_staff_display_text
    else:
        data.pop("accepted_staff_display_text", None)

    # zYao 3C3B website order refresh safety v1
    if data.get("website_finance_settled"):
        website_selected_method = str(
            data.get("website_payment_method")
            or payment_method
            or ""
        ).strip()

        if website_selected_method:
            data["website_payment_method"] = website_selected_method

        # 網站只是預選付款方式。
        # 正式付款仍由原本 Discord PaymentMethodView 決定。
        payment_method = "待付款"

    claim_data = ORDER_CLAIMS.setdefault(
        dispatch_message_id,
        {
            "companion": set(),
            "booster": set(),
            "locked": False,
        },
    )

    _apply_acceptance_state_to_claim_data(claim_data, state)

    companion_preference = data.get("companion_preference") or claim_data.get("companion_preference") or "不指定陪玩/打手"

    claim_data["locked"] = False
    claim_data["customer_id"] = customer_id
    claim_data["category_label"] = category_label
    claim_data["item"] = item
    claim_data["quantity"] = quantity
    claim_data["payment_method"] = payment_method
    claim_data["amount"] = amount
    claim_data["total_amount"] = amount
    claim_data["source_channel_id"] = ticket_channel_id
    claim_data["dispatch_channel_id"] = dispatch_channel_id
    claim_data["companion_preference"] = companion_preference
    claim_data["status"] = str(state.status)

    data["customer_id"] = customer_id
    data["category_label"] = category_label
    data["item"] = item
    data["quantity"] = quantity
    data["amount"] = amount
    data["total_amount"] = amount
    data["amount_text"] = _format_plain_amount(amount)

    for key, value in web_price_data.items():
        if value is not None:
            data[key] = value

    if data.get("website_finance_settled"):
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
            data.pop(unsafe_key, None)

    if web_order_note:
        data["web_order_note"] = web_order_note

    data["dispatch_message_id"] = dispatch_message_id
    data["dispatch_channel_id"] = dispatch_channel_id
    data["web_order_id"] = int(order_id)
    data["status"] = str(state.status)
    data.setdefault("payment_method", None)

    receiver_text = _build_receiver_text_from_claim_data(claim_data)

    dispatch_embed = build_self_service_order_embed(
        customer_mention=f"<@{customer_id}>",
        category_label=category_label,
        item=item,
        quantity=quantity,
        payment_method=payment_method,
        source_channel=ticket_channel,
        companion_preference=companion_preference,
        receiver_text=receiver_text,
        staff_note=str(data.get("extra_requirements") or data.get("staff_note") or "").strip() or None,
    )

    add_self_service_financial_breakdown_fields(
        dispatch_embed,
        web_price_data,
    )

    website_info_lines = [
        f"網站訂單：WEB-{order_id}"
    ]

    # 官網不選付款方式。
    website_payment_method = ""

    service_terms_version = str(
        data.get("service_terms_version")
        or ""
    ).strip()

    if service_terms_version:
        website_info_lines.append(
            f"服務規章：已同意｜{service_terms_version}"
        )

    specified_staff_ids = [
        str(value).strip()
        for value
        in (
            data.get("specified_staff_ids")
            or []
        )
        if str(value).strip()
    ]

    if specified_staff_ids:
        website_info_lines.append(
            "指定人員："
            + "、".join(
                f"<@{staff_id}>"
                for staff_id
                in specified_staff_ids
            )
        )

    dispatch_embed.add_field(
        name="網站下單資訊",
        value="\n".join(
            website_info_lines
        )[:1024],
        inline=False,
    )

    dispatch_embed.add_field(
        name="接單進度",
        value=f"{state.accepted_count}/{state.required_staff_count}",
        inline=True,
    )

    if int(getattr(state, "min_protector_count", 0) or 0) > 0:
        dispatch_embed.add_field(
            name="護航需求",
            value=f"{state.protector_count}/{state.min_protector_count}",
            inline=True,
        )

    dispatch_embed.add_field(
        name="狀態",
        value="人數已滿，等待顧客付款" if str(state.status) == ACCEPTED_PENDING_PAY else "等待接單中",
        inline=False,
    )

    dispatch_embed.set_footer(
        text=f"WEB-{order_id}｜網站訂單"
    )

    try:
        dispatch_message = await dispatch_channel.fetch_message(dispatch_message_id)
        await dispatch_message.edit(
            embed=dispatch_embed,
            view=DispatchClaimView(
                customer_id=customer_id,
                category_label=category_label,
                item=item,
                quantity=quantity,
                payment_method=payment_method,
                source_channel_id=ticket_channel_id,
                companion_preference=companion_preference,
                locked=False,
                status=str(state.status),
            ),
            allowed_mentions=discord.AllowedMentions(users=True, roles=False, everyone=False),
        )
    except discord.HTTPException as exc:
        raise ValueError(f"更新 Discord 派單 panel 失敗：{exc}") from exc

    remember_claim_data(dispatch_message_id, claim_data)

    if str(state.status) == ACCEPTED_PENDING_PAY:
        if _to_int(data.get("payment_message_id")) is None:
            payment_embed = build_payment_method_embed(
                customer_id=customer_id,
                category_label=category_label,
                item=item,
                quantity=quantity,
                companion_preference=companion_preference,
                amount=amount,
                receiver_text=accepted_staff_display_text,
            )

            payment_message = await ticket_channel.send(
                content=f"<@{customer_id}> 接單人數已滿，請選擇付款方式。",
                embed=payment_embed,
                view=PaymentMethodView(
                    customer_id=customer_id,
                    channel_id=ticket_channel_id,
                ),
                allowed_mentions=discord.AllowedMentions(users=True, roles=False, everyone=False),
            )

            data["payment_channel_id"] = ticket_channel.id
            data["payment_message_id"] = payment_message.id
            data["accepted_pending_pay_at"] = get_taipei_now_iso()

            await send_order_log(
                guild,
                title="網站接單滿人｜開放付款",
                fields=[
                    ("顧客", f"<@{customer_id}>", True),
                    ("訂單", f"{category_label}｜{item} x{quantity}", False),
                    ("接單進度", f"{state.accepted_count}/{state.required_staff_count}", True),
                    ("票口", ticket_channel.mention, False),
                ],
                color=discord.Color.gold(),
            )
    else:
        old_payment_message_id = _to_int(data.get("payment_message_id"))
        old_payment_channel_id = _to_int(data.get("payment_channel_id"), ticket_channel.id) or ticket_channel.id

        if old_payment_message_id is not None:
            old_payment_channel = guild.get_channel(old_payment_channel_id)

            if isinstance(old_payment_channel, discord.TextChannel):
                try:
                    old_payment_message = await old_payment_channel.fetch_message(old_payment_message_id)
                    disabled_embed = build_payment_method_embed(
                        customer_id=customer_id,
                        category_label=category_label,
                        item=item,
                        quantity=quantity,
                        payment_method="等待接單人數補滿",
                        companion_preference=companion_preference,
                        amount=amount,
                        receiver_text=accepted_staff_display_text,
                        submitted=True,
                    )
                    disabled_embed.add_field(
                        name="付款狀態",
                        value="接單人數目前不足，這個付款面板已失效。人數再次補滿時會重新開付款面板。",
                        inline=False,
                    )
                    await old_payment_message.edit(
                        embed=disabled_embed,
                        view=PaymentMethodView(
                            customer_id=customer_id,
                            channel_id=ticket_channel_id,
                            submitted=True,
                        ),
                        allowed_mentions=discord.AllowedMentions(users=True, roles=False, everyone=False),
                    )
                except discord.HTTPException:
                    pass

        data.pop("payment_message_id", None)
        data.pop("payment_channel_id", None)
        data.pop("accepted_pending_pay_at", None)

    remember_order_data(ticket_channel_id, data)
    save_bot_data()


async def send_acceptance_payment_panel_if_ready(view, interaction: discord.Interaction, state) -> None:
    try:
        from shared.order_acceptance import ACCEPTED_PENDING_PAY
    except Exception:
        ACCEPTED_PENDING_PAY = "accepted_pending_pay"

    if str(getattr(state, "status", "")) != ACCEPTED_PENDING_PAY:
        return

    guild = interaction.guild
    if guild is None:
        return

    ticket_channel = guild.get_channel(view.source_channel_id)
    if not isinstance(ticket_channel, discord.TextChannel):
        return

    data = SELF_SERVICE_ORDER_SELECTIONS.setdefault(view.source_channel_id, {})

    if _to_int(data.get("payment_message_id")) is not None:
        return

    amount = _to_int(data.get("amount"), 0) or _to_int(data.get("total_amount"), 0) or 0
    quantity = _to_int(data.get("quantity"), view.quantity) or view.quantity
    category_label = str(data.get("category_label") or view.category_label)
    item = str(data.get("item") or view.item)
    companion_preference = data.get("companion_preference") or view.companion_preference
    accepted_staff_display_text = _acceptance_staff_display_text(guild, state)

    if accepted_staff_display_text:
        data["accepted_staff_display_text"] = accepted_staff_display_text
    else:
        data.pop("accepted_staff_display_text", None)

    if str(data.get("payment_method") or "") == "待付款":
        data.pop("payment_method", None)

    payment_embed = build_payment_method_embed(
        customer_id=view.customer_id,
        category_label=category_label,
        item=item,
        quantity=quantity,
        companion_preference=companion_preference,
        amount=amount,
        receiver_text=accepted_staff_display_text,
    )

    payment_message = await ticket_channel.send(
        content=f"<@{view.customer_id}> 接單人數已滿，請選擇付款方式。",
        embed=payment_embed,
        view=PaymentMethodView(
            customer_id=view.customer_id,
            channel_id=view.source_channel_id,
        ),
        allowed_mentions=discord.AllowedMentions(users=True, roles=False, everyone=False),
    )

    data["status"] = ACCEPTED_PENDING_PAY
    data["payment_channel_id"] = ticket_channel.id
    data["payment_message_id"] = payment_message.id
    data["accepted_pending_pay_at"] = get_taipei_now_iso()

    remember_order_data(view.source_channel_id, data)
    save_bot_data()

    await send_order_log(
        guild,
        title="接單人數已滿｜開放付款",
        fields=[
            ("顧客", f"<@{view.customer_id}>", True),
            ("訂單", f"{category_label}｜{item} x{quantity}", False),
            ("接單進度", f"{state.accepted_count}/{state.required_staff_count}", True),
            ("票口", ticket_channel.mention, False),
        ],
        color=discord.Color.gold(),
    )


def _build_receiver_text_from_claim_data(claim_data: dict) -> str | None:
    receiver_ids = sorted(
        set(claim_data.get("companion", set()))
        | set(claim_data.get("booster", set()))
    )

    if not receiver_ids:
        return None

    return "、".join(f"<@{user_id}>" for user_id in receiver_ids)
