from __future__ import annotations


_INSTALLED = False


def install_root_benefit_integrations() -> None:
    """Install shared benefit lifecycle hooks exactly once.

    Business rules and pricing live in their canonical modules. This startup hook
    is limited to one-time data migrations plus cross-table lifecycle integration;
    it must not rebind point/loyalty pricing or eligibility functions.
    """
    global _INSTALLED
    if _INSTALLED:
        return

    from services.loyalty_companion_fix_20261029 import run_loyalty_companion_repair_20261029
    from services.payout_policy_migration import freeze_existing_orders_on_legacy_cs_policy
    from services.self_service_financial_copy import install_self_service_financial_copy_policy
    from services.self_service_promotion_integration import install_self_service_promotion_integration
    from services.self_service_vip_monthly_ux import install_self_service_vip_monthly_ux
    from services.vip_monthly_cash_policy import install_cash_entitlement_wrapper

    # First startup after deployment is the policy boundary. Orders that already
    # exist keep the old gross-5% CS formula; new orders use margin-pool 25%.
    freeze_existing_orders_on_legacy_cs_policy()

    # Cash coupons are tier entitlements and no longer require trailing-30-day
    # spend. The Black Diamond service benefit keeps its existing activity gate
    # until that separate policy is decided.
    install_cash_entitlement_wrapper()

    # 2026-10-29 v5 is a data reconciliation only. Runtime parsing and selected-
    # tier valuation now live directly in loyalty_benefits.py.
    run_loyalty_companion_repair_20261029()

    install_self_service_promotion_integration()
    install_self_service_financial_copy_policy()
    install_self_service_vip_monthly_ux()

    # Promotion reservation/release/redemption now live in their canonical
    # source functions; do not rebind already imported lifecycle functions.
    _INSTALLED = True
