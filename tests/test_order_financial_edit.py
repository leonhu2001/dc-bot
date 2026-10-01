from web.app.services.order_financial_edit import (
    preserve_order_financial_gaps,
)


def test_preserve_customer_discount_gap_on_generic_admin_edit():
    result = preserve_order_financial_gaps(
        previous_amount=1152,
        previous_customer_pay_amount=652,
        previous_payout_base_amount=1152,
        new_amount=1152,
    )

    assert result["customer_pay_amount"] == 652
    assert result["payout_base_amount"] == 1152


def test_preserve_absolute_customer_discount_when_amount_changes():
    result = preserve_order_financial_gaps(
        previous_amount=1152,
        previous_customer_pay_amount=652,
        previous_payout_base_amount=1152,
        new_amount=1200,
    )

    assert result["customer_pay_amount"] == 700
    assert result["payout_base_amount"] == 1200


def test_preserve_existing_payout_base_gap():
    result = preserve_order_financial_gaps(
        previous_amount=1000,
        previous_customer_pay_amount=800,
        previous_payout_base_amount=900,
        new_amount=1100,
    )

    assert result["customer_pay_amount"] == 900
    assert result["payout_base_amount"] == 1000


def test_null_customer_pay_remains_null():
    result = preserve_order_financial_gaps(
        previous_amount=1000,
        previous_customer_pay_amount=None,
        previous_payout_base_amount=None,
        new_amount=1200,
    )

    assert result["customer_pay_amount"] is None
    assert result["payout_base_amount"] == 1200
