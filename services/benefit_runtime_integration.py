from __future__ import annotations


_INSTALLED = False


def install_root_benefit_integrations() -> None:
    """Install shared benefit lifecycle hooks exactly once.

    The existing loyalty coupon lifecycle remains the canonical order hook. We
    extend that hook for the new promotion-benefit table so cancellation and
    close-order paths automatically release/redeem both kinds of benefits.
    """
    global _INSTALLED
    if _INSTALLED:
        return

    from services import loyalty_benefits as loyalty
    from services import promotion_benefits as promotion
    from services import promotion_benefit_lifecycle as promotion_lifecycle
    from services.dynamic_game_point_policy import install_dynamic_game_point_policy
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
    install_dynamic_game_point_policy()
    install_self_service_promotion_integration()
    install_self_service_financial_copy_policy()
    install_self_service_vip_monthly_ux()

    # Keep one canonical reservation implementation. promotion_benefits retains
    # its public compatibility name, but production callers are routed through
    # the transaction-safe lifecycle service rather than the retired draft path.
    promotion.reserve_issued_benefit_in_session = promotion_lifecycle.reserve_in_session

    if not hasattr(loyalty, "_promotion_original_reserve_coupon_in_session"):
        loyalty._promotion_original_reserve_coupon_in_session = loyalty.reserve_coupon_in_session
        loyalty._promotion_original_release_coupon_for_order = loyalty.release_coupon_for_order
        loyalty._promotion_original_redeem_coupon_for_order = loyalty.redeem_coupon_for_order

        def reserve_coupon_in_session(
            db,
            *,
            coupon_id: int,
            customer_id,
            order_id: int,
            rule_key: str,
            player_count: int = 1,
        ) -> None:
            if promotion.decode_selection_id(coupon_id) is not None:
                promotion_lifecycle.reserve_in_session(
                    db,
                    selection_id=coupon_id,
                    customer_discord_id=customer_id,
                    order_id=order_id,
                )
                return
            loyalty._promotion_original_reserve_coupon_in_session(
                db,
                coupon_id=coupon_id,
                customer_id=customer_id,
                order_id=order_id,
                rule_key=rule_key,
                player_count=player_count,
            )

        def release_coupon_for_order(order_id: int) -> int:
            loyalty_count = loyalty._promotion_original_release_coupon_for_order(order_id)
            promotion_count = promotion_lifecycle.release_for_order(order_id)
            return int(loyalty_count or 0) + int(promotion_count or 0)

        def redeem_coupon_for_order(order_id: int) -> int:
            loyalty_count = loyalty._promotion_original_redeem_coupon_for_order(order_id)
            promotion_count = promotion_lifecycle.redeem_for_order(order_id)
            return int(loyalty_count or 0) + int(promotion_count or 0)

        loyalty.reserve_coupon_in_session = reserve_coupon_in_session
        loyalty.release_coupon_for_order = release_coupon_for_order
        loyalty.redeem_coupon_for_order = redeem_coupon_for_order

    _INSTALLED = True
