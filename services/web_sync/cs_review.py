from __future__ import annotations

import asyncio
import re
import sqlite3
from pathlib import Path
from typing import Any, Callable

import discord

import core.permissions as permissions_runtime
from core.database import (
    delete_order_row_from_db,
    remember_order_data,
    save_bot_data,
)
from core.permissions import is_customer_staff
from services.acceptance.runtime import refresh_acceptance_dispatch_from_web_order
from services.logging_service import send_order_log
from services.order_lifecycle_runtime import (
    CANCEL_REASON_OPTIONS,
    OrderCancellationReasonSelect,
)
from services.orders import _to_int
from services.self_service_financials import _format_plain_amount
from services.web_sync.cs_presentation import (
    admin_order_workspace_url,
    build_cs_review_alert_text,
)
from services.web_sync.discord_helpers import (
    has_footer as _web_order_created_has_footer,
)
from services.web_sync.event_store import (
    load_order_created_bundle as _web_order_created_load_bundle,
)
from services.web_sync.presentation import (
    build_order_created_details as _web_order_created_details,
)
from shared.order_state import (
    PENDING_CS_DISPATCH as WEB_ORDER_PENDING_CS_DISPATCH,
    WAITING_ACCEPTANCE as WEB_ORDER_WAITING_ACCEPTANCE,
)


SELF_SERVICE_ORDER_SELECTIONS: dict[int, dict[str, Any]]
_ensure_dispatch: Callable[..., Any]
_seed_state: Callable[..., Any]


def configure_web_sync_cs_review(
    *,
    order_selections: dict[int, dict[str, Any]],
    ensure_dispatch: Callable[..., Any],
    seed_state: Callable[..., Any],
) -> None:
    """Bind the small set of runtime callbacks/state used by the CS review UI."""
    global SELF_SERVICE_ORDER_SELECTIONS, _ensure_dispatch, _seed_state

    SELF_SERVICE_ORDER_SELECTIONS = order_selections
    _ensure_dispatch = ensure_dispatch
    _seed_state = seed_state


def _web_dashboard_db_path_for_bot() -> str:
    return str(Path(__file__).resolve().parents[2] / "web_dashboard.db")


# zYao 3C3B2R3 CS review gate v1


def _web_cs_order_id_from_channel(
    channel,
):

    topic = str(
        getattr(
            channel,
            "topic",
            "",
        )
        or ""
    )


    match = re.search(
        r"(?:^|;)"
        r"web_order_id="
        r"(\d+)"
        r"(?:;|$)",
        topic,
    )


    if not match:

        return None


    return int(
        match.group(1)
    )


def _web_cs_set_status(
    order_id: int,
    status: str,
    *,
    cs_user=None,
):
    """更新官網訂單 bridge 狀態；所有 lifecycle 變更統一走中央狀態機。"""
    from sqlalchemy import text

    from shared.db import engine
    from shared.order_state import transition_order_state_in_connection

    cs_id = ""
    cs_name = ""

    if cs_user is not None:
        cs_id = str(
            getattr(
                cs_user,
                "id",
                "",
            )
            or ""
        ).strip()

        cs_name = str(
            getattr(
                cs_user,
                "display_name",
                None,
            )
            or getattr(
                cs_user,
                "global_name",
                None,
            )
            or getattr(
                cs_user,
                "name",
                None,
            )
            or cs_id
        ).strip()

    with engine.begin() as conn:
        transition_order_state_in_connection(
            conn,
            order_id=int(order_id),
            target_status=str(status),
            source=(
                "website_cs_dispatch"
                if cs_user is not None
                else "website_cs_lifecycle"
            ),
            reason=f"客服流程更新狀態為 {status}",
            actor_discord_id=cs_id or None,
        )

        if cs_user is not None:
            conn.execute(
                text(
                    """
                    UPDATE web_orders
                    SET customer_service_discord_id = :cs_id,
                        customer_service_display_name = :cs_name,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE id = :order_id
                    """
                ),
                {
                    "cs_id": cs_id or None,
                    "cs_name": cs_name or None,
                    "order_id": int(order_id),
                },
            )


async def _web_cs_ensure_review_panel(
    order_id: int,
    bundle: dict,
    ticket_channel:
        discord.TextChannel,
):

    footer_text = (
        f"WEB-{order_id}"
        "｜客服送單前"
    )


    if await _web_order_created_has_footer(
        ticket_channel,
        footer_text,
        limit=40,
    ):

        return


    order = (
        bundle.get(
            "order"
        )
        or {}
    )


    details = (
        _web_order_created_details(
            bundle
        )
    )


    customer_id = _to_int(
        order.get(
            "customer_discord_id"
        ),
        None,
    )


    amount = _to_int(
        order.get(
            "customer_pay_amount"
        ),
        details.get(
            "amount"
        )
        or 0,
    )


    amount = int(
        amount
        or 0
    )


    embed = discord.Embed(
        title=(
            "網站訂單｜"
            "等待客服確認"
        ),
        description=(
            "官網訂單已建立完成。\n\n"
            "目前尚未送到派單頻道，"
            "也尚未開放任何人接單。\n"
            "請客服確認內容後再送單。"
        ),
        color=discord.Color.gold(),
    )


    embed.add_field(
        name="網站訂單",
        value=f"WEB-{order_id}",
        inline=True,
    )


    embed.add_field(
        name="顧客",
        value=(
            f"<@{customer_id}>"
            if customer_id
            else "未紀錄"
        ),
        inline=True,
    )


    embed.add_field(
        name="項目",
        value=(
            f"{details.get('category_label') or '未紀錄'}"
            f"｜"
            f"{details.get('item') or '未紀錄'}"
        ),
        inline=False,
    )


    embed.add_field(
        name="數量",
        value=str(
            details.get(
                "quantity"
            )
            or 1
        ),
        inline=True,
    )


    amount_text = _format_plain_amount(amount)


    embed.add_field(
        name="顧客應付",
        value=amount_text,
        inline=True,
    )


    embed.add_field(
        name="付款方式",
        value=(
            "尚未選擇\n"
            "人員接滿後於 Discord 選擇"
        ),
        inline=False,
    )


    specified = (
        details.get(
            "specified_staff_ids"
        )
        or []
    )


    if specified:

        embed.add_field(
            name="指定人員",
            value="、".join(
                f"<@{staff_id}>"
                for staff_id
                in specified
            )[:1024],
            inline=False,
        )


    extra = str(
        details.get(
            "extra_requirements"
        )
        or ""
    ).strip()


    if extra:

        embed.add_field(
            name="附加需求",
            value=extra[:1024],
            inline=False,
        )


    terms = str(
        details.get(
            "service_terms_version"
        )
        or ""
    ).strip()


    if terms:

        embed.add_field(
            name="服務規章",
            value=(
                f"已同意｜{terms}"
            ),
            inline=False,
        )


    embed.add_field(
        name="Web 後台",
        value=(
            f"[開啟 WEB-{order_id}]"
            f"({admin_order_workspace_url(order_id)})"
        ),
        inline=False,
    )


    embed.set_footer(
        text=footer_text
    )


    customer_service_role_id = getattr(
        permissions_runtime,
        "CUSTOMER_ROLE_ID",
        None,
    )


    await ticket_channel.send(
        content=build_cs_review_alert_text(
            order_id,
            customer_service_role_id,
        ),
        embed=embed,
        view=WebsiteOrderCsConfirmView(),
        allowed_mentions=(
            discord.AllowedMentions(
                users=True,
                roles=bool(customer_service_role_id),
                everyone=False,
            )
        ),
    )


class WebsiteOrderCsConfirmView(
    discord.ui.View
):

    def __init__(
        self,
    ):

        super().__init__(
            timeout=None
        )


    @discord.ui.button(
        label="客服確認送單",
        style=(
            discord.ButtonStyle.success
        ),
        custom_id=(
            "website_order_"
            "cs_confirm_dispatch_v3"
        ),
    )
    async def confirm(
        self,
        interaction:
            discord.Interaction,
        button:
            discord.ui.Button,
    ):

        if (
            not isinstance(
                interaction.user,
                discord.Member,
            )
            or not is_customer_staff(
                interaction.user
            )
        ):

            await interaction.response.send_message(
                "只有客服可以確認送單。",
                ephemeral=True,
            )

            return


        if not isinstance(
            interaction.channel,
            discord.TextChannel,
        ):

            await interaction.response.send_message(
                "目前不是有效訂單票口。",
                ephemeral=True,
            )

            return


        order_id = (
            _web_cs_order_id_from_channel(
                interaction.channel
            )
        )


        if order_id is None:

            await interaction.response.send_message(
                "找不到網站訂單編號。",
                ephemeral=True,
            )

            return


        bundle = (
            _web_order_created_load_bundle(
                order_id
            )
        )


        order = (
            bundle.get(
                "order"
            )
            or {}
        )


        current_status = str(
            order.get(
                "status"
            )
            or ""
        ).lower()


        if (
            current_status
            != WEB_ORDER_PENDING_CS_DISPATCH
        ):

            await interaction.response.send_message(
                (
                    "這張訂單目前不是"
                    "等待客服確認狀態。"
                ),
                ephemeral=True,
            )

            return


        await interaction.response.defer(
            ephemeral=True
        )


        try:

            # 先放行為正式等待接單。
            _web_cs_set_status(
                order_id,
                WEB_ORDER_WAITING_ACCEPTANCE,
                cs_user=interaction.user,
            )


            bundle = (
                _web_order_created_load_bundle(
                    order_id
                )
            )


            guild = interaction.guild


            if guild is None:

                raise RuntimeError(
                    "找不到 Discord guild"
                )


            (
                dispatch_channel,
                dispatch_message,
            ) = (
                await _ensure_dispatch(
                    guild,
                    order_id,
                    bundle,
                    interaction.channel,
                )
            )


            # 接回原本 3C-3B seed。
            _seed_state(
                order_id,
                bundle,
                interaction.channel,
                dispatch_channel,
                dispatch_message,
            )


            # 官網沒有付款方式。
            data = (
                SELF_SERVICE_ORDER_SELECTIONS
                .setdefault(
                    interaction.channel.id,
                    {},
                )
            )


            data.pop(
                "payment_method",
                None,
            )


            data.pop(
                "website_payment_method",
                None,
            )


            data[
                "web_order_no_payment_selection"
            ] = True


            remember_order_data(
                interaction.channel.id,
                data,
            )


            save_bot_data()


            await (
                refresh_acceptance_dispatch_from_web_order(
                    guild,
                    order_id,
                )
            )


            await interaction.channel.send(
                (
                    "✅ "
                    f"{interaction.user.mention} "
                    "已確認訂單並送出等待接單。"
                ),
                allowed_mentions=(
                    discord.AllowedMentions(
                        users=True,
                        roles=False,
                        everyone=False,
                    )
                ),
            )


            if interaction.message:

                try:

                    await interaction.message.edit(
                        view=None
                    )

                except discord.HTTPException:

                    pass


            await interaction.followup.send(
                "已確認並送出等待接單。",
                ephemeral=True,
            )


        except Exception as exc:

            # 派單失敗就恢復客服確認狀態，
            # 讓客服可以重試。恢復失敗時不可再對客服宣稱已恢復。
            rollback_error = None

            try:

                _web_cs_set_status(
                    order_id,
                    WEB_ORDER_PENDING_CS_DISPATCH,
                )

            except Exception as rollback_exc:

                rollback_error = rollback_exc

                print(
                    "[web-order-create] "
                    f"CS dispatch rollback failed "
                    f"WEB-{order_id}: "
                    f"{type(rollback_exc).__name__}: "
                    f"{rollback_exc}",
                    flush=True,
                )


            print(
                "[web-order-create] "
                f"CS dispatch failed "
                f"WEB-{order_id}: "
                f"{type(exc).__name__}: "
                f"{exc}",
                flush=True,
            )


            if rollback_error is None:

                followup_message = (
                    "送單失敗，"
                    "訂單已恢復等待客服確認。"
                )

            else:

                followup_message = (
                    "送單失敗，而且訂單狀態沒有成功恢復。"
                    f"請先不要重複操作 WEB-{order_id}，"
                    "通知總管檢查訂單狀態。"
                )


            await interaction.followup.send(
                followup_message,
                ephemeral=True,
            )


    # MAWAN_R12_WEBSITE_PENDING_CANCEL

    @discord.ui.button(
        label="取消訂單",
        style=discord.ButtonStyle.danger,
        custom_id="website_order_pending_cancel",
        row=1,
    )
    async def cancel_pending_order(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ):
        # MAWAN_R12_1_PENDING_CANCEL_DB_FALLBACK
        if (
            not isinstance(interaction.user, discord.Member)
            or not is_customer_staff(interaction.user)
        ):
            await interaction.response.send_message(
                "只有客服可以取消網站訂單。",
                ephemeral=True,
            )
            return

        if not isinstance(interaction.channel, discord.TextChannel):
            await interaction.response.send_message(
                "目前不是有效的訂單票口。",
                ephemeral=True,
            )
            return

        channel = interaction.channel
        channel_id = channel.id
        data = SELF_SERVICE_ORDER_SELECTIONS.setdefault(channel_id, {})

        # 待客服確認階段尚未建立派單資料，不能只依賴 Bot 記憶體。
        # 依序使用：Bot state -> 頻道 topic -> web_orders.ticket_channel_id。
        order_id = _to_int(data.get("web_order_id"), None)

        if order_id is None:
            try:
                order_id = _web_cs_order_id_from_channel(channel)
            except Exception:
                order_id = None

        conn = sqlite3.connect(
            _web_dashboard_db_path_for_bot(),
            timeout=15,
        )
        conn.row_factory = sqlite3.Row

        try:
            row = None

            if order_id is not None:
                row = conn.execute(
                    """
                    SELECT id, status, dispatch_message_id, ticket_channel_id
                    FROM web_orders
                    WHERE id = ?
                    LIMIT 1
                    """,
                    (int(order_id),),
                ).fetchone()

            if row is None:
                row = conn.execute(
                    """
                    SELECT id, status, dispatch_message_id, ticket_channel_id
                    FROM web_orders
                    WHERE ticket_channel_id = ?
                    ORDER BY id DESC
                    LIMIT 1
                    """,
                    (str(channel_id),),
                ).fetchone()
        finally:
            conn.close()

        if row is None:
            await interaction.response.send_message(
                "找不到這張票口對應的網站訂單，請通知管理員確認。",
                ephemeral=True,
            )
            return

        order_id = int(row["id"])
        db_status = str(row["status"] or "").strip().lower()
        db_dispatch_message_id = str(row["dispatch_message_id"] or "").strip()

        # 把 canonical DB 身分補回 Bot state，之後同票口都能正常取到 WEB ID。
        data["web_order_id"] = order_id
        data["web_order_source"] = "website"
        data["status"] = db_status
        remember_order_data(channel_id, data)
        save_bot_data()

        if db_status != WEB_ORDER_PENDING_CS_DISPATCH:
            await interaction.response.send_message(
                "這張訂單已經進入後續流程，不能從待確認面板取消。",
                ephemeral=True,
            )
            return

        if db_dispatch_message_id or data.get("dispatch_message_id"):
            await interaction.response.send_message(
                "這張訂單已經送出派單，請使用正式訂單操作取消。",
                ephemeral=True,
            )
            return

        await interaction.response.send_message(
            "請先選擇取消原因，再按「確認取消網站訂單」。",
            view=WebsitePendingCancelConfirmView(
                order_id=int(order_id),
                order_channel_id=int(channel_id),
            ),
            ephemeral=True,
        )


class WebsitePendingCancelConfirmView(discord.ui.View):
    def __init__(
        self,
        *,
        order_id: int,
        order_channel_id: int,
    ):
        super().__init__(timeout=60)
        self.order_id = int(order_id)
        self.order_channel_id = int(order_channel_id)
        self.cancellation_reason_code = "unspecified"
        self.add_item(OrderCancellationReasonSelect())

    @discord.ui.button(
        label="確認取消網站訂單",
        style=discord.ButtonStyle.danger,
        row=0,
    )
    async def confirm_cancel(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ):
        if (
            not isinstance(interaction.user, discord.Member)
            or not is_customer_staff(interaction.user)
        ):
            await interaction.response.send_message(
                "只有客服可以取消網站訂單。",
                ephemeral=True,
            )
            return

        if self.cancellation_reason_code == "unspecified":
            await interaction.response.send_message(
                "請先從下拉選單選擇取消原因。",
                ephemeral=True,
            )
            return

        if interaction.guild is None:
            await interaction.response.send_message(
                "找不到 Discord 伺服器，請重新操作。",
                ephemeral=True,
            )
            return

        channel = interaction.guild.get_channel(
            self.order_channel_id
        )
        if not isinstance(channel, discord.TextChannel):
            await interaction.response.send_message(
                "找不到這張網站訂單票口。",
                ephemeral=True,
            )
            return

        await interaction.response.defer(ephemeral=True)

        reason_label = dict(CANCEL_REASON_OPTIONS).get(
            self.cancellation_reason_code,
            self.cancellation_reason_code,
        )

        try:
            from shared.order_state import (
                CANCELLED,
                PENDING_CS_DISPATCH,
                transition_order_state,
            )

            transition_order_state(
                order_id=self.order_id,
                target_status=CANCELLED,
                source="website_pending_cancel",
                reason=reason_label,
                actor_discord_id=interaction.user.id,
                expected_statuses={PENDING_CS_DISPATCH},
                require_empty_dispatch_message=True,
                cancellation_reason_code=self.cancellation_reason_code,
            )
        except ValueError:
            await interaction.followup.send(
                "取消前訂單狀態已被其他操作更新，或已產生派單訊息，請重新確認目前狀態。",
                ephemeral=True,
            )
            return

        SELF_SERVICE_ORDER_SELECTIONS.pop(
            self.order_channel_id,
            None,
        )

        try:
            delete_order_row_from_db(self.order_channel_id)
        except Exception as exc:
            print(
                "[website-order] cancel local row cleanup failed "
                f"channel_id={self.order_channel_id}: {exc}",
                flush=True,
            )

        save_bot_data()

        try:
            await send_order_log(
                interaction.guild,
                title="網站訂單已取消",
                fields=[
                    ("網站訂單", f"WEB-{self.order_id}", True),
                    ("操作客服", interaction.user.mention, True),
                    ("取消原因", reason_label, True),
                    ("票口", channel.mention, False),
                ],
                color=discord.Color.red(),
            )
        except Exception as exc:
            print(
                "[website-order] "
                f"cancel log failed: {exc}",
                flush=True,
            )

        await interaction.followup.send(
            (
                f"已取消 WEB-{self.order_id}｜"
                f"{reason_label}，票口將在 3 秒後關閉。"
            ),
            ephemeral=False,
        )

        await asyncio.sleep(3)

        try:
            await channel.delete(
                reason=(
                    f"Website order WEB-{self.order_id} "
                    f"cancelled by {interaction.user}"
                )
            )
        except discord.HTTPException as exc:
            print(
                "[website-order] cancel ticket delete failed "
                f"channel_id={self.order_channel_id}: {exc}",
                flush=True,
            )

    @discord.ui.button(
        label="保留訂單",
        style=discord.ButtonStyle.secondary,
        row=0,
    )
    async def keep_order(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ):
        if (
            not isinstance(interaction.user, discord.Member)
            or not is_customer_staff(interaction.user)
        ):
            await interaction.response.send_message(
                "只有客服可以操作。",
                ephemeral=True,
            )
            return

        await interaction.response.edit_message(
            content="已保留網站訂單。",
            view=None,
        )
