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

    from services.self_service_retract_runtime_fix import install_self_service_retract_runtime_fix

    install_self_service_retract_runtime_fix()

    from services.vip_timer_catalog_guard import install_vip_timer_catalog_guard
    from services.vip_timer_lifecycle import install_vip_timer_lifecycle_guard
    from services.vip_timer_ops import install_vip_timer_snapshot_guard

    install_vip_timer_catalog_guard()
    install_vip_timer_lifecycle_guard()
    # Install before importing the Discord self-service bridge so every new
    # timer session records the member level that existed at order creation.
    install_vip_timer_snapshot_guard()

    from services.vip_timer_self_service import install_vip_timer_self_service

    install_vip_timer_self_service()

    # VIP timer self-service replaces the generic dispatch creator. Install the
    # unpaid-timer guard afterward so it is the outer boundary for every new
    # Discord self-service order, normal or VIP timer.
    from services.vip_timer_pending_order_guard import install_discord_pending_order_guard

    install_discord_pending_order_guard()

    from services.vip_timer_select_flow import install_vip_timer_select_flow
    from services.vip_timer_selector_order_v2 import install_vip_timer_selector_order_v2
    from services.vip_timer_selector_order_v3 import install_vip_timer_selector_order_v3
    from services.vip_timer_selector_order_v4 import install_vip_timer_selector_order_v4

    install_vip_timer_select_flow()
    install_vip_timer_selector_order_v2()
    install_vip_timer_selector_order_v3()
    # v4 fixes the checkout hierarchy to category -> game -> gameplay ->
    # headcount without changing the normal self-service catalog.
    install_vip_timer_selector_order_v4()

    from services.vip_timer_policy_v5 import install_vip_timer_policy_v5

    install_vip_timer_policy_v5()

    from services.vip_timer_billing_guard import install_vip_timer_billing_guard
    from services.vip_timer_end_confirmation import install_vip_timer_end_confirmation
    from services.vip_timer_monitor import install_vip_timer_monitor
    from services.vip_timer_pause_expiry import install_vip_timer_pause_expiry
    from services.vip_timer_recovery import install_vip_timer_payment_recovery
    from services import vip_timer_runtime as timer_runtime
    from services.vip_timer_runtime_guard import install_vip_timer_runtime_guard
    from services.vip_timer_runtime_order_v5 import install_vip_timer_runtime_order_v5
    from services.vip_timer_runtime_selector_v6 import install_vip_timer_runtime_selector_v6
    from services.vip_timer_roster_payout import install_vip_timer_roster_payout
    from services.vip_timer_roster_runtime import install_vip_timer_roster_runtime

    install_vip_timer_billing_guard()
    install_vip_timer_runtime_order_v5()
    # Replace the legacy two-level in-ticket switcher after the category-order
    # compatibility patch. The switcher now mirrors checkout exactly:
    # game -> gameplay -> currently-available headcount package.
    install_vip_timer_runtime_selector_v6()
    timer_runtime.install_acceptance_payment_hook()
    install_vip_timer_payment_recovery()
    install_vip_timer_runtime_guard(
        bot_instance=bot_instance,
        guild_id=int(guild_id),
    )
    # Roster controls must wrap the final guarded runtime so Resume can open a
    # fresh segment after an add/reduce/replace boundary.
    install_vip_timer_roster_runtime(
        bot_instance=bot_instance,
        guild_id=int(guild_id),
    )
    # End confirmation is installed after roster guards so the second side's
    # confirmation still observes incomplete-roster protections.
    install_vip_timer_end_confirmation()
    # Pause expiry must be the outermost resume guard: every resume path,
    # including a fresh post-roster segment, is blocked after two hours or a
    # Taiwan calendar-day rollover.
    install_vip_timer_pause_expiry()
    # Payment finalization imports acceptance promotion lazily, so this wrapper
    # safely replaces the equal-share payout with the timer segment ledger.
    install_vip_timer_roster_payout()
    install_vip_timer_monitor(bot_instance)

    if getattr(bot_instance, "_vip_timer_control_view_registered", False):
        return

    try:
        add_view(timer_runtime.VipTimerControlView())
    except ValueError:
        pass

    bot_instance._vip_timer_control_view_registered = True


__all__ = ["configure_vip_timer_acceptance"]
