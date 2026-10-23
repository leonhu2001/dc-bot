from __future__ import annotations

from dataclasses import replace

import discord


_INSTALLED = False
_LEGACY_RESELECT_FLAG = "legacy_four_selector_panel"


def _apply_selected_dropdown_state(view: discord.ui.View, data: dict) -> None:
    """Keep the classic four selectors visibly synced with the saved draft."""
    from services.orders import ORDER_CATEGORY_LABELS, get_order_item_detail_for_selection

    category = str(data.get("category") or "").strip()
    item_group = str(data.get("item_group") or "").strip()
    detail_value = str(data.get("item_detail_value") or "").strip()
    quantity = str(data.get("quantity") or "").strip()

    detail_label = ""
    if category and item_group and detail_value:
        try:
            detail = get_order_item_detail_for_selection(category, item_group, detail_value)
            detail_label = str((detail or {}).get("label") or (detail or {}).get("item") or "").strip()
        except Exception:
            detail_label = ""
    if not detail_label:
        detail_label = str(data.get("item") or "").strip()

    selected_values = {
        "self_service_order_category_select": category,
        "self_service_order_item_select": item_group,
        "self_service_order_detail_select": detail_value,
        "self_service_order_quantity_select": quantity,
    }
    selected_labels = {
        "self_service_order_category_select": ORDER_CATEGORY_LABELS.get(category, category) if category else "",
        "self_service_order_item_select": item_group,
        "self_service_order_detail_select": detail_label,
        "self_service_order_quantity_select": quantity,
    }

    for child in getattr(view, "children", []):
        custom_id = str(getattr(child, "custom_id", "") or "")
        selected_value = selected_values.get(custom_id, "")
        selected_label = selected_labels.get(custom_id, "")
        if not selected_value:
            continue

        # Discord can visually fall back to the placeholder after an edited
        # select message. Mark the saved option as default again and also show a
        # deterministic "已選" placeholder so the current value never disappears.
        for option in getattr(child, "options", []) or []:
            try:
                option.default = str(getattr(option, "value", "")) == selected_value
            except Exception:
                pass

        if selected_label:
            try:
                child.placeholder = f"已選：{selected_label}"[:150]
            except Exception:
                pass


def _is_paid_active_order(data: dict) -> bool:
    """Only treat a canonical, completed active payment as an established order."""
    status = str(data.get("status") or "").strip().lower()
    if status != "active":
        return False

    if data.get("payment_processing") or data.get("payment_finalizing"):
        return False

    return any(
        data.get(key)
        for key in (
            "payment_submitted_at",
            "payment_zero_amount_completed_at",
            "payment_review_applied_at",
            "payment_review_finalized_id",
            "receipt_id",
            "receipt_message_id",
            "wallet_transaction_id",
        )
    )


def _install_payment_finalize_rename_policy(order_runtime) -> None:
    """Rename only after finalize has actually reached the completed active state."""
    from services import order_payment_runtime as payment_runtime
    from services import order_ticket_name_restore_runtime as names

    if getattr(payment_runtime, "_paid_ticket_finalize_rename_installed", False):
        return

    original_finalize = payment_runtime.finalize_accepted_pending_payment

    async def finalize_with_paid_ticket_rename(
        *,
        interaction: discord.Interaction,
        customer_id: int,
        channel_id: int,
    ) -> None:
        await original_finalize(
            interaction=interaction,
            customer_id=customer_id,
            channel_id=channel_id,
        )

        data = payment_runtime.SELF_SERVICE_ORDER_SELECTIONS.get(channel_id, {})
        if not isinstance(data, dict) or not _is_paid_active_order(data):
            return
        if not isinstance(interaction.channel, discord.TextChannel):
            return

        await names._rename_quick_ticket_from_data(
            interaction.channel,
            data,
            status="active",
            member=(
                interaction.guild.get_member(customer_id)
                if interaction.guild is not None
                else None
            ),
        )

    payment_runtime.finalize_accepted_pending_payment = finalize_with_paid_ticket_rename
    # order_runtime imported the payment finalizer directly, so update its alias too.
    order_runtime.finalize_accepted_pending_payment = finalize_with_paid_ticket_rename
    payment_runtime._paid_ticket_finalize_rename_installed = True
    print("[order-ticket-ui] post-payment ticket rename installed", flush=True)


def _install_quick_reselect_policy() -> None:
    from services import quick_order_v2 as quick

    if getattr(quick, "_legacy_reselect_policy_installed", False):
        return

    original_install_ticket_patch = quick._install_ticket_patch

    def install_ticket_patch_with_legacy_reselect() -> None:
        original_install_ticket_patch()
        if getattr(quick, "_legacy_reselect_view_installed", False):
            return

        from core.database import remember_order_data
        from services import order_runtime
        from services import self_service_runtime as runtime
        from services import self_service_selection_runtime as selection_runtime
        from services import self_service_ui_runtime as ui

        quick_view_init = ui.SelfServiceOrderView.__init__
        quick_panel_builder = ui.build_self_service_panel_embed

        def classic_aware_view_init(
            self,
            customer_id: int,
            channel_id: int,
            selected_category: str | None = None,
        ) -> None:
            data = ui.SELF_SERVICE_ORDER_SELECTIONS.get(channel_id, {})
            is_quick = isinstance(data, dict) and bool(data.get("quick_order_v2"))

            # The customer-service "重派自助下單" path intentionally constructs
            # SelfServiceOrderView without a fixed category. Treat that as an
            # explicit request for the original four-row selector UI and persist
            # the mode so every subsequent refresh stays on the classic layout.
            if is_quick and selected_category is None:
                data[_LEGACY_RESELECT_FLAG] = True
                remember_order_data(channel_id, data)

            if (
                is_quick
                and bool(data.get(_LEGACY_RESELECT_FLAG))
                and quick._ORIGINAL_VIEW_INIT is not None
            ):
                quick._ORIGINAL_VIEW_INIT(
                    self,
                    customer_id,
                    channel_id,
                    selected_category,
                )
                _apply_selected_dropdown_state(self, data)
                return

            quick_view_init(
                self,
                customer_id,
                channel_id,
                selected_category,
            )

        def classic_aware_panel_builder(
            customer_id: int,
            data: dict,
            guild=None,
        ):
            if (
                isinstance(data, dict)
                and data.get("quick_order_v2")
                and data.get(_LEGACY_RESELECT_FLAG)
                and quick._ORIGINAL_PANEL_BUILDER is not None
            ):
                return quick._ORIGINAL_PANEL_BUILDER(customer_id, data, guild)
            return quick_panel_builder(customer_id, data, guild)

        ui.SelfServiceOrderView.__init__ = classic_aware_view_init
        ui.build_self_service_panel_embed = classic_aware_panel_builder
        runtime.build_self_service_panel_embed = classic_aware_panel_builder
        selection_runtime.build_self_service_panel_embed = classic_aware_panel_builder

        state = getattr(order_runtime, "_RUNTIME_STATE", None)
        if state is not None:
            try:
                order_runtime._RUNTIME_STATE = replace(
                    state,
                    self_service_panel_embed_builder=classic_aware_panel_builder,
                )
            except Exception:
                pass

        _install_payment_finalize_rename_policy(order_runtime)
        quick._legacy_reselect_view_installed = True
        print("[order-ticket-ui] classic four-selector re-dispatch installed", flush=True)

    quick._install_ticket_patch = install_ticket_patch_with_legacy_reselect
    quick._legacy_reselect_policy_installed = True


def _install_paid_ticket_prefix_policy() -> None:
    from services import order_ticket_name_restore_runtime as names

    if getattr(names, "_paid_ticket_prefix_policy_installed", False):
        return

    original_order_prefix = names._order_prefix

    def paid_aware_order_prefix(data: dict, status: str = "active") -> str:
        prefix = original_order_prefix(data, status)
        normalized = str(status or "").strip().lower()
        if normalized != "active" or not _is_paid_active_order(data):
            return prefix

        if prefix == "下單":
            return "訂單"
        if prefix.startswith("下單-"):
            return "訂單-" + prefix[len("下單-"):]
        return prefix

    names._order_prefix = paid_aware_order_prefix
    names._paid_ticket_prefix_policy_installed = True
    print("[order-ticket-ui] paid quick-ticket prefix policy installed", flush=True)


def install_order_ticket_ui_policy() -> None:
    global _INSTALLED
    if _INSTALLED:
        return

    _install_quick_reselect_policy()
    _install_paid_ticket_prefix_policy()
    _INSTALLED = True


__all__ = ["install_order_ticket_ui_policy"]
