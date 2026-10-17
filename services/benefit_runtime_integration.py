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
    from services import vip_monthly_benefits as vip_monthly

    # New VIP monthly cash policy: tier entitlement opens the monthly benefit;
    # usage eligibility is enforced against the current order amount instead of
    # a trailing-30-day spend gate.
    for level_name in list(vip_monthly.VIP_MONTHLY_RECENT_SPEND_MINIMUM):
        vip_monthly.VIP_MONTHLY_RECENT_SPEND_MINIMUM[level_name] = 0

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
                promotion.reserve_in_sqlalchemy_session(
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
            promotion_count = promotion.release_for_order(order_id)
            return int(loyalty_count or 0) + int(promotion_count or 0)

        def redeem_coupon_for_order(order_id: int) -> int:
            loyalty_count = loyalty._promotion_original_redeem_coupon_for_order(order_id)
            promotion_count = promotion.redeem_for_order(order_id)
            return int(loyalty_count or 0) + int(promotion_count or 0)

        loyalty.reserve_coupon_in_session = reserve_coupon_in_session
        loyalty.release_coupon_for_order = release_coupon_for_order
        loyalty.redeem_coupon_for_order = redeem_coupon_for_order

    _INSTALLED = True
