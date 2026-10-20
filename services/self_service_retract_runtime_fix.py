from __future__ import annotations

from types import MethodType

import discord

from core.permissions import is_customer_staff, is_manager_or_admin
from services.orders import _to_int


_INSTALLED = False
_ORIGINAL_VIEW_INIT = None


async def _fixed_retract_dispatch(view, interaction: discord.Interaction, button: discord.ui.Button) -> None:
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

    # Acknowledge before touching the refactored runtime/DB. The old callback
    # accessed removed module globals before defer(), which made Discord show
    # 「應用程式未及時回應」 instead of surfacing the actual error.
    await interaction.response.defer(ephemeral=True)

    from services import self_service_runtime as runtime
    from services.self_service_retract import retract_self_service_dispatch

    channel_id = int(interaction.channel.id)
    try:
        state = runtime._require_runtime_state()
    except Exception as exc:
        await interaction.followup.send(
            f"撤回派單暫時無法使用，請通知客服主管查看後台紀錄。（{type(exc).__name__}）",
            ephemeral=True,
        )
        return

    data = state.order_selections.get(channel_id, {})
    customer_id = _to_int(data.get("customer_id"), None)
    if customer_id is None:
        await interaction.followup.send("找不到這張票口的顧客資料。", ephemeral=True)
        return

    try:
        response_text = await retract_self_service_dispatch(
            interaction,
            channel_id=channel_id,
            order_selections=state.order_selections,
            order_claims=state.order_claims,
            dispatch_channel_id=state.dispatch_channel_id,
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
            f"[dispatch-retract] failed channel_id={channel_id}: {type(exc).__name__}: {exc}",
            flush=True,
        )
        await interaction.followup.send(
            "撤回派單失敗，原訂單已鎖住付款；請再按一次撤回，若仍失敗請通知客服主管查看後台紀錄。",
            ephemeral=True,
        )
        return

    panel_refreshed = False
    if interaction.message is not None:
        try:
            updated_data = state.order_selections.get(channel_id, {})
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
        except Exception as exc:
            print(
                f"[dispatch-retract] panel refresh failed channel_id={channel_id}: {type(exc).__name__}: {exc}",
                flush=True,
            )

    if not panel_refreshed:
        response_text += "\n⚠️ 自助下單 Panel 未能自動刷新，請重新開啟票口 Panel 後再修改。"

    await interaction.followup.send(response_text, ephemeral=True)


def install_self_service_retract_runtime_fix() -> None:
    """Repair the persistent retract button after self-service runtime state refactor."""
    global _INSTALLED, _ORIGINAL_VIEW_INIT
    if _INSTALLED:
        return

    from services.self_service_retract import SelfServiceDispatchedView

    if _ORIGINAL_VIEW_INIT is None:
        _ORIGINAL_VIEW_INIT = SelfServiceDispatchedView.__init__
    original_init = _ORIGINAL_VIEW_INIT

    def fixed_init(self) -> None:
        original_init(self)
        for child in self.children:
            if str(getattr(child, "custom_id", "") or "") != "self_service_retract_dispatch_button":
                continue

            async def callback(interaction: discord.Interaction, _child=child, _view=self):
                await _fixed_retract_dispatch(_view, interaction, _child)

            child.callback = callback
            break

    SelfServiceDispatchedView.__init__ = fixed_init
    _INSTALLED = True


__all__ = [
    "install_self_service_retract_runtime_fix",
]
