from __future__ import annotations

from typing import Any, Mapping

import discord

from core.database import (
    delete_claim_row_from_db,
    delete_order_row_from_db,
    remember_claim_data,
    save_bot_data,
)
from services.acceptance.ticket_access import (
    grant_order_ticket_access,
    revoke_order_ticket_access,
)
from services.logging_service import send_order_log
from services.orders import _to_int, build_self_service_order_embed


_CONFIGURED = False
_DEPENDENCY_NAMES = (
    "BOOSTER_RECEIVER_ROLE_ID",
    "DISPATCH_CHANNEL_ID",
    "ORDER_CLAIMS",
    "SELF_SERVICE_ORDER_SELECTIONS",
    "_apply_acceptance_state_to_claim_data",
    "_member_display_name",
    "_member_role_id_texts",
    "_order_requires_credentials",
    "revoke_order_credential_messages",
    "send_acceptance_payment_panel_if_ready",
)


def configure_order_dispatch_runtime(namespace: Mapping[str, Any]) -> None:
    """Bind the bot-owned adapters needed by the Discord dispatch lifecycle."""
    global _CONFIGURED

    missing = [name for name in _DEPENDENCY_NAMES if name not in namespace]
    if missing:
        raise RuntimeError(
            "order dispatch runtime missing dependencies: " + ", ".join(missing)
        )

    for name in _DEPENDENCY_NAMES:
        globals()[name] = namespace[name]

    _CONFIGURED = True


class DispatchCancelClaimButton(discord.ui.Button):
    def __init__(self, disabled: bool = False):
        super().__init__(
            label="取消接單",
            style=discord.ButtonStyle.danger,
            custom_id="dispatch_cancel_claim",
            disabled=disabled
        )

    async def callback(self, interaction: discord.Interaction):
        view = self.view

        if not isinstance(view, DispatchClaimView):
            await interaction.response.send_message("接單面板狀態異常，請重新派單。", ephemeral=True)
            return

        await view.cancel_claim(interaction)

def sync_single_discord_claim_event_to_web(interaction, claim_type: str, action: str) -> None:
    """把 Discord 接單按鈕單一操作同步到網站。

    action:
    - claim：只新增目前這個人
    - unclaim：只移除目前這個人
    """
    try:
        from shared.web_order_sync import apply_discord_claim_event_to_web

        if interaction.message is None:
            return

        role_type = "booster"

        apply_discord_claim_event_to_web(
            dispatch_message_id=interaction.message.id,
            worker_discord_id=interaction.user.id,
            worker_display_name=getattr(interaction.user, "display_name", None) or getattr(interaction.user, "name", None) or str(interaction.user.id),
            role_type=role_type,
            action=action,
        )
    except Exception as exc:
        print(
            f"[web-sync] Discord 接單事件同步網站失敗 "
            f"message_id={getattr(getattr(interaction, 'message', None), 'id', None)} "
            f"user_id={getattr(getattr(interaction, 'user', None), 'id', None)} "
            f"claim_type={claim_type} action={action}: {exc}"
        )

async def maybe_handle_prepay_acceptance_claim(
    view: "DispatchClaimView",
    interaction: discord.Interaction,
) -> bool:
    if interaction.message is None:
        return False

    try:
        from shared.order_acceptance import (
            ACCEPTED_PENDING_PAY,
            claim_acceptance_order,
            find_acceptance_order_id_by_dispatch_message_id,
        )

        acceptance_order_id = find_acceptance_order_id_by_dispatch_message_id(interaction.message.id)
    except Exception as exc:
        print(f"[acceptance] 查詢 Discord 派單是否為新流程失敗 message_id={getattr(interaction.message, 'id', None)}: {exc}")
        return False

    if acceptance_order_id is None:
        return False

    if not isinstance(interaction.user, discord.Member):
        await interaction.response.send_message("無法確認你的身分組。", ephemeral=True)
        return True

    # acceptance_claim_ack_v1
    # Acknowledge Discord before synchronous DB validation/write.
    await interaction.response.defer(
        ephemeral=True
    )

    try:
        state = claim_acceptance_order(
            order_id=acceptance_order_id,
            staff_discord_id=str(interaction.user.id),
            staff_display_name=_member_display_name(interaction.user),
            staff_role_ids=_member_role_id_texts(interaction.user),
            source="discord",
        )
    except ValueError as exc:
        print(
            "[acceptance] claim rejected "
            f"order_id={acceptance_order_id} "
            f"user_id={interaction.user.id} "
            f"role_ids={_member_role_id_texts(interaction.user)} "
            f"reason={exc}"
        )
        await interaction.followup.send(
            str(exc),
            ephemeral=True,
        )
        return True
    except Exception as exc:
        print(
            "[acceptance] Discord new-flow claim failed "
            f"order_id={acceptance_order_id} "
            f"user_id={interaction.user.id}: "
            f"{type(exc).__name__}: {exc}"
        )
        await interaction.followup.send(
            "接單失敗，請稍後再試或通知客服。",
            ephemeral=True,
        )
        return True

    ticket_access_ok = await grant_order_ticket_access(
        interaction.guild,
        view.source_channel_id,
        interaction.user,
    )

    claim_data = view.get_claim_data(interaction.message.id)
    _apply_acceptance_state_to_claim_data(claim_data, state)
    remember_claim_data(interaction.message.id, claim_data)

    if not ticket_access_ok:
        await interaction.followup.send(
            "已接單，但票口權限同步失敗，請通知客服檢查票口權限。",
            ephemeral=True,
        )

    try:
        await send_order_log(
            interaction.guild,
            title="我要接單｜待付款",
            fields=[
                ("接單人員", interaction.user.mention, True),
                ("顧客", f"<@{view.customer_id}>", True),
                ("訂單", f"{view.category_label}｜{view.item} x{view.quantity}", False),
                ("接單進度", f"{state.accepted_count}/{state.required_staff_count}", True),
                ("狀態", "人數已滿，等待付款" if state.status == ACCEPTED_PENDING_PAY else "等待接單", True),
            ],
            color=discord.Color.green(),
        )
    except Exception as exc:
        print(f"[acceptance] 接單日誌送出失敗：{exc}")

    await view.refresh_panel(interaction)

    if str(getattr(state, "status", "")) == "accepted_pending_pay":
        await send_acceptance_payment_panel_if_ready(view, interaction, state)

    return True

async def maybe_handle_prepay_acceptance_unclaim(
    view: "DispatchClaimView",
    interaction: discord.Interaction,
) -> bool:
    if interaction.message is None:
        return False

    try:
        from shared.order_acceptance import (
            find_acceptance_order_id_by_dispatch_message_id,
            unclaim_acceptance_order,
        )

        acceptance_order_id = find_acceptance_order_id_by_dispatch_message_id(interaction.message.id)
    except Exception as exc:
        print(f"[acceptance] 查詢 Discord 派單是否為新流程失敗 message_id={getattr(interaction.message, 'id', None)}: {exc}")
        return False

    if acceptance_order_id is None:
        return False

    if not isinstance(interaction.user, discord.Member):
        await interaction.response.send_message("無法確認你的身分組。", ephemeral=True)
        return True

    # acceptance_unclaim_ack_v1
    await interaction.response.defer(
        ephemeral=True
    )

    try:
        state = unclaim_acceptance_order(
            order_id=acceptance_order_id,
            staff_discord_id=str(interaction.user.id),
            source="discord",
        )
    except ValueError as exc:
        await interaction.followup.send(
            str(exc),
            ephemeral=True,
        )
        return True
    except Exception as exc:
        print(
            "[acceptance] Discord new-flow unclaim failed "
            f"order_id={acceptance_order_id} "
            f"user_id={interaction.user.id}: "
            f"{type(exc).__name__}: {exc}"
        )
        await interaction.followup.send(
            "取消接單失敗，請稍後再試或通知客服。",
            ephemeral=True,
        )
        return True

    ticket_access_ok = await revoke_order_ticket_access(
        interaction.guild,
        view.source_channel_id,
        interaction.user,
    )

    claim_data = view.get_claim_data(interaction.message.id)
    _apply_acceptance_state_to_claim_data(claim_data, state)
    remember_claim_data(interaction.message.id, claim_data)

    if not ticket_access_ok:
        await interaction.followup.send(
            "已取消接單，但票口權限同步失敗，請通知客服檢查票口權限。",
            ephemeral=True,
        )

    try:
        await send_order_log(
            interaction.guild,
            title="取消接單｜待付款",
            fields=[
                ("操作人", interaction.user.mention, True),
                ("顧客", f"<@{view.customer_id}>", True),
                ("訂單", f"{view.category_label}｜{view.item} x{view.quantity}", False),
                ("接單進度", f"{state.accepted_count}/{state.required_staff_count}", True),
            ],
            color=discord.Color.orange(),
        )
    except Exception as exc:
        print(f"[acceptance] 取消接單日誌送出失敗：{exc}")

    await view.refresh_panel(interaction)
    return True

class DispatchClaimView(discord.ui.View):
    def __init__(
        self,
        customer_id: int,
        category_label: str,
        item: str,
        quantity: int,
        payment_method: str,
        source_channel_id: int,
        companion_preference: str | None = None,
        locked: bool = False,
        status: str = "active",
    ):
        super().__init__(timeout=None)
        self.customer_id = customer_id
        self.category_label = category_label
        self.item = item
        self.quantity = quantity
        self.payment_method = payment_method
        self.source_channel_id = source_channel_id
        self.companion_preference = companion_preference
        self.locked = locked
        self.status = status

        self.add_item(DispatchCancelClaimButton(disabled=locked))

        if locked:
            for item in self.children:
                item.disabled = True


    def get_receiver_label(self, claim_type: str) -> str:
        return "我要接單"


    def get_required_role_id(self, claim_type: str) -> int:
        return BOOSTER_RECEIVER_ROLE_ID

    def get_claim_data(self, message_id: int) -> dict:
        data = ORDER_CLAIMS.setdefault(
            message_id,
            {
                "companion": set(),
                "booster": set(),
                "locked": False,
            }
        )

        data.setdefault("customer_id", self.customer_id)
        data.setdefault("category_label", self.category_label)
        data.setdefault("item", self.item)
        data.setdefault("quantity", self.quantity)
        data.setdefault("payment_method", self.payment_method)
        data.setdefault("source_channel_id", self.source_channel_id)
        data.setdefault("companion_preference", self.companion_preference)
        data.setdefault("dispatch_channel_id", DISPATCH_CHANNEL_ID)
        data.setdefault("status", self.status)

        return data


    def build_receiver_text(self, claim_data: dict) -> str | None:
        receiver_ids = sorted(
            set(claim_data.get("companion", set()))
            | set(claim_data.get("booster", set()))
        )

        if not receiver_ids:
            return None

        return "、".join(f"<@{user_id}>" for user_id in receiver_ids)

    async def refresh_panel(self, interaction: discord.Interaction, locked: bool | None = None):
        guild = interaction.guild

        # dispatch_refresh_after_defer_v1
        async def send_ephemeral(message: str) -> None:
            if interaction.response.is_done():
                await interaction.followup.send(
                    message,
                    ephemeral=True,
                )
            else:
                await interaction.response.send_message(
                    message,
                    ephemeral=True,
                )

        if guild is None:
            await send_ephemeral("這個功能只能在伺服器內使用。")
            return

        if not isinstance(interaction.channel, discord.TextChannel):
            await send_ephemeral("這個功能只能在派單文字頻道使用。")
            return

        source_channel = guild.get_channel(self.source_channel_id)

        if source_channel is None or not isinstance(source_channel, discord.TextChannel):
            await send_ephemeral("找不到來源票口。")
            return

        claim_data = self.get_claim_data(interaction.message.id)

        if locked is not None:
            claim_data["locked"] = locked

        remember_claim_data(interaction.message.id, claim_data)

        receiver_text = self.build_receiver_text(claim_data)

        new_embed = build_self_service_order_embed(
            customer_mention=f"<@{self.customer_id}>",
            category_label=self.category_label,
            item=self.item,
            quantity=_to_int(claim_data.get("quantity"), self.quantity) or 1,
            payment_method=self.payment_method,
            source_channel=source_channel,
            companion_preference=self.companion_preference,
            receiver_text=receiver_text
        )

        status = claim_data.get("status", "active")

        if status == "stored":
            new_embed.add_field(
                name="狀態",
                value=(
                    "已存單，接單面板已鎖定\n"
                    f"存單原因：{claim_data.get('stored_reason') or '未填寫'}\n"
                    f"預計恢復：{claim_data.get('stored_expected_time') or '未填寫'}"
                ),
                inline=False
            )
        elif claim_data.get("locked"):
            new_embed.add_field(
                name="狀態",
                value="已結單，接單面板已鎖定",
                inline=False
            )

        updated_view = DispatchClaimView(
            customer_id=self.customer_id,
            category_label=self.category_label,
            item=self.item,
            quantity=_to_int(
                claim_data.get("quantity"),
                self.quantity,
            ) or 1,
            payment_method=self.payment_method,
            source_channel_id=self.source_channel_id,
            companion_preference=self.companion_preference,
            locked=bool(
                claim_data.get("locked")
            ),
            status=str(
                claim_data.get(
                    "status",
                    "active",
                )
            ),
        )

        edit_kwargs = {
            "embed": new_embed,
            "view": updated_view,
            "allowed_mentions": discord.AllowedMentions(
                users=True,
                roles=False,
                everyone=False,
            ),
        }

        if interaction.response.is_done():
            await interaction.edit_original_response(
                **edit_kwargs
            )
        else:
            await interaction.response.edit_message(
                **edit_kwargs
            )


    async def claim_order(self, interaction: discord.Interaction, claim_type: str):
        handled = await maybe_handle_prepay_acceptance_claim(self, interaction)

        if handled:
            return

        await interaction.response.send_message(
            "舊接單流程已停用。這張接單面板不是目前的付款前接單流程，請客服重新用自助下單送出等待接單。",
            ephemeral=True,
        )

    async def cancel_claim(self, interaction: discord.Interaction):
        handled = await maybe_handle_prepay_acceptance_unclaim(self, interaction)

        if handled:
            return

        await interaction.response.send_message(
            "舊取消接單流程已停用。這張接單面板不是目前的付款前接單流程，請客服確認訂單狀態。",
            ephemeral=True,
        )


    async def companion_claim(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.claim_order(interaction, "companion")

    @discord.ui.button(
        label="我要接單",
        style=discord.ButtonStyle.primary,
        custom_id="dispatch_claim_booster"
    )
    async def booster_claim(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.claim_order(interaction, "booster")

async def delete_dispatch_claim_panel_for_order(
    guild: discord.Guild,
    order_channel_id: int,
    *,
    actor_discord_id: str | int | None = None,
    cancellation_reason_code: str | None = None,
    cancellation_reason_text: str | None = None,
):
    """取消票口時，一併刪除派單頻道對應的接單面板，並清除保存資料。"""
    data = SELF_SERVICE_ORDER_SELECTIONS.get(order_channel_id, {})
    dispatch_message_id = _to_int(data.get("dispatch_message_id"))
    dispatch_channel_id = _to_int(data.get("dispatch_channel_id"), DISPATCH_CHANNEL_ID) or DISPATCH_CHANNEL_ID

    if dispatch_message_id is not None:
        try:
            from shared.order_acceptance import (
                cancel_acceptance_order,
                find_acceptance_order_id_by_dispatch_message_id,
            )

            acceptance_order_id = find_acceptance_order_id_by_dispatch_message_id(dispatch_message_id)
            if acceptance_order_id is not None:
                cancel_acceptance_order(
                    acceptance_order_id,
                    source="discord_cancel",
                    actor_discord_id=actor_discord_id,
                    cancellation_reason_code=cancellation_reason_code,
                    cancellation_reason_text=cancellation_reason_text,
                )
                print(f"[acceptance] cancelled order_id={acceptance_order_id} dispatch_message_id={dispatch_message_id}")
        except Exception as exc:
            print(f"[acceptance] 取消訂單同步付款前接單狀態失敗 dispatch_message_id={dispatch_message_id}: {exc}")

        dispatch_channel = guild.get_channel(dispatch_channel_id)

        if isinstance(dispatch_channel, discord.TextChannel):
            try:
                message = await dispatch_channel.fetch_message(dispatch_message_id)
                await message.delete()
            except discord.NotFound:
                pass
            except discord.Forbidden:
                print("Bot 權限不足，無法刪除派單接單面板。")
            except discord.HTTPException as e:
                print(f"刪除派單接單面板失敗：{e}")

        ORDER_CLAIMS.pop(dispatch_message_id, None)
        delete_claim_row_from_db(message_id=dispatch_message_id)

    if _order_requires_credentials(data):
        try:
            from services.order_credentials import get_order_id_by_ticket_channel
            credential_order_id = _to_int(data.get("web_order_id")) or get_order_id_by_ticket_channel(order_channel_id)
            if credential_order_id is not None:
                credential_ticket_channel = guild.get_channel(order_channel_id)
                await revoke_order_credential_messages(
                    credential_order_id,
                    reason="cancelled",
                    ticket_channel=credential_ticket_channel if isinstance(credential_ticket_channel, discord.TextChannel) else None,
                    notify_customer=True,
                )
        except Exception as exc:
            print(f"[credentials] 取消票口撤回失敗 channel_id={order_channel_id}: {exc}")

    if order_channel_id in SELF_SERVICE_ORDER_SELECTIONS:
        SELF_SERVICE_ORDER_SELECTIONS.pop(order_channel_id, None)
        delete_order_row_from_db(order_channel_id)
        save_bot_data()
    elif dispatch_message_id is not None:
        save_bot_data()

def sync_web_order_status_from_bot(ticket_channel_id, status: str, dispatch_message_id=None, note: str | None = None) -> None:
    """DC bot 訂單狀態變更後，同步網站 web_orders.status。"""
    try:
        from shared.web_order_sync import update_web_order_status_by_ticket_channel

        ok = update_web_order_status_by_ticket_channel(
            ticket_channel_id=ticket_channel_id,
            status=status,
            dispatch_message_id=dispatch_message_id,
            note=note,
        )
        print(
            f"[web-sync] order status sync "
            f"ticket_channel_id={ticket_channel_id} "
            f"dispatch_message_id={dispatch_message_id} "
            f"status={status} ok={ok}"
        )
    except Exception as exc:
        print(
            f"[web-sync] 訂單狀態同步網站失敗 "
            f"ticket_channel_id={ticket_channel_id} "
            f"status={status}: {exc}"
        )

