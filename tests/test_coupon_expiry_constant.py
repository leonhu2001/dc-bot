from services.loyalty_benefits import COUPON_VALID_DAYS


def test_coupon_validity_days():
    assert COUPON_VALID_DAYS == 90
