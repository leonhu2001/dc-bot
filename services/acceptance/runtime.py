from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any, Mapping

import discord


_CONFIGURED = False


def configure_acceptance_runtime(namespace: Mapping[str, Any]) -> None:
    """Bind bot-owned runtime dependencies without importing bot.py.

    This adapter keeps the extracted acceptance runtime import-safe while the
    remaining legacy bot globals are split in later refactors.
    """
    global _CONFIGURED

    for name, value in namespace.items():
        if name.startswith("__"):
            continue
        if name == "configure_acceptance_runtime":
            continue
        globals()[name] = value

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
    data["amount_text"] = _format_plain_amount(amount) if "_format_plain_amount" in globals() else str(amount)

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




async def repair_pending_acceptance_dispatch_panels_once(
    guild: discord.Guild,
    *,
    limit: int = 100,
) -> int:
    """依 canonical acceptance 狀態修復等待接單中的 Discord panel。"""
    import sqlite3

    db_path = Path(__file__).parent / "web_dashboard.db"
    conn = sqlite3.connect(db_path, timeout=15)
    conn.row_factory = sqlite3.Row

    try:
        rows = conn.execute(
            """
            SELECT id
            FROM web_orders
            WHERE status IN ('waiting_acceptance', 'accepted_pending_pay')
            ORDER BY id DESC
            LIMIT ?
            """,
            (int(limit),),
        ).fetchall()
    finally:
        conn.close()

    repaired = 0

    for row in rows:
        order_id = int(row["id"])

        try:
            await refresh_acceptance_dispatch_from_web_order(
                guild,
                order_id,
            )
            repaired += 1
        except Exception as exc:
            print(
                f"[acceptance-sync] startup reconcile failed "
                f"order_id={order_id}: {type(exc).__name__}: {exc}",
                flush=True,
            )

    return repaired


async def process_acceptance_sync_events_once() -> None:
    import json
    from datetime import datetime

    from sqlalchemy import select, update

    from shared.db import SessionLocal
    from shared.models import SyncEvent, SyncEventStatus, SyncEventType, WebOrder

    guild = bot.get_guild(GUILD_ID)

    if guild is None:
        return

    async def _resolve_member(worker_id: int | None):
        if worker_id is None:
            return None

        member = guild.get_member(worker_id)
        if member is not None:
            return member

        try:
            fetched_member = await guild.fetch_member(worker_id)
            return (
                fetched_member
                if isinstance(fetched_member, discord.Member)
                else None
            )
        except (
            discord.NotFound,
            discord.Forbidden,
            discord.HTTPException,
        ):
            return None

    db = SessionLocal()

    try:
        events = list(
            db.scalars(
                select(SyncEvent)
                .where(SyncEvent.status == SyncEventStatus.PENDING.value)
                .where(SyncEvent.event_type.in_([
                    SyncEventType.ORDER_CLAIMED.value,
                    SyncEventType.ORDER_UNCLAIMED.value,
                ]))
                .order_by(SyncEvent.created_at.asc())
                .limit(10)
            ).all()
        )

        for event in events:
            try:
                payload = json.loads(event.payload_json or "{}")
            except Exception:
                payload = {}

            is_prepay_acceptance = bool(payload.get("prepay_acceptance"))
            is_admin_worker_change = payload.get("reason") in {
                "admin_added_worker",
                "admin_removed_worker",
            }

            # Claim/unclaim events have one owner: this worker. Claim the row
            # conditionally so a second Bot instance cannot process the same event.
            claimed = db.execute(
                update(SyncEvent)
                .where(SyncEvent.id == int(event.id))
                .where(SyncEvent.status == SyncEventStatus.PENDING.value)
                .values(
                    status=SyncEventStatus.PROCESSING.value,
                    retry_count=int(event.retry_count or 0) + 1,
                    processed_at=datetime.utcnow(),
                )
            )
            db.commit()

            if claimed.rowcount != 1:
                continue

            if not is_prepay_acceptance and not is_admin_worker_change:
                # Legacy claim events already completed in their original Discord
                # flow. Mark them consumed instead of leaving them pending forever.
                event.status = SyncEventStatus.DONE.value
                event.error_message = None
                event.processed_at = datetime.utcnow()
                db.commit()
                continue

            try:
                order = db.get(WebOrder, int(event.order_id))
                ticket_channel_id = (
                    _to_int(order.ticket_channel_id)
                    if order is not None
                    else None
                )

                if is_prepay_acceptance:
                    await refresh_acceptance_dispatch_from_web_order(
                        guild,
                        int(event.order_id),
                    )
                elif is_admin_worker_change:
                    if order is None:
                        raise RuntimeError(
                            f"web order not found: {event.order_id}"
                        )

                    await _refresh_existing_web_sync_dispatch(
                        {
                            "order_id": int(event.order_id),
                            "dispatch_channel_id": order.dispatch_channel_id,
                            "dispatch_message_id": order.dispatch_message_id,
                        }
                    )

                worker_id = _to_int(payload.get("worker_discord_id"))

                if worker_id is not None and ticket_channel_id is not None:
                    member = await _resolve_member(worker_id)

                    if member is not None:
                        if event.event_type == SyncEventType.ORDER_CLAIMED.value:
                            await grant_order_ticket_access(
                                guild,
                                ticket_channel_id,
                                member,
                            )
                        elif event.event_type == SyncEventType.ORDER_UNCLAIMED.value:
                            await revoke_order_ticket_access(
                                guild,
                                ticket_channel_id,
                                member,
                            )

                event.status = SyncEventStatus.DONE.value
                event.error_message = None
                event.processed_at = datetime.utcnow()
                db.commit()
            except Exception as exc:
                event.status = SyncEventStatus.FAILED.value
                event.error_message = f"{type(exc).__name__}: {exc}"
                event.processed_at = datetime.utcnow()
                db.commit()
                print(f"[acceptance-sync] 處理網站接單事件失敗 event_id={event.id}: {exc}")
    finally:
        db.close()


async def acceptance_sync_event_worker() -> None:
    await bot.wait_until_ready()
    print("[acceptance-sync] worker loop running", flush=True)

    while not bot.is_closed():
        try:
            await process_acceptance_sync_events_once()
        except Exception as exc:
            print(f"[acceptance-sync] 背景同步失敗：{exc}")

        await asyncio.sleep(5)

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



async def restore_acceptance_payment_panel_for_order(
    guild: discord.Guild,
    order_id: int,
    *,
    reason: str = "manual",
) -> tuple[bool, str]:
    """補送或重掛付款前接單流程的付款 panel。

    只處理 accepted_pending_pay，避免影響 active / stored / closed。
    """
    import sqlite3

    try:
        from shared.order_acceptance import ACCEPTED_PENDING_PAY, get_acceptance_state
    except Exception:
        ACCEPTED_PENDING_PAY = "accepted_pending_pay"
        get_acceptance_state = None

    db_path = Path(__file__).parent / "web_dashboard.db"
    conn = sqlite3.connect(db_path, timeout=15)
    conn.row_factory = sqlite3.Row

    try:
        row = conn.execute(
            """
            SELECT *
            FROM web_orders
            WHERE id = ?
            LIMIT 1
            """,
            (int(order_id),),
        ).fetchone()

        if row is None:
            return False, f"找不到 WEB-{order_id}。"

        row_keys = set(row.keys())
        current_status = str(row["status"] or "").lower()

        state = None
        state_status = current_status
        accepted_count = None
        required_count = None

        if get_acceptance_state is not None:
            try:
                state = get_acceptance_state(int(order_id))
                state_status = str(getattr(state, "status", current_status) or current_status).lower()
                accepted_count = getattr(state, "accepted_count", None)
                required_count = getattr(state, "required_staff_count", None)
            except Exception:
                state = None

        if state_status != ACCEPTED_PENDING_PAY and current_status != ACCEPTED_PENDING_PAY:
            return False, f"WEB-{order_id} 目前不是等待付款狀態，status={current_status}，acceptance_status={state_status}。"

        ticket_channel_id = _to_int(row["ticket_channel_id"])
        if ticket_channel_id is None:
            return False, f"WEB-{order_id} 沒有 ticket_channel_id。"

        ticket_channel = guild.get_channel(ticket_channel_id)
        if not isinstance(ticket_channel, discord.TextChannel):
            return False, f"WEB-{order_id} 找不到票口頻道：{ticket_channel_id}。"

        customer_id = _to_int(row["customer_discord_id"])
        if customer_id is None:
            return False, f"WEB-{order_id} 沒有 customer_discord_id。"

        amount = 0
        for amount_key in ("customer_pay_amount", "amount", "total_amount"):
            if amount_key in row_keys:
                amount = _to_int(row[amount_key], 0) or 0
                if amount:
                    break

        quantity = _to_int(row["quantity"], 1) or 1
        category_label = str(row["category"] or "訂單")
        item = str(row["item"] or "未紀錄")

        data = SELF_SERVICE_ORDER_SELECTIONS.setdefault(ticket_channel_id, {})
        data["status"] = ACCEPTED_PENDING_PAY
        data["customer_id"] = customer_id
        data["category"] = data.get("category") or category_label
        data["category_label"] = data.get("category_label") or category_label
        data["item"] = data.get("item") or item
        data["quantity"] = _to_int(data.get("quantity"), quantity) or quantity
        data["amount"] = _to_int(data.get("amount"), amount) or amount
        data["total_amount"] = _to_int(data.get("total_amount"), amount) or amount

        if "dispatch_channel_id" in row_keys and row["dispatch_channel_id"]:
            data["dispatch_channel_id"] = _to_int(row["dispatch_channel_id"])
        if "dispatch_message_id" in row_keys and row["dispatch_message_id"]:
            data["dispatch_message_id"] = _to_int(row["dispatch_message_id"])

        if str(data.get("payment_method") or "") == "待付款":
            data.pop("payment_method", None)

        selected_payment_method = str(data.get("payment_method") or "").strip() or None
        accepted_staff_display_text = (
            _acceptance_staff_display_text(guild, state)
            if state is not None
            else str(data.get("accepted_staff_display_text") or "").strip() or None
        )

        if accepted_staff_display_text:
            data["accepted_staff_display_text"] = accepted_staff_display_text

        payment_embed = build_payment_method_embed(
            customer_id=customer_id,
            category_label=str(data.get("category_label") or category_label),
            item=str(data.get("item") or item),
            quantity=_to_int(data.get("quantity"), quantity) or quantity,
            payment_method=selected_payment_method,
            companion_preference=data.get("companion_preference"),
            amount=_to_int(data.get("amount"), amount) or amount,
            receiver_text=accepted_staff_display_text,
        )

        payment_view = PaymentMethodView(
            customer_id=customer_id,
            channel_id=ticket_channel_id,
            selected_method=selected_payment_method,
        )

        existing_message_id = _to_int(data.get("payment_message_id"))
        existing_channel_id = _to_int(data.get("payment_channel_id"), ticket_channel_id) or ticket_channel_id
        existing_channel = guild.get_channel(existing_channel_id)
        existing_message = None

        if isinstance(existing_channel, discord.TextChannel) and existing_message_id is not None:
            try:
                existing_message = await existing_channel.fetch_message(existing_message_id)
            except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                existing_message = None

        content = f"<@{customer_id}> 接單人數已滿，請選擇付款方式。"

        if existing_message is not None:
            try:
                await existing_message.edit(
                    content=content,
                    embed=payment_embed,
                    view=payment_view,
                    allowed_mentions=discord.AllowedMentions(users=True, roles=False, everyone=False),
                )
                data["payment_channel_id"] = existing_message.channel.id
                data["payment_message_id"] = existing_message.id
                action = "已重新掛回付款 panel"
            except discord.HTTPException:
                existing_message = None

        if existing_message is None:
            payment_message = await ticket_channel.send(
                content=content,
                embed=payment_embed,
                view=payment_view,
                allowed_mentions=discord.AllowedMentions(users=True, roles=False, everyone=False),
            )
            data["payment_channel_id"] = ticket_channel.id
            data["payment_message_id"] = payment_message.id
            action = "已補送新的付款 panel"

        data["accepted_pending_pay_at"] = data.get("accepted_pending_pay_at") or get_taipei_now_iso()
        remember_order_data(ticket_channel_id, data)
        save_bot_data()

        if current_status != ACCEPTED_PENDING_PAY:
            from shared.order_state import (
                WAITING_ACCEPTANCE,
                transition_order_state,
            )

            transition_order_state(
                order_id=int(order_id),
                target_status=ACCEPTED_PENDING_PAY,
                source="payment_panel_repair",
                reason=f"付款 panel 修復：{reason}",
                expected_statuses={
                    WAITING_ACCEPTANCE,
                    ACCEPTED_PENDING_PAY,
                },
            )

        progress_text = ""
        if accepted_count is not None and required_count is not None:
            progress_text = f"｜接單進度 {accepted_count}/{required_count}"

        try:
            await send_order_log(
                guild,
                title="付款 panel 已修復",
                fields=[
                    ("訂單", f"WEB-{order_id}", True),
                    ("顧客", f"<@{customer_id}>", True),
                    ("狀態", f"{action}{progress_text}", False),
                    ("票口", ticket_channel.mention, False),
                    ("來源", reason, True),
                ],
                color=discord.Color.gold(),
            )
        except Exception:
            pass

        return True, f"WEB-{order_id} {action}。"

    finally:
        conn.close()


async def repair_pending_acceptance_payment_panels_once(
    guild: discord.Guild,
    *,
    reason: str = "startup",
    limit: int = 30,
) -> int:
    import sqlite3

    db_path = Path(__file__).parent / "web_dashboard.db"
    conn = sqlite3.connect(db_path, timeout=15)
    conn.row_factory = sqlite3.Row

    try:
        rows = conn.execute(
            """
            SELECT id
            FROM web_orders
            WHERE status IN ('accepted_pending_pay', 'waiting_acceptance')
            ORDER BY id DESC
            LIMIT ?
            """,
            (int(limit),),
        ).fetchall()
    finally:
        conn.close()

    repaired = 0

    for row in rows:
        try:
            ok, message = await restore_acceptance_payment_panel_for_order(
                guild,
                int(row["id"]),
                reason=reason,
            )
            if ok:
                repaired += 1
                print(f"[acceptance-repair] {message}", flush=True)
        except Exception as exc:
            print(f"[acceptance-repair] failed order_id={row['id']}: {type(exc).__name__}: {exc}", flush=True)

    return repaired


async def repair_pending_acceptance_ticket_access_once(
    guild: discord.Guild,
    *,
    limit: int = 100,
) -> int:
    """Bot 啟動時把目前接單者的票口權限補齊。"""
    import sqlite3

    from shared.order_acceptance import get_acceptance_state

    db_path = Path(__file__).parent / "web_dashboard.db"
    conn = sqlite3.connect(db_path, timeout=15)
    conn.row_factory = sqlite3.Row

    try:
        rows = conn.execute(
            """
            SELECT id, ticket_channel_id
            FROM web_orders
            WHERE status IN ('waiting_acceptance', 'accepted_pending_pay')
              AND ticket_channel_id IS NOT NULL
              AND TRIM(ticket_channel_id) <> ''
            ORDER BY id DESC
            LIMIT ?
            """,
            (int(limit),),
        ).fetchall()
    finally:
        conn.close()

    restored = 0

    for row in rows:
        order_id = int(row["id"])
        ticket_channel_id = _to_int(row["ticket_channel_id"])

        if ticket_channel_id is None:
            continue

        try:
            state = get_acceptance_state(order_id)
            accepted_count = int(getattr(state, "accepted_count", 0) or 0)

            if accepted_count <= 0:
                continue

            await sync_acceptance_ticket_access_from_state(
                guild,
                ticket_channel_id,
                state,
            )
            restored += accepted_count
        except Exception as exc:
            print(
                f"[ticket-access] startup repair failed "
                f"order_id={order_id}: {type(exc).__name__}: {exc}",
                flush=True,
            )

    return restored


def _build_receiver_text_from_claim_data(claim_data: dict) -> str | None:
    receiver_ids = sorted(
        set(claim_data.get("companion", set()))
        | set(claim_data.get("booster", set()))
    )

    if not receiver_ids:
        return None

    return "、".join(f"<@{user_id}>" for user_id in receiver_ids)
