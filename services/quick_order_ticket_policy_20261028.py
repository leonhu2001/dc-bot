from __future__ import annotations

from dataclasses import replace

import discord


_INSTALLED = False


class QuickOrderNoticeConfirmView(discord.ui.View):
    """Explicit order-notice acknowledgement before a quick-order ticket opens."""

    def __init__(
        self,
        *,
        customer_id: int,
        category: str,
        item_group: str,
        source_channel_id: int,
        quick_module,
    ):
        super().__init__(timeout=180)
        self.customer_id = int(customer_id)
        self.category = str(category)
        self.item_group = str(item_group)
        self.source_channel_id = int(source_channel_id)
        self.quick_module = quick_module
        self.opening = False

    @discord.ui.button(
        label="已閱讀下單須知，建立票口",
        emoji="✅",
        style=discord.ButtonStyle.success,
    )
    async def read_and_open(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ):
        if interaction.user.id != self.customer_id:
            await interaction.response.send_message(
                "這不是你的下單確認畫面。",
                ephemeral=True,
            )
            return

        if self.opening:
            await interaction.response.send_message(
                "票口正在建立，請勿重複點擊。",
                ephemeral=True,
            )
            return

        self.opening = True
        button.disabled = True
        try:
            await self.quick_module._create_ticket(
                interaction,
                category=self.category,
                item_group=self.item_group,
                source_channel_id=self.source_channel_id,
            )
        finally:
            self.opening = False

    @discord.ui.button(
        label="尚未閱讀",
        emoji="📖",
        style=discord.ButtonStyle.secondary,
    )
    async def not_read(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ):
        if interaction.user.id != self.customer_id:
            await interaction.response.send_message(
                "這不是你的下單確認畫面。",
                ephemeral=True,
            )
            return

        await interaction.response.send_message(
            "請先閱讀店內下單須知；確認看完後，再按「已閱讀下單須知，建立票口」。",
            ephemeral=True,
        )


async def _send_notice_confirmation(
    interaction: discord.Interaction,
    *,
    category: str,
    item_group: str,
    source_channel_id: int,
    quick_module,
):
    if not isinstance(interaction.user, discord.Member):
        await interaction.response.send_message(
            "這個功能只能在伺服器內使用。",
            ephemeral=True,
        )
        return

    timer = category == quick_module.VIP_TIMER_CATEGORY
    category_label = (
        quick_module.VIP_TIMER_CATEGORY_LABEL
        if timer
        else quick_module.ORDER_CATEGORY_LABELS.get(category, category)
    )

    embed = discord.Embed(
        title="📖 下單須知確認",
        description=(
            f"**遊戲／類型：** {category_label}\n"
            f"**{'起始遊戲' if timer else '服務'}：** {item_group}\n\n"
            "開票前請先確認：**你是否已閱讀店內下單須知？**\n"
            "只有確認已閱讀後才會建立私人票口。\n\n"
            "票口建立後仍可在自助下單面板重新切換訂單類別／服務，"
            "再完成規格、陪玩人數與時長／數量。"
        ),
        color=discord.Color.gold(),
    )

    await interaction.response.send_message(
        embed=embed,
        view=QuickOrderNoticeConfirmView(
            customer_id=interaction.user.id,
            category=category,
            item_group=item_group,
            source_channel_id=source_channel_id,
            quick_module=quick_module,
        ),
        ephemeral=True,
    )


def _restore_full_self_service_ticket_patch(quick_module) -> None:
    """Undo the legacy quick-ticket selector stripping after its base patch runs."""
    from services import order_runtime
    from services import self_service_runtime as runtime
    from services import self_service_selection_runtime as selection_runtime
    from services import self_service_ui_runtime as ui

    original_view_init = quick_module._ORIGINAL_VIEW_INIT
    original_panel_builder = quick_module._ORIGINAL_PANEL_BUILDER
    if original_view_init is None or original_panel_builder is None:
        raise RuntimeError("quick-order ticket patch did not capture its original UI hooks")

    def unified_view_init(
        self,
        customer_id: int,
        channel_id: int,
        selected_category: str | None = None,
    ):
        # The captured original is the companion-count EnhancedSelfServiceOrderView
        # initializer. It already fits Discord's five-row limit and keeps the first
        # visible selector able to return to the category chooser.
        original_view_init(self, customer_id, channel_id, selected_category)

        data = ui.SELF_SERVICE_ORDER_SELECTIONS.get(channel_id, {})
        if not data.get("quick_order_v2"):
            return

        is_timer = str(data.get("category") or "") == quick_module.VIP_TIMER_CATEGORY
        for child in self.children:
            if getattr(child, "custom_id", None) == "self_service_order_detail_select":
                child.placeholder = "選擇起始玩法" if is_timer else "請選擇規格"

    # quick_order_v2's old patch removed both category + item selectors from ticket
    # views. Replace only that patched initializer with the normal enhanced view;
    # this makes auto-created tickets use the same UI as regular self-service.
    ui.SelfServiceOrderView.__init__ = unified_view_init

    # The old patch also replaced the panel copy with an "已選服務" locked-looking
    # version. Restore the shared panel builder everywhere it was rebound.
    ui.build_self_service_panel_embed = original_panel_builder
    runtime.build_self_service_panel_embed = original_panel_builder
    selection_runtime.build_self_service_panel_embed = original_panel_builder

    state = getattr(order_runtime, "_RUNTIME_STATE", None)
    if state is not None:
        try:
            order_runtime._RUNTIME_STATE = replace(
                state,
                self_service_panel_embed_builder=original_panel_builder,
            )
        except Exception:
            pass

    quick_module._unified_ticket_ui_installed = True


def install_quick_order_ticket_policy_20261028() -> None:
    """Restore notice acknowledgement and use the normal self-service ticket UI."""
    global _INSTALLED
    if _INSTALLED:
        return

    from services import quick_order_v2 as quick

    if not getattr(quick, "_order_notice_confirmation_installed", False):
        async def send_confirmation(
            interaction: discord.Interaction,
            *,
            category: str,
            item_group: str,
            source_channel_id: int,
        ):
            await _send_notice_confirmation(
                interaction,
                category=category,
                item_group=item_group,
                source_channel_id=source_channel_id,
                quick_module=quick,
            )

        quick._send_confirmation = send_confirmation
        quick._order_notice_confirmation_installed = True

    if not getattr(quick, "_unified_ticket_patch_wrapper_installed", False):
        original_install_ticket_patch = quick._install_ticket_patch

        def install_ticket_patch() -> None:
            original_install_ticket_patch()
            _restore_full_self_service_ticket_patch(quick)

        quick._install_ticket_patch = install_ticket_patch
        quick._unified_ticket_patch_wrapper_installed = True

    _INSTALLED = True


__all__ = [
    "QuickOrderNoticeConfirmView",
    "install_quick_order_ticket_policy_20261028",
]
