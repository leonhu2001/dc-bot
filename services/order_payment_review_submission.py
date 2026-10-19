from __future__ import annotations

from typing import Callable

import discord

from services.order_payment_policy import requires_external_payment_review


async def submit_external_payment_review_if_needed(
    *,
    interaction: discord.Interaction,
    data: dict,
    customer_id: int,
    channel_id: int,
    amount: int,
    payment_method: str,
    web_order_id: int,
    order_category_labels: dict,
    to_int: Callable,
    taipei_now_iso: Callable,
    remember_order: Callable,
    save_data: Callable,
    payment_method_embed_builder: Callable,
    payment_method_view,
) -> bool:
    """Submit an external-payment review and update the Discord payment panel.

    Returns ``True`` when this function handled the interaction and the caller
    must stop payment finalization. Returns ``False`` when the order can keep
    following the normal wallet / zero-amount / approved-review path.
    """
    if not requires_external_payment_review(payment_method, amount):
        return False

    if data.get("payment_review_approved"):
        return False

    if data.get("payment_review_pending"):
        await interaction.response.send_message(
            "這筆付款已送出網站審核，請不要重複送出。\n"
            "請將付款截圖直接傳在此票口，方便客服核對。",
            ephemeral=True,
        )
        return True

    guild = interaction.guild
    channel = interaction.channel
    if guild is None or not isinstance(channel, discord.TextChannel):
        await interaction.response.send_message(
            "無法確認目前付款票口，請通知客服確認。",
            ephemeral=True,
        )
        return True

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
        return True

    data["payment_review_id"] = int(review["id"])
    data["payment_review_no"] = str(review.get("review_no") or "")
    data["payment_review_pending"] = True
    data["payment_review_submitted_at"] = taipei_now_iso()
    data["payment_review_submitted_by"] = int(
        getattr(interaction.user, "id", 0) or 0
    )
    remember_order(channel_id, data)
    save_data()

    if not interaction.response.is_done():
        await interaction.response.defer(ephemeral=True)

    category_label = str(
        data.get("category_label")
        or order_category_labels.get(
            data.get("category"),
            data.get("category") or "未紀錄",
        )
    )
    item = str(data.get("item") or "未紀錄")
    quantity = to_int(data.get("quantity"), 1) or 1
    companion_preference = data.get("companion_preference")

    pending_embed = payment_method_embed_builder(
        customer_id=customer_id,
        category_label=category_label,
        item=item,
        quantity=quantity,
        payment_method=str(payment_method),
        companion_preference=companion_preference,
        amount=amount,
        receiver_text=(
            str(data.get("accepted_staff_display_text") or "").strip()
            or None
        ),
    )
    pending_embed.add_field(
        name="付款狀態",
        value=(
            "已送出網站審核，等待客服確認收款。\n"
            "請將付款截圖直接傳在本票口，方便客服核對。"
        ),
        inline=False,
    )

    payment_channel_id = to_int(
        data.get("payment_channel_id"),
        channel.id,
    ) or channel.id
    payment_message_id = to_int(data.get("payment_message_id"))
    payment_channel = guild.get_channel(payment_channel_id)

    if isinstance(payment_channel, discord.TextChannel) and payment_message_id is not None:
        try:
            payment_message = await payment_channel.fetch_message(payment_message_id)
            await payment_message.edit(
                embed=pending_embed,
                view=payment_method_view(
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

    review_notice = await channel.send(
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
    remember_order(channel_id, data)
    save_data()

    try:
        set_payment_review_notification(int(review["id"]), review_notice.id)
    except Exception:
        pass

    await interaction.followup.send(
        "付款已送出網站審核。請記得把付款截圖貼在這個票口，等待客服確認。",
        ephemeral=True,
    )
    return True
