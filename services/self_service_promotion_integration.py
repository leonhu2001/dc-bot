from __future__ import annotations

from services.order_discounts import FUNDING_SHARED


_INSTALLED = False


def _original_service_amount(rule, data: dict, fallback: int) -> int:
    """Resolve the current order's original eligible service amount.

    Manual-price rules must use the current staff-entered amount. Standard rules
    are recalculated from the current quantity/player count first so changing an
    order after selecting a benefit cannot keep an older, higher eligibility
    amount in the draft. Stored values are only a compatibility fallback.
    """
    try:
        from services.self_service_financials import (
            get_self_service_staff_price,
            is_self_service_staff_price_required,
        )

        if is_self_service_staff_price_required(rule):
            manual = get_self_service_staff_price(data)
            return max(0, int(manual or 0))
    except Exception:
        pass

    try:
        from services.order_rules import calculate_price

        price = calculate_price(
            rule,
            quantity=max(1, int(data.get("quantity") or 1)),
            player_count=max(1, int(data.get("player_count") or 1)),
            specified_roles=[],
        )
        return max(
            0,
            int(getattr(price, "base_amount", 0) or 0)
            + int(getattr(price, "staff_adjustment_amount", 0) or 0),
        )
    except Exception:
        pass

    values = [
        data.get("service_original_amount"),
        data.get("original_amount"),
        data.get("manual_staff_amount"),
        fallback,
    ]
    for value in values:
        try:
            amount = int(value or 0)
        except (TypeError, ValueError):
            amount = 0
        if amount > 0:
            return amount
    return 0


def _category_for_rule_key(rule_key: str) -> str:
    try:
        from services.order_rules import get_rule

        return str(getattr(get_rule(str(rule_key or "")), "category", "") or "")
    except Exception:
        return ""


def install_self_service_promotion_integration() -> None:
    """Make web-issued promotion benefits selectable and payable in Discord checkout."""
    global _INSTALLED
    if _INSTALLED:
        return

    from services import loyalty_benefits as loyalty
    from services import promotion_benefits as promotion
    from services import self_service_financials as financials
    from services import self_service_loyalty_discount as loyalty_discount

    if not hasattr(loyalty, "_promotion_original_list_applicable_coupons"):
        loyalty._promotion_original_list_applicable_coupons = loyalty.list_applicable_coupons

        def list_applicable_coupons(customer_id, *, rule_key: str, player_count: int = 1):
            rows = list(
                loyalty._promotion_original_list_applicable_coupons(
                    customer_id,
                    rule_key=rule_key,
                    player_count=player_count,
                )
            )
            category = _category_for_rule_key(rule_key)
            for item in promotion.list_issued_benefits(customer_discord_id=customer_id):
                if str(item.get("status") or "") != promotion.ACTIVE:
                    continue
                if int(item.get("remaining_uses") or 0) <= 0:
                    continue
                decorated = promotion._decorate_issued(item)
                rules = decorated.get("rules") or {}
                scope_type = str(rules.get("scope_type") or "all")
                if scope_type == "category" and not category:
                    # Unknown/dynamic rule: do not advertise a category-restricted
                    # benefit unless we can prove the category matches. Final
                    # checkout validation remains authoritative as well.
                    continue
                if not promotion._scope_allowed(
                    rules,
                    rule_key=str(rule_key or ""),
                    category=category,
                ):
                    continue
                decorated["summary"] = promotion.benefit_note(decorated)
                rows.append(decorated)
            return rows

        loyalty.list_applicable_coupons = list_applicable_coupons

    if not hasattr(loyalty_discount, "_promotion_original_resolve_self_service_loyalty_discount"):
        loyalty_discount._promotion_original_resolve_self_service_loyalty_discount = (
            loyalty_discount.resolve_self_service_loyalty_discount
        )

        def resolve_self_service_loyalty_discount(
            *,
            data: dict,
            rule,
            point_benefit_selected: bool,
            vip_monthly_selected: bool,
            available_service_amount: int,
            to_int,
        ):
            selected_id = data.get("selected_benefit_coupon_id")
            if promotion.decode_selection_id(selected_id) is None:
                return loyalty_discount._promotion_original_resolve_self_service_loyalty_discount(
                    data=data,
                    rule=rule,
                    point_benefit_selected=point_benefit_selected,
                    vip_monthly_selected=vip_monthly_selected,
                    available_service_amount=available_service_amount,
                    to_int=to_int,
                )
            if point_benefit_selected or vip_monthly_selected:
                raise ValueError("優惠福利、VIP 每月福利券與點數福利同張訂單只能擇一使用。")

            customer_id = data.get("customer_id")
            if not customer_id:
                raise ValueError("找不到會員資料，無法使用這張優惠福利。")
            original = _original_service_amount(rule, data, available_service_amount)

            try:
                rate, _reason, discount_source, _vip_level = (
                    financials._resolve_self_service_discount_rate(rule, data)
                )
                vip_discount_active = discount_source == "vip" and float(rate) < 100
            except Exception:
                vip_discount_active = False

            benefit = promotion.get_applicable_issued_benefit(
                selected_id,
                customer_discord_id=customer_id,
                rule_key=str(getattr(rule, "key", "") or ""),
                category=str(getattr(rule, "category", "") or ""),
                original_service_amount=original,
                vip_discount_active=vip_discount_active,
                point_selected=False,
            )
            if benefit is None:
                raise ValueError("這張優惠福利已使用、已保留，或目前訂單未達使用條件。")

            specify_fee = max(
                0,
                int(
                    data.get("effective_specify_fee")
                    or data.get("specified_fee_before_waiver")
                    or 0
                ),
            )
            quantity = max(1, int(data.get("quantity") or 1))
            player_count = max(1, int(data.get("player_count") or 1))
            try:
                from services.order_rules import get_required_staff_count

                staff_count = max(1, int(get_required_staff_count(rule, player_count) or 1))
            except Exception:
                staff_count = player_count

            discount = promotion.calculate_discount_amount(
                benefit,
                service_amount_after_percent=max(0, int(available_service_amount or 0)),
                original_service_amount=original,
                specify_fee=specify_fee,
                quantity=quantity,
                staff_count=staff_count,
            )
            return {
                "coupon": benefit,
                "coupon_id": int(selected_id),
                "coupon_title": str(benefit.get("title") or "優惠福利"),
                "service_note": promotion.benefit_note(benefit),
                "service_value": int(discount),
                "discount_amount": int(discount),
            }

        loyalty_discount.resolve_self_service_loyalty_discount = resolve_self_service_loyalty_discount

    if not hasattr(financials, "_promotion_original_calculate_self_service_financials"):
        financials._promotion_original_calculate_self_service_financials = financials.calculate_self_service_financials

        def calculate_self_service_financials(rule, price_result, data: dict):
            result = financials._promotion_original_calculate_self_service_financials(rule, price_result, data)
            benefit = result.get("benefit_coupon")
            if not isinstance(benefit, dict) or str(benefit.get("source") or "") != "promotion":
                return result
            discount = max(0, int(result.get("benefit_discount_amount") or 0))
            if str(benefit.get("funding") or "") == FUNDING_SHARED and discount > 0:
                # Shared benefit affects customer payment and payout basis once at
                # order level. The base financial engine initially treats member
                # service benefits as store-funded, so reverse only that subsidy.
                result["payout_base_amount"] = max(
                    0,
                    int(result.get("payout_base_amount") or 0) - discount,
                )
                result["store_absorbed_amount"] = max(
                    0,
                    int(result.get("store_absorbed_amount") or 0) - discount,
                )
            return result

        financials.calculate_self_service_financials = calculate_self_service_financials

    _INSTALLED = True
