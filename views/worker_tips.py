from __future__ import annotations

from collections.abc import Awaitable, Callable

import discord

from core.permissions import is_customer_staff
from services.worker_tips import (
    create_worker_tip,
    get_worker_tip,
    mark_worker_tip_cancelled,
    mark_worker_tip_paid,
    set_worker_tip_confirmation_message,
)


_WALLET_HANDLER = None
_LOG_HANDLER = None
_REVIEW_TARGET_GETTER: Callable | None = None
_REFRESH_POST_CLOSE_HANDLER: Callable[..., Awaitable] | None = None

WORKER_TIP_POLICY_TEXT = (
    "🍗 **加雞腿說明**\n"
    "• 雞腿金額 100% 給你指定的打手／陪玩。\n"
    "• 雞腿採獨立帳務，不併入原訂單金額。\n"
    "• 雞腿不計原單抽成，也不影響原訂單分潤。\n"
    "• 雞腿不列入 VIP 累積消費，也不增加會員點數。\n"
    "• 使用「我的錢包」會立即扣款；街口／轉帳送出後會進網站審核，請在票口貼付款截圖，客服確認後才會入帳。"
)


def configure_worker_tip_views(
    *,
    wallet_handler=None,
    log_handler=None,
    review_target_getter: Callable,
    refresh_post_close_handler: Callable[..., Awaitable],
) -> None:
    global _WALLET_HANDLER, _LOG_HANDLER
    global _REVIEW_TARGET_GETTER, _REFRESH_POST_CLOSE_HANDLER
    _WALLET_HANDLER = wallet_handler
    _LOG_HANDLER = log_handler
    _REVIEW_TARGET_GETTER = review_target_getter
    _REFRESH_POST_CLOSE_HANDLER = refresh_post_close_handler


def _review_targets(ticket_channel_id, dispatch_message_id=None):
    if _REVIEW_TARGET_GETTER is None:
        raise RuntimeError("worker-tip views are not configured: review target getter missing")
    return _REVIEW_TARGET_GETTER(ticket_channel_id, dispatch_message_id)


async def _refresh_post_close(channel, customer_id: int):
    if _REFRESH_POST_CLOSE_HANDLER is None:
        raise RuntimeError("worker-tip views are not configured: post-close refresh missing")
    return await _REFRESH_POST_CLOSE_HANDLER(channel, customer_id)


async def _log_worker_tip(event: str, *, interaction: discord.Interaction, tip_row: sqlite3.Row | None) -> None:
    callback = _LOG_HANDLER
    if callback is None or tip_row is None:
        return

    try:
        await callback(
            event=event,
            interaction=interaction,
            tip=dict(tip_row),
        )
    except Exception as exc:
        print(f"[worker-tip] log callback failed tip_id={tip_row['id']}: {exc}")


async def _notify_worker_tip_paid(interaction: discord.Interaction, tip_row: sqlite3.Row | None) -> None:
    if tip_row is None:
        return

    guild = interaction.guild
    if guild is None:
        return

    try:
        worker_id = int(str(tip_row["worker_discord_id"] or "0"))
    except (TypeError, ValueError):
        worker_id = 0

    worker = guild.get_member(worker_id) if worker_id else None
    amount = int(tip_row["amount"] or 0)
    customer_name = str(tip_row["customer_display_name"] or tip_row["customer_discord_id"] or "老闆")

    if worker is not None:
        try:
            await worker.send(
                f"🍗 你收到 {customer_name} 的雞腿 {amount:,}T！\n"
                "此筆雞腿 100% 歸你，已列入獨立薪資紀錄。"
            )
        except discord.HTTPException:
            pass


def _worker_tip_preview_text(*, target: dict, amount: int) -> str:
    return (
        f"{WORKER_TIP_POLICY_TEXT}\n\n"
        f"指定成員：**{target.get('display_name') or target.get('staff_id')}**\n"
        f"雞腿金額：**{int(amount):,}T**\n\n"
        "確認金額後，請選擇付款方式；付款前仍可修改金額。"
    )


class WorkerTipAmountEditModal(discord.ui.Modal, title="修改雞腿金額"):
    def __init__(
        self,
        *,
        customer_id: int,
        ticket_channel_id: int,
        target: dict,
        amount: int,
    ):
        super().__init__(timeout=300)
        self.customer_id = int(customer_id)
        self.ticket_channel_id = int(ticket_channel_id)
        self.target = dict(target)
        self.amount_input = discord.ui.TextInput(
            label="雞腿金額",
            default=str(int(amount)),
            placeholder="請輸入正整數，例如：100、500、1000",
            required=True,
            min_length=1,
            max_length=9,
        )
        self.add_item(self.amount_input)

    async def on_submit(self, interaction: discord.Interaction):
        if interaction.user.id != self.customer_id:
            await interaction.response.send_message(
                "只有這張票口的老闆可以修改雞腿金額。",
                ephemeral=True,
            )
            return

        raw = str(self.amount_input.value or "").strip().replace(",", "")
        if not raw.isdigit() or int(raw) <= 0:
            await interaction.response.send_message(
                "雞腿金額必須是大於 0 的正整數。",
                ephemeral=True,
            )
            return

        amount = int(raw)
        await interaction.response.edit_message(
            content=_worker_tip_preview_text(
                target=self.target,
                amount=amount,
            ),
            view=WorkerTipPaymentMethodView(
                customer_id=self.customer_id,
                ticket_channel_id=self.ticket_channel_id,
                target=self.target,
                amount=amount,
            ),
        )


class WorkerTipAmountModal(discord.ui.Modal, title="🍗 加雞腿"):
    amount = discord.ui.TextInput(
        label="雞腿金額",
        placeholder="請輸入正整數，例如：100、500、1000",
        required=True,
        min_length=1,
        max_length=9,
    )

    def __init__(self, *, customer_id: int, ticket_channel_id: int, target: dict):
        super().__init__(timeout=300)
        self.customer_id = int(customer_id)
        self.ticket_channel_id = int(ticket_channel_id)
        self.target = dict(target)

    async def on_submit(self, interaction: discord.Interaction):
        if interaction.user.id != self.customer_id:
            await interaction.response.send_message(
                "只有這張票口的老闆可以加雞腿。",
                ephemeral=True,
            )
            return

        raw = str(self.amount.value or "").strip().replace(",", "")
        if not raw.isdigit() or int(raw) <= 0:
            await interaction.response.send_message(
                "雞腿金額必須是大於 0 的正整數。",
                ephemeral=True,
            )
            return

        amount = int(raw)
        await interaction.response.edit_message(
            content=_worker_tip_preview_text(
                target=self.target,
                amount=amount,
            ),
            view=WorkerTipPaymentMethodView(
                customer_id=self.customer_id,
                ticket_channel_id=self.ticket_channel_id,
                target=self.target,
                amount=amount,
            ),
        )


class WorkerTipMemberSelect(discord.ui.Select):
    def __init__(self, *, customer_id: int, ticket_channel_id: int, targets: list[dict]):
        self.customer_id = int(customer_id)
        self.ticket_channel_id = int(ticket_channel_id)
        self.targets = [dict(item) for item in targets]

        options = []
        for target in self.targets[:25]:
            staff_id = str(target.get("staff_id") or "")
            if not staff_id:
                continue
            options.append(
                discord.SelectOption(
                    label=str(target.get("display_name") or staff_id)[:80],
                    value=staff_id,
                    description="選擇後輸入雞腿金額",
                    emoji="🍗",
                )
            )

        super().__init__(
            placeholder="選擇要加雞腿的成員",
            min_values=1,
            max_values=1,
            options=options,
            disabled=not bool(options),
        )

    async def callback(self, interaction: discord.Interaction):
        if interaction.user.id != self.customer_id:
            await interaction.response.send_message("只有這張票口的老闆可以加雞腿。", ephemeral=True)
            return

        staff_id = str(self.values[0])
        target = next(
            (item for item in self.targets if str(item.get("staff_id") or "") == staff_id),
            None,
        )

        if target is None:
            await interaction.response.send_message("找不到這位成員，請重新打開加雞腿面板。", ephemeral=True)
            return

        await interaction.response.send_modal(
            WorkerTipAmountModal(
                customer_id=self.customer_id,
                ticket_channel_id=self.ticket_channel_id,
                target=target,
            )
        )


class WorkerTipMemberMenuView(discord.ui.View):
    def __init__(self, *, customer_id: int, ticket_channel_id: int, targets: list[dict]):
        super().__init__(timeout=900)
        if targets:
            self.add_item(
                WorkerTipMemberSelect(
                    customer_id=customer_id,
                    ticket_channel_id=ticket_channel_id,
                    targets=targets,
                )
            )


class WorkerTipPaymentMethodSelect(discord.ui.Select):
    def __init__(self, *, customer_id: int, ticket_channel_id: int, target: dict, amount: int):
        self.customer_id = int(customer_id)
        self.ticket_channel_id = int(ticket_channel_id)
        self.target = dict(target)
        self.amount = int(amount)
        self.processed = False

        super().__init__(
            placeholder="選擇雞腿付款方式",
            min_values=1,
            max_values=1,
            options=[
                discord.SelectOption(label="我的錢包", value="我的錢包", emoji="👛"),
                discord.SelectOption(label="街口", value="街口", emoji="💳"),
                discord.SelectOption(label="轉帳", value="轉帳", emoji="🏦"),
            ],
        )

    async def callback(self, interaction: discord.Interaction):
        if interaction.user.id != self.customer_id:
            await interaction.response.send_message("只有這張票口的老闆可以操作雞腿付款。", ephemeral=True)
            return

        if self.processed:
            await interaction.response.send_message("這次雞腿付款已經處理過了。", ephemeral=True)
            return

        channel = interaction.channel
        if not isinstance(channel, discord.TextChannel) or channel.id != self.ticket_channel_id:
            await interaction.response.send_message("找不到原本的訂單票口，請重新操作。", ephemeral=True)
            return

        payment_method = str(self.values[0])
        order, _targets = _review_targets(channel.id)

        if order is None:
            await interaction.response.send_message("找不到這張已結單訂單資料，暫時無法加雞腿。", ephemeral=True)
            return

        self.processed = True
        await interaction.response.defer(ephemeral=True)

        customer_name = (
            getattr(interaction.user, "display_name", None)
            or getattr(interaction.user, "name", None)
            or str(self.customer_id)
        )

        tip_id = create_worker_tip(
            order=order,
            ticket_channel_id=channel.id,
            customer_id=self.customer_id,
            customer_display_name=customer_name,
            target=self.target,
            amount=self.amount,
            payment_method=payment_method,
            payment_status=(
                "pending"
                if payment_method == "我的錢包"
                else "pending_review"
            ),
        )

        if payment_method == "我的錢包":
            handler = _WALLET_HANDLER

            if handler is None:
                mark_worker_tip_cancelled(tip_id, cancelled_by=interaction.user)
                await interaction.followup.send(
                    "錢包付款系統尚未初始化，這筆雞腿沒有扣款，請稍後再試。",
                    ephemeral=True,
                )
                return

            base_order_no = str(order["bot_order_no"] or f"WEB-{order['id']}")
            wallet_reference = f"{base_order_no}:TIP-{tip_id}"

            try:
                tx = await handler(
                    customer_id=self.customer_id,
                    amount=self.amount,
                    order_channel_id=channel.id,
                    order_no=wallet_reference,
                    worker_id=str(self.target.get("staff_id") or ""),
                    worker_name=str(self.target.get("display_name") or self.target.get("staff_id") or ""),
                    operator=interaction.user,
                )
            except Exception as exc:
                mark_worker_tip_cancelled(tip_id, cancelled_by=interaction.user)
                error_text = str(exc).strip()
                if "duplicate wallet transaction reference" in error_text.lower():
                    error_text = (
                        "雞腿付款未完成：系統偵測到重複交易，"
                        "本次操作已取消且不會重複扣款。請重新開啟「加雞腿」再試一次。"
                    )
                elif not error_text:
                    error_text = "雞腿付款失敗，這筆雞腿沒有扣款，請重新操作。"

                await interaction.followup.send(error_text, ephemeral=True)
                return

            tip_row = mark_worker_tip_paid(
                tip_id,
                confirmed_by=interaction.user,
                wallet_transaction_id=int(tx.get("id") or 0) or None,
            )

            await channel.send(
                (
                    f"🍗 {interaction.user.mention} 給 "
                    f"<@{self.target.get('staff_id')}> 加了 **{self.amount:,}T** 雞腿！\n"
                    "此筆雞腿 100% 給指定成員，已由「我的錢包」完成付款。"
                ),
                allowed_mentions=discord.AllowedMentions(users=True, roles=False, everyone=False),
            )
            await _notify_worker_tip_paid(interaction, tip_row)
            await _log_worker_tip("paid", interaction=interaction, tip_row=tip_row)

            await _refresh_post_close(channel, self.customer_id)

            # 已付款會直接顯示在公開 Embed；把付款方式選單收掉即可。
            try:
                await interaction.delete_original_response()
            except (discord.NotFound, discord.HTTPException):
                pass
            return

        try:
            from services.payment_reviews import (
                create_payment_review,
                set_payment_review_notification,
            )

            review = create_payment_review(
                source_type="worker_tip",
                source_id=tip_id,
                ticket_channel_id=channel.id,
                customer_discord_id=self.customer_id,
                customer_display_name=customer_name,
                target_discord_id=str(self.target.get("staff_id") or ""),
                target_display_name=str(
                    self.target.get("display_name")
                    or self.target.get("staff_id")
                    or ""
                ),
                amount=self.amount,
                payment_method=payment_method,
            )
        except Exception as exc:
            mark_worker_tip_cancelled(tip_id, cancelled_by=interaction.user)
            await interaction.followup.send(
                f"建立雞腿付款審核失敗：{exc}",
                ephemeral=True,
            )
            return

        review_message = await channel.send(
            (
                f"🍗 **雞腿付款已送出網站審核**\n"
                f"老闆：{interaction.user.mention}\n"
                f"指定成員：<@{self.target.get('staff_id')}>\n"
                f"金額：**{self.amount:,}T**\n"
                f"付款方式：**{payment_method}**\n\n"
                "雞腿 100% 給指定成員；不計原單抽成、不影響原訂單金額，"
                "也不列入 VIP 累積或會員點數。\n\n"
                "📎 **請將轉帳／街口付款截圖直接傳在此票口**，"
                "方便客服核對後到網站完成付款審核。\n"
                "客服確認前，這筆雞腿不會列入打手薪資。"
            ),
            allowed_mentions=discord.AllowedMentions(
                users=True,
                roles=False,
                everyone=False,
            ),
        )
        set_worker_tip_confirmation_message(tip_id, review_message.id)

        try:
            set_payment_review_notification(
                int(review["id"]),
                review_message.id,
            )
        except Exception:
            pass

        tip_row = get_worker_tip(tip_id)
        await _log_worker_tip("pending", interaction=interaction, tip_row=tip_row)

        # 這是仍需要使用者下一步動作的提示，因此保留；
        # 直接取代原付款方式選單，避免再多生一則私人訊息。
        await interaction.edit_original_response(
            content=(
                f"已建立 **{self.amount:,}T** 雞腿並送出網站審核。\n"
                "請把付款截圖貼在這個票口，等待客服確認。"
            ),
            view=None,
        )
        await _refresh_post_close(channel, self.customer_id)


class WorkerTipPaymentMethodView(discord.ui.View):
    def __init__(
        self,
        *,
        customer_id: int,
        ticket_channel_id: int,
        target: dict,
        amount: int,
    ):
        super().__init__(timeout=600)
        self.customer_id = int(customer_id)
        self.ticket_channel_id = int(ticket_channel_id)
        self.target = dict(target)
        self.amount = int(amount)
        self.add_item(
            WorkerTipPaymentMethodSelect(
                customer_id=self.customer_id,
                ticket_channel_id=self.ticket_channel_id,
                target=self.target,
                amount=self.amount,
            )
        )

    @discord.ui.button(
        label="修改金額",
        style=discord.ButtonStyle.secondary,
        custom_id="worker_tip_edit_amount",
        row=1,
    )
    async def modify_amount(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ):
        if interaction.user.id != self.customer_id:
            await interaction.response.send_message(
                "只有這張票口的老闆可以修改雞腿金額。",
                ephemeral=True,
            )
            return

        await interaction.response.send_modal(
            WorkerTipAmountEditModal(
                customer_id=self.customer_id,
                ticket_channel_id=self.ticket_channel_id,
                target=self.target,
                amount=self.amount,
            )
        )


class WorkerTipPaymentConfirmView(discord.ui.View):
    def __init__(self, *, tip_id: int, customer_id: int):
        super().__init__(timeout=None)
        self.tip_id = int(tip_id)
        self.customer_id = int(customer_id)

    @discord.ui.button(
        label="客服確認已收款",
        style=discord.ButtonStyle.success,
        custom_id="worker_tip_confirm_paid",
    )
    async def confirm_paid(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not isinstance(interaction.user, discord.Member) or not is_customer_staff(interaction.user):
            await interaction.response.send_message("只有客服可以確認雞腿款項。", ephemeral=True)
            return

        tip_row = get_worker_tip(self.tip_id)
        if tip_row is None:
            await interaction.response.send_message("找不到這筆雞腿紀錄。", ephemeral=True)
            return

        if str(tip_row["payment_status"] or "") == "paid":
            await interaction.response.send_message("這筆雞腿已經確認付款。", ephemeral=True)
            return

        if str(tip_row["payment_status"] or "") == "cancelled":
            await interaction.response.send_message("這筆雞腿已取消。", ephemeral=True)
            return

        try:
            tip_row = mark_worker_tip_paid(self.tip_id, confirmed_by=interaction.user)
        except ValueError as exc:
            await interaction.response.send_message(str(exc), ephemeral=True)
            return

        await interaction.response.edit_message(
            content=(
                "✅ **雞腿款項已確認**\n"
                f"老闆：<@{tip_row['customer_discord_id']}>\n"
                f"指定成員：<@{tip_row['worker_discord_id']}>\n"
                f"金額：**{int(tip_row['amount'] or 0):,}T**\n"
                f"付款方式：**{tip_row['payment_method']}**\n"
                f"確認客服：{interaction.user.mention}\n\n"
                "此筆已列入指定成員的獨立雞腿薪資。"
            ),
            view=None,
        )
        await _notify_worker_tip_paid(interaction, tip_row)
        await _log_worker_tip("paid", interaction=interaction, tip_row=tip_row)
        if isinstance(interaction.channel, discord.TextChannel):
            await _refresh_post_close(
                interaction.channel,
                self.customer_id,
            )

    @discord.ui.button(
        label="取消雞腿",
        style=discord.ButtonStyle.danger,
        custom_id="worker_tip_cancel_pending",
    )
    async def cancel_tip(self, interaction: discord.Interaction, button: discord.ui.Button):
        is_customer = interaction.user.id == self.customer_id
        is_staff = isinstance(interaction.user, discord.Member) and is_customer_staff(interaction.user)

        if not is_customer and not is_staff:
            await interaction.response.send_message("只有這張單的老闆或客服可以取消待確認雞腿。", ephemeral=True)
            return

        try:
            tip_row = mark_worker_tip_cancelled(self.tip_id, cancelled_by=interaction.user)
        except ValueError as exc:
            await interaction.response.send_message(str(exc), ephemeral=True)
            return

        if tip_row is None:
            await interaction.response.send_message("找不到這筆雞腿紀錄。", ephemeral=True)
            return

        await interaction.response.edit_message(
            content=(
                "❌ **雞腿已取消**\n"
                f"老闆：<@{tip_row['customer_discord_id']}>\n"
                f"指定成員：<@{tip_row['worker_discord_id']}>\n"
                f"金額：**{int(tip_row['amount'] or 0):,}T**\n"
                f"原付款方式：**{tip_row['payment_method']}**"
            ),
            view=None,
        )
        await _log_worker_tip("cancelled", interaction=interaction, tip_row=tip_row)
        if isinstance(interaction.channel, discord.TextChannel):
            await _refresh_post_close(
                interaction.channel,
                self.customer_id,
            )
