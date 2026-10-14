from pathlib import Path


path = Path("services/self_service_financials.py")
text = path.read_text(encoding="utf-8")

old = '''    selected_vip_monthly, vip_monthly_cash = resolve_vip_monthly_cash_discount(
        data,
        has_point_benefit=benefit is not None,
        max_discount_amount=after_fixed,
    )

    from services.loyalty_benefits import (
        calculate_coupon_service_value,
        coupon_service_note,
        get_applicable_coupon,
        preview_same_order_benefit,
    )

    selected_coupon = None
    selected_coupon_id = data.get("selected_benefit_coupon_id")
    selected_same_order = bool(data.get("selected_same_order_benefit"))
    if selected_coupon_id not in (None, "") or selected_same_order:
        if benefit is not None or selected_vip_monthly is not None:
            raise ValueError("福利券、VIP 每月福利券與點數福利同張訂單只能擇一使用。")

        customer_id = data.get("customer_id")
        if selected_coupon_id not in (None, ""):
            if customer_id:
                selected_coupon = get_applicable_coupon(
                    selected_coupon_id,
                    customer_id=customer_id,
                    rule_key=str(getattr(rule, "key", "")),
                    player_count=_to_int(data.get("player_count"), 1) or 1,
                )
            if selected_coupon is None:
                raise ValueError("這張福利券已使用、已保留，或不適用這個方案。")
        elif customer_id:
            selected_coupon = preview_same_order_benefit(
                customer_id,
                rule_key=str(getattr(rule, "key", "")),
                quantity=max(1, _to_int(data.get("quantity"), 1) or 1),
                player_count=_to_int(data.get("player_count"), 1) or 1,
            )

    quantity_for_extra = max(1, _to_int(data.get("quantity"), 1) or 1)
    point_service_value = 0
    if extra_hours > 0:
        point_service_value = max(0, int(round((service_original / quantity_for_extra) * extra_hours)))
    elif extra_games > 0:
        point_service_value = max(0, int(round((service_original / quantity_for_extra) * extra_games)))

    benefit_service_value = calculate_coupon_service_value(
        rule_key=str(getattr(rule, "key", "")),
        player_count=_to_int(data.get("player_count"), 1) or 1,
        coupon=selected_coupon,
    )
    benefit_discount_amount = max(
        0,
        min(after_fixed, int(benefit_service_value or 0)),
    )

    allocation = allocate_store_absorbed_fixed_discount(
        after_percent_amount=after_percent,
        fixed_discount_amount=fixed,
        additional_store_discount_amount=(
            point_cash
            + vip_monthly_cash
            + benefit_discount_amount
        ),
        extra_customer_charge_amount=specify_effective,
    )
'''
new = '''    selected_vip_monthly, vip_monthly_cash = resolve_vip_monthly_cash_discount(
        data,
        has_point_benefit=benefit is not None,
        max_discount_amount=after_fixed,
    )

    allocation = allocate_store_absorbed_fixed_discount(
        after_percent_amount=after_percent,
        fixed_discount_amount=fixed,
        additional_store_discount_amount=point_cash + vip_monthly_cash,
        extra_customer_charge_amount=specify_effective,
    )

    from services.self_service_loyalty_discount import resolve_self_service_loyalty_discount

    loyalty_discount = resolve_self_service_loyalty_discount(
        data=data,
        rule=rule,
        point_benefit_selected=benefit is not None,
        vip_monthly_selected=selected_vip_monthly is not None,
        available_service_amount=after_fixed,
        to_int=_to_int,
    )
    benefit_service_value = loyalty_discount["service_value"]
    benefit_discount_amount = loyalty_discount["discount_amount"]

    quantity_for_extra = max(1, _to_int(data.get("quantity"), 1) or 1)
    point_service_value = 0
    if extra_hours > 0:
        point_service_value = max(0, int(round((service_original / quantity_for_extra) * extra_hours)))
    elif extra_games > 0:
        point_service_value = max(0, int(round((service_original / quantity_for_extra) * extra_games)))
'''
if old not in text:
    raise SystemExit("loyalty calculation block not found")
text = text.replace(old, new, 1)

text = text.replace(
    "    customer_pay = allocation.customer_pay_amount\n",
    "    customer_pay = max(0, allocation.customer_pay_amount - benefit_discount_amount)\n",
    1,
)

old_return = '''        "benefit_coupon_id": (
            int(selected_coupon.get("id"))
            if selected_coupon and selected_coupon.get("id") not in (None, "")
            else None
        ),
        "benefit_coupon_title": (str(selected_coupon.get("title") or "") if selected_coupon else ""),
        "benefit_coupon": (dict(selected_coupon) if selected_coupon else None),
        "benefit_service_note": coupon_service_note(selected_coupon),
        "benefit_service_value": benefit_service_value,
        "benefit_discount_amount": benefit_discount_amount,
'''
new_return = '''        "benefit_coupon_id": loyalty_discount["coupon_id"],
        "benefit_coupon_title": loyalty_discount["coupon_title"],
        "benefit_coupon": loyalty_discount["coupon"],
        "benefit_service_note": loyalty_discount["service_note"],
        "benefit_service_value": benefit_service_value,
        "benefit_discount_amount": benefit_discount_amount,
'''
if old_return not in text:
    raise SystemExit("loyalty return block not found")
text = text.replace(old_return, new_return, 1)

text = text.replace(
    '''        "store_absorbed_amount": (
            allocation.store_absorbed_amount
            + point_specify
            + point_service_value
        ),
''',
    '''        "store_absorbed_amount": (
            allocation.store_absorbed_amount
            + benefit_discount_amount
            + point_specify
            + point_service_value
        ),
''',
    1,
)

path.write_text(text, encoding="utf-8")
