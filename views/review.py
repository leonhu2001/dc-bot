from __future__ import annotations

import asyncio
import sqlite3
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import discord

from views.staff_profiles import refresh_staff_profile_panel_for_staff

from core.permissions import is_customer_staff
from services.ticket_archives import save_ticket_archive
from services.worker_tips import (
    configure_worker_tip_store,
    ensure_worker_tip_tables,
    get_pending_worker_tip_confirmations,
    has_pending_worker_tips,
)
from services.review_storage import (
    ensure_review_tables,
    get_review_targets,
    build_review_status,
    record_review_skip,
    record_member_review,
    get_staff_favorites,
    get_post_close_status,
    add_staff_favorite,
)
from views.worker_tips import (
    WORKER_TIP_POLICY_TEXT,
    WorkerTipMemberMenuView,
    WorkerTipPaymentConfirmView,
    configure_worker_tip_views,
)


_REVIEW_CHANNEL_ID: int | None = None
_REORDER_TICKET_CREATOR = None


def configure_review_views(*, review_channel_id: int) -> None:
    global _REVIEW_CHANNEL_ID
    _REVIEW_CHANNEL_ID = review_channel_id
    ensure_review_tables()


def configure_reorder_ticket_creator(callback) -> None:
    global _REORDER_TICKET_CREATOR
    _REORDER_TICKET_CREATOR = callback


def configure_worker_tip_callbacks(*, wallet_handler=None, log_handler=None) -> None:
    ensure_worker_tip_tables()
    configure_worker_tip_views(
        wallet_handler=wallet_handler,
        log_handler=log_handler,
        review_target_getter=get_review_targets,
        refresh_post_close_handler=refresh_post_close_panel,
    )


def get_review_channel_id() -> int:
    if _REVIEW_CHANNEL_ID is None:
        raise RuntimeError("Review views are not configured: REVIEW_CHANNEL_ID is missing")
    return _REVIEW_CHANNEL_ID


def rating_to_stars(rating_text: str) -> tuple[int | None, str | None]:
    try:
        rating = int(str(rating_text).strip())
    except ValueError:
        return None, None

    if rating < 1 or rating > 5:
        return None, None

    return rating, "⭐" * rating


def is_customer_name_public_answer(text: str | None) -> bool:
    value = str(text or "").strip().lower()
    return value in {
        "是",
        "公開",
        "公開姓名",
        "要",
        "yes",
        "y",
        "true",
        "1",
    }


def can_operate_review(interaction: discord.Interaction, customer_id: int) -> bool:
    is_customer = interaction.user.id == customer_id
    is_staff = isinstance(interaction.user, discord.Member) and is_customer_staff(interaction.user)
    return is_customer or is_staff


def _clip_post_close_value(value: str, limit: int = 1000) -> str:
    text = str(value or "").strip()
    if not text:
        return "—"
    if len(text) <= limit:
        return text
    return text[: max(1, limit - 1)].rstrip() + "…"


def build_post_close_status_embed(
    ticket_channel_id: int | str,
    customer_id: int | str,
) -> discord.Embed:
    status = get_post_close_status(ticket_channel_id, customer_id)
    targets = status["targets"]
    favorite_ids = set(status["favorite_ids"])
    tip_rows = status["tip_rows"]

    tips_by_staff: dict[str, list[sqlite3.Row]] = {}
    for row in tip_rows:
        staff_id = str(row["worker_discord_id"] or "")
        tips_by_staff.setdefault(staff_id, []).append(row)

    description_lines = [
        "這裡顯示本次服務的正式結果；操作與修改會在只有你看得到的面板中進行。"
    ]
    if status["skipped_all"]:
        description_lines.append("⏭️ 老闆已選擇不留評價。")

    embed_title = (
        str(
            targets[0].get("display_name")
            or targets[0].get("staff_id")
            or "服務成員"
        )
        if len(targets) == 1
        else "本次服務紀錄"
    )
    embed = discord.Embed(
        title=embed_title,
        description="\n".join(description_lines),
        color=discord.Color.gold(),
    )

    if not targets:
        embed.add_field(
            name="服務成員",
            value="目前找不到接單成員資料。",
            inline=False,
        )
    else:
        for item in targets[:20]:
            staff_id = str(item.get("staff_id") or "")
            name = str(item.get("display_name") or staff_id or "成員")
            lines: list[str] = []

            if item.get("reviewed"):
                rating = int(item.get("rating") or 0)
                lines.append(f"⭐ **評星**｜{'⭐' * rating}（{rating}/5）")
                comment = str(item.get("comment") or "").strip()
                lines.append(
                    "💬 **評價**｜"
                    + (_clip_post_close_value(comment, 420) if comment else "未填寫文字評價")
                )
            elif status["skipped_all"]:
                lines.append("⭐ **評星**｜已略過")
                lines.append("💬 **評價**｜已選擇不留評價")
            else:
                lines.append("⭐ **評星**｜尚未評價")
                lines.append("💬 **評價**｜尚未填寫")

            staff_tips = tips_by_staff.get(staff_id, [])
            if staff_tips:
                tip_parts: list[str] = []
                for row in staff_tips:
                    amount = int(row["amount"] or 0)
                    tip_status = str(row["payment_status"] or "")
                    if tip_status == "paid":
                        label = "✅ 已付款"
                    elif tip_status == "pending_review":
                        label = "⏳ 待客服確認"
                    else:
                        label = "⏳ 處理中"
                    tip_parts.append(f"{amount:,}T {label}")
                lines.append("🍗 **雞腿**｜" + "、".join(tip_parts))
            else:
                lines.append("🍗 **雞腿**｜尚未加")

            lines.append(
                "❤️ **收藏**｜"
                + ("已收藏" if staff_id in favorite_ids else "尚未收藏")
            )

            embed.add_field(
                name=name,
                value=_clip_post_close_value("\n".join(lines)),
                inline=False,
            )

    paid_total = int(status["tip_paid_total"] or 0)
    pending_total = int(status["tip_pending_total"] or 0)
    if paid_total or pending_total:
        totals: list[str] = []
        if paid_total:
            totals.append(f"已付款 {paid_total:,}T")
        if pending_total:
            totals.append(f"待確認 {pending_total:,}T")
        embed.add_field(
            name="雞腿總覽",
            value="｜".join(totals),
            inline=False,
        )

    embed.set_footer(text="公開 Embed = 正式結果｜私人面板 = 選擇、預覽與修改")
    return embed

def _is_post_close_panel_message(message: discord.Message) -> bool:
    for row in getattr(message, "components", []) or []:
        for child in getattr(row, "children", []) or []:
            if getattr(child, "custom_id", None) == "review_leave_button":
                return True
    return False


async def refresh_post_close_panel(
    channel: discord.TextChannel | None,
    customer_id: int | str,
) -> bool:
    if not isinstance(channel, discord.TextChannel):
        return False

    try:
        panel_message = None
        async for message in channel.history(limit=100):
            if _is_post_close_panel_message(message):
                panel_message = message
                break

        if panel_message is None:
            return False

        await panel_message.edit(
            embed=build_post_close_status_embed(
                channel.id,
                customer_id,
            )
        )
        return True
    except (discord.Forbidden, discord.NotFound, discord.HTTPException):
        return False
    except Exception as exc:
        print(
            f"[post-close-status] refresh failed "
            f"ticket_channel_id={channel.id}: {type(exc).__name__}: {exc}"
        )
        return False


def build_reorder_summary(order, targets: list[dict], order_content: str | None = None) -> str:
    if order is None:
        base_lines = [
            "找不到網站訂單資料，請客服依照票口內容協助再約。",
        ]
    else:
        base_lines = [
            f"訂單：WEB-{order['id']}",
            f"分類：{order['category'] or '未記錄'}",
            f"項目：{order['item'] or '未記錄'}",
            f"數量：{order['quantity'] or 1}",
            f"原金額：{order['amount'] or 0}",
            f"付款方式：{order['payment_method'] or '未記錄'}",
        ]

        note = str(order["note"] or "").strip()
        if note:
            base_lines.append(f"原備註：{note}")

    if order_content:
        base_lines.append(f"票口內容：{str(order_content).strip()}")

    if targets:
        base_lines.append("")
        base_lines.append("本次接單成員：")
        for target in targets:
            base_lines.append(f"- {_target_label(target)}")
    else:
        base_lines.append("")
        base_lines.append("本次接單成員：未找到網站接單資料")

    return "\n".join(base_lines)


def _target_label(target: dict) -> str:
    name = str(target.get("display_name") or target.get("staff_id") or "成員")
    staff_id = str(target.get("staff_id") or "")
    if staff_id:
        return f"{name}｜<@{staff_id}>"
    return name


async def _send_review_channel_embed(
    *,
    guild: discord.Guild,
    customer_id: int,
    target: dict,
    rating: int,
    comment: str,
    customer_name_public: bool,
    order_content: str | None,
) -> None:
    """評價只寫入網站 DB，不再轉發到 Discord 評價頻道。

    舊的 REVIEW_CHANNEL_ID 保留給相容設定用，但這裡不再發訊息，
    之後刪除舊評價頻道也不會影響結單後評價流程。
    """
    return


def _review_draft_preview(
    *,
    target: dict,
    rating: int,
    comment: str,
    customer_name_public: bool,
) -> str:
    name = str(target.get("display_name") or target.get("staff_id") or "成員")
    comment_text = str(comment or "").strip() or "未填寫文字評價"
    privacy = "公開老闆姓名" if customer_name_public else "匿名"
    return (
        f"**評價預覽｜{name}**\n\n"
        f"⭐ 評星：**{rating}/5**\n"
        f"💬 評價：{comment_text}\n"
        f"👤 顯示方式：{privacy}\n\n"
        "確認後才會正式寫入評價並更新公開 Embed。"
    )


class ReviewDraftConfirmView(discord.ui.View):
    def __init__(
        self,
        *,
        customer_id: int,
        ticket_channel_id: int,
        order_content: str | None,
        target: dict,
        customer_display_name: str,
        customer_name_public: bool,
        rating: int,
        comment: str,
    ):
        super().__init__(timeout=900)
        self.customer_id = int(customer_id)
        self.ticket_channel_id = int(ticket_channel_id)
        self.order_content = order_content
        self.target = dict(target)
        self.customer_display_name = str(customer_display_name or customer_id)
        self.customer_name_public = bool(customer_name_public)
        self.rating = int(rating)
        self.comment = str(comment or "")

    def preview_text(self) -> str:
        return _review_draft_preview(
            target=self.target,
            rating=self.rating,
            comment=self.comment,
            customer_name_public=self.customer_name_public,
        )

    @discord.ui.button(
        label="確認送出",
        style=discord.ButtonStyle.success,
        custom_id="review_draft_confirm",
        row=0,
    )
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not can_operate_review(interaction, self.customer_id):
            await interaction.response.send_message(
                "只有這張票口的點單顧客或客服可以送出評價。",
                ephemeral=True,
            )
            return

        guild = interaction.guild
        if guild is None:
            await interaction.response.send_message(
                "這個功能只能在伺服器內使用。",
                ephemeral=True,
            )
            return

        order, _targets = get_review_targets(self.ticket_channel_id)
        ok, message = record_member_review(
            order=order,
            ticket_channel_id=self.ticket_channel_id,
            staff_id=str(self.target.get("staff_id") or ""),
            staff_display_name=str(
                self.target.get("display_name")
                or self.target.get("staff_id")
                or ""
            ),
            customer_id=self.customer_id,
            customer_display_name=self.customer_display_name,
            customer_name_public=self.customer_name_public,
            rating=self.rating,
            comment=self.comment,
            order_content=self.order_content,
        )

        if not ok:
            await interaction.response.send_message(message, ephemeral=True)
            return

        await interaction.response.defer()

        await refresh_staff_profile_panel_for_staff(
            guild,
            str(self.target.get("staff_id") or ""),
            reason="review_submitted",
        )

        await _send_review_channel_embed(
            guild=guild,
            customer_id=self.customer_id,
            target=self.target,
            rating=self.rating,
            comment=self.comment,
            customer_name_public=self.customer_name_public,
            order_content=self.order_content,
        )

        _order, statuses, _skipped_all = build_review_status(
            self.ticket_channel_id,
            self.customer_id,
        )
        all_done = bool(statuses) and all(
            bool(item.get("reviewed"))
            for item in statuses
        )

        if isinstance(interaction.channel, discord.TextChannel):
            await refresh_post_close_panel(
                interaction.channel,
                self.customer_id,
            )

        try:
            if all_done:
                await interaction.delete_original_response()
            else:
                lines = ["請選擇下一位要評價的成員：", ""]
                for item in statuses:
                    state = (
                        f"已評價 ⭐ {item['rating']}"
                        if item.get("reviewed")
                        else "尚未評價"
                    )
                    lines.append(f"{_target_label(item)}｜{state}")

                await interaction.edit_original_response(
                    content="\n".join(lines),
                    view=MemberReviewMenuView(
                        customer_id=self.customer_id,
                        ticket_channel_id=self.ticket_channel_id,
                        order_content=self.order_content,
                    ),
                )
        except (discord.NotFound, discord.HTTPException):
            pass

    @discord.ui.button(
        label="修改",
        style=discord.ButtonStyle.secondary,
        custom_id="review_draft_edit",
        row=0,
    )
    async def modify(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not can_operate_review(interaction, self.customer_id):
            await interaction.response.send_message(
                "只有這張票口的點單顧客或客服可以修改評價。",
                ephemeral=True,
            )
            return

        await interaction.response.send_modal(
            ReviewDraftEditModal(draft_view=self)
        )


class ReviewDraftEditModal(discord.ui.Modal, title="修改評價預覽"):
    def __init__(self, *, draft_view: ReviewDraftConfirmView):
        super().__init__(timeout=600)
        self.draft_view = draft_view

        self.rating_input = discord.ui.TextInput(
            label="星等",
            default=str(draft_view.rating),
            placeholder="請輸入 1～5",
            required=True,
            max_length=1,
        )
        self.comment_input = discord.ui.TextInput(
            label="評語",
            default=str(draft_view.comment or ""),
            placeholder="可空白；例如：報點清楚、很穩、很有耐心",
            style=discord.TextStyle.paragraph,
            required=False,
            max_length=1000,
        )
        self.public_input = discord.ui.TextInput(
            label="是否公開老闆姓名",
            default="是" if draft_view.customer_name_public else "否",
            placeholder="輸入「是」才顯示姓名；否則匿名",
            required=False,
            max_length=10,
        )
        self.add_item(self.rating_input)
        self.add_item(self.comment_input)
        self.add_item(self.public_input)

    async def on_submit(self, interaction: discord.Interaction):
        rating_number, _stars = rating_to_stars(self.rating_input.value)
        if rating_number is None:
            await interaction.response.send_message(
                "星等請輸入 1～5 的數字。",
                ephemeral=True,
            )
            return

        self.draft_view.rating = int(rating_number)
        self.draft_view.comment = str(self.comment_input.value or "")
        self.draft_view.customer_name_public = (
            interaction.user.id == self.draft_view.customer_id
            and is_customer_name_public_answer(self.public_input.value)
        )

        await interaction.response.edit_message(
            content=self.draft_view.preview_text(),
            view=self.draft_view,
        )


class MemberReviewModal(discord.ui.Modal, title="評價指定成員｜先預覽再送出"):
    rating = discord.ui.TextInput(
        label="星等",
        placeholder="請輸入 1～5",
        required=True,
        max_length=1,
    )
    comment = discord.ui.TextInput(
        label="評語",
        placeholder="可空白；例如：報點清楚、很穩、很有耐心",
        style=discord.TextStyle.paragraph,
        required=False,
        max_length=1000,
    )
    customer_name_public_answer = discord.ui.TextInput(
        label="是否公開老闆姓名",
        placeholder="輸入「是」才顯示姓名；空白或「否」=匿名",
        required=False,
        max_length=10,
    )

    def __init__(
        self,
        *,
        customer_id: int,
        ticket_channel_id: int,
        order_content: str | None,
        target: dict,
    ):
        super().__init__()
        self.customer_id = customer_id
        self.ticket_channel_id = ticket_channel_id
        self.order_content = order_content
        self.target = target

    async def on_submit(self, interaction: discord.Interaction):
        if not can_operate_review(interaction, self.customer_id):
            await interaction.response.send_message(
                "只有這張票口的點單顧客或客服可以留下評價。",
                ephemeral=True,
            )
            return

        rating_number, _stars = rating_to_stars(self.rating.value)
        if rating_number is None:
            await interaction.response.send_message(
                "星等請輸入 1～5 的數字。",
                ephemeral=True,
            )
            return

        order, _targets = get_review_targets(self.ticket_channel_id)
        order_customer_display_name = (
            str(order["customer_display_name"] or "").strip()
            if order is not None and "customer_display_name" in order.keys()
            else ""
        )
        customer_display_name = str(
            order_customer_display_name
            or getattr(interaction.user, "display_name", None)
            or getattr(interaction.user, "name", None)
            or self.customer_id
        ).strip()

        customer_name_public = (
            interaction.user.id == self.customer_id
            and is_customer_name_public_answer(
                self.customer_name_public_answer.value
            )
        )

        preview_view = ReviewDraftConfirmView(
            customer_id=self.customer_id,
            ticket_channel_id=self.ticket_channel_id,
            order_content=self.order_content,
            target=self.target,
            customer_display_name=customer_display_name,
            customer_name_public=customer_name_public,
            rating=int(rating_number),
            comment=str(self.comment.value or ""),
        )

        await interaction.response.edit_message(
            content=preview_view.preview_text(),
            view=preview_view,
        )




































class MemberReviewSelect(discord.ui.Select):
    def __init__(self, *, customer_id: int, ticket_channel_id: int, order_content: str | None, targets: list[dict]):
        self.customer_id = customer_id
        self.ticket_channel_id = ticket_channel_id
        self.order_content = order_content
        self.targets = targets

        options = []
        for target in targets[:25]:
            staff_id = str(target.get("staff_id") or "")
            reviewed = bool(target.get("reviewed"))
            label = str(target.get("display_name") or staff_id or "成員")[:80]
            desc = "已評價" if reviewed else "尚未評價"
            options.append(
                discord.SelectOption(
                    label=label,
                    value=staff_id,
                    description=desc,
                    emoji="✅" if reviewed else "⭐",
                )
            )

        super().__init__(
            placeholder="選擇要評價的成員",
            min_values=1,
            max_values=1,
            options=options,
            disabled=not bool(options),
        )

    async def callback(self, interaction: discord.Interaction):
        if not can_operate_review(interaction, self.customer_id):
            await interaction.response.send_message("只有這張票口的點單顧客或客服可以留下評價。", ephemeral=True)
            return

        staff_id = str(self.values[0])
        target = next((item for item in self.targets if str(item.get("staff_id")) == staff_id), None)

        if target is None:
            await interaction.response.send_message("找不到這位成員，請重新打開評價面板。", ephemeral=True)
            return

        if target.get("reviewed"):
            await interaction.response.send_message("這位成員已經評價過了。", ephemeral=True)
            return

        await interaction.response.send_modal(
            MemberReviewModal(
                customer_id=self.customer_id,
                ticket_channel_id=self.ticket_channel_id,
                order_content=self.order_content,
                target=target,
            )
        )


class MemberReviewMenuView(discord.ui.View):
    def __init__(self, *, customer_id: int, ticket_channel_id: int, order_content: str | None = None):
        super().__init__(timeout=900)
        self.customer_id = customer_id
        self.ticket_channel_id = ticket_channel_id
        self.order_content = order_content

        _order, targets, skipped_all = build_review_status(ticket_channel_id, customer_id)
        if targets and not skipped_all:
            self.add_item(
                MemberReviewSelect(
                    customer_id=customer_id,
                    ticket_channel_id=ticket_channel_id,
                    order_content=order_content,
                    targets=targets,
                )
            )



class FavoriteCurrentMembersSelect(discord.ui.Select):
    def __init__(self, *, customer_id: int, targets: list[dict]):
        self.customer_id = customer_id
        self.targets = targets
        favorite_ids = get_staff_favorites(
            customer_id,
            [str(item.get("staff_id") or "") for item in targets],
        )

        options = []
        for target in targets[:25]:
            staff_id = str(target.get("staff_id") or "")
            if not staff_id:
                continue

            already = staff_id in favorite_ids
            label = str(target.get("display_name") or staff_id or "成員")[:80]
            options.append(
                discord.SelectOption(
                    label=label,
                    value=staff_id,
                    description="已收藏" if already else "加入我的收藏",
                    emoji="❤️" if already else None,
                    default=False,
                )
            )

        super().__init__(
            placeholder="選擇要收藏的本次成員",
            min_values=1,
            max_values=max(1, min(len(options), 25)),
            options=options,
            disabled=not bool(options),
        )

    async def callback(self, interaction: discord.Interaction):
        if interaction.user.id != self.customer_id:
            await interaction.response.send_message("只有這張票口的老闆可以收藏成員。", ephemeral=True)
            return

        await interaction.response.defer()

        selected_ids = {str(value) for value in self.values}

        for target in self.targets:
            staff_id = str(target.get("staff_id") or "")
            if staff_id not in selected_ids:
                continue

            display_name = str(target.get("display_name") or staff_id)
            add_staff_favorite(
                customer_id=self.customer_id,
                staff_id=staff_id,
                staff_display_name=display_name,
                source="post_close",
            )

        guild = interaction.guild
        if guild is not None:
            for staff_id in selected_ids:
                await refresh_staff_profile_panel_for_staff(
                    guild,
                    staff_id,
                    reason="post_close_favorite",
                )

        if isinstance(interaction.channel, discord.TextChannel):
            await refresh_post_close_panel(
                interaction.channel,
                self.customer_id,
            )

        # 收藏結果已反映在公開 Embed，收掉私人收藏選單。
        try:
            await interaction.delete_original_response()
        except (discord.NotFound, discord.HTTPException):
            pass


class FavoriteCurrentMembersView(discord.ui.View):
    def __init__(self, *, customer_id: int, targets: list[dict]):
        super().__init__(timeout=300)
        self.customer_id = customer_id
        self.targets = targets

        if targets:
            self.add_item(FavoriteCurrentMembersSelect(customer_id=customer_id, targets=targets))


def _taipei_iso(value: datetime | None = None) -> str:
    current = value or datetime.now(tz=ZoneInfo("Asia/Taipei"))
    if current.tzinfo is None:
        current = current.replace(tzinfo=ZoneInfo("Asia/Taipei"))
    else:
        current = current.astimezone(ZoneInfo("Asia/Taipei"))
    return current.isoformat(timespec="seconds")


async def archive_ticket_channel(
    channel: discord.TextChannel,
    *,
    customer_id: int,
    closed_by: discord.Member | discord.User,
) -> int:
    order, _targets = get_review_targets(channel.id)

    customer_member = channel.guild.get_member(int(customer_id))
    customer_name = (
        str(order["customer_display_name"] or "").strip()
        if order is not None and "customer_display_name" in order.keys()
        else ""
    )
    if not customer_name:
        customer_name = str(
            getattr(customer_member, "display_name", None)
            or getattr(customer_member, "name", None)
            or customer_id
        )

    cs_id = ""
    cs_name = ""
    if order is not None:
        if "customer_service_discord_id" in order.keys():
            cs_id = str(order["customer_service_discord_id"] or "").strip()
        if "customer_service_display_name" in order.keys():
            cs_name = str(order["customer_service_display_name"] or "").strip()

    if not cs_id and isinstance(closed_by, discord.Member) and is_customer_staff(closed_by):
        cs_id = str(closed_by.id)
        cs_name = str(
            getattr(closed_by, "display_name", None)
            or getattr(closed_by, "name", None)
            or closed_by.id
        )

    messages: list[dict] = []
    async for message in channel.history(limit=None, oldest_first=True):
        attachments = [
            {
                "filename": str(attachment.filename or "附件"),
                "url": str(attachment.url),
                "content_type": str(attachment.content_type or ""),
                "size": int(attachment.size or 0),
            }
            for attachment in message.attachments
        ]

        embeds = []
        for embed in message.embeds:
            try:
                embeds.append(embed.to_dict())
            except Exception:
                continue

        messages.append(
            {
                "discord_message_id": str(message.id),
                "author_discord_id": str(getattr(message.author, "id", "") or ""),
                "author_display_name": str(
                    getattr(message.author, "display_name", None)
                    or getattr(message.author, "global_name", None)
                    or getattr(message.author, "name", None)
                    or getattr(message.author, "id", "未知使用者")
                ),
                "author_is_bot": bool(getattr(message.author, "bot", False)),
                "content": str(message.content or ""),
                "attachments": attachments,
                "embeds": embeds,
                "reply_to_message_id": str(
                    getattr(getattr(message, "reference", None), "message_id", "")
                    or ""
                ),
                "created_at": _taipei_iso(message.created_at),
                "edited_at": (
                    _taipei_iso(message.edited_at)
                    if message.edited_at is not None
                    else ""
                ),
            }
        )

    now_text = _taipei_iso()
    order_id = int(order["id"]) if order is not None else None
    order_no = (
        str(order["bot_order_no"] or "").strip()
        if order is not None and "bot_order_no" in order.keys()
        else ""
    )

    return save_ticket_archive(
        ticket_channel_id=channel.id,
        ticket_channel_name=channel.name,
        order_id=order_id,
        order_no=order_no,
        customer_discord_id=customer_id,
        customer_display_name=customer_name,
        customer_service_discord_id=cs_id,
        customer_service_display_name=cs_name,
        closed_by_discord_id=getattr(closed_by, "id", ""),
        closed_by_display_name=str(
            getattr(closed_by, "display_name", None)
            or getattr(closed_by, "name", None)
            or getattr(closed_by, "id", "未知")
        ),
        closed_at=now_text,
        archived_at=now_text,
        messages=messages,
    )


class ConfirmCloseTicketView(discord.ui.View):
    def __init__(self, *, customer_id: int):
        super().__init__(timeout=60)
        self.customer_id = customer_id

    @discord.ui.button(label="確認關閉票口", style=discord.ButtonStyle.danger, custom_id="post_close_confirm_delete_ticket")
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        is_customer = interaction.user.id == self.customer_id
        is_staff = isinstance(interaction.user, discord.Member) and is_customer_staff(interaction.user)

        if not is_customer and not is_staff:
            await interaction.response.send_message("只有這張票口的點單顧客或客服可以關閉票口。", ephemeral=True)
            return

        channel = interaction.channel
        if not isinstance(channel, discord.TextChannel):
            await interaction.response.send_message("無法確認目前票口頻道。", ephemeral=True)
            return

        if has_pending_worker_tips(channel.id):
            await interaction.response.send_message(
                "這張票口還有待客服確認的雞腿款項。請先完成確認或取消雞腿，再關閉票口。",
                ephemeral=True,
            )
            return

        # 關閉前一定先封存；封存失敗就保留票口，避免爭議紀錄一起消失。
        await interaction.response.defer(ephemeral=True)

        try:
            archive_id = await archive_ticket_channel(
                channel,
                customer_id=self.customer_id,
                closed_by=interaction.user,
            )
        except Exception as exc:
            print(
                f"[ticket-archive] failed channel_id={channel.id}: "
                f"{type(exc).__name__}: {exc}"
            )
            await interaction.followup.send(
                "票口聊天紀錄封存失敗，因此本次沒有刪除票口。請客服稍後重試。",
                ephemeral=True,
            )
            return

        try:
            await channel.send(
                (
                    f"{interaction.user.mention} 已確認關閉票口。"
                    f"聊天紀錄已封存（紀錄 #{archive_id}），頻道將在 3 秒後刪除。"
                ),
                allowed_mentions=discord.AllowedMentions(
                    users=True,
                    roles=False,
                    everyone=False,
                ),
            )
        except discord.HTTPException:
            pass

        await asyncio.sleep(3)
        await channel.delete(
            reason=f"Closed post-order ticket by {interaction.user}"
        )

    @discord.ui.button(label="先不要關閉", style=discord.ButtonStyle.secondary, custom_id="post_close_keep_ticket")
    async def keep(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message("已保留票口。", ephemeral=True)


class ReviewButtonView(discord.ui.View):
    def __init__(self, customer_id: int, order_content: str | None = None):
        super().__init__(timeout=86400)
        self.customer_id = customer_id
        self.order_content = order_content
        ensure_review_tables()

    @discord.ui.button(
        label="⭐ 評價本次服務",
        style=discord.ButtonStyle.success,
        custom_id="review_leave_button",
        row=0,
    )
    async def leave_review(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not can_operate_review(interaction, self.customer_id):
            await interaction.response.send_message("只有這張票口的點單顧客或客服可以留下評價。", ephemeral=True)
            return

        channel = interaction.channel
        if not isinstance(channel, discord.TextChannel):
            await interaction.response.send_message("無法確認目前票口頻道。", ephemeral=True)
            return

        order, targets, skipped_all = build_review_status(channel.id, self.customer_id)

        if skipped_all:
            await interaction.response.send_message("這張單已經選擇不留評價。", ephemeral=True)
            return

        if not targets:
            await interaction.response.send_message(
                "這張單目前找不到接單成員資料，因此無法分別評價。\n"
                "可以請客服確認網站接單資料，或直接按「不留評價 / 關閉票口」。",
                ephemeral=True,
            )
            return

        lines = [
            "請選擇要評價的成員：",
            "",
        ]

        for item in targets:
            status = f"已評價 ⭐ {item['rating']}" if item.get("reviewed") else "尚未評價"
            lines.append(f"{_target_label(item)}｜{status}")

        await interaction.response.send_message(
            "\n".join(lines),
            ephemeral=True,
            view=MemberReviewMenuView(
                customer_id=self.customer_id,
                ticket_channel_id=channel.id,
                order_content=self.order_content,
            ),
        )

    @discord.ui.button(
        label="🍗 加雞腿",
        style=discord.ButtonStyle.primary,
        custom_id="review_worker_tip_button",
        row=0,
    )
    async def add_worker_tip(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.customer_id:
            await interaction.response.send_message("只有這張票口的老闆可以加雞腿。", ephemeral=True)
            return

        channel = interaction.channel
        if not isinstance(channel, discord.TextChannel):
            await interaction.response.send_message("無法確認目前票口頻道。", ephemeral=True)
            return

        _order, targets = get_review_targets(channel.id)

        if not targets:
            await interaction.response.send_message(
                "這張單目前找不到接單成員資料，因此無法指定雞腿對象。請客服先確認網站接單資料。",
                ephemeral=True,
            )
            return

        lines = [
            WORKER_TIP_POLICY_TEXT,
            "",
            "**請從下拉清單選擇要加雞腿的成員：**",
        ]

        for item in targets:
            lines.append(f"• {_target_label(item)}")

        await interaction.response.send_message(
            "\n".join(lines),
            ephemeral=True,
            view=WorkerTipMemberMenuView(
                customer_id=self.customer_id,
                ticket_channel_id=channel.id,
                targets=targets,
            ),
        )

    @discord.ui.button(
        label="不留評價",
        style=discord.ButtonStyle.secondary,
        custom_id="review_skip_button",
        row=0,
    )
    async def skip_review(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not can_operate_review(interaction, self.customer_id):
            await interaction.response.send_message("只有這張票口的點單顧客或客服可以操作。", ephemeral=True)
            return

        channel = interaction.channel
        if not isinstance(channel, discord.TextChannel):
            await interaction.response.send_message("無法確認目前票口頻道。", ephemeral=True)
            return

        order, targets = get_review_targets(channel.id)
        record_review_skip(
            order=order,
            ticket_channel_id=channel.id,
            dispatch_message_id=order["dispatch_message_id"] if order is not None else None,
            customer_id=self.customer_id,
            targets=targets,
        )

        for child in self.children:
            if getattr(child, "custom_id", "") in {"review_leave_button", "review_skip_button"}:
                child.disabled = True

        # 不另外留下私人成功訊息；公開 Embed 會直接顯示「已選擇不留評價」。
        await interaction.response.defer()

        try:
            await interaction.message.edit(view=self)
        except discord.HTTPException:
            pass

        try:
            await channel.send(
                f"{interaction.user.mention} 已選擇不留評價。需要時可按「關閉票口」。",
                allowed_mentions=discord.AllowedMentions(users=True, roles=False, everyone=False),
            )
        except discord.HTTPException:
            pass

        await refresh_post_close_panel(channel, self.customer_id)

    @discord.ui.button(
        label="❤️ 收藏本次成員",
        style=discord.ButtonStyle.secondary,
        custom_id="review_favorite_members_button",
        row=1,
    )
    async def favorite_members(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.customer_id:
            await interaction.response.send_message("只有這張票口的老闆可以收藏成員。", ephemeral=True)
            return

        channel = interaction.channel
        if not isinstance(channel, discord.TextChannel):
            await interaction.response.send_message("無法確認目前票口頻道。", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)

        _order, targets = get_review_targets(channel.id)

        if not targets:
            await interaction.followup.send(
                "這張單目前找不到接單成員資料，暫時無法收藏本次成員。",
                ephemeral=True,
            )
            return

        favorite_ids = get_staff_favorites(
            self.customer_id,
            [str(item.get("staff_id") or "") for item in targets],
        )

        lines = [
            "選擇要加入收藏的本次成員：",
            "",
        ]

        for item in targets:
            staff_id = str(item.get("staff_id") or "")
            status = "已收藏" if staff_id in favorite_ids else "尚未收藏"
            lines.append(f"{_target_label(item)}｜{status}")

        await interaction.followup.send(
            "\n".join(lines),
            ephemeral=True,
            view=FavoriteCurrentMembersView(
                customer_id=self.customer_id,
                targets=targets,
            ),
        )

    @discord.ui.button(
        label="🔁 再約",
        style=discord.ButtonStyle.primary,
        custom_id="review_reorder_button",
        row=1,
    )
    async def reorder(self, interaction: discord.Interaction, button: discord.ui.Button):
        # reorder_v2_direct_self_service
        if interaction.user.id != self.customer_id:
            await interaction.response.send_message(
                "只有這張票口的老闆可以使用再約。",
                ephemeral=True,
            )
            return

        channel = interaction.channel

        if not isinstance(channel, discord.TextChannel):
            await interaction.response.send_message(
                "無法確認目前票口頻道。",
                ephemeral=True,
            )
            return

        order, targets = get_review_targets(
            channel.id
        )

        if order is None:
            await interaction.response.send_message(
                "找不到這張已結單訂單的網站資料，暫時無法自動建立再約單。",
                ephemeral=True,
            )
            return

        creator = _REORDER_TICKET_CREATOR

        if creator is None:
            await interaction.response.send_message(
                "再約系統尚未完成初始化，請通知客服。",
                ephemeral=True,
            )
            return

        await interaction.response.defer(
            ephemeral=True,
            thinking=True,
        )

        try:
            result = await creator(
                interaction=interaction,
                order=order,
                targets=targets,
                order_content=self.order_content,
            )
        except Exception as exc:
            print(
                f"[reorder] create ticket failed "
                f"customer_id={self.customer_id} "
                f"ticket_channel_id={channel.id}: "
                f"{type(exc).__name__}: {exc}"
            )

            await interaction.followup.send(
                "建立再約票口失敗，請通知客服確認機器人紀錄。",
                ephemeral=True,
            )
            return

        if not isinstance(result, dict):
            await interaction.followup.send(
                "再約系統回傳資料異常，請通知客服。",
                ephemeral=True,
            )
            return

        new_channel = result.get("channel")

        if not isinstance(
            new_channel,
            discord.TextChannel,
        ):
            await interaction.followup.send(
                "沒有成功建立再約票口，請通知客服。",
                ephemeral=True,
            )
            return

        created = bool(
            result.get("created", True)
        )

        warning = str(
            result.get("warning")
            or ""
        ).strip()

        if created:
            text = (
                f"已建立再約票口：{new_channel.mention}\n"
                "系統已先帶入上一張單的內容，你可以直接進去修改。\n"
                "確認完成後由客服按「客服確認送出」。"
            )
        else:
            text = (
                f"你已經有一張這筆訂單的再約草稿：{new_channel.mention}\n"
                "直接進去修改即可，不會重複建立票口。"
            )

        if warning:
            text += (
                "\n\n提醒："
                + warning
            )

        await interaction.followup.send(
            text,
            ephemeral=True,
        )


    @discord.ui.button(
        label="關閉票口",
        style=discord.ButtonStyle.danger,
        custom_id="review_close_ticket_button",
        row=1,
    )
    async def close_ticket(self, interaction: discord.Interaction, button: discord.ui.Button):
        is_customer = interaction.user.id == self.customer_id
        is_staff = isinstance(interaction.user, discord.Member) and is_customer_staff(interaction.user)

        if not is_customer and not is_staff:
            await interaction.response.send_message("只有這張票口的點單顧客或客服可以關閉票口。", ephemeral=True)
            return

        await interaction.response.send_message(
            "確定要關閉這個票口嗎？",
            ephemeral=True,
            view=ConfirmCloseTicketView(customer_id=self.customer_id),
        )
