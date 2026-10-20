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

    # These guards patch services.vip_timer itself. Install them before
    # vip_timer_runtime imports timer functions into local bindings so every
    # persistent Discord callback gets the guarded lifecycle/catalog behavior.
    from services.vip_timer_catalog_guard import install_vip_timer_catalog_guard
    from services.vip_timer_lifecycle import install_vip_timer_lifecycle_guard

    install_vip_timer_catalog_guard()
    install_vip_timer_lifecycle_guard()

    # The timer core is shared by web and Discord. The Discord self-service
    # storefront is a separate catalog/runtime, so install its bridge explicitly
    # after the canonical timer guards are in place.
    from services.vip_timer_self_service import install_vip_timer_self_service

    install_vip_timer_self_service()

    from services.vip_timer_recovery import install_vip_timer_payment_recovery
    from services.vip_timer_runtime import (
        VipTimerControlView,
        install_acceptance_payment_hook,
    )
    from services.vip_timer_runtime_guard import install_vip_timer_runtime_guard

    install_acceptance_payment_hook()
    install_vip_timer_payment_recovery()
    install_vip_timer_runtime_guard(
        bot_instance=bot_instance,
        guild_id=int(guild_id),
    )

    if getattr(bot_instance, "_vip_timer_control_view_registered", False):
        return

    try:
        add_view(VipTimerControlView())
    except ValueError:
        pass

    bot_instance._vip_timer_control_view_registered = True


__all__ = ["configure_vip_timer_acceptance"]
