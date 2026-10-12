from __future__ import annotations

from typing import Callable

import discord

from services.order_credential_runtime import (
    _order_requires_credentials,
    ensure_order_credential_request,
    revoke_order_credential_messages,
)
from services.smart_dispatch import create_smart_dispatch_plan
from services.ticket_identity import get_order_customer_id_from_channel


_CONFIGURED = False


def configure_order_storage_runtime(
    *,
    dispatch_channel_id: int,
    dispatch_claim_view,
    order_category_labels: dict,
    order_claims: dict,
    self_service_order_selections: dict,
    to_int: Callable,
    self_service_order_embed_builder: Callable,
    taipei_now_iso: Callable,
    remember_claim: Callable,
    remember_order: Callable,
    save_data: Callable,
    acceptance_state_applier: Callable,
    self_service_rule_getter: Callable,
    claim_row_deleter: Callable,
    initial_dispatch_preparer: Callable,
    initial_dispatch_alert_sender: Callable,
    specified_staff_dm_sender: Callable,
    specified_dm_result_setter: Callable,
    web_order_status_syncer: Callable,
) -> None:
    """Bind explicit runtime collaborators for store/lock/resume flows."""
    global _CONFIGURED
    global DISPATCH_CHANNEL_ID, DispatchClaimView, ORDER_CATEGORY_LABELS, ORDER_CLAIMS
    global SELF_SERVICE_ORDER_SELECTIONS, _to_int, build_self_service_order_embed
    global get_taipei_now_iso, remember_claim_data, remember_order_data, save_bot_data
    global _apply_acceptance_state_to_claim_data, _get_rule_from_self_service_data
    global delete_claim_row_from_db, prepare_initial_smart_dispatch
    global send_initial_smart_dispatch_alert, send_specified_staff_dispatch_dms
    global set_specified_dm_results, sync_web_order_status_from_bot

    DISPATCH_CHANNEL_ID = int(dispatch_channel_id)
    DispatchClaimView = dispatch_claim_view
    ORDER_CATEGORY_LABELS = order_category_labels
    ORDER_CLAIMS = order_claims
    SELF_SERVICE_ORDER_SELECTIONS = self_service_order_selections
    _to_int = to_int
    build_self_service_order_embed = self_service_order_embed_builder
    get_taipei_now_iso = taipei_now_iso
    remember_claim_data = remember_claim
    remember_order_data = remember_order
    save_bot_data = save_data
    _apply_acceptance_state_to_claim_data = acceptance_state_applier
    _get_rule_from_self_service_data = self_service_rule_getter
    delete_claim_row_from_db = claim_row_deleter
    prepare_initial_smart_dispatch = initial_dispatch_preparer
    send_initial_smart_dispatch_alert = initial_dispatch_alert_sender
    send_specified_staff_dispatch_dms = specified_staff_dm_sender
    set_specified_dm_results = specified_dm_result_setter
    sync_web_order_status_from_bot = web_order_status_syncer
    _CONFIGURED = True


async def lock_dispatch_claim_panel(guild: discord.Guild, order_channel_id: int):
    """客服結單後，鎖定派單頻道對應的陪玩 / 打手接單面板。

    這版會同時處理「恢復訂單後重新發派單面板」的情況：
    如果 orders 裡記到的是舊 dispatch_message_id，會再從 ORDER_CLAIMS 裡找同一張票口的派單訊息，
    並把找到的派單面板全部鎖定，避免最新那則恢復訂單面板還能繼續被按。
    """
    data = SELF_SERVICE_ORDER_SELECTIONS.get(order_channel_id, {})
    dispatch_channel_id = data.get("dispatch_channel_id", DISPATCH_CHANNEL_ID)

    source_channel = guild.get_channel(order_channel_id)

    if source_channel is None or not isinstance(source_channel, discord.TextChannel):
        return

    if _order_requires_credentials(data):
        try:
            from services.order_credentials import get_order_id_by_ticket_channel
            credential_order_id = _to_int(data.get("web_order_id")) or get_order_id_by_ticket_channel(order_channel_id)
            if credential_order_id is not None:
                await revoke_order_credential_messages(
                    credential_order_id,
                    reason="closed",
                    ticket_channel=source_channel,
                    notify_customer=True,
                )
        except Exception as exc:
            print(f"[credentials] 結單撤回失敗 channel_id={order_channel_id}: {exc}")

    dispatch_channel = guild.get_channel(dispatch_channel_id)

    # 優先鎖 orders 目前記錄的派單訊息，同時補抓所有 claims 裡來源票口相同的派單訊息。
    candidate_message_ids: list[int] = []

    first_dispatch_message_id = _to_int(data.get("dispatch_message_id"))
    if first_dispatch_message_id is not None:
        candidate_message_ids.append(first_dispatch_message_id)

    for message_id, claim in list(ORDER_CLAIMS.items()):
        claim_source_channel_id = _to_int(claim.get("source_channel_id"))
        if claim_source_channel_id == order_channel_id:
            parsed_message_id = _to_int(message_id)
            if parsed_message_id is not None and parsed_message_id not in candidate_message_ids:
                candidate_message_ids.append(parsed_message_id)

    if not candidate_message_ids:
        return

    customer_id = data.get("customer_id")
    category = data.get("category")
    item = data.get("item", "未紀錄")
    quantity = _to_int(data.get("quantity"), 1) or 1
    payment_method = data.get("payment_method", "未紀錄")
    companion_preference = data.get("companion_preference")
    category_label = ORDER_CATEGORY_LABELS.get(category, category or data.get("category_label") or "未紀錄")
    customer_mention = f"<@{customer_id}>" if customer_id is not None else "未紀錄"

    data["closed"] = True
    data["status"] = "closed"
    data["closed_at"] = get_taipei_now_iso()
    data["quantity"] = quantity
    data["dispatch_channel_id"] = dispatch_channel_id

    locked_any = False
    newest_existing_message_id: int | None = None

    for dispatch_message_id in candidate_message_ids:
        claim_data = ORDER_CLAIMS.setdefault(
            dispatch_message_id,
            {
                "companion": set(),
                "booster": set(),
                "locked": False,
            }
        )

        # 先把 canonical claim 狀態終結並移除持久化資料。
        # Discord 訊息即使已被刪除／無權限讀取，也不能讓 bot.db 留著 active claim。
        claim_data["customer_id"] = claim_data.get("customer_id") or customer_id
        claim_data["category_label"] = claim_data.get("category_label") or category_label
        claim_data["item"] = claim_data.get("item") or item
        claim_data["quantity"] = _to_int(claim_data.get("quantity"), quantity) or quantity
        claim_data["payment_method"] = claim_data.get("payment_method") or payment_method
        claim_data["source_channel_id"] = order_channel_id
        claim_data["companion_preference"] = claim_data.get("companion_preference") or companion_preference
        claim_data["dispatch_channel_id"] = dispatch_channel_id
        claim_data["locked"] = True
        claim_data["status"] = "closed"
        remember_claim_data(dispatch_message_id, claim_data)

        if not isinstance(dispatch_channel, discord.TextChannel):
            continue

        try:
            message = await dispatch_channel.fetch_message(dispatch_message_id)
        except (discord.NotFound, discord.Forbidden, discord.HTTPException):
            continue

        companion_ids = sorted(claim_data.get("companion", set()))
        booster_ids = sorted(claim_data.get("booster", set()))
        lines = []

        if companion_ids:
            lines.extend(f"<@{user_id}>" for user_id in companion_ids)

        if booster_ids:
            lines.extend(f"<@{user_id}>" for user_id in booster_ids)

        receiver_text = "、".join(dict.fromkeys(lines)) if lines else None

        embed = build_self_service_order_embed(
            customer_mention=customer_mention,
            category_label=str(claim_data.get("category_label") or category_label),
            item=str(claim_data.get("item") or item),
            quantity=_to_int(claim_data.get("quantity"), quantity) or quantity,
            payment_method=str(claim_data.get("payment_method") or payment_method),
            source_channel=source_channel,
            companion_preference=claim_data.get("companion_preference") or companion_preference,
            receiver_text=receiver_text
        )
        embed.add_field(
            name="狀態",
            value="已結單，接單面板已鎖定",
            inline=False
        )

        try:
            await message.edit(
                embed=embed,
                view=DispatchClaimView(
                    customer_id=_to_int(claim_data.get("customer_id"), _to_int(customer_id, 0) or 0) or 0,
                    category_label=str(claim_data.get("category_label") or category_label),
                    item=str(claim_data.get("item") or item),
                    quantity=_to_int(claim_data.get("quantity"), quantity) or quantity,
                    payment_method=str(claim_data.get("payment_method") or payment_method),
                    source_channel_id=order_channel_id,
                    companion_preference=claim_data.get("companion_preference") or companion_preference,
                    locked=True,
                    status="closed"
                ),
                allowed_mentions=discord.AllowedMentions(
                    users=True,
                    roles=False,
                    everyone=False
                )
            )
            locked_any = True
            newest_existing_message_id = dispatch_message_id
        except (discord.NotFound, discord.Forbidden, discord.HTTPException):
            continue

    # 用實際成功鎖定的最新派單訊息覆蓋，避免之後再找到舊面板。
    if newest_existing_message_id is not None:
        data["dispatch_message_id"] = newest_existing_message_id

    # 即使 Discord panel 已不存在，訂單與 claim 的 final 狀態仍必須落地。
    remember_order_data(order_channel_id, data)
    save_bot_data()


async def store_dispatch_claim_panel(
    guild: discord.Guild,
    order_channel: discord.TextChannel,
    staff_member: discord.Member,
    reason: str,
    expected_time: str | None = None,
    note: str | None = None,
):
    """將訂單標記為存單，鎖定派單接單面板但保留票口。"""
    data = SELF_SERVICE_ORDER_SELECTIONS.get(order_channel.id, {})
    dispatch_message_id = data.get("dispatch_message_id")
    dispatch_channel_id = data.get("dispatch_channel_id", DISPATCH_CHANNEL_ID)

    if dispatch_message_id is None:
        raise ValueError("找不到這張訂單對應的派單訊息，請確認顧客是否已完成付款方式並送出派單。")

    dispatch_channel = guild.get_channel(dispatch_channel_id)

    if dispatch_channel is None or not isinstance(dispatch_channel, discord.TextChannel):
        raise ValueError("找不到派單頻道，請確認 DISPATCH_CHANNEL_ID 是否正確。")

    try:
        message = await dispatch_channel.fetch_message(dispatch_message_id)
    except discord.NotFound as exc:
        raise ValueError("找不到派單訊息，可能已被刪除。") from exc
    except discord.Forbidden as exc:
        raise ValueError("Bot 權限不足，無法讀取派單訊息。") from exc
    except discord.HTTPException as exc:
        raise ValueError(f"讀取派單訊息失敗：{exc}") from exc

    customer_id = data.get("customer_id") or get_order_customer_id_from_channel(order_channel)
    category = data.get("category")
    item = data.get("item", "未紀錄")
    quantity = _to_int(data.get("quantity"), 1) or 1
    payment_method = data.get("payment_method", "未紀錄")
    companion_preference = data.get("companion_preference")
    category_label = ORDER_CATEGORY_LABELS.get(category, category or data.get("category_label") or "未紀錄")
    customer_mention = f"<@{customer_id}>" if customer_id is not None else "未紀錄"

    claim_data = ORDER_CLAIMS.setdefault(
        dispatch_message_id,
        {
            "companion": set(),
            "booster": set(),
            "locked": False,
        }
    )
    claim_data["customer_id"] = customer_id
    claim_data["category_label"] = category_label
    claim_data["item"] = item
    claim_data["quantity"] = quantity
    claim_data["payment_method"] = payment_method
    claim_data["source_channel_id"] = order_channel.id
    claim_data["companion_preference"] = companion_preference
    claim_data["dispatch_channel_id"] = dispatch_channel_id
    claim_data["locked"] = True
    claim_data["status"] = "stored"
    claim_data["stored_at"] = get_taipei_now_iso()
    claim_data["stored_by"] = staff_member.id
    claim_data["stored_reason"] = reason
    claim_data["stored_expected_time"] = expected_time or None
    claim_data["stored_note"] = note or None

    data["customer_id"] = customer_id
    data["quantity"] = quantity
    data["dispatch_message_id"] = dispatch_message_id
    data["dispatch_channel_id"] = dispatch_channel_id
    data["closed"] = False
    data["status"] = "stored"
    data["stored_at"] = claim_data["stored_at"]
    data["stored_by"] = staff_member.id
    data["stored_reason"] = reason
    data["stored_expected_time"] = expected_time or None
    data["stored_note"] = note or None
    data["stored_reminders_sent"] = []

    remember_order_data(order_channel.id, data)

    try:
        from shared.order_acceptance import (
            find_acceptance_order_id_by_dispatch_message_id,
            pause_acceptance_order,
        )

        acceptance_order_id = find_acceptance_order_id_by_dispatch_message_id(dispatch_message_id)
        if acceptance_order_id is not None:
            pause_acceptance_order(acceptance_order_id, source="discord_store")
            print(f"[acceptance] stored order_id={acceptance_order_id} dispatch_message_id={dispatch_message_id}")
    except Exception as exc:
        print(f"[acceptance] 存單同步付款前接單狀態失敗 dispatch_message_id={dispatch_message_id}: {exc}")

    sync_web_order_status_from_bot(
        ticket_channel_id=order_channel.id,
        status="stored",
        dispatch_message_id=dispatch_message_id,
        note="由 DC bot 存單同步。",
    )

    if _order_requires_credentials(data):
        try:
            from services.order_credentials import get_order_id_by_ticket_channel
            credential_order_id = _to_int(data.get("web_order_id")) or get_order_id_by_ticket_channel(order_channel.id)
            if credential_order_id is not None:
                await revoke_order_credential_messages(
                    credential_order_id,
                    reason="stored",
                    ticket_channel=order_channel,
                    notify_customer=True,
                )
        except Exception as exc:
            print(f"[credentials] 存單撤回失敗 channel_id={order_channel.id}: {exc}")

    remember_claim_data(dispatch_message_id, claim_data)

    companion_ids = sorted(claim_data.get("companion", set()))
    booster_ids = sorted(claim_data.get("booster", set()))
    lines = []

    if companion_ids:
        lines.extend(f"<@{user_id}>" for user_id in companion_ids)

    if booster_ids:
        lines.extend(f"<@{user_id}>" for user_id in booster_ids)

    receiver_text = "、".join(dict.fromkeys(lines)) if lines else None

    embed = build_self_service_order_embed(
        customer_mention=customer_mention,
        category_label=category_label,
        item=item,
        quantity=quantity,
        payment_method=payment_method,
        source_channel=order_channel,
        companion_preference=companion_preference,
        receiver_text=receiver_text
    )
    embed.add_field(
        name="狀態",
        value=(
            "已存單，接單面板已鎖定\n"
            f"存單原因：{reason}\n"
            f"預計恢復：{expected_time or '未填寫'}"
        ),
        inline=False
    )

    if note:
        embed.add_field(
            name="存單備註",
            value=note,
            inline=False
        )

    await message.edit(
        embed=embed,
        view=DispatchClaimView(
            customer_id=customer_id or 0,
            category_label=category_label,
            item=item,
            quantity=quantity,
            payment_method=payment_method,
            source_channel_id=order_channel.id,
            companion_preference=companion_preference,
            locked=True,
            status="stored"
        ),
        allowed_mentions=discord.AllowedMentions(
            users=True,
            roles=False,
            everyone=False
        )
    )


async def resume_stored_order(
    guild: discord.Guild,
    order_channel: discord.TextChannel,
    staff_member: discord.Member,
):
    """恢復已存單的訂單，保留原本接單人員，重新發派單面板，並清掉舊派單訊息。"""
    data = SELF_SERVICE_ORDER_SELECTIONS.get(order_channel.id, {})
    old_dispatch_message_id = _to_int(data.get("dispatch_message_id"))
    dispatch_channel_id = _to_int(data.get("dispatch_channel_id"), DISPATCH_CHANNEL_ID) or DISPATCH_CHANNEL_ID

    # 收集這張票口所有舊派單訊息，避免同一張存單恢復後派單頻道殘留舊面板。
    old_dispatch_message_ids: set[int] = set()

    if old_dispatch_message_id:
        old_dispatch_message_ids.add(old_dispatch_message_id)

    for message_id, claim in list(ORDER_CLAIMS.items()):
        if not isinstance(claim, dict):
            continue

        claim_source_channel_id = _to_int(claim.get("source_channel_id"))

        if claim_source_channel_id == order_channel.id:
            parsed_message_id = _to_int(message_id)
            if parsed_message_id:
                old_dispatch_message_ids.add(parsed_message_id)

    if not old_dispatch_message_ids:
        raise ValueError("找不到這張訂單對應的派單訊息，無法恢復。")

    dispatch_channel = guild.get_channel(dispatch_channel_id)

    if dispatch_channel is None or not isinstance(dispatch_channel, discord.TextChannel):
        raise ValueError("找不到派單頻道，請確認 DISPATCH_CHANNEL_ID 是否正確。")

    # 優先取原本 dispatch_message_id 的 claim；沒有的話，找同票口任一 claim。
    claim_data = ORDER_CLAIMS.get(old_dispatch_message_id) if old_dispatch_message_id else None

    if not claim_data:
        for message_id in old_dispatch_message_ids:
            possible_claim = ORDER_CLAIMS.get(message_id)
            if isinstance(possible_claim, dict):
                claim_data = possible_claim
                break

    if not claim_data:
        raise ValueError("找不到已保存的接單資料，請重新派單。")

    customer_id = claim_data.get("customer_id") or data.get("customer_id") or get_order_customer_id_from_channel(order_channel)
    category_label = claim_data.get("category_label") or ORDER_CATEGORY_LABELS.get(data.get("category"), data.get("category") or "未紀錄")
    item = claim_data.get("item") or data.get("item", "未紀錄")
    quantity = _to_int(claim_data.get("quantity"), _to_int(data.get("quantity"), 1)) or 1
    payment_method = claim_data.get("payment_method") or data.get("payment_method", "未紀錄")
    companion_preference = claim_data.get("companion_preference") or data.get("companion_preference")
    customer_mention = f"<@{customer_id}>" if customer_id is not None else "未紀錄"

    resume_status = "active"
    acceptance_state = None
    acceptance_order_id = None

    try:
        from shared.order_acceptance import (
            find_acceptance_order_id_by_dispatch_message_id,
            resume_acceptance_order,
        )

        for candidate_message_id in [old_dispatch_message_id, *old_dispatch_message_ids]:
            parsed_candidate_id = _to_int(candidate_message_id)
            if parsed_candidate_id is None:
                continue

            acceptance_order_id = find_acceptance_order_id_by_dispatch_message_id(parsed_candidate_id)
            if acceptance_order_id is not None:
                break

        if acceptance_order_id is not None:
            acceptance_state = resume_acceptance_order(acceptance_order_id, source="discord_resume")
            resume_status = str(acceptance_state.status or "waiting_acceptance")
            _apply_acceptance_state_to_claim_data(claim_data, acceptance_state)
            print(
                f"[acceptance] resumed order_id={acceptance_order_id} "
                f"status={resume_status} old_dispatch={old_dispatch_message_id}"
            )
    except Exception as exc:
        raise ValueError(f"恢復付款前接單狀態失敗：{exc}") from exc

    claim_data["locked"] = False
    claim_data["status"] = resume_status
    claim_data["customer_id"] = customer_id
    claim_data["category_label"] = str(category_label)
    claim_data["item"] = str(item)
    claim_data["quantity"] = quantity
    claim_data["payment_method"] = str(payment_method)
    claim_data["source_channel_id"] = order_channel.id
    claim_data["companion_preference"] = companion_preference
    claim_data["dispatch_channel_id"] = dispatch_channel.id

    # 存單相關資料保留在資料中當紀錄；舊單回 active，新流程回 waiting_acceptance / accepted_pending_pay。
    data["closed"] = False
    data["status"] = resume_status
    data["quantity"] = quantity
    data["dispatch_channel_id"] = dispatch_channel.id
    data["stored_at"] = None
    data["stored_by"] = None
    data["stored_reason"] = None
    data["stored_expected_time"] = None
    data["stored_note"] = None

    if resume_status == "active" and _order_requires_credentials(data):
        try:
            await ensure_order_credential_request(
                channel=order_channel,
                customer_id=_to_int(customer_id, 0) or 0,
                data=data,
            )
            if customer_id is not None:
                await order_channel.send(
                    f"<@{customer_id}> 🔐 訂單已恢復。先前登入資料私訊已撤回，請重新提交本單登入資料。",
                    allowed_mentions=discord.AllowedMentions(users=True, roles=False, everyone=False),
                )
        except Exception as exc:
            print(f"[credentials] 恢復訂單登入資料提示失敗 channel_id={order_channel.id}: {exc}")

    companion_ids = sorted(claim_data.get("companion", set()))
    booster_ids = sorted(claim_data.get("booster", set()))
    lines = []

    if companion_ids:
        lines.extend(f"<@{user_id}>" for user_id in companion_ids)

    if booster_ids:
        lines.extend(f"<@{user_id}>" for user_id in booster_ids)

    receiver_text = "、".join(dict.fromkeys(lines)) if lines else None

    embed = build_self_service_order_embed(
        customer_mention=customer_mention,
        category_label=str(category_label),
        item=str(item),
        quantity=quantity,
        payment_method=str(payment_method),
        source_channel=order_channel,
        companion_preference=companion_preference,
        receiver_text=receiver_text
    )
    embed.add_field(
        name="狀態",
        value=f"已由 {staff_member.mention} 恢復訂單，接單面板已重新發到最新位置。",
        inline=False
    )

    resume_smart_dispatch = None
    resume_allowed_role_ids: list[str] = []
    resume_required_game_role_ids: list[str] = []
    resume_specified_staff_ids = [
        str(item)
        for item in (
            data.get("specified_staff_ids")
            or claim_data.get("specified_staff_ids")
            or []
        )
        if str(item).strip()
    ]
    resume_unresolved_specified_ids = list(
        resume_specified_staff_ids
    )

    if (
        resume_status == "waiting_acceptance"
        and acceptance_state is not None
        and acceptance_order_id is not None
    ):
        try:
            from services.order_rules import (
                get_allowed_role_ids,
                get_required_game_role_ids,
            )

            resume_rule = _get_rule_from_self_service_data(
                data
            )
            resume_allowed_role_ids = get_allowed_role_ids(
                resume_rule
            )
            resume_required_game_role_ids = get_required_game_role_ids(
                resume_rule
            )
            accepted_ids = {
                str(claim.staff_discord_id)
                for claim in acceptance_state.claims
            }
            resume_unresolved_specified_ids = [
                staff_id
                for staff_id in resume_specified_staff_ids
                if staff_id not in accepted_ids
            ]
            remaining_count = max(
                1,
                int(acceptance_state.required_staff_count or 1)
                - int(acceptance_state.accepted_count or 0),
            )

            resume_smart_dispatch = prepare_initial_smart_dispatch(
                guild,
                customer_id=customer_id,
                allowed_role_ids=resume_allowed_role_ids,
                specified_staff_ids=resume_unresolved_specified_ids,
                required_staff_count=remaining_count,
                required_game_role_ids=resume_required_game_role_ids,
                excluded_staff_ids=accepted_ids,
            )
        except Exception as exc:
            print(
                f"[smart-dispatch] resume prepare failed "
                f"order_id={acceptance_order_id}: "
                f"{type(exc).__name__}: {exc}",
                flush=True,
            )

    new_message = await dispatch_channel.send(
        content=None,
        embed=embed,
        view=DispatchClaimView(
            customer_id=customer_id or 0,
            category_label=str(category_label),
            item=str(item),
            quantity=quantity,
            payment_method=str(payment_method),
            source_channel_id=order_channel.id,
            companion_preference=companion_preference,
            locked=False,
            status=resume_status
        ),
        allowed_mentions=discord.AllowedMentions(
            users=True,
            roles=resume_smart_dispatch is not None,
            everyone=False
        )
    )

    if resume_smart_dispatch is not None:
        try:
            await send_initial_smart_dispatch_alert(
                guild,
                content=resume_smart_dispatch["content"],
                dispatch_jump_url=new_message.jump_url,
            )
        except (discord.Forbidden, discord.HTTPException) as exc:
            print(f"[smart-dispatch] resume initial alert failed: {exc}", flush=True)

    # 刪除同一張票口的所有舊派單訊息，避免存單恢復後殘留不能操作的舊面板。
    for message_id in old_dispatch_message_ids:
        if message_id == new_message.id:
            continue

        try:
            old_message = await dispatch_channel.fetch_message(message_id)
        except discord.NotFound:
            old_message = None
        except (discord.Forbidden, discord.HTTPException):
            old_message = None

        if old_message is not None:
            try:
                await old_message.delete()
            except (discord.NotFound, discord.Forbidden, discord.HTTPException, TypeError):
                pass

        ORDER_CLAIMS.pop(message_id, None)
        delete_claim_row_from_db(message_id=message_id, source_channel_id=order_channel.id)

    # 把接單資料移到新的 message_id，保留原本陪玩/打手接單人員。
    ORDER_CLAIMS[new_message.id] = claim_data
    data["dispatch_message_id"] = new_message.id
    data["dispatch_channel_id"] = dispatch_channel.id

    if (
        resume_smart_dispatch is not None
        and acceptance_order_id is not None
        and acceptance_state is not None
    ):
        try:
            create_smart_dispatch_plan(
                order_id=int(acceptance_order_id),
                dispatch_channel_id=dispatch_channel.id,
                dispatch_message_id=new_message.id,
                required_staff_count=int(
                    acceptance_state.required_staff_count
                    or 1
                ),
                allowed_role_ids=resume_allowed_role_ids,
                specified_staff_ids=resume_specified_staff_ids,
                required_game_role_ids=resume_required_game_role_ids,
                ranked_candidate_ids=resume_smart_dispatch[
                    "ranked_candidate_ids"
                ],
                notified_candidate_ids=resume_smart_dispatch[
                    "initial_notified_ids"
                ],
                reset_existing=True,
            )

            if resume_unresolved_specified_ids:
                dm_sent_ids, dm_failed_ids = (
                    await send_specified_staff_dispatch_dms(
                        guild,
                        specified_staff_ids=resume_unresolved_specified_ids,
                        category_label=str(category_label),
                        item_label=str(item),
                        required_staff_count=int(
                            acceptance_state.required_staff_count
                            or 1
                        ),
                        dispatch_jump_url=new_message.jump_url,
                        allowed_role_ids=resume_allowed_role_ids,
                        required_game_role_ids=resume_required_game_role_ids,
                    )
                )
                set_specified_dm_results(
                    int(acceptance_order_id),
                    sent_ids=dm_sent_ids,
                    failed_ids=dm_failed_ids,
                )
        except Exception as exc:
            print(
                f"[smart-dispatch] resume lifecycle failed "
                f"order_id={acceptance_order_id}: "
                f"{type(exc).__name__}: {exc}",
                flush=True,
            )

    remember_order_data(order_channel.id, data)
    sync_web_order_status_from_bot(
        ticket_channel_id=order_channel.id,
        status=resume_status,
        dispatch_message_id=data.get("dispatch_message_id"),
        note="由 DC bot 恢復存單同步。",
    )
    remember_claim_data(new_message.id, claim_data)
    save_bot_data()
