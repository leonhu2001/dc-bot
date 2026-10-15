from __future__ import annotations

from typing import Any, Mapping

import asyncio
import discord

from services.payment_methods import WALLET_PAYMENT_METHOD
from services.order_payment_policy import is_zero_amount_order
from services.order_close_panel_recovery import (
    ensure_post_close_panel,
    is_order_already_closed,
)


_REQUIRED_DEPENDENCIES = (
    "RECEIPT_CHANNEL_ID",
    "SELF_SERVICE_ORDER_SELECTIONS",
    "ORDER_CATEGORY_LABELS",
    "_to_int",
    "format_t_amount",
    "parse_receipt_amount",
    "generate_order_receipt_id",
    "get_taipei_now",
    "get_taipei_now_iso",
    "get_taipei_now_text",
    "remember_order_data",
    "send_order_log",
    "is_customer_staff",
    "get_order_customer_id_from_channel",
    "get_order_summary_from_channel",
    "sync_web_order_closed_from_bot",
    "sync_web_order_cancelled_from_bot",
    "refresh_staff_profile_panels_for_order",
    "lock_dispatch_claim_panel",
    "delete_dispatch_claim_panel_for_order",
    "rename_ticket_channel",
    "build_post_close_status_embed",
    "ReviewButtonView",
)

_CONFIGURED = False


def configure_order_lifecycle_runtime(namespace: Mapping[str, Any]) -> None:
    """Bind the bot-owned lifecycle adapters after bot.py finishes defining them."""
    global _CONFIGURED

    missing = [name for name in _REQUIRED_DEPENDENCIES if name not in namespace]
    if missing:
        raise RuntimeError(
            "order lifecycle runtime missing dependencies: " + ", ".join(missing)
        )

    for name in _REQUIRED_DEPENDENCIES:
        globals()[name] = namespace[name]

    _CONFIGURED = True


def validate_order_ready_to_close(order_data: dict) -> None:
    """Fail closed unless payment has already promoted the order to service."""
    status = str(order_data.get("status") or "").strip().lower()

    if status in {"active", "paid"}:
        return

    if is_order_already_closed(order_data):
        raise ValueError("這張單已經結單，請勿重複操作。")

    if status == "stored":
        raise ValueError("這張單目前已暫存；請先恢復服務狀態，再執行結單。")

    if status in {
        "pending_cs_dispatch",
        "created",
        "waiting_acceptance",
        "accepted_pending_pay",
    }:
        raise ValueError("這張單尚未完成付款並正式成立，不能結單。")

    if status in {"cancelled", "canceled"}:
        raise ValueError("這張單已取消，不能再結單。")

    raise ValueError("無法確認這張單已完成付款，請先確認付款狀態後再結單。")


def _post_close_panel_content(
    *,
    staff_mention: str,
    receipt_text: str,
    reward_text: str,
) -> str:
    return (
        f"此單已由 {staff_mention} 結單，{receipt_text}\n\n"
        f"{reward_text}\n\n"
        "可以選擇評價本次服務、加雞腿、不留評價，或關閉票口。"
    )


async def _ensure_public_post_close_panel(
    *,
    order_channel: discord.TextChannel,
    order_data: dict,
    customer_id: int,
    order_content: str | None,
    staff_mention: str,
    receipt_text: str,
    reward_text: str,
) -> tuple[discord.Message, bool]:
    return await ensure_post_close_panel(
        order_channel=order_channel,
        order_data=order_data,
        customer_id=customer_id,
        order_content=order_content,
        content=_post_close_panel_content(
            staff_mention=staff_mention,
            receipt_text=receipt_text,
            reward_text=reward_text,
        ),
        build_embed=build_post_close_status_embed,
        build_view=ReviewButtonView,
        remember_order=remember_order_data,
    )


async def _recover_closed_order_panel(
    interaction: discord.Interaction,
    *,
    order_channel: discord.TextChannel,
    order_data: dict,
    customer_id: int,
) -> None:
    """Repair only the post-close UI; never repeat close financial side effects."""
    if not interaction.response.is_done():
        await interaction.response.defer(ephemeral=True)

    order_content, _payment_method = get_order_summary_from_channel(order_channel.id)
    reward_text = (
        "會員累積已在顧客送出付款方式時處理。"
        if order_data.get("reward_counted")
        else "提醒：這張單尚未標記會員累積，請確認顧客是否已送出付款方式。"
    )
    _panel_message, created = await _ensure_public_post_close_panel(
        order_channel=order_channel,
        order_data=order_data,
        customer_id=customer_id,
        order_content=order_content,
        staff_mention=getattr(interaction.user, "mention", f"<@{getattr(interaction.user, 'id', '')}>"),
        receipt_text="收據與結單狀態已存在，本次不重複處理。",
        reward_text=reward_text,
    )

    await interaction.followup.send(
        "這張單已經結單；已補回結單後 Panel。"
        if created
        else "這張單已經結單；結單後 Panel 已存在並已重新整理。",
        ephemeral=True,
    )


async def ensure_payment_submit_receipt(
    *,
    guild: discord.Guild,
    order_channel: discord.TextChannel,
    customer_id: int,
    customer_member: discord.Member | None,
    staff_member: discord.Member | discord.User,
    category_label: str,
    item: str,
    quantity: int,
    amount: int,
    payment_method: str,
    companion_preference: str | None = None,
) -> tuple[str | None, discord.Message | None]:
    """在付款方式 panel 按下送出後產生交易收據。

    重要：
    - 已經有 receipt_id 的訂單不重複產生。
    - 舊單如果沒有 receipt_id，仍可保留原本已結單 ReceiptModal 補開收據。
    """
    receipt_channel = guild.get_channel(RECEIPT_CHANNEL_ID)

    if receipt_channel is None or not isinstance(receipt_channel, discord.TextChannel):
        raise ValueError("找不到收據頻道，請確認 RECEIPT_CHANNEL_ID 是否正確。")

    order_data = SELF_SERVICE_ORDER_SELECTIONS.setdefault(order_channel.id, {})

    existing_receipt_id = str(order_data.get("receipt_id") or order_data.get("order_no") or "").strip()
    existing_message_id = _to_int(order_data.get("receipt_message_id"))

    if existing_receipt_id:
        return existing_receipt_id, None

    receipt_id = generate_order_receipt_id()
    created_at_iso = get_taipei_now_iso()
    created_at_text = get_taipei_now_text()

    payer_name = (
        getattr(customer_member, "display_name", None)
        or getattr(customer_member, "name", None)
        or str(customer_id)
    )

    staff_name = (
        getattr(staff_member, "display_name", None)
        or getattr(staff_member, "name", None)
        or str(getattr(staff_member, "id", "未紀錄"))
    )

    amount_text = format_t_amount(amount)
    if is_zero_amount_order(amount):
        payment_status_text = "免付款／已完成"
    else:
        payment_status_text = (
            "已確認收款"
            if payment_method == WALLET_PAYMENT_METHOD
            or bool(order_data.get("payment_review_approved"))
            else "已送出，待客服確認"
        )
    order_content = f"{category_label}｜{item}｜數量：{quantity} 單"
    if companion_preference:
        order_content += f"｜{companion_preference}"

    receipt_text = (
        "```text\n"
        "【魔丸娛樂｜交易收據】\n"
        "\n"
        f"收據編號：{receipt_id}\n"
        f"訂單編號：{receipt_id}\n"
        f"開立時間：{created_at_text}\n"
        "\n"
        f"顧客：{payer_name}\n"
        f"顧客 ID：{customer_id}\n"
        "\n"
        f"服務類別：{category_label}\n"
        f"服務項目：{item}\n"
        f"數量：{quantity} 單\n"
        f"金額：{amount_text}\n"
        f"付款方式：{payment_method}\n"
        f"付款狀態：{payment_status_text}\n"
        "\n"
        f"客服人員：{staff_name}\n"
        "\n"
        "備註：\n"
        "此收據為魔丸娛樂服務交易紀錄，非統一發票。\n"
        "如需正式報帳憑證，請先與客服確認。\n"
        "```"
    )

    embed = discord.Embed(
        title="魔丸娛樂｜交易收據",
        description=receipt_text,
        color=discord.Color.green(),
        timestamp=get_taipei_now(),
    )
    embed.add_field(name="收據編號", value=receipt_id, inline=True)
    embed.add_field(name="顧客", value=f"<@{customer_id}>", inline=True)
    embed.add_field(name="金額", value=amount_text, inline=True)
    embed.add_field(name="付款方式", value=payment_method, inline=True)
    embed.add_field(name="付款狀態", value=payment_status_text, inline=True)
    embed.add_field(name="票口", value=order_channel.mention, inline=False)
    embed.set_footer(text="此收據為交易紀錄，非統一發票。")

    receipt_message = await receipt_channel.send(
        embed=embed,
        allowed_mentions=discord.AllowedMentions(
            users=True,
            roles=False,
            everyone=False,
        ),
    )

    order_data["receipt_id"] = receipt_id
    order_data["order_no"] = receipt_id
    order_data["receipt_created_at"] = created_at_iso
    order_data["receipt_created_by"] = getattr(staff_member, "id", None)
    order_data["receipt_message_id"] = receipt_message.id
    order_data["receipt_channel_id"] = receipt_channel.id
    order_data["receipt_status"] = "payment_submitted"
    order_data["receipt_note"] = "付款方式送出後自動產生，非統一發票。"
    order_data["amount"] = int(amount)
    order_data["total_amount"] = int(amount)
    order_data["amount_text"] = amount_text
    order_data["payment_method"] = payment_method
    order_data["quantity"] = int(quantity)
    remember_order_data(order_channel.id, order_data)

    await send_order_log(
        guild,
        title="交易收據已產生",
        fields=[
            ("收據編號", receipt_id, True),
            ("顧客", f"<@{customer_id}>", True),
            ("金額", amount_text, True),
            ("付款方式", payment_method, True),
            ("付款狀態", payment_status_text, True),
            ("客服人員", getattr(staff_member, "mention", staff_name), True),
            ("票口", order_channel.mention, False),
            ("收據訊息", receipt_message.jump_url, False),
        ],
        color=discord.Color.green(),
    )

    return receipt_id, receipt_message


# ========= 收據 Modal =========

class ReceiptModal(discord.ui.Modal, title="已結單收據"):
    payee = discord.ui.TextInput(
        label="收款人",
        placeholder="例如：zYao或客服暱稱(代收)",
        required=True,
        max_length=100
    )

    staff = discord.ui.TextInput(
        label="對接客服",
        placeholder="請輸入對接客服名稱",
        required=True,
        max_length=100
    )

    receiver = discord.ui.TextInput(
        label="接單打手/陪玩",
        placeholder="請輸入接單打手/陪玩名稱",
        required=True,
        max_length=100
    )

    async def on_submit(self, interaction: discord.Interaction):
        if not isinstance(interaction.user, discord.Member):
            await interaction.response.send_message("無法確認你的身分組。", ephemeral=True)
            return

        if not is_customer_staff(interaction.user):
            await interaction.response.send_message("只有客服可以操作已結單。", ephemeral=True)
            return

        guild = interaction.guild

        if guild is None:
            await interaction.response.send_message("這個功能只能在伺服器內使用。", ephemeral=True)
            return

        if not isinstance(interaction.channel, discord.TextChannel):
            await interaction.response.send_message("無法確認目前票口頻道。", ephemeral=True)
            return

        receipt_channel = guild.get_channel(RECEIPT_CHANNEL_ID)

        if receipt_channel is None or not isinstance(receipt_channel, discord.TextChannel):
            await interaction.response.send_message(
                "找不到收據頻道，請確認 RECEIPT_CHANNEL_ID 是否正確。",
                ephemeral=True
            )
            return

        order_channel = interaction.channel
        customer_id = get_order_customer_id_from_channel(order_channel)

        if customer_id is None:
            await interaction.response.send_message(
                "無法辨識這張票口的下單顧客，因此無法自動帶入付款人。",
                ephemeral=True
            )
            return

        customer_member = guild.get_member(customer_id)
        payer_text = f"@{customer_member.display_name}" if customer_member is not None else f"@{customer_id}"

        order_content, payment_method = get_order_summary_from_channel(order_channel.id)
        date_text = get_taipei_now_text()

        order_data = SELF_SERVICE_ORDER_SELECTIONS.setdefault(order_channel.id, {})
        try:
            validate_order_ready_to_close(order_data)
        except ValueError as exc:
            if is_order_already_closed(order_data):
                await _recover_closed_order_panel(
                    interaction,
                    order_channel=order_channel,
                    order_data=order_data,
                    customer_id=customer_id,
                )
                return
            await interaction.response.send_message(str(exc), ephemeral=True)
            return

        parsed_amount = _to_int(order_data.get("amount"), 0) or _to_int(order_data.get("total_amount"), 0) or 0
        if parsed_amount < 0:
            await interaction.response.send_message(
                "這張單還沒有訂單價格，請先在付款面板按「填寫訂單價格」讓客服輸入金額。",
                ephemeral=True
            )
            return

        # legacy_receipt_close_ack_v1
        await interaction.response.defer()

        amount_text = str(order_data.get("amount_text") or format_t_amount(parsed_amount))

        existing_receipt_id = str(order_data.get("receipt_id") or order_data.get("order_no") or "").strip()
        receipt_already_created = bool(existing_receipt_id)
        receipt_id = existing_receipt_id or generate_order_receipt_id()
        closed_at_text = get_taipei_now_iso()

        order_data["receipt_id"] = receipt_id
        order_data["order_no"] = receipt_id
        order_data.setdefault("receipt_created_at", closed_at_text)
        order_data["closed_at"] = closed_at_text
        order_data["closed"] = True
        order_data["status"] = "closed"
        order_data["amount"] = parsed_amount
        order_data["total_amount"] = parsed_amount
        order_data["payment_method"] = payment_method
        remember_order_data(order_channel.id, order_data)
        sync_web_order_closed_from_bot(
            ticket_channel_id=order_channel.id,
            dispatch_message_id=order_data.get("dispatch_message_id"),
        )

        await refresh_staff_profile_panels_for_order(
            guild,
            ticket_channel_id=order_channel.id,
            reason="order_closed",
        )

        receipt_text = (
            "```text\n"
            "收據\n"
            "\n"
            f"編號：{receipt_id}\n"
            f"日期：{date_text}\n"
            "\n"
            f"收款人：{self.payee.value}\n"
            f"付款人：{payer_text}\n"
            "\n"
            f"內容：{order_content}\n"
            "\n"
            f"金額：{amount_text}\n"
            f"付款方式：{payment_method}\n"
            "```"
        )

        embed = discord.Embed(
            title="收據",
            description=receipt_text,
            color=discord.Color.green()
        )

        embed.add_field(
            name="付款人",
            value=payer_text,
            inline=False
        )

        embed.add_field(
            name="對接客服",
            value=self.staff.value,
            inline=False
        )

        embed.add_field(
            name="接單打手/陪玩",
            value=self.receiver.value,
            inline=False
        )

        if not receipt_already_created:
            receipt_message = await receipt_channel.send(
                embed=embed,
                allowed_mentions=discord.AllowedMentions(
                    users=True,
                    roles=False,
                    everyone=False
                )
            )
            order_data["receipt_message_id"] = receipt_message.id
            order_data["receipt_channel_id"] = receipt_channel.id
            remember_order_data(order_channel.id, order_data)

        await lock_dispatch_claim_panel(guild, order_channel.id)
        await rename_ticket_channel(order_channel, "已結單", member=customer_member)

        reward_result = "會員累積已在顧客送出付款方式時處理。" if order_data.get("reward_counted") else "提醒：這張單尚未標記會員累積，請確認顧客是否已送出付款方式。"

        await send_order_log(
            guild,
            title="訂單已結單",
            fields=[
                ("訂單編號", receipt_id, True),
                ("顧客", f"<@{customer_id}>", True),
                ("客服", interaction.user.mention, True),
                ("金額", amount_text, True),
                ("付款方式", payment_method, True),
                ("票口", order_channel.mention, False),
                ("內容", order_content, False),
            ],
            color=discord.Color.green(),
        )

        close_receipt_text = "收據已於付款送出時產生，本次不重複送出。" if receipt_already_created else "收據已送出。"

        _panel_message, created = await _ensure_public_post_close_panel(
            order_channel=order_channel,
            order_data=order_data,
            customer_id=customer_id,
            order_content=order_content,
            staff_mention=interaction.user.mention,
            receipt_text=close_receipt_text,
            reward_text=reward_result,
        )
        await interaction.followup.send(
            "結單完成，結單後 Panel 已建立。"
            if created
            else "結單完成，既有結單後 Panel 已重新整理。",
            ephemeral=True,
        )


def get_stored_order_amount_or_none(order_data: dict) -> int | None:
    for key in ("amount", "total_amount", "amount_text"):
        raw = order_data.get(key)
        if raw is None or str(raw).strip() == "":
            continue

        if isinstance(raw, int):
            return raw

        parsed = parse_receipt_amount(str(raw))
        if parsed is not None:
            return parsed

    return None


async def close_order_without_receipt_modal(interaction: discord.Interaction) -> None:
    if not isinstance(interaction.user, discord.Member):
        await interaction.response.send_message("無法確認你的身分組。", ephemeral=True)
        return

    if not is_customer_staff(interaction.user):
        await interaction.response.send_message("只有客服可以操作已結單。", ephemeral=True)
        return

    guild = interaction.guild
    if guild is None:
        await interaction.response.send_message("這個功能只能在伺服器內使用。", ephemeral=True)
        return

    if not isinstance(interaction.channel, discord.TextChannel):
        await interaction.response.send_message("無法確認目前票口頻道。", ephemeral=True)
        return

    order_channel = interaction.channel
    customer_id = get_order_customer_id_from_channel(order_channel)

    if customer_id is None:
        await interaction.response.send_message(
            "無法辨識這張票口的下單顧客，因此無法結單。",
            ephemeral=True,
        )
        return

    customer_member = guild.get_member(customer_id)
    order_data = SELF_SERVICE_ORDER_SELECTIONS.setdefault(order_channel.id, {})

    try:
        validate_order_ready_to_close(order_data)
    except ValueError as exc:
        if is_order_already_closed(order_data):
            await _recover_closed_order_panel(
                interaction,
                order_channel=order_channel,
                order_data=order_data,
                customer_id=customer_id,
            )
            return
        await interaction.response.send_message(str(exc), ephemeral=True)
        return

    parsed_amount = get_stored_order_amount_or_none(order_data)
    if parsed_amount is None:
        await interaction.response.send_message(
            "這張單還沒有訂單價格，請先讓客服填寫金額；贈送單請填 0。",
            ephemeral=True,
        )
        return

    if parsed_amount < 0:
        await interaction.response.send_message(
            "訂單金額不可為負數，請先修正金額後再結單。",
            ephemeral=True,
        )
        return

    # close_interaction_ack_v1
    await interaction.response.defer()

    order_content, detected_payment_method = get_order_summary_from_channel(order_channel.id)
    payment_method = str(
        order_data.get("payment_method")
        or detected_payment_method
        or "未填寫"
    ).strip()

    amount_text = str(order_data.get("amount_text") or format_t_amount(parsed_amount))
    existing_receipt_id = str(order_data.get("receipt_id") or order_data.get("order_no") or "").strip()
    receipt_already_created = bool(existing_receipt_id)

    receipt_id = existing_receipt_id

    # 新流程通常在付款送出時已產生收據；如果舊單沒有收據，這裡自動補一張，不再要求客服填 Modal。
    if not receipt_id:
        category = order_data.get("category")
        item = order_data.get("item")
        quantity = _to_int(order_data.get("quantity"), 1) or 1
        category_label = str(order_data.get("category_label") or ORDER_CATEGORY_LABELS.get(category, str(category or "訂單")))

        if category is not None and item is not None:
            try:
                receipt_id, _receipt_message = await ensure_payment_submit_receipt(
                    guild=guild,
                    order_channel=order_channel,
                    customer_id=customer_id,
                    customer_member=customer_member,
                    staff_member=interaction.user,
                    category_label=category_label,
                    item=str(item),
                    quantity=quantity,
                    amount=parsed_amount,
                    payment_method=payment_method,
                    companion_preference=order_data.get("companion_preference"),
                )
                order_data = SELF_SERVICE_ORDER_SELECTIONS.setdefault(order_channel.id, {})
            except ValueError as exc:
                await interaction.followup.send(str(exc), ephemeral=True)
                return
        else:
            receipt_id = generate_order_receipt_id()
            order_data["receipt_id"] = receipt_id
            order_data["order_no"] = receipt_id

    closed_at_text = get_taipei_now_iso()
    order_data["receipt_id"] = receipt_id
    order_data["order_no"] = receipt_id
    order_data.setdefault("receipt_created_at", closed_at_text)
    order_data["closed_at"] = closed_at_text
    order_data["closed"] = True
    order_data["status"] = "closed"
    order_data["amount"] = parsed_amount
    order_data["total_amount"] = parsed_amount
    order_data["amount_text"] = amount_text
    order_data["payment_method"] = payment_method
    remember_order_data(order_channel.id, order_data)

    sync_web_order_closed_from_bot(
        ticket_channel_id=order_channel.id,
        dispatch_message_id=order_data.get("dispatch_message_id"),
    )

    await refresh_staff_profile_panels_for_order(
        guild,
        ticket_channel_id=order_channel.id,
        reason="order_closed",
    )

    await lock_dispatch_claim_panel(guild, order_channel.id)
    await rename_ticket_channel(order_channel, "已結單", member=customer_member)

    reward_result = (
        "會員累積已在顧客送出付款方式時處理。"
        if order_data.get("reward_counted")
        else "提醒：這張單尚未標記會員累積，請確認顧客是否已送出付款方式。"
    )

    await send_order_log(
        guild,
        title="訂單已結單",
        fields=[
            ("訂單編號", receipt_id or "未產生", True),
            ("顧客", f"<@{customer_id}>", True),
            ("客服", interaction.user.mention, True),
            ("金額", amount_text, True),
            ("付款方式", payment_method, True),
            ("票口", order_channel.mention, False),
            ("內容", order_content, False),
        ],
        color=discord.Color.green(),
    )

    close_receipt_text = "收據已於付款送出時產生，本次不重複送出。" if receipt_already_created else "收據已自動產生或補登。"

    _panel_message, created = await _ensure_public_post_close_panel(
        order_channel=order_channel,
        order_data=order_data,
        customer_id=customer_id,
        order_content=order_content,
        staff_mention=interaction.user.mention,
        receipt_text=close_receipt_text,
        reward_text=reward_result,
    )
    await interaction.followup.send(
        "結單完成，結單後 Panel 已建立。"
        if created
        else "結單完成，既有結單後 Panel 已重新整理。",
        ephemeral=True,
    )


class ConfirmCloseOrderView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=60)

    @discord.ui.button(
        label="是，確認結單",
        style=discord.ButtonStyle.success,
        custom_id="confirm_close_order_yes",
    )
    async def confirm_close(self, interaction: discord.Interaction, button: discord.ui.Button):
        await close_order_without_receipt_modal(interaction)

    @discord.ui.button(
        label="否，保留訂單",
        style=discord.ButtonStyle.secondary,
        custom_id="confirm_close_order_no",
    )
    async def keep_order(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not isinstance(interaction.user, discord.Member):
            await interaction.response.send_message("無法確認你的身分組。", ephemeral=True)
            return

        if not is_customer_staff(interaction.user):
            await interaction.response.send_message("只有客服可以操作。", ephemeral=True)
            return

        await interaction.response.send_message("已保留訂單。", ephemeral=True)


# ========= 下單操作按鈕 =========

CANCEL_REASON_OPTIONS = [
    ("customer_changed_mind", "客人取消／改變需求"),
    ("schedule_conflict", "時間無法配合"),
    ("no_staff", "缺少可接人員"),
    ("payment_issue", "未付款／付款問題"),
    ("price_issue", "價格／預算問題"),
    ("duplicate_order", "重複／誤下單"),
    ("service_unavailable", "服務無法提供"),
    ("internal_correction", "店內修正"),
    ("other", "其他"),
]


class OrderCancellationReasonSelect(discord.ui.Select):
    def __init__(self):
        super().__init__(
            placeholder="先選擇取消原因",
            min_values=1,
            max_values=1,
            options=[
                discord.SelectOption(label=label, value=code)
                for code, label in CANCEL_REASON_OPTIONS
            ],
            row=1,
        )

    async def callback(self, interaction: discord.Interaction):
        parent = self.view
        if parent is None:
            await interaction.response.send_message(
                "取消原因面板已失效，請重新操作。",
                ephemeral=True,
            )
            return

        setattr(parent, "cancellation_reason_code", self.values[0])
        selected_label = dict(CANCEL_REASON_OPTIONS).get(
            self.values[0],
            self.values[0],
        )
        await interaction.response.send_message(
            f"已選擇取消原因：{selected_label}",
            ephemeral=True,
        )


class ConfirmCancelOrderView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=60)
        self.cancellation_reason_code = "unspecified"
        self.add_item(OrderCancellationReasonSelect())

    @discord.ui.button(
        label="是，取消訂單",
        style=discord.ButtonStyle.danger,
        custom_id="confirm_cancel_order_yes"
    )
    async def confirm_cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not isinstance(interaction.user, discord.Member):
            await interaction.response.send_message("無法確認你的身分組。", ephemeral=True)
            return

        if not is_customer_staff(interaction.user):
            await interaction.response.send_message("只有客服可以取消訂單。", ephemeral=True)
            return

        if self.cancellation_reason_code == "unspecified":
            await interaction.response.send_message(
                "請先從下拉選單選擇取消原因。",
                ephemeral=True,
            )
            return

        channel = interaction.channel

        # MAWAN_R13_CANCEL_SYNC
        if isinstance(channel, discord.TextChannel):
            order_data = SELF_SERVICE_ORDER_SELECTIONS.get(channel.id, {})
            dispatch_message_id = _to_int(order_data.get("dispatch_message_id"), None)
            sync_web_order_cancelled_from_bot(
                channel.id,
                dispatch_message_id=dispatch_message_id,
                note="由 DC bot 客服取消訂單同步。",
                actor_discord_id=interaction.user.id,
                cancellation_reason_code=self.cancellation_reason_code,
            )

        if interaction.guild is not None and isinstance(channel, discord.TextChannel):
            await delete_dispatch_claim_panel_for_order(
                guild=interaction.guild,
                order_channel_id=channel.id,
                actor_discord_id=interaction.user.id,
                cancellation_reason_code=self.cancellation_reason_code,
            )

        await interaction.response.send_message(
            "已確認取消訂單，這個頻道將在 3 秒後關閉，對應的派單訊息也會一併刪除。",
            ephemeral=False
        )

        await asyncio.sleep(3)

        if isinstance(channel, discord.TextChannel):
            await channel.delete(reason=f"Order cancelled by {interaction.user}")

    @discord.ui.button(
        label="否，保留訂單",
        style=discord.ButtonStyle.secondary,
        custom_id="confirm_cancel_order_no"
    )
    async def keep_order(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not isinstance(interaction.user, discord.Member):
            await interaction.response.send_message("無法確認你的身分組。", ephemeral=True)
            return

        if not is_customer_staff(interaction.user):
            await interaction.response.send_message("只有客服可以操作。", ephemeral=True)
            return

        await interaction.response.send_message("已保留訂單。", ephemeral=True)
