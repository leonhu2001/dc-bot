from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

import discord

from core.permissions import is_customer_staff, is_manager_or_admin
from services.orders import _to_int


async def retract_self_service_dispatch(
    interaction: discord.Interaction,
    *,
    channel_id: int,
    order_selections: dict,
    order_claims: dict,
    dispatch_channel_id: int,
    remember_order: Callable[[int, dict], Any],
    save_data: Callable[[], Any],
    delete_claim_row: Callable[..., Any],
    order_log_sender: Callable[..., Awaitable[Any]],
    now_iso: Callable[[], str],
) -> str:
    """撤回付款前派單，但保留票口自助下單草稿供客服修改後重送。"""
    guild = interaction.guild

    if guild is None:
        raise ValueError("這個功能只能在伺服器內使用。")

    if not isinstance(interaction.channel, discord.TextChannel):
        raise ValueError("無法確認目前票口頻道。")

    channel_id = int(channel_id)
    data = order_selections.get(channel_id)

    if not isinstance(data, dict):
        raise ValueError("找不到這張票口的自助下單資料。")

    dispatch_message_id = _to_int(data.get("dispatch_message_id"), None)
    if dispatch_message_id is None:
        raise ValueError("這張單目前沒有可撤回的派單。")

    order_id = _to_int(data.get("web_order_id"), None)
    current_status = str(data.get("status") or "").strip().lower()
    claim_staff_ids: list[str] = []

    from shared.order_acceptance import PREPAY_ACCEPTANCE_STATUSES

    allowed_statuses = set(PREPAY_ACCEPTANCE_STATUSES) | {"cancelled"}

    def ensure_retractable_status(status: str) -> None:
        if status and status not in allowed_statuses:
            raise ValueError("這張單已進入付款／進行中或已結束，不能用『撤回派單』回到改單。")

    # 部分建立中的單可能還沒有 web_order_id；本地狀態仍然必須先過鎖。
    ensure_retractable_status(current_status)

    if order_id is not None:
        from shared.order_acceptance import cancel_acceptance_order, get_acceptance_state

        try:
            state = get_acceptance_state(int(order_id))
        except ValueError:
            state = None

        if state is not None:
            current_status = str(
                getattr(state, "status", None) or current_status
            ).strip().lower()
            ensure_retractable_status(current_status)

        if current_status in PREPAY_ACCEPTANCE_STATUSES:
            cancel_acceptance_order(
                int(order_id),
                source="dispatch_retracted",
                actor_discord_id=getattr(interaction.user, "id", None),
                cancellation_reason_code="dispatch_retracted_for_edit",
                cancellation_reason_text="客服撤回派單並返回原票口改單",
            )

        # 取消後 active claim 會變 inactive；仍讀完整歷史名單，確保已取得
        # 票口權限的人全部被收回。
        try:
            from sqlalchemy import text as sql_text
            from shared.db import engine as acceptance_engine

            with acceptance_engine.begin() as conn:
                rows = conn.execute(
                    sql_text(
                        """
                        SELECT DISTINCT staff_discord_id
                        FROM order_acceptance_claims
                        WHERE order_id = :order_id
                        """
                    ),
                    {"order_id": int(order_id)},
                ).mappings().all()
            claim_staff_ids = [
                str(row.get("staff_discord_id") or "").strip()
                for row in rows
                if str(row.get("staff_discord_id") or "").strip()
            ]
        except Exception as exc:
            print(
                f"[dispatch-retract] claim history lookup failed order_id={order_id}: "
                f"{type(exc).__name__}: {exc}",
                flush=True,
            )

    # 先 fail-safe：後續任何 Discord / DB 清理失敗時，舊付款元件也不能再
    # 把本地 accepted_pending_pay 單送進付款流程。此狀態可再次按撤回重試。
    data["status"] = "cancelled"
    remember_order(channel_id, data)
    save_data()

    warnings: list[str] = []

    payment_message_id = _to_int(data.get("payment_message_id"), None)
    if payment_message_id is not None:
        try:
            payment_message = await interaction.channel.fetch_message(payment_message_id)
            await payment_message.delete()
        except discord.NotFound:
            pass
        except (discord.Forbidden, discord.HTTPException) as exc:
            warnings.append(f"付款 Panel 未能自動刪除：{type(exc).__name__}")

    if claim_staff_ids:
        from services.acceptance.runtime import revoke_order_ticket_access

        for staff_id_text in claim_staff_ids:
            staff_id = _to_int(staff_id_text, None)
            if staff_id is None:
                continue
            member = guild.get_member(staff_id)
            if member is None:
                try:
                    member = await guild.fetch_member(staff_id)
                except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                    member = None
            if member is not None:
                await revoke_order_ticket_access(guild, channel_id, member)

    source_dispatch_channel_id = (
        _to_int(data.get("dispatch_channel_id"), dispatch_channel_id)
        or dispatch_channel_id
    )
    dispatch_channel = guild.get_channel(source_dispatch_channel_id)

    if not isinstance(dispatch_channel, discord.TextChannel):
        try:
            fetched_channel = await guild.fetch_channel(source_dispatch_channel_id)
            dispatch_channel = (
                fetched_channel
                if isinstance(fetched_channel, discord.TextChannel)
                else None
            )
        except (discord.NotFound, discord.Forbidden, discord.HTTPException):
            dispatch_channel = None

    if isinstance(dispatch_channel, discord.TextChannel):
        try:
            dispatch_message = await dispatch_channel.fetch_message(dispatch_message_id)
            await dispatch_message.delete()
        except discord.NotFound:
            pass
        except (discord.Forbidden, discord.HTTPException) as exc:
            warnings.append(f"派單訊息未能自動刪除：{type(exc).__name__}")
    else:
        warnings.append("找不到原派單頻道，派單訊息可能需要人工確認")

    from shared.web_order_sync import delete_web_order_by_ticket_channel

    delete_web_order_by_ticket_channel(
        ticket_channel_id=channel_id,
        dispatch_message_id=dispatch_message_id,
    )

    claim_message_ids: set[int] = {int(dispatch_message_id)}
    for raw_message_id, claim_data in list(order_claims.items()):
        if _to_int((claim_data or {}).get("source_channel_id"), None) == channel_id:
            parsed_message_id = _to_int(raw_message_id, None)
            if parsed_message_id is not None:
                claim_message_ids.add(int(parsed_message_id))

    for message_id in claim_message_ids:
        order_claims.pop(message_id, None)
        delete_claim_row(
            message_id=message_id,
            source_channel_id=channel_id,
        )

    for key in (
        "dispatch_message_id",
        "dispatch_channel_id",
        "web_order_id",
        "status",
        "waiting_acceptance_created_at",
        "accepted_staff_display_text",
        "payment_message_id",
        "payment_channel_id",
        "payment_finalizing",
        "payment_finalized_at",
        "payment_finalized_by",
        "rule_version",
        "rule_snapshot_json",
        "price_snapshot_json",
        "web_order_note",
    ):
        data.pop(key, None)

    data.pop("payment_method", None)
    data["closed"] = False
    data["dispatch_retracted_at"] = now_iso()
    data["dispatch_retracted_by"] = getattr(interaction.user, "id", None)

    remember_order(channel_id, data)
    save_data()

    try:
        await order_log_sender(
            guild,
            title="撤回派單｜返回改單",
            fields=[
                (
                    "操作人員",
                    getattr(
                        interaction.user,
                        "mention",
                        str(getattr(interaction.user, "id", "未知")),
                    ),
                    True,
                ),
                (
                    "顧客",
                    f"<@{data.get('customer_id')}>"
                    if data.get("customer_id")
                    else "未紀錄",
                    True,
                ),
                ("項目", str(data.get("item") or "未紀錄"), True),
                ("票口", interaction.channel.mention, False),
            ],
            color=discord.Color.orange(),
        )
    except Exception as exc:
        print(
            f"[dispatch-retract] order log failed channel_id={channel_id}: "
            f"{type(exc).__name__}: {exc}",
            flush=True,
        )

    result = "已撤回派單，原票口已恢復可改單；修改完成後可重新送出等待接單。"
    if warnings:
        result += "\n" + "\n".join(f"⚠️ {warning}" for warning in warnings)
    return result



class SelfServiceDispatchedView(discord.ui.View):
    """送出後只保留撤回操作；固定 custom_id 讓重啟後仍可操作。"""

    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(
        label="撤回派單",
        style=discord.ButtonStyle.danger,
        custom_id="self_service_retract_dispatch_button",
    )
    async def retract_dispatch(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ):
        if (
            not isinstance(interaction.user, discord.Member)
            or not (
                is_customer_staff(interaction.user)
                or is_manager_or_admin(interaction.user)
            )
        ):
            await interaction.response.send_message(
                "只有客服、店長或管理員可以撤回派單。",
                ephemeral=True,
            )
            return

        if not isinstance(interaction.channel, discord.TextChannel):
            await interaction.response.send_message(
                "無法確認目前票口頻道。",
                ephemeral=True,
            )
            return

        # Lazy import avoids a module cycle while keeping the legacy runtime's
        # state stores as the single source of truth until that boundary is retired.
        from services import self_service_runtime as runtime

        channel_id = int(interaction.channel.id)
        data = runtime.SELF_SERVICE_ORDER_SELECTIONS.get(channel_id, {})
        customer_id = _to_int(data.get("customer_id"), None)

        if customer_id is None:
            await interaction.response.send_message(
                "找不到這張票口的顧客資料。",
                ephemeral=True,
            )
            return

        await interaction.response.defer(ephemeral=True)

        try:
            response_text = await retract_self_service_dispatch(
                interaction,
                channel_id=channel_id,
                order_selections=runtime.SELF_SERVICE_ORDER_SELECTIONS,
                order_claims=runtime.ORDER_CLAIMS,
                dispatch_channel_id=runtime.DISPATCH_CHANNEL_ID,
                remember_order=runtime.remember_order_data,
                save_data=runtime.save_bot_data,
                delete_claim_row=runtime.delete_claim_row_from_db,
                order_log_sender=runtime.send_order_log,
                now_iso=runtime.get_taipei_now_iso,
            )
        except ValueError as exc:
            await interaction.followup.send(str(exc), ephemeral=True)
            return
        except Exception as exc:
            print(
                f"[dispatch-retract] failed channel_id={channel_id}: "
                f"{type(exc).__name__}: {exc}",
                flush=True,
            )
            await interaction.followup.send(
                "撤回派單失敗，原訂單已鎖住付款；請再按一次撤回，"
                "若仍失敗請通知客服主管查看後台紀錄。",
                ephemeral=True,
            )
            return

        panel_refreshed = False
        if interaction.message is not None:
            try:
                updated_data = runtime.SELF_SERVICE_ORDER_SELECTIONS.get(
                    channel_id,
                    {},
                )
                await interaction.message.edit(
                    embed=runtime.build_self_service_panel_embed(
                        customer_id,
                        updated_data,
                        interaction.guild,
                    ),
                    view=runtime.SelfServiceOrderView(
                        customer_id=customer_id,
                        channel_id=channel_id,
                        selected_category=updated_data.get("category"),
                    ),
                    allowed_mentions=discord.AllowedMentions(
                        users=True,
                        roles=False,
                        everyone=False,
                    ),
                )
                panel_refreshed = True
            except discord.HTTPException:
                panel_refreshed = False

        if not panel_refreshed:
            response_text += (
                "\n⚠️ 自助下單 Panel 未能自動刷新，"
                "請重新開啟票口 Panel 後再修改。"
            )

        await interaction.followup.send(response_text, ephemeral=True)
