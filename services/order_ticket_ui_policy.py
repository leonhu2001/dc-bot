from __future__ import annotations

import discord


_INSTALLED = False


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


def install_payment_finalize_rename_policy(order_runtime) -> None:
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
    """Install order-ticket naming policy without owning Quick Order View patches."""
    global _INSTALLED
    if _INSTALLED:
        return

    _install_paid_ticket_prefix_policy()
    _INSTALLED = True


__all__ = [
    "install_order_ticket_ui_policy",
    "install_payment_finalize_rename_policy",
]
