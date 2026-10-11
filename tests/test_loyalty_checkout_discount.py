from web.app.services.checkout_preview import calculate_checkout_financials


def test_loyalty_coupon_reduces_customer_service_charge_without_reducing_payout():
    coupon = {"id": 7, "title": "VALORANT｜娛樂陪｜折抵 30 分鐘額度", "benefit_kind": "extra_hours", "benefit_units": 0.5}

    finance = calculate_checkout_financials(
        service_amount=1200,
        vip_pay_rate=100,
        specify_fee=0,
        point_item=None,
        wallet_balance=0,
        use_wallet=False,
        benefit_coupon=coupon,
        benefit_service_value=150,
    )

    assert finance["benefit_discount_amount"] == 150
    assert finance["customer_pay_amount"] == 1050
    assert finance["cash_coupon_amount"] == 150
    assert finance["store_absorbed_amount"] == 150
    assert finance["payout_base_amount"] == 1200


def test_loyalty_coupon_only_discounts_service_and_never_makes_total_negative():
    coupon = {"id": 8, "title": "福利券", "benefit_kind": "extra_hours", "benefit_units": 10}

    finance = calculate_checkout_financials(
        service_amount=100,
        vip_pay_rate=100,
        specify_fee=80,
        point_item=None,
        wallet_balance=0,
        use_wallet=False,
        benefit_coupon=coupon,
        benefit_service_value=9999,
    )

    assert finance["benefit_discount_amount"] == 100
    assert finance["customer_pay_amount"] == 80
    assert finance["payout_base_amount"] == 180
    assert finance["store_absorbed_amount"] == 100
