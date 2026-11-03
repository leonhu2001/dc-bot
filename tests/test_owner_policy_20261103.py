from services import order_rules
from services.self_service_financials import calculate_manual_price_adjustment
from web.app.services import customer_portal


def test_aw_and_halfcoin_receiver_roles_are_distinct_and_owner_approved():
    assert order_rules.AW_COLLISION_RECEIVER_ROLE_ID == "1565369317929918554"
    assert order_rules.HALFCOIN_RECEIVER_ROLE_ID == "1565369029005287595"
    assert (
        order_rules.ALL_ROLE_IDS[order_rules.AW_COLLISION_RECEIVER_ROLE_KEY]
        == "1565369317929918554"
    )
    assert (
        order_rules.ALL_ROLE_IDS[order_rules.HALFCOIN_RECEIVER_ROLE_KEY]
        == "1565369029005287595"
    )


def test_store_funded_fixed_discount_does_not_reduce_payout_base():
    result = calculate_manual_price_adjustment(
        1800,
        {
            "manual_discount_percent": 96,
            "manual_discount_mode": "pay_rate",
            "cash_coupon_amount": 200,
        },
    )

    assert result["payout_base_amount"] == 1728
    assert result["cash_coupon_amount"] == 200
    assert result["store_absorbed_amount"] == 200
    assert result["customer_pay_amount"] == 1528


def test_active_member_order_never_falls_back_to_waiting_payment():
    result = customer_portal._order_to_public(
        {
            "id": 1,
            "status": "active",
            "category": "test",
            "item": "test order",
            "quantity": 1,
            "amount": 100,
            "customer_pay_amount": 100,
            "payment_method": None,
            "ticket_channel_id": None,
            "created_at": "2026-11-03 12:00:00",
            "updated_at": "2026-11-03 12:01:00",
        },
        payment=None,
        support=None,
        assignments=[],
        guild_id=None,
    )

    assert result["status_label"] == "已付款｜進行中"
    assert result["payment_method"] == "已付款"
