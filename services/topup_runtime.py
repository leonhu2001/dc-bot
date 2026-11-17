from __future__ import annotations

import asyncio
import traceback

import discord

import services.rewards as rewards
from core.discord_settings import (
    CUSTOMER_SERVICE_REVIEW_CHANNEL_ID,
    CUSTOMER_SERVICE_ROLE_ID,
)
from core.vip_levels import (
    VIP_TOPUP_REBATE_POLICY_LEGACY,
    get_topup_rebate_percent,
)
from services.legacy_topup_bridge import install_legacy_wallet_add_bridge
from services.cs_review_presentation import (
    REVIEW_ACTION_LABEL, review_embed_payload, review_notification_text,
)
from services.topup_notifications import (
    ensure_topup_notification_columns,
    list_review_notifications_to_update,
    list_unnotified_pending_reviews,
    mark_review_notification_updated,
    mark_review_notified,
)
from services.topups import (
    calculate_topup_preview,
    ensure_topup_tables,
    get_pending_credit_topups,
    mark_topup_completed,
    mark_topup_processing,
    reset_topup_credit_error,
    topup_payment_method_label,
    topup_payment_reference_label,
)
from services.vip_progress_repair import (
    calculate_member_topup_preview,
    repair_all_legacy_vip_progress,
    repair_vip_progress_data,
)
from services.vip_review_runtime import process_vip_review_tick
from services.wallet_refund_runtime import process_pending_wallet_refunds
from services.wallet_service import adjust_wallet_balance, find_wallet_transaction, get_wallet_balance

TOPUP_REVIEW_CHANNEL_ID = CUSTOMER_SERVICE_REVIEW_CHANNEL_ID
TOPUP_REVIEW_URL = "https://mowanentertainment.com/admin/payment-reviews?status=pending"


async def _sync_member_vip_benefits(
    guild: discord.Guild | None,
    customer_id: int,
    data: dict,
) -> None:
    if guild is None:
        return
    member = await rewards.fetch_member_safely(guild, customer_id)
    if member is not None:
        await rewards.ensure_reward_member_benefits(guild, member, data)


async def _repair_stuck_vip_members(bot: discord.Client) -> None:
    repaired = repair_all_legacy_vip_progress()
    if not repaired:
        print("[vip-repair] no stuck VIP progress found", flush=True)
        return

    guilds = list(getattr(bot, "guilds", []) or [])
    guild = guilds[0] if guilds else None

    for item in repaired:
        customer_id = int(item["user_id"])
        data = rewards.get_customer_reward_data(customer_id)
        try:
            await _sync_member_vip_benefits(guild, customer_id, data)
        except Exception:
            print(
                f"[vip-repair] role sync failed user={customer_id}\n{traceback.format_exc()}",
                flush=True,
            )

    if rewards._SAVE_BOT_DATA is not None:
        rewards._SAVE_BOT_DATA()

    for item in repaired:
        print(
            "[vip-repair] repaired "
            f"user={item['user_id']} {item['old_level']} -> {item['new_level']} "
            f"total={item['total_spent']}",
            flush=True,
        )

    print(f"[vip-repair] repaired members: {len(repaired)}", flush=True)


_TOPUP_REVIEW_STATUS_LABELS = {
    "pending_review": "待客服審核",
    "approved_pending_credit": "已核准，待入帳",
    "crediting": "入帳處理中",
    "completed": "已完成",
    "rejected": "已駁回",
    "cancelled": "已取消",
}


def _topup_review_embed(row: dict) -> discord.Embed:
    """The same customer-service card for pending and updated top-ups."""
    status = str(row.get("status") or "pending_review").strip()
    customer_id = str(row.get("customer_discord_id") or "").strip()
    customer_name = str(row.get("customer_display_name") or "").strip()
    applicant = customer_name or customer_id or "未知"
    if customer_name and customer_id:
        applicant += f"\n\`{customer_id}\`"
    topup_no = str(row.get("topup_no") or f"TOPUP-{row.get('id')}")
    payment_method = str(row.get("payment_method") or "bank_transfer").strip()
    payment_reference = str(row.get("payment_reference") or row.get("bank_last5") or "—")
    source = str(row.get("source") or "").strip()
    source_label = {
        "web": "網站", "discord": "Discord", "discord_staff": "客服指令",
    }.get(source, source or "未知")
    fields = [
        ("付款方式", topup_payment_method_label(payment_method), True),
        (topup_payment_reference_label(payment_method), payment_reference, False),
        ("來源", source_label, True),
    ]
    note = str(row.get("payment_note") or "").strip()
    if note:
        fields.append(("付款備註", note, False))

    if status in {"approved_pending_credit", "crediting", "completed"}:
        reviewer = (
            str(row.get("approved_by_display_name") or "").strip()
            or str(row.get("approved_by_discord_id") or "").strip()
            or "未知客服"
        )
        fields.append(("審核人員", reviewer, True))
        description = "客服已核准，入帳狀態請以後台紀錄為準。"
    elif status == "rejected":
        reviewer = str(row.get("rejected_by_discord_id") or "").strip() or "未知客服"
        fields.append(("處理人員", reviewer, True))
        if row.get("rejected_at"):
            fields.append(("處理時間", row["rejected_at"], True))
        if row.get("rejected_reason"):
            fields.append(("駁回原因", row["rejected_reason"], False))
        description = "儲值審核已駁回，不會進行入帳。"
    elif status == "cancelled":
        description = "儲值申請已取消，不再等待客服審核。"
    else:
        description = "老闆已送出付款資料，請核對款項後到網站後台審核。"

    return discord.Embed.from_dict(review_embed_payload(
        category="儲值",
        status=status,
        status_label=_TOPUP_REVIEW_STATUS_LABELS.get(status, status),
        description=description,
        reference=topup_no,
        applicant=applicant,
        amount=int(row.get("amount") or 0),
        fields=fields,
    ))


async def _notify_one_pending_review(bot: discord.Client, row: dict) -> None:
    channel = bot.get_channel(TOPUP_REVIEW_CHANNEL_ID)
    if channel is None:
        try:
            channel = await bot.fetch_channel(TOPUP_REVIEW_CHANNEL_ID)
        except Exception:
            channel = None
    if channel is None or not hasattr(channel, "send"):
        raise RuntimeError(f"找不到儲值審核通知頻道 {TOPUP_REVIEW_CHANNEL_ID}")

    topup_no = str(row.get("topup_no") or f"TOPUP-{row.get('id')}")
    view = discord.ui.View(timeout=None)
    view.add_item(discord.ui.Button(
        label=REVIEW_ACTION_LABEL, style=discord.ButtonStyle.link, url=TOPUP_REVIEW_URL,
    ))
    message = await channel.send(
        content=f"<@&{CUSTOMER_SERVICE_ROLE_ID}> {review_notification_text('儲值', reference=topup_no)}",
        embed=_topup_review_embed(row),
        view=view,
        allowed_mentions=discord.AllowedMentions(everyone=False, users=False, roles=True),
    )
    mark_review_notified(int(row["id"]), message.id)
    print(f"[topup] review notification sent: {topup_no}", flush=True)


async def _notify_pending_reviews(bot: discord.Client) -> None:
    rows = list_unnotified_pending_reviews(limit=20)
    for row in rows:
        try:
            await _notify_one_pending_review(bot, row)
        except Exception:
            print(
                f"[topup] review notification failed id={row.get('id')}\n{traceback.format_exc()}",
                flush=True,
            )


async def _sync_one_review_notification(bot: discord.Client, row: dict) -> None:
    channel = bot.get_channel(TOPUP_REVIEW_CHANNEL_ID)
    if channel is None:
        try:
            channel = await bot.fetch_channel(TOPUP_REVIEW_CHANNEL_ID)
        except Exception:
            channel = None

    if channel is None or not hasattr(channel, "fetch_message"):
        raise RuntimeError(f"找不到儲值審核通知頻道 {TOPUP_REVIEW_CHANNEL_ID}")

    message_id = str(row.get("review_notification_message_id") or "").strip()
    if not message_id:
        mark_review_notification_updated(int(row["id"]))
        return

    try:
        message = await channel.fetch_message(int(message_id))
    except discord.NotFound:
        mark_review_notification_updated(int(row["id"]))
        return

    topup_no = str(row.get("topup_no") or f"TOPUP-{row.get('id')}")
    status = str(row.get("status") or "").strip()
    embed = _topup_review_embed(row)
    content = f"📋 儲值審核狀態已更新｜{topup_no}"

    await message.edit(
        content=content,
        embed=embed,
        view=None,
        allowed_mentions=discord.AllowedMentions.none(),
    )
    mark_review_notification_updated(int(row["id"]))
    print(f"[topup] review notification updated: {topup_no} -> {status}", flush=True)


async def _sync_review_notifications(bot: discord.Client) -> None:
    rows = list_review_notifications_to_update(limit=20)
    for row in rows:
        try:
            await _sync_one_review_notification(bot, row)
        except Exception:
            print(
                f"[topup] review notification update failed id={row.get('id')}\n{traceback.format_exc()}",
                flush=True,
            )


async def _process_one_topup(bot: discord.Client, row: dict) -> None:
    topup_id = int(row["id"])
    if not mark_topup_processing(topup_id):
        return

    customer_id = int(str(row["customer_discord_id"]))
    amount = int(row["amount"] or 0)
    topup_no = str(row["topup_no"])
    policy_version = str(row.get("policy_version") or VIP_TOPUP_REBATE_POLICY_LEGACY)
    is_legacy_policy = policy_version == VIP_TOPUP_REBATE_POLICY_LEGACY
    bonus_tx_type = "topup_bonus_legacy" if is_legacy_policy else "topup_bonus"
    operator_id = str(row.get("approved_by_discord_id") or "") or None
    operator_name = str(row.get("approved_by_display_name") or "").strip() or None

    try:
        data = rewards.get_customer_reward_data(customer_id)
        repair_vip_progress_data(data)
        old_level = rewards.get_effective_member_level(data)

        reward_key = f"topup:{topup_no}"
        reward_keys = data.setdefault("manual_purchase_keys", [])
        if not isinstance(reward_keys, list):
            reward_keys = []
            data["manual_purchase_keys"] = reward_keys

        already_applied = reward_key in reward_keys

        if already_applied:
            before_total = max(0, int(data.get("total_spent", 0) or 0) - amount)
            current_level = rewards.get_effective_member_level(data)
            preview = calculate_topup_preview(
                before_total,
                amount,
                policy_version=policy_version,
            )
            preview["vip_level_after"] = str(
                current_level.get("name") or preview["vip_level_after"]
            )
            preview["rebate_percent"] = get_topup_rebate_percent(
                preview["vip_level_after"],
                policy_version=policy_version,
            )
            preview["rebate_amount"] = amount * int(preview["rebate_percent"]) // 100
            preview["credited_amount"] = amount + int(preview["rebate_amount"])
        else:
            preview = calculate_member_topup_preview(
                data,
                amount,
                policy_version=policy_version,
            )

        principal_tx = find_wallet_transaction(
            customer_id=customer_id,
            order_no=topup_no,
            tx_type="topup",
        )
        if principal_tx is None:
            principal_tx = adjust_wallet_balance(
                customer_id=customer_id,
                amount=amount,
                tx_type="topup",
                operator_discord_id=operator_id,
                operator_display_name=operator_name,
                order_no=topup_no,
                note=f"儲值本金 {topup_no}",
            )

        bonus_amount = int(preview["rebate_amount"] or 0)
        bonus_tx = None
        if bonus_amount > 0:
            bonus_tx = find_wallet_transaction(
                customer_id=customer_id,
                order_no=topup_no,
                tx_type=bonus_tx_type,
            )
            if bonus_tx is None:
                bonus_tx = adjust_wallet_balance(
                    customer_id=customer_id,
                    amount=bonus_amount,
                    tx_type=bonus_tx_type,
                    operator_discord_id=operator_id,
                    operator_display_name=operator_name,
                    order_no=topup_no,
                    note=f"{preview['vip_level_after']} 儲值回饋 {preview['rebate_percent']}%",
                )

        if reward_key not in reward_keys:
            points_before = rewards.get_current_reward_points(data)

            data["total_spent"] = int(data.get("total_spent", 0) or 0) + amount
            reward_keys.append(reward_key)
            data["manual_purchase_keys"] = reward_keys[-500:]

            base_points_after = rewards.calculate_reward_points(int(data["total_spent"]))
            data["point_adjustment"] = int(points_before) - int(base_points_after)
            data["points"] = int(points_before)

            rewards.sync_vip_level_to_cumulative_if_higher(data)
            repair_vip_progress_data(data)

            guilds = list(getattr(bot, "guilds", []) or [])
            guild = guilds[0] if guilds else None
            await _sync_member_vip_benefits(guild, customer_id, data)

            if rewards._SAVE_BOT_DATA is not None:
                rewards._SAVE_BOT_DATA()

        new_level = rewards.get_effective_member_level(data)
        if new_level.get("threshold", 0) < old_level.get("threshold", 0):
            raise RuntimeError("VIP 等級計算異常：儲值後等級不應下降。")

        preview = dict(preview)
        preview["vip_level_after"] = str(new_level.get("name") or preview["vip_level_after"])
        preview["vip_total_after"] = int(data.get("total_spent", preview["vip_total_after"]) or 0)

        mark_topup_completed(
            topup_id,
            preview=preview,
            wallet_transaction_id=int(principal_tx["id"]),
            bonus_transaction_id=int(bonus_tx["id"]) if bonus_tx else None,
        )

        user = bot.get_user(customer_id)
        if user is None:
            try:
                user = await bot.fetch_user(customer_id)
            except Exception:
                user = None
        if user is not None:
            try:
                balance = get_wallet_balance(customer_id)
                upgraded = int(new_level.get("threshold", 0) or 0) > int(old_level.get("threshold", 0) or 0)
                text = (
                    f"✅ 儲值完成｜`{topup_no}`\n"
                    f"儲值本金：**{amount:,}T**\n"
                    f"VIP 等級：**{new_level['name']}**\n"
                    f"儲值回饋：**{preview['rebate_percent']}%（+{bonus_amount:,}T）**\n"
                    f"本次實得：**{int(preview['credited_amount']):,}T**\n"
                    f"目前錢包餘額：**{balance:,}T**"
                )
                if upgraded:
                    text += f"\n\n🎉 恭喜升級為「**{new_level['name']}**」！"
                await user.send(text)
            except Exception:
                pass

    except Exception:
        reset_topup_credit_error(topup_id)
        print(f"[topup] credit failed id={topup_id}\n{traceback.format_exc()}", flush=True)


async def topup_credit_worker(bot: discord.Client) -> None:
    await bot.wait_until_ready()
    await _repair_stuck_vip_members(bot)

    while not bot.is_closed():
        try:
            await _notify_pending_reviews(bot)
            await _sync_review_notifications(bot)
            await process_vip_review_tick(bot)
            await process_pending_wallet_refunds(bot)
            rows = get_pending_credit_topups(limit=20)
            for row in rows:
                await _process_one_topup(bot, row)
        except Exception:
            print(f"[topup] worker error\n{traceback.format_exc()}", flush=True)
        await asyncio.sleep(4)


def ensure_topup_credit_worker_started(bot: discord.Client) -> None:
    ensure_topup_tables()
    ensure_topup_notification_columns()
    install_legacy_wallet_add_bridge(bot)
    if getattr(bot, "_topup_credit_worker_started", False):
        return
    bot._topup_credit_worker_started = True
    bot.loop.create_task(topup_credit_worker(bot))
