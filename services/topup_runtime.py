from __future__ import annotations

import asyncio
import traceback

import discord

import services.rewards as rewards
from core.discord_settings import (
    CUSTOMER_SERVICE_REVIEW_CHANNEL_ID,
    CUSTOMER_SERVICE_ROLE_ID,
)
from services.legacy_topup_bridge import install_legacy_wallet_add_bridge
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
                f"[vip-repair] role sync failed user={customer_id}\n"
                f"{traceback.format_exc()}",
                flush=True,
            )

    if rewards._SAVE_BOT_DATA is not None:
        rewards._SAVE_BOT_DATA()

    for item in repaired:
        print(
            "[vip-repair] repaired "
            f"user={item['user_id']} "
            f"{item['old_level']} -> {item['new_level']} "
            f"total={item['total_spent']}",
            flush=True,
        )

    print(f"[vip-repair] repaired members: {len(repaired)}", flush=True)


async def _notify_one_pending_review(bot: discord.Client, row: dict) -> None:
    channel = bot.get_channel(TOPUP_REVIEW_CHANNEL_ID)
    if channel is None:
        try:
            channel = await bot.fetch_channel(TOPUP_REVIEW_CHANNEL_ID)
        except Exception:
            channel = None

    if channel is None or not hasattr(channel, "send"):
        raise RuntimeError(f"找不到儲值審核通知頻道 {TOPUP_REVIEW_CHANNEL_ID}")

    customer_id = str(row.get("customer_discord_id") or "").strip()
    customer_name = str(row.get("customer_display_name") or "").strip() or customer_id or "未知"
    topup_no = str(row.get("topup_no") or f"TOPUP-{row.get('id')}")
    amount = int(row.get("amount") or 0)
    payment_method = str(row.get("payment_method") or "bank_transfer").strip()
    payment_method_label = topup_payment_method_label(payment_method)
    payment_reference_label = topup_payment_reference_label(payment_method)
    payment_reference = str(
        row.get("payment_reference")
        or row.get("bank_last5")
        or "—"
    )
    source = str(row.get("source") or "").strip()
    source_label = {
        "web": "網站",
        "discord": "Discord",
        "discord_staff": "客服指令",
    }.get(source, source or "未知")

    embed = discord.Embed(
        title="💰 新儲值待審核",
        description="老闆已送出付款資料，請客服確認款項後前往後台審核。",
        color=discord.Color.gold(),
    )
    embed.add_field(name="儲值單", value=f"`{topup_no}`", inline=False)
    embed.add_field(name="老闆", value=f"{customer_name}\n`{customer_id}`", inline=True)
    embed.add_field(name="儲值金額", value=f"{amount:,}T", inline=True)
    embed.add_field(name="付款方式", value=payment_method_label, inline=True)
    embed.add_field(name=payment_reference_label, value=payment_reference, inline=False)
    embed.add_field(name="來源", value=source_label, inline=True)

    note = str(row.get("payment_note") or "").strip()
    if note:
        embed.add_field(name="付款備註", value=note[:1000], inline=False)

    view = discord.ui.View(timeout=None)
    view.add_item(
        discord.ui.Button(
            label="前往審核",
            style=discord.ButtonStyle.link,
            url=TOPUP_REVIEW_URL,
        )
    )

    message = await channel.send(
        content=f"<@&{CUSTOMER_SERVICE_ROLE_ID}> 有新的儲值付款待審核。",
        embed=embed,
        view=view,
        allowed_mentions=discord.AllowedMentions(
            everyone=False,
            users=False,
            roles=True,
        ),
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
                f"[topup] review notification failed id={row.get('id')}\n"
                f"{traceback.format_exc()}",
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
        # 通知已被人工刪除，不要讓 worker 每 4 秒重試同一筆。
        mark_review_notification_updated(int(row["id"]))
        return

    customer_id = str(row.get("customer_discord_id") or "").strip()
    customer_name = str(row.get("customer_display_name") or "").strip() or customer_id or "未知"
    topup_no = str(row.get("topup_no") or f"TOPUP-{row.get('id')}")
    amount = int(row.get("amount") or 0)
    payment_method = str(row.get("payment_method") or "bank_transfer").strip()
    payment_method_label = topup_payment_method_label(payment_method)
    payment_reference_label = topup_payment_reference_label(payment_method)
    payment_reference = str(
        row.get("payment_reference")
        or row.get("bank_last5")
        or "—"
    )
    source = str(row.get("source") or "").strip()
    source_label = {
        "web": "網站",
        "discord": "Discord",
        "discord_staff": "客服指令",
    }.get(source, source or "未知")
    status = str(row.get("status") or "").strip()

    approved_statuses = {"approved_pending_credit", "crediting", "completed"}
    if status in approved_statuses:
        reviewer_id = str(row.get("approved_by_discord_id") or "").strip()
        reviewer_name = str(row.get("approved_by_display_name") or "").strip()
        reviewer_display = reviewer_name or (f"Discord ID {reviewer_id}" if reviewer_id else "未知客服")
        reviewer_value = reviewer_display
        if reviewer_id:
            reviewer_value += f"\n`{reviewer_id}`"

        embed = discord.Embed(
            title="✅ 儲值已審核",
            description="此筆儲值已由客服審核通過。",
            color=discord.Color.green(),
        )
        content = f"✅ 儲值付款已審核｜審核人：{reviewer_display}"
        embed.add_field(name="審核人員", value=reviewer_value, inline=True)

    elif status == "rejected":
        reviewer_id = str(row.get("rejected_by_discord_id") or "").strip()
        reviewer_display = f"Discord ID {reviewer_id}" if reviewer_id else "未知客服"
        embed = discord.Embed(
            title="❌ 儲值審核未通過",
            description="此筆儲值已由客服駁回，不會進行入帳。",
            color=discord.Color.red(),
        )
        content = f"❌ 儲值付款審核未通過｜處理人：{reviewer_display}"
        embed.add_field(name="處理人員", value=reviewer_display, inline=True)
        rejected_at = str(row.get("rejected_at") or "").strip()
        if rejected_at:
            embed.add_field(name="處理時間", value=rejected_at, inline=True)
        reason = str(row.get("rejected_reason") or "").strip()
        if reason:
            embed.add_field(name="駁回原因", value=reason[:1000], inline=False)

    else:
        embed = discord.Embed(
            title="⚪ 儲值審核已取消",
            description="此筆儲值已取消，不再等待客服審核。",
            color=discord.Color.light_grey(),
        )
        content = "⚪ 儲值付款審核已取消。"

    embed.add_field(name="儲值單", value=f"`{topup_no}`", inline=False)
    embed.add_field(name="老闆", value=f"{customer_name}\n`{customer_id}`", inline=True)
    embed.add_field(name="儲值金額", value=f"{amount:,}T", inline=True)
    embed.add_field(name="付款方式", value=payment_method_label, inline=True)
    embed.add_field(name=payment_reference_label, value=payment_reference, inline=False)
    embed.add_field(name="來源", value=source_label, inline=True)

    note = str(row.get("payment_note") or "").strip()
    if note:
        embed.add_field(name="付款備註", value=note[:1000], inline=False)

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
                f"[topup] review notification update failed id={row.get('id')}\n"
                f"{traceback.format_exc()}",
                flush=True,
            )


async def _process_one_topup(bot: discord.Client, row: dict) -> None:
    topup_id = int(row["id"])
    if not mark_topup_processing(topup_id):
        return

    customer_id = int(str(row["customer_discord_id"]))
    amount = int(row["amount"] or 0)
    topup_no = str(row["topup_no"])
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
            # 上一次處理若已寫入會員資料但尚未標記儲值完成，
            # 以目前真正有效 VIP 作為重試時的返利基準，避免重複推進。
            before_total = max(
                0,
                int(data.get("total_spent", 0) or 0) - amount,
            )
            current_level = rewards.get_effective_member_level(data)
            preview = calculate_topup_preview(before_total, amount)
            preview["vip_level_after"] = str(
                current_level.get("name")
                or preview["vip_level_after"]
            )
            from core.vip_levels import get_topup_rebate_percent
            preview["rebate_percent"] = get_topup_rebate_percent(
                preview["vip_level_after"]
            )
            preview["rebate_amount"] = (
                amount
                * int(preview["rebate_percent"])
                // 100
            )
            preview["credited_amount"] = (
                amount
                + int(preview["rebate_amount"])
            )
        else:
            preview = calculate_member_topup_preview(
                data,
                amount,
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
                tx_type="topup_bonus",
            )
            if bonus_tx is None:
                bonus_tx = adjust_wallet_balance(
                    customer_id=customer_id,
                    amount=bonus_amount,
                    tx_type="topup_bonus",
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

            # 儲值本金只計 VIP，不額外產生消費點數。
            base_points_after = rewards.calculate_reward_points(int(data["total_spent"]))
            data["point_adjustment"] = int(points_before) - int(base_points_after)
            data["points"] = int(points_before)

            # 先沿用原本降級後重新累積的規則，再修復沒有降級紀錄卻卡階的舊資料。
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

        # 寫入儲值單的 VIP 顯示以真正完成後的會員等級為準。
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