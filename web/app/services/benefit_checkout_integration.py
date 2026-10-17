from __future__ import annotations

from typing import Any

from services import promotion_benefits as promotion


_INSTALLED = False


def install_checkout_benefit_integration() -> None:
    """Extend the existing checkout with issued promotion benefits.

    This adapter keeps the established quote / staff / point validation as the
    single source of truth. It only adds promotion selection and applies funding
    semantics after the existing finance calculator has produced its canonical
    base result.
    """
    global _INSTALLED
    if _INSTALLED:
        return

    from web.app.services import checkout_preview as checkout

    if getattr(checkout, "_promotion_benefit_integration_installed", False):
        _INSTALLED = True
        return

    original_list = checkout.list_applicable_coupons
    original_get = checkout.get_applicable_coupon
    original_coupon_value = checkout.calculate_coupon_service_value
    original_coupon_note = checkout.coupon_service_note
    original_finance = checkout.calculate_checkout_financials

    def _rule_category(rule_key: str) -> str:
        rule = checkout.ORDER_RULES.get(str(rule_key or ""))
        return str(getattr(rule, "category", "") or "") if rule is not None else ""

    def list_applicable_coupons(
        customer_id,
        *,
        rule_key: str,
        player_count: int = 1,
    ) -> list[dict[str, Any]]:
        result = list(
            original_list(
                customer_id,
                rule_key=rule_key,
                player_count=player_count,
            )
            or []
        )
        promotions = promotion.list_applicable_issued_benefits(
            customer_id,
            rule_key=rule_key,
            category=_rule_category(rule_key),
            # Options are loaded before the user has selected a final coupon.
            # Show scope-valid coupons here; the exact order minimum is always
            # revalidated in the server finance call and again at formal create.
            original_service_amount=10**12,
        )
        for item in promotions:
            rules = item.get("rules") if isinstance(item.get("rules"), dict) else {}
            minimum = max(0, int(rules.get("min_order_amount") or 0))
            if minimum > 0:
                item["title"] = f"{item.get('title') or '優惠福利'}｜滿 {minimum:,}T 可用"
            result.append(item)
        return result

    def get_applicable_coupon(
        coupon_id,
        *,
        customer_id,
        rule_key: str,
        player_count: int = 1,
    ) -> dict[str, Any] | None:
        if promotion.decode_selection_id(coupon_id) is None:
            return original_get(
                coupon_id,
                customer_id=customer_id,
                rule_key=rule_key,
                player_count=player_count,
            )
        # Exact amount/VIP restrictions are checked by the financial adapter.
        candidates = promotion.list_applicable_issued_benefits(
            customer_id,
            rule_key=rule_key,
            category=_rule_category(rule_key),
            original_service_amount=10**12,
        )
        wanted = int(promotion.decode_selection_id(coupon_id) or 0)
        for item in candidates:
            if int(item.get("issued_benefit_id") or 0) == wanted:
                return item
        return None

    def calculate_coupon_service_value(
        *,
        rule_key: str,
        player_count: int,
        coupon: dict[str, Any] | None,
    ) -> int:
        if not coupon or str(coupon.get("source") or "") != "promotion":
            return original_coupon_value(
                rule_key=rule_key,
                player_count=player_count,
                coupon=coupon,
            )

        rules = coupon.get("rules") if isinstance(coupon.get("rules"), dict) else {}
        kind = str(rules.get("effect_kind") or "")
        if kind not in {promotion.EFFECT_FREE_HOURS, promotion.EFFECT_FREE_GAMES}:
            return 0

        rule = checkout.ORDER_RULES.get(str(rule_key or ""))
        if rule is None:
            return 0
        pricing_type = str(getattr(rule, "pricing_type", "") or "")
        if kind == promotion.EFFECT_FREE_HOURS and pricing_type != "hourly":
            raise ValueError("這張折抵時數福利只能用於計時商品。")
        if kind == promotion.EFFECT_FREE_GAMES and pricing_type != "game":
            raise ValueError("這張折抵局數福利只能用於計局商品。")

        units = max(0.0, float(rules.get("effect_value") or 0))
        if units <= 0:
            return 0
        try:
            one_unit = checkout.calculate_price(
                rule,
                quantity=1,
                player_count=(max(1, int(player_count or 1)) if bool(rule.player_count_enabled) else None),
                specified_roles=[],
                staff_adjustments=[],
            )
            order_unit_value = max(0, int(one_unit.customer_pay_amount or 0))
        except Exception:
            order_unit_value = max(0, int(getattr(rule, "price", 0) or 0))
            if bool(getattr(rule, "price_multiply_player_count", False)):
                order_unit_value *= max(1, int(player_count or 1))

        staff_count = max(
            1,
            int(checkout.get_required_staff_count(rule, max(1, int(player_count or 1))) or 1),
        )
        if str(rules.get("seat_mode") or "one_seat") == "whole_order":
            return max(0, int(round(order_unit_value * units)))
        return max(0, int(round((order_unit_value / staff_count) * units)))

    def coupon_service_note(coupon: dict[str, Any] | None) -> str:
        if coupon and str(coupon.get("source") or "") == "promotion":
            return promotion.benefit_note(coupon)
        return original_coupon_note(coupon)

    def calculate_checkout_financials(**kwargs) -> dict:
        benefit = kwargs.get("benefit_coupon")
        is_promotion = bool(
            benefit
            and isinstance(benefit, dict)
            and str(benefit.get("source") or "") == "promotion"
        )

        # Generic promotions are applied here instead of pretending they are a
        # loyalty service-unit coupon. This keeps customer charge and payroll
        # basis independent, which is required for store-funded sponsor/raffle
        # benefits where customer payment may be zero but payroll remains whole.
        base_kwargs = dict(kwargs)
        if is_promotion:
            base_kwargs["benefit_coupon"] = None
            base_kwargs["benefit_service_value"] = 0
        result = original_finance(**base_kwargs)

        # Point cash coupons are normal fixed discounts under the new policy:
        # customer, worker, CS and store share them. Free specify / added service
        # remain store-funded and therefore are intentionally untouched.
        point_cash = max(0, int(result.get("point_cash_discount") or 0))
        if point_cash > 0:
            result["payout_base_amount"] = max(
                0,
                int(result.get("payout_base_amount") or 0) - point_cash,
            )
            result["payout_base_preview"] = result["payout_base_amount"]
            result["point_store_absorbed_amount"] = max(
                0,
                int(result.get("point_store_absorbed_amount") or 0) - point_cash,
            )
            result["store_absorbed_amount"] = max(
                0,
                int(result.get("store_absorbed_amount") or 0) - point_cash,
            )
            result["store_absorbed_preview"] = result["store_absorbed_amount"]

        if not is_promotion:
            return result

        rules = benefit.get("rules") if isinstance(benefit.get("rules"), dict) else {}
        service_amount = max(0, int(kwargs.get("service_amount") or 0))
        vip_rate = max(0, min(100, int(kwargs.get("vip_pay_rate") or 100)))
        minimum = max(0, int(rules.get("min_order_amount") or 0))
        if service_amount < minimum:
            raise ValueError(
                f"{benefit.get('title') or '這張福利'}需單筆原始服務金額滿 {minimum:,}T 才能使用。"
            )
        if vip_rate < 100 and not bool(rules.get("allow_vip_discount", True)):
            raise ValueError("這張福利不可與 VIP 百分比折扣同時使用。")

        kind = str(rules.get("effect_kind") or "")
        service_after = max(
            0,
            int(result.get("service_after_vip") or 0)
            - max(0, int(result.get("point_cash_discount") or 0)),
        )
        specify_fee = max(0, int(result.get("effective_specify_fee") or 0))
        include_specify = bool(rules.get("include_specify_fee"))
        eligible_amount = service_after + (specify_fee if include_specify else 0)
        value = max(0.0, float(rules.get("effect_value") or 0))

        if kind == promotion.EFFECT_FIXED_CASH:
            remaining_value = benefit.get("remaining_value")
            cap = value if remaining_value in (None, "") else max(0.0, float(remaining_value or 0))
            discount = min(eligible_amount, max(0, int(round(cap))))
        elif kind == promotion.EFFECT_PERCENT:
            discount = min(eligible_amount, max(0, int(round(eligible_amount * value / 100))))
        elif kind == promotion.EFFECT_FREE_ORDER:
            discount = eligible_amount
        elif kind == promotion.EFFECT_WAIVE_SPECIFY:
            discount = min(eligible_amount, specify_fee)
        elif kind in {promotion.EFFECT_FREE_HOURS, promotion.EFFECT_FREE_GAMES}:
            discount = min(
                eligible_amount,
                max(0, int(kwargs.get("benefit_service_value") or 0)),
            )
        else:
            raise ValueError("這張福利的抵免類型目前不支援。")

        subtotal_before = max(0, int(result.get("subtotal_before_wallet") or 0))
        discount = min(subtotal_before, max(0, int(discount or 0)))
        subtotal_after = max(0, subtotal_before - discount)
        wallet_balance = max(0, int(kwargs.get("wallet_balance") or 0))
        wallet_use = min(wallet_balance, subtotal_after) if bool(kwargs.get("use_wallet")) else 0
        remaining = max(0, subtotal_after - wallet_use)

        funding = str(rules.get("funding") or promotion.FUNDING_STORE)
        store_absorbed = max(0, int(result.get("store_absorbed_amount") or 0))
        payout_base = max(0, int(result.get("payout_base_amount") or 0))
        if funding == promotion.FUNDING_SHARED:
            payout_base = max(0, payout_base - discount)
        else:
            store_absorbed += discount

        result.update(
            {
                "cash_coupon_amount": discount,
                "fixed_discount_amount": discount,
                "benefit_coupon_id": int(benefit.get("id")),
                "benefit_coupon_title": str(benefit.get("title") or ""),
                "benefit_service_note": promotion.benefit_note(benefit),
                # Promotion time/game vouchers discount ordered service; they do
                # not add extra service units, so do not subtract this from the
                # CS commission basis as loyalty/point bonus service would.
                "benefit_service_value": 0,
                "benefit_discount_amount": discount,
                "benefit_store_absorbed_amount": (
                    discount if funding == promotion.FUNDING_STORE else 0
                ),
                "promotion_benefit_id": int(benefit.get("issued_benefit_id") or 0),
                "promotion_funding": funding,
                "promotion_discount_amount": discount,
                "subtotal_before_wallet": subtotal_after,
                "customer_pay_amount": subtotal_after,
                "wallet_use_amount": wallet_use,
                "remaining_pay_amount": remaining,
                "payout_base_amount": payout_base,
                "payout_base_preview": payout_base,
                "store_absorbed_amount": store_absorbed,
                "store_absorbed_preview": store_absorbed,
            }
        )
        return result

    checkout.list_applicable_coupons = list_applicable_coupons
    checkout.get_applicable_coupon = get_applicable_coupon
    checkout.calculate_coupon_service_value = calculate_coupon_service_value
    checkout.coupon_service_note = coupon_service_note
    checkout.calculate_checkout_financials = calculate_checkout_financials
    checkout._promotion_benefit_integration_installed = True
    _INSTALLED = True
