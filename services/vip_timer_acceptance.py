from __future__ import annotations


def configure_vip_timer_acceptance(bot_instance, guild_id: int) -> None:
    """Install VIP timer acceptance hooks for a live Discord bot.

    Keep this out of services.acceptance.runtime so the legacy orchestration
    module stays under its architecture growth budget, and skip harmless test
    doubles that do not expose discord.Client.add_view().
    """
    add_view = getattr(bot_instance, "add_view", None)
    if not callable(add_view):
        return

    # The persistent self-service retract view is registered later by bot.py.
    # Patch its instance callback now so the refactored runtime state is used and
    # Discord is acknowledged before any DB/network cleanup begins.
    from services.self_service_retract_runtime_fix import install_self_service_retract_runtime_fix

    install_self_service_retract_runtime_fix()

    # These guards patch services.vip_timer itself. Install them before
    # vip_timer_runtime imports timer functions into local bindings so every
    # persistent Discord callback gets the guarded lifecycle/catalog behavior.
    from services.vip_timer_catalog_guard import install_vip_timer_catalog_guard
    from services.vip_timer_lifecycle import install_vip_timer_lifecycle_guard
    from services.vip_timer_billing_guard import install_vip_timer_billing_guard

    install_vip_timer_catalog_guard()
    install_vip_timer_lifecycle_guard()
    install_vip_timer_billing_guard()

    # The timer core is shared by web and Discord. The Discord self-service
    # storefront is a separate catalog/runtime, so install its bridge explicitly
    # after the canonical timer guards are in place.
    from services.vip_timer_self_service import install_vip_timer_self_service

    install_vip_timer_self_service()

    # Build the timer-only selector tree first, then refine it to:
    # category -> game -> gameplay -> family-specific service choice. Duration
    # remains free-running and is never selected up front.
    from services.vip_timer_select_flow import install_vip_timer_select_flow
    from services.vip_timer_selector_order_v2 import install_vip_timer_selector_order_v2
    from services.vip_timer_selector_order_v3 import install_vip_timer_selector_order_v3
    from services.vip_timer_selector_order_v4 import install_vip_timer_selector_order_v4

    install_vip_timer_select_flow()
    install_vip_timer_selector_order_v2()
    install_vip_timer_selector_order_v3()
    install_vip_timer_selector_order_v4()

    from services.vip_timer_recovery import install_vip_timer_payment_recovery
    from services.vip_timer_runtime import (
        VipTimerControlView,
        install_acceptance_payment_hook,
    )
    from services.vip_timer_pause_runtime_guard import install_vip_timer_pause_runtime_guard
    from services.vip_timer_runtime_guard import install_vip_timer_runtime_guard

    install_acceptance_payment_hook()
    install_vip_timer_payment_recovery()
    install_vip_timer_runtime_guard(
        bot_instance=bot_instance,
        guild_id=int(guild_id),
    )
    # Patch the already-imported persistent control view before registering it.
    install_vip_timer_pause_runtime_guard()

    if getattr(bot_instance, "_vip_timer_control_view_registered", False):
        return

    try:
        add_view(VipTimerControlView())
    except ValueError:
        pass

    bot_instance._vip_timer_control_view_registered = True


__all__ = ["configure_vip_timer_acceptance"]
