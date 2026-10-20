from __future__ import annotations

from services.vip_timer import get_session, is_vip_timer_order_data


_INSTALLED = False


def install_vip_timer_payment_recovery() -> None:
    """Make the timer -> payment handoff restart-safe.

    The live Discord state dict is persisted separately from the authoritative
    timer session. If the bot stops after end_timer() commits but before the
    payment-panel flag is saved, repair workers must still route the order to
    payment rather than recreating a non-operable timer panel.
    """
    global _INSTALLED
    if _INSTALLED:
        return
    _INSTALLED = True

    from services.acceptance import dispatch_refresh as dispatch_module
    from services.acceptance import payment_panel as payment_module

    current = dispatch_module.ensure_acceptance_payment_panel

    async def restart_safe_ensure(*args, **kwargs):
        data = kwargs.get("data")
        if is_vip_timer_order_data(data):
            state = kwargs.get("state")
            order_id = int(
                getattr(state, "order_id", 0)
                or (data or {}).get("web_order_id")
                or 0
            )
            if order_id > 0:
                session = get_session(order_id)
                if str((session or {}).get("status") or "") == "pending_payment":
                    if isinstance(data, dict):
                        data["vip_timer_pending_payment"] = True
        return await current(*args, **kwargs)

    dispatch_module.ensure_acceptance_payment_panel = restart_safe_ensure
    payment_module.ensure_acceptance_payment_panel = restart_safe_ensure


__all__ = ["install_vip_timer_payment_recovery"]
