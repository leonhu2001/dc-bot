from __future__ import annotations

import asyncio
import traceback
from types import SimpleNamespace

import discord

from services import order_payment_runtime
from services.payment_reviews import (
    PAYMENT_REVIEW_APPROVED,
    PAYMENT_REVIEW_REJECTED,
    list_payment_reviews_for_runtime,
    mark_payment_review_applied,
    mark_payment_review_apply_error,
    mark_payment_review_rejection_applied,
)
from services.worker_tips import (
    mark_worker_tip_cancelled,
    mark_worker_tip_paid,
)
from views.review import refresh_post_close_panel


def _target_bot_module():
    """Return the explicitly configured order-payment runtime adapter.

    Payment review used to scan every loaded Python module and guess which one
    happened to be bot.py.  order_payment_runtime already owns the exact
    payment dependencies we need, so reuse that configured adapter instead.
    """
    if not getattr(order_payment_runtime, "_CONFIGURED", False):
        return None
    return order_payment_runtime


def _int_or_zero(value) -> int:
    try:
        return int(str(value or "0").strip())
    except (TypeError, ValueError):
        return 0


def _validate_order_review_snapshot(
    row: dict,
    data: dict,
    *,
    customer_id: int,
) -> None:
    """Ensure an approved review still describes the order being finalized."""
    status = str(data.get("status") or "").strip().lower()
    if status != "accepted_pending_pay":
        raise RuntimeError("訂單目前不是等待付款狀態，付款審核不可套用。")

    review_id = _int_or_zero(row.get("id"))
    current_review_id = _int_or_zero(data.get("payment_review_id"))
    if current_review_id and review_id and current_review_id != review_id:
        raise RuntimeError("付款審核編號已變更，請重新確認最新一筆付款。")

    raw_amount = data.get("amount")
    if raw_amount is None or str(raw_amount).strip() == "":
        raw_amount = data.get("total_amount")
    current_amount = _int_or_zero(raw_amount)
    review_amount = _int_or_zero(row.get("amount"))
    if current_amount != review_amount:
        raise RuntimeError(
            f"付款審核金額已過期：審核 {review_amount}T，訂單目前 {current_amount}T。"
        )

    current_method = str(data.get("payment_method") or "").strip()
    review_method = str(row.get("payment_method") or "").strip()
    if current_method != review_method:
        raise RuntimeError(
            "付款方式已在審核後變更，請重新送出付款審核。"
        )

    current_order_id = _int_or_zero(data.get("web_order_id"))
    review_order_id = _int_or_zero(row.get("source_id"))
    if current_order_id and review_order_id and current_order_id != review_order_id:
        raise RuntimeError("付款審核所屬訂單已變更，請重新送出付款審核。")

    runtime_customer_id = _int_or_zero(data.get("customer_id"))
    if runtime_customer_id and runtime_customer_id != int(customer_id):
        raise RuntimeError("付款審核顧客與目前訂單顧客不一致，請重新確認。")


def _release_stale_review_runtime_lock(row: dict, data: dict, error_text: str) -> bool:
    """Release only the stale review's own pending flag so payment can be resubmitted."""
    if str(data.get("status") or "").strip().lower() != "accepted_pending_pay":
        return False

    review_id = _int_or_zero(row.get("id"))
    current_review_id = _int_or_zero(data.get("payment_review_id"))
    if current_review_id and review_id and current_review_id != review_id:
        return False

    data["payment_review_pending"] = False
    data["payment_review_approved"] = False
    data["payment_review_last_apply_error_id"] = review_id or None
    data["payment_review_apply_error"] = str(error_text or "付款審核資料已過期")
    data.pop("payment_review_id", None)
    data.pop("payment_review_no", None)
    data.pop("payment_finalizing", None)
    return True


def _rejection_still_targets_current_order_review(row: dict, data: dict) -> bool:
    """A late rejection must never clear a newer review or an active order."""
    if str(data.get("status") or "").strip().lower() != "accepted_pending_pay":
        return False

    review_id = _int_or_zero(row.get("id"))
    current_review_id = _int_or_zero(data.get("payment_review_id"))
    if current_review_id and review_id and current_review_id != review_id:
        return False

    return True


def _actor(guild: discord.Guild | None, row: dict):
    actor_id = str(row.get("approved_by_discord_id") or row.get("rejected_by_discord_id") or "").strip()
    member = None

    if guild is not None and actor_id.isdigit():
        member = guild.get_member(int(actor_id))

    if member is not None:
        return member

    actor_name = str(
        row.get("approved_by_display_name")
        or row.get("rejected_by_display_name")
        or "網站客服"
    ).strip() or "網站客服"

    actor_int = int(actor_id) if actor_id.isdigit() else 0
    return SimpleNamespace(
        id=actor_int,
        name=actor_name,
        display_name=actor_name,
        mention=(f"<@{actor_int}>" if actor_int else actor_name),
    )


class _RuntimeResponse:
    def is_done(self) -> bool:
        return True

    async def defer(self, *args, **kwargs):
        return None

    async def send_message(self, *args, **kwargs):
        return None

    async def edit_message(self, *args, **kwargs):
        return None


class _RuntimeFollowup:
    async def send(self, *args, **kwargs):
        return None


class _RuntimeInteraction:
    def __init__(self, *, guild, channel, user):
        self.guild = guild
        self.channel = channel
        self.user = user
        self.response = _RuntimeResponse()
        self.followup = _RuntimeFollowup()
        self.message = None


async def _fetch_ticket_channel(bot: discord.Client, row: dict):
    raw = str(row.get("ticket_channel_id") or "").strip()
    if not raw.isdigit():
        return None

    channel_id = int(raw)
    channel = bot.get_channel(channel_id)

    if channel is None:
        try:
            channel = await bot.fetch_channel(channel_id)
        except Exception:
            channel = None

    return channel if isinstance(channel, discord.TextChannel) else None


async def _edit_review_notification(
    channel: discord.TextChannel,
    row: dict,
    *,
    content: str,
) -> None:
    message_id = str(row.get("discord_notification_message_id") or "").strip()

    if message_id.isdigit():
        try:
            message = await channel.fetch_message(int(message_id))
            await message.edit(
                content=content,
                view=None,
                allowed_mentions=discord.AllowedMentions(
                    users=True,
                    roles=False,
                    everyone=False,
                ),
            )
            return
        except Exception:
            pass

    await channel.send(
        content,
        allowed_mentions=discord.AllowedMentions(
            users=True,
            roles=False,
            everyone=False,
        ),
    )


async def _apply_order_approval(bot: discord.Client, row: dict) -> None:
    target = _target_bot_module()
    if target is None:
        raise RuntimeError("找不到 Bot 訂單付款模組。")

    channel = await _fetch_ticket_channel(bot, row)
    if channel is None:
        raise RuntimeError("找不到原訂單票口。")

    guild = channel.guild
    customer_id = int(str(row.get("customer_discord_id") or "0"))
    if not customer_id:
        raise RuntimeError("付款審核缺少顧客 ID。")

    data = target.SELF_SERVICE_ORDER_SELECTIONS.get(channel.id)
    if not isinstance(data, dict):
        raise RuntimeError("找不到原訂單的 Discord runtime 資料。")

    try:
        _validate_order_review_snapshot(
            row,
            data,
            customer_id=customer_id,
        )
    except RuntimeError as exc:
        if _release_stale_review_runtime_lock(row, data, str(exc)):
            target.remember_order_data(channel.id, data)
            target.save_bot_data()
        raise

    data["payment_review_id"] = int(row["id"])
    data["payment_review_no"] = str(row.get("review_no") or "")
    data["payment_review_pending"] = False
    data["payment_review_approved"] = True
    data["payment_review_approved_by"] = str(row.get("approved_by_discord_id") or "")
    data["payment_review_approved_at"] = str(row.get("approved_at") or "")
    data.pop("payment_finalizing", None)

    target.remember_order_data(channel.id, data)
    target.save_bot_data()

    actor = _actor(guild, row)
    interaction = _RuntimeInteraction(
        guild=guild,
        channel=channel,
        user=actor,
    )

    await target.finalize_accepted_pending_payment(
        interaction=interaction,
        customer_id=customer_id,
        channel_id=channel.id,
    )

    data = target.SELF_SERVICE_ORDER_SELECTIONS.get(channel.id, {})
    if (
        str(data.get("status") or "").lower() != "active"
        or int(data.get("payment_review_finalized_id") or 0) != int(row["id"])
    ):
        raise RuntimeError("Bot 未完整套用付款審核結果，請查看 Bot 日誌。")

    await _edit_review_notification(
        channel,
        row,
        content=(
            f"<@{customer_id}> ✅ **付款審核已通過**\n"
            f"付款方式：**{row.get('payment_method')}**｜金額：**{int(row.get('amount') or 0):,}T**\n"
            "客服已在網站確認收款，訂單已正式成立。"
        ),
    )

    mark_payment_review_applied(int(row["id"]))


async def _apply_order_rejection(bot: discord.Client, row: dict) -> None:
    target = _target_bot_module()
    if target is None:
        raise RuntimeError("找不到 Bot 訂單付款模組。")

    channel = await _fetch_ticket_channel(bot, row)
    if channel is None:
        raise RuntimeError("找不到原訂單票口。")

    customer_id = int(str(row.get("customer_discord_id") or "0"))
    data = target.SELF_SERVICE_ORDER_SELECTIONS.get(channel.id)

    if not isinstance(data, dict):
        raise RuntimeError("找不到原訂單的 Discord runtime 資料。")

    if not _rejection_still_targets_current_order_review(row, data):
        # The rejection belongs to an older review, or the order has already
        # advanced. Mark only the review event as consumed; never clear current
        # payment state or a newer review from the runtime order.
        mark_payment_review_rejection_applied(int(row["id"]))
        return

    data["payment_review_pending"] = False
    data["payment_review_approved"] = False
    data["payment_review_last_rejected_id"] = int(row["id"])
    data["payment_review_rejected_reason"] = str(row.get("rejected_reason") or "客服駁回")
    data.pop("payment_review_id", None)
    data.pop("payment_review_no", None)
    data.pop("payment_finalizing", None)

    target.remember_order_data(channel.id, data)
    target.save_bot_data()

    amount = int(data.get("amount") or data.get("total_amount") or row.get("amount") or 0)
    quantity = int(data.get("quantity") or 1)
    category_label = str(
        data.get("category_label")
        or target.ORDER_CATEGORY_LABELS.get(
            data.get("category"),
            data.get("category") or "未紀錄",
        )
    )
    item = str(data.get("item") or "未紀錄")
    payment_method = str(data.get("payment_method") or row.get("payment_method") or "")
    companion_preference = data.get("companion_preference")

    payment_embed = target.build_payment_method_embed(
        customer_id=customer_id,
        category_label=category_label,
        item=item,
        quantity=quantity,
        payment_method=payment_method,
        companion_preference=companion_preference,
        amount=amount,
    )
    payment_embed.add_field(
        name="付款審核",
        value=(
            "上一筆付款未通過審核，可以確認付款後重新按「送出」。\n"
            f"原因：{row.get('rejected_reason') or '客服未確認到款項'}"
        ),
        inline=False,
    )

    payment_message_id = str(data.get("payment_message_id") or "").strip()
    payment_channel_id = str(data.get("payment_channel_id") or channel.id).strip()

    if payment_message_id.isdigit() and payment_channel_id.isdigit():
        payment_channel = bot.get_channel(int(payment_channel_id))
        if isinstance(payment_channel, discord.TextChannel):
            try:
                message = await payment_channel.fetch_message(int(payment_message_id))
                await message.edit(
                    embed=payment_embed,
                    view=target.PaymentMethodView(
                        customer_id=customer_id,
                        channel_id=channel.id,
                        submitted=False,
                        selected_method=payment_method,
                    ),
                    allowed_mentions=discord.AllowedMentions(
                        users=True,
                        roles=False,
                        everyone=False,
                    ),
                )
            except Exception:
                pass

    await _edit_review_notification(
        channel,
        row,
        content=(
            f"<@{customer_id}> ❌ **付款審核未通過**\n"
            f"原因：{row.get('rejected_reason') or '客服未確認到款項'}\n\n"
            "請確認付款資訊／付款截圖後，再從付款面板重新送出審核。"
        ),
    )

    mark_payment_review_rejection_applied(int(row["id"]))


async def _notify_worker_tip_paid(
    bot: discord.Client,
    channel: discord.TextChannel,
    tip_row,
) -> None:
    worker_id_text = str(tip_row["worker_discord_id"] or "").strip()
    if not worker_id_text.isdigit():
        return

    worker_id = int(worker_id_text)
    worker = channel.guild.get_member(worker_id)

    if worker is None:
        try:
            worker = await bot.fetch_user(worker_id)
        except Exception:
            worker = None

    if worker is None:
        return

    try:
        await worker.send(
            f"🍗 你收到 {tip_row['customer_display_name'] or tip_row['customer_discord_id']} "
            f"的雞腿 **{int(tip_row['amount'] or 0):,}T**！\n"
            "此筆雞腿 100% 歸你，已列入獨立薪資紀錄。"
        )
    except Exception:
        pass


async def _apply_tip_approval(bot: discord.Client, row: dict) -> None:
    channel = await _fetch_ticket_channel(bot, row)
    if channel is None:
        raise RuntimeError("找不到原雞腿票口。")

    actor = _actor(channel.guild, row)
    tip_id = int(str(row.get("source_id") or "0"))
    tip_row = mark_worker_tip_paid(
        tip_id,
        confirmed_by=actor,
    )

    if tip_row is None:
        raise RuntimeError("找不到雞腿紀錄。")

    await _edit_review_notification(
        channel,
        row,
        content=(
            "✅ **雞腿付款審核已通過**\n"
            f"老闆：<@{tip_row['customer_discord_id']}>\n"
            f"指定成員：<@{tip_row['worker_discord_id']}>\n"
            f"金額：**{int(tip_row['amount'] or 0):,}T**\n"
            f"付款方式：**{tip_row['payment_method']}**\n\n"
            "客服已在網站確認收款，此筆已列入指定成員的雞腿薪資。"
        ),
    )

    await _notify_worker_tip_paid(bot, channel, tip_row)

    target = _target_bot_module()
    if target is not None and hasattr(target, "send_order_log"):
        try:
            await target.send_order_log(
                channel.guild,
                title="雞腿付款審核通過",
                fields=[
                    ("雞腿", f"TIP-{tip_id}", True),
                    ("老闆", f"<@{tip_row['customer_discord_id']}>", True),
                    ("指定成員", f"<@{tip_row['worker_discord_id']}>", True),
                    ("金額", f"{int(tip_row['amount'] or 0):,}T", True),
                    ("付款方式", str(tip_row["payment_method"]), True),
                    ("審核客服", getattr(actor, "mention", str(getattr(actor, "id", "網站客服"))), True),
                ],
                color=discord.Color.green(),
            )
        except Exception:
            pass

    await refresh_post_close_panel(
        channel,
        str(tip_row["customer_discord_id"] or ""),
    )
    mark_payment_review_applied(int(row["id"]))


async def _apply_tip_rejection(bot: discord.Client, row: dict) -> None:
    channel = await _fetch_ticket_channel(bot, row)
    if channel is None:
        raise RuntimeError("找不到原雞腿票口。")

    actor = _actor(channel.guild, row)
    tip_id = int(str(row.get("source_id") or "0"))
    tip_row = mark_worker_tip_cancelled(
        tip_id,
        cancelled_by=actor,
    )

    if tip_row is None:
        raise RuntimeError("找不到雞腿紀錄。")

    await _edit_review_notification(
        channel,
        row,
        content=(
            "❌ **雞腿付款審核未通過**\n"
            f"老闆：<@{tip_row['customer_discord_id']}>\n"
            f"指定成員：<@{tip_row['worker_discord_id']}>\n"
            f"金額：**{int(tip_row['amount'] or 0):,}T**\n"
            f"原因：{row.get('rejected_reason') or '客服未確認到款項'}\n\n"
            "這筆雞腿沒有列入薪資；需要時可以重新按「🍗 加雞腿」送出。"
        ),
    )

    await refresh_post_close_panel(
        channel,
        str(tip_row["customer_discord_id"] or ""),
    )
    mark_payment_review_rejection_applied(int(row["id"]))


async def _process_payment_review(bot: discord.Client, row: dict) -> None:
    source_type = str(row.get("source_type") or "")
    status = str(row.get("status") or "")

    if source_type == "order":
        if status == PAYMENT_REVIEW_APPROVED:
            await _apply_order_approval(bot, row)
        elif status == PAYMENT_REVIEW_REJECTED:
            await _apply_order_rejection(bot, row)
        return

    if source_type == "worker_tip":
        if status == PAYMENT_REVIEW_APPROVED:
            await _apply_tip_approval(bot, row)
        elif status == PAYMENT_REVIEW_REJECTED:
            await _apply_tip_rejection(bot, row)
        return

    raise RuntimeError(f"不支援的付款審核類型：{source_type}")


async def payment_review_worker(bot: discord.Client) -> None:
    await bot.wait_until_ready()

    while not bot.is_closed():
        rows = list_payment_reviews_for_runtime(limit=30)

        for row in rows:
            try:
                await _process_payment_review(bot, row)
            except Exception as exc:
                if str(row.get("status") or "") == PAYMENT_REVIEW_APPROVED:
                    mark_payment_review_apply_error(
                        int(row["id"]),
                        f"{type(exc).__name__}: {exc}",
                    )
                print(
                    "[payment-review] apply failed "
                    f"id={row.get('id')} source={row.get('source_type')}:{row.get('source_id')}\n"
                    f"{traceback.format_exc()}",
                    flush=True,
                )

        await asyncio.sleep(4)


def ensure_payment_review_worker_started(bot: discord.Client) -> None:
    if getattr(bot, "_payment_review_worker_started", False):
        return

    bot._payment_review_worker_started = True
    bot.loop.create_task(payment_review_worker(bot))
