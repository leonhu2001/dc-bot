from __future__ import annotations

from typing import Callable

import discord

from services.payment_methods import WALLET_PAYMENT_METHOD

from services.order_credential_runtime import (
    _order_requires_credentials,
    ensure_order_credential_request,
)
from services.order_point_redemption import (
    precheck_order_point_benefit_for_payment,
    redeem_order_point_benefit_on_payment,
)
from services.self_service_financials import (
    _format_plain_amount,
    add_self_service_financial_breakdown_fields,
)


_CONFIGURED = False


def configure_order_payment_runtime(
    *,
    dispatch_channel_id: int,
    dispatch_claim_view,
    order_category_labels: dict,
    order_claims: dict,
    payment_method_view,
    self_service_order_selections: dict,
    staff_order_operation_view,
    receiver_text_builder: Callable,
    to_int: Callable,
    customer_reward_adder: Callable,
    wallet_adjuster: Callable,
    payment_method_embed_builder: Callable,
    self_service_order_embed_builder: Callable,
    payment_receipt_ensurer: Callable,
    fetch_member: Callable,
    amount_formatter: Callable,
    taipei_now_iso: Callable,
    remember_claim: Callable,
    remember_order: Callable,
    ticket_channel_renamer: Callable,
    save_data: Callable,
    order_log_sender: Callable,
    wallet_log_sender: Callable,
) -> None:
    """Bind explicit bot/runtime APIs used by payment finalization."""
    global _CONFIGURED
    global DISPATCH_CHANNEL_ID, DispatchClaimView, ORDER_CATEGORY_LABELS, ORDER_CLAIMS
    global PaymentMethodView, SELF_SERVICE_ORDER_SELECTIONS, StaffOrderOperationView
    global _build_receiver_text_from_claim_data, _to_int
    global add_customer_reward_from_order, adjust_customer_wallet_balance
    global build_payment_method_embed, build_self_service_order_embed
    global ensure_payment_submit_receipt, fetch_member_safely, format_t_amount
    global get_taipei_now_iso, remember_claim_data, remember_order_data
    global rename_ticket_channel, save_bot_data, send_order_log, send_wallet_log

    DISPATCH_CHANNEL_ID = int(dispatch_channel_id)
    DispatchClaimView = dispatch_claim_view
    ORDER_CATEGORY_LABELS = order_category_labels
    ORDER_CLAIMS = order_claims
    PaymentMethodView = payment_method_view
    SELF_SERVICE_ORDER_SELECTIONS = self_service_order_selections
    StaffOrderOperationView = staff_order_operation_view
    _build_receiver_text_from_claim_data = receiver_text_builder
    _to_int = to_int
    add_customer_reward_from_order = customer_reward_adder
    adjust_customer_wallet_balance = wallet_adjuster
    build_payment_method_embed = payment_method_embed_builder
    build_self_service_order_embed = self_service_order_embed_builder
    ensure_payment_submit_receipt = payment_receipt_ensurer
    fetch_member_safely = fetch_member
    format_t_amount = amount_formatter
    get_taipei_now_iso = taipei_now_iso
    remember_claim_data = remember_claim
    remember_order_data = remember_order
    rename_ticket_channel = ticket_channel_renamer
    save_bot_data = save_data
    send_order_log = order_log_sender
    send_wallet_log = wallet_log_sender
    _CONFIGURED = True


async def finalize_accepted_pending_payment(
    *,
    interaction: discord.Interaction,
    customer_id: int,
    channel_id: int,
) -> None:
    guild = interaction.guild

    if guild is None:
        await interaction.response.send_message("這個功能只能在伺服器內使用。", ephemeral=True)
        return

    if not isinstance(interaction.channel, discord.TextChannel):
        await interaction.response.send_message("無法確認目前票口頻道。", ephemeral=True)
        return

    data = SELF_SERVICE_ORDER_SELECTIONS.get(channel_id, {})

    if str(data.get("status") or "").lower() != "accepted_pending_pay":
        await interaction.response.send_message("這張單目前不是等待付款狀態。", ephemeral=True)
        return

    if data.get("payment_finalizing"):
        await interaction.response.send_message("這張單正在確認付款，請稍等，不要重複送出。", ephemeral=True)
        return

    payment_method = data.get("payment_method")

    if not payment_method or str(payment_method) in {"待付款", "未紀錄"}:
        await interaction.response.send_message("請先選擇付款方式，再按送出。", ephemeral=True)
        return

    amount = _to_int(data.get("amount"), 0) or _to_int(data.get("total_amount"), 0) or 0

    if amount < 0:
        await interaction.response.send_message("訂單金額異常，請通知客服確認。", ephemeral=True)
        return

    dispatch_message_id = _to_int(data.get("dispatch_message_id"))
    dispatch_channel_id = _to_int(data.get("dispatch_channel_id"), DISPATCH_CHANNEL_ID) or DISPATCH_CHANNEL_ID

    if dispatch_message_id is None:
        await interaction.response.send_message("找不到派單訊息，請通知客服確認。", ephemeral=True)
        return

    external_review_methods = {"街口", "轉帳"}

    if str(payment_method) in external_review_methods and not data.get("payment_review_approved"):
        if data.get("payment_review_pending"):
            await interaction.response.send_message(
                "這筆付款已送出網站審核，請不要重複送出。\n"
                "請將付款截圖直接傳在此票口，方便客服核對。",
                ephemeral=True,
            )
            return

        web_order_id = _to_int(data.get("web_order_id"))

        if web_order_id is None:
            try:
                from shared.order_acceptance import find_acceptance_order_id_by_dispatch_message_id
                web_order_id = find_acceptance_order_id_by_dispatch_message_id(dispatch_message_id)
            except Exception:
                web_order_id = None

        if web_order_id is None:
            await interaction.response.send_message(
                "找不到這張訂單的網站資料，暫時無法送出付款審核，請通知客服。",
                ephemeral=True,
            )
            return

        customer_member_for_review = guild.get_member(customer_id)
        customer_display_name = (
            getattr(customer_member_for_review, "display_name", None)
            or getattr(customer_member_for_review, "global_name", None)
            or getattr(customer_member_for_review, "name", None)
            or str(data.get("customer_display_name") or "").strip()
            or "未知顧客"
        )

        try:
            from services.payment_reviews import (
                create_payment_review,
                set_payment_review_notification,
            )

            review = create_payment_review(
                source_type="order",
                source_id=web_order_id,
                ticket_channel_id=channel_id,
                customer_discord_id=customer_id,
                customer_display_name=customer_display_name,
                amount=amount,
                payment_method=str(payment_method),
            )
        except ValueError as exc:
            await interaction.response.send_message(str(exc), ephemeral=True)
            return

        data["web_order_id"] = int(web_order_id)
        data["payment_review_id"] = int(review["id"])
        data["payment_review_no"] = str(review.get("review_no") or "")
        data["payment_review_pending"] = True
        data["payment_review_submitted_at"] = get_taipei_now_iso()
        data["payment_review_submitted_by"] = int(getattr(interaction.user, "id", 0) or 0)
        remember_order_data(channel_id, data)
        save_bot_data()

        if not interaction.response.is_done():
            await interaction.response.defer(ephemeral=True)

        category_label = str(
            data.get("category_label")
            or ORDER_CATEGORY_LABELS.get(
                data.get("category"),
                data.get("category") or "未紀錄",
            )
        )
        item = str(data.get("item") or "未紀錄")
        quantity = _to_int(data.get("quantity"), 1) or 1
        companion_preference = data.get("companion_preference")

        pending_embed = build_payment_method_embed(
            customer_id=customer_id,
            category_label=category_label,
            item=item,
            quantity=quantity,
            payment_method=str(payment_method),
            companion_preference=companion_preference,
            amount=amount,
            receiver_text=str(data.get("accepted_staff_display_text") or "").strip() or None,
        )
        pending_embed.add_field(
            name="付款狀態",
            value=(
                "已送出網站審核，等待客服確認收款。\n"
                "請將付款截圖直接傳在本票口，方便客服核對。"
            ),
            inline=False,
        )

        payment_channel_id = _to_int(
            data.get("payment_channel_id"),
            interaction.channel.id,
        ) or interaction.channel.id
        payment_message_id = _to_int(data.get("payment_message_id"))
        payment_channel = guild.get_channel(payment_channel_id)

        if isinstance(payment_channel, discord.TextChannel) and payment_message_id is not None:
            try:
                payment_message = await payment_channel.fetch_message(payment_message_id)
                await payment_message.edit(
                    embed=pending_embed,
                    view=PaymentMethodView(
                        customer_id=customer_id,
                        channel_id=channel_id,
                        submitted=True,
                        selected_method=str(payment_method),
                    ),
                    allowed_mentions=discord.AllowedMentions(
                        users=True,
                        roles=False,
                        everyone=False,
                    ),
                )
            except discord.HTTPException:
                pass

        review_notice = await interaction.channel.send(
            (
                f"<@{customer_id}> ✅ **付款資料已送出審核**\n"
                f"付款方式：**{payment_method}**｜金額：**{amount:,}T**\n\n"
                "📎 **請將轉帳／街口付款截圖直接傳在此票口**，"
                "方便客服核對後到網站完成付款審核。\n"
                "客服確認前，訂單不會正式成立。"
            ),
            allowed_mentions=discord.AllowedMentions(
                users=True,
                roles=False,
                everyone=False,
            ),
        )

        data["payment_review_notification_message_id"] = review_notice.id
        remember_order_data(channel_id, data)
        save_bot_data()

        try:
            set_payment_review_notification(int(review["id"]), review_notice.id)
        except Exception:
            pass

        await interaction.followup.send(
            "付款已送出網站審核。請記得把付款截圖貼在這個票口，等待客服確認。",
            ephemeral=True,
        )
        return

    data["payment_finalizing"] = True
    remember_order_data(channel_id, data)

    if not interaction.response.is_done():
        await interaction.response.defer(ephemeral=True)

    try:
        category_label = str(data.get("category_label") or ORDER_CATEGORY_LABELS.get(data.get("category"), data.get("category") or "未紀錄"))
        item = str(data.get("item") or "未紀錄")
        quantity = _to_int(data.get("quantity"), 1) or 1
        companion_preference = data.get("companion_preference")
        staff_note = str(data.get("staff_note") or data.get("customer_service_note") or "").strip() or None

        customer_member = guild.get_member(customer_id)
        if customer_member is None:
            try:
                customer_member = await fetch_member_safely(guild, customer_id)
            except Exception:
                customer_member = None

        order_point_benefit_result = None

        try:
            precheck_order_point_benefit_for_payment(data, customer_id)
        except ValueError as exc:
            data.pop("payment_finalizing", None)
            remember_order_data(channel_id, data)
            save_bot_data()
            message = str(exc)
            if interaction.response.is_done():
                await interaction.followup.send(message, ephemeral=True)
            else:
                await interaction.response.send_message(message, ephemeral=True)
            return

        if payment_method == WALLET_PAYMENT_METHOD:
            existing_wallet_tx_id = data.get("wallet_transaction_id")

            if not existing_wallet_tx_id:
                try:
                    wallet_tx = adjust_customer_wallet_balance(
                        customer_id=customer_id,
                        amount=-amount,
                        tx_type="payment",
                        operator=interaction.user,
                        order_channel_id=channel_id,
                        order_no=data.get("order_no") or data.get("receipt_id"),
                        note=f"訂單扣款：{item}",
                    )
                except ValueError as exc:
                    data.pop("payment_finalizing", None)
                    remember_order_data(channel_id, data)
                    await interaction.followup.send(str(exc), ephemeral=True)
                    return

                data["wallet_transaction_id"] = wallet_tx["id"]
                data["wallet_paid_amount"] = amount
                data["wallet_balance_before"] = wallet_tx["balance_before"]
                data["wallet_balance_after"] = wallet_tx["balance_after"]
                remember_order_data(channel_id, data)

                await send_wallet_log(
                    guild,
                    title="錢包訂單扣款",
                    customer=customer_member if customer_member is not None else interaction.user,
                    operator=interaction.user,
                    tx=wallet_tx,
                )

        try:
            order_point_benefit_result = await redeem_order_point_benefit_on_payment(
                interaction=interaction,
                data=data,
                customer_id=customer_id,
                channel_id=channel_id,
            )
        except ValueError as exc:
            data.pop("payment_finalizing", None)
            remember_order_data(channel_id, data)
            save_bot_data()
            message = str(exc)
            if interaction.response.is_done():
                await interaction.followup.send(message, ephemeral=True)
            else:
                await interaction.response.send_message(message, ephemeral=True)
            return

        data["amount"] = amount
        data["total_amount"] = amount
        data["amount_text"] = _format_plain_amount(amount) if "_format_plain_amount" in globals() else format_t_amount(amount)
        data["payment_submitted_at"] = get_taipei_now_iso()
        data["payment_submitted_by"] = interaction.user.id
        data["closed"] = False
        data["payment_processing"] = True
        remember_order_data(channel_id, data)

        reward_result = await add_customer_reward_from_order(
            guild=guild,
            order_channel_id=channel_id,
            customer_id=customer_id,
            amount_text=str(amount),
            notify_channel=interaction.channel,
        )

        receipt_staff_member = interaction.user
        amount_set_by = _to_int(data.get("amount_set_by"))

        if amount_set_by is not None:
            possible_staff_member = guild.get_member(amount_set_by)
            if possible_staff_member is not None:
                receipt_staff_member = possible_staff_member

        receipt_id, receipt_message = await ensure_payment_submit_receipt(
            guild=guild,
            order_channel=interaction.channel,
            customer_id=customer_id,
            customer_member=customer_member,
            staff_member=receipt_staff_member,
            category_label=category_label,
            item=item,
            quantity=quantity,
            amount=amount,
            payment_method=payment_method,
            companion_preference=companion_preference,
        )

        if receipt_id:
            data["receipt_id"] = receipt_id
            data["order_no"] = receipt_id

        if receipt_message is not None:
            data["receipt_message_id"] = receipt_message.id
            data["receipt_channel_id"] = receipt_message.channel.id

        web_order_id = _to_int(data.get("web_order_id"))

        if web_order_id is None:
            try:
                from shared.order_acceptance import find_acceptance_order_id_by_dispatch_message_id
                web_order_id = find_acceptance_order_id_by_dispatch_message_id(dispatch_message_id)
            except Exception:
                web_order_id = None

        if web_order_id is not None:
            data["web_order_id"] = int(web_order_id)
            from shared.order_acceptance import promote_acceptance_claims_to_assignments
            payout_base_amount = _to_int(data.get("payout_base_amount"), amount) or amount
            promoted_count = promote_acceptance_claims_to_assignments(
                order_id=web_order_id,
                payment_method=str(payment_method),
                amount=amount,
                payout_base_amount=payout_base_amount,
                original_amount=_to_int(data.get("original_amount"), payout_base_amount) or payout_base_amount,
                manual_discount_amount=_to_int(data.get("manual_discount_amount"), 0) or 0,
                cash_coupon_amount=_to_int(data.get("cash_coupon_amount"), 0) or 0,
                store_absorbed_amount=_to_int(data.get("store_absorbed_amount"), 0) or 0,
                customer_pay_amount=amount,
                bot_order_no=data.get("order_no") or data.get("receipt_id"),
            )
            data["promoted_assignment_count"] = promoted_count

        dispatch_channel = guild.get_channel(dispatch_channel_id)
        dispatch_url = None

        if isinstance(dispatch_channel, discord.TextChannel):
            try:
                dispatch_message = await dispatch_channel.fetch_message(dispatch_message_id)
                dispatch_url = dispatch_message.jump_url

                claim_data = ORDER_CLAIMS.setdefault(dispatch_message_id, {})
                claim_data["locked"] = True
                claim_data["status"] = "active"
                claim_data["payment_method"] = str(payment_method)
                claim_data["amount"] = amount
                claim_data["total_amount"] = amount
                claim_data["customer_id"] = customer_id
                claim_data["category_label"] = category_label
                claim_data["item"] = item
                claim_data["quantity"] = quantity
                claim_data["source_channel_id"] = channel_id
                claim_data["dispatch_channel_id"] = dispatch_channel_id

                receiver_text = _build_receiver_text_from_claim_data(claim_data)

                dispatch_embed = build_self_service_order_embed(
                    customer_mention=f"<@{customer_id}>",
                    category_label=category_label,
                    item=item,
                    quantity=quantity,
                    payment_method=str(payment_method),
                    source_channel=interaction.channel,
                    companion_preference=companion_preference,
                    receiver_text=receiver_text,
                    staff_note=staff_note,
                )
                add_self_service_financial_breakdown_fields(
                    dispatch_embed,
                    data,
                    final_label="顧客實付",
                )

                dispatch_embed.add_field(name="付款狀態", value="已付款，接單人員已確認", inline=False)

                await dispatch_message.edit(
                    embed=dispatch_embed,
                    view=DispatchClaimView(
                        customer_id=customer_id,
                        category_label=category_label,
                        item=item,
                        quantity=quantity,
                        payment_method=str(payment_method),
                        source_channel_id=channel_id,
                        companion_preference=companion_preference,
                        locked=True,
                        status="active",
                    ),
                    allowed_mentions=discord.AllowedMentions(users=True, roles=False, everyone=False),
                )

                remember_claim_data(dispatch_message_id, claim_data)
            except discord.HTTPException:
                pass

        await rename_ticket_channel(interaction.channel, item, member=customer_member)

        payment_channel_id = _to_int(data.get("payment_channel_id"), interaction.channel.id) or interaction.channel.id
        payment_message_id = _to_int(data.get("payment_message_id"))
        payment_channel = guild.get_channel(payment_channel_id)

        submitted_embed = build_payment_method_embed(
            customer_id=customer_id,
            category_label=category_label,
            item=item,
            quantity=quantity,
            payment_method=str(payment_method),
            companion_preference=companion_preference,
            amount=amount,
            receiver_text=str(data.get("accepted_staff_display_text") or "").strip() or None,
            submitted=True,
            dispatch_url=dispatch_url,
        )

        if isinstance(payment_channel, discord.TextChannel) and payment_message_id is not None:
            try:
                payment_message = await payment_channel.fetch_message(payment_message_id)
                await payment_message.edit(
                    embed=submitted_embed,
                    view=PaymentMethodView(
                        customer_id=customer_id,
                        channel_id=channel_id,
                        submitted=True,
                        selected_method=str(payment_method),
                    ),
                    allowed_mentions=discord.AllowedMentions(users=True, roles=False, everyone=False),
                )
            except discord.HTTPException:
                pass

        if _to_int(data.get("operation_panel_message_id")) is None:
            operation_embed = discord.Embed(
                title="訂單操作",
                description="請客服從下拉式清單選擇後，按下確認。",
                color=discord.Color.green(),
            )
            operation_message = await interaction.channel.send(embed=operation_embed, view=StaffOrderOperationView())
            data["operation_panel_message_id"] = operation_message.id

        data["status"] = "active"
        data["closed"] = False
        data.pop("payment_processing", None)
        data.pop("payment_finalizing", None)
        if data.get("payment_review_approved"):
            data["payment_review_pending"] = False
            data["payment_review_applied_at"] = get_taipei_now_iso()
        if data.get("payment_review_approved") and data.get("payment_review_id"):
            data["payment_review_finalized_id"] = int(data["payment_review_id"])
        remember_order_data(channel_id, data)
        save_bot_data()

        if _order_requires_credentials(data):
            try:
                await ensure_order_credential_request(
                    channel=interaction.channel,
                    customer_id=customer_id,
                    data=data,
                )
            except Exception as exc:
                print(
                    f"[credentials] request panel failed channel_id={channel_id}: "
                    f"{type(exc).__name__}: {exc}",
                    flush=True,
                )

        response_text = f"已確認付款方式：{payment_method}，訂單正式成立。"
        if _order_requires_credentials(data):
            response_text += "\n🔐 請在票口的登入資料面板填寫代肝／代解帳號資料。"
        if data.get("receipt_id"):
            response_text += f"\n交易收據已產生：{data.get('receipt_id')}"
        if order_point_benefit_result:
            response_text += f"\n\n{order_point_benefit_result}"
        if reward_result:
            response_text += f"\n\n{reward_result}"

        await interaction.followup.send(response_text, ephemeral=True)

        await send_order_log(
            guild,
            title="等待接單訂單已付款成立",
            fields=[
                ("顧客", f"<@{customer_id}>", True),
                ("訂單", f"{category_label}｜{item} x{quantity}", False),
                ("訂單總價", _format_plain_amount(amount) if "_format_plain_amount" in globals() else format_t_amount(amount), True),
                ("付款方式", str(payment_method), True),
                ("票口", interaction.channel.mention, False),
            ],
            color=discord.Color.green(),
        )

    except Exception as exc:
        data.pop("payment_processing", None)
        data.pop("payment_finalizing", None)
        remember_order_data(channel_id, data)
        save_bot_data()
        print(f"[acceptance] waiting_acceptance 付款成立失敗 channel_id={channel_id}: {exc}")
        await interaction.followup.send(f"付款成立失敗：`{type(exc).__name__}: {exc}`", ephemeral=True)
