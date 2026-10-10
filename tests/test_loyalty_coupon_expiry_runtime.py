from __future__ import annotations

from datetime import datetime, timedelta

import services.loyalty_benefits as loyalty


def test_coupon_expiry_is_ninety_days_after_issue():
    issued = datetime(2026, 10, 10, 12, 0, tzinfo=loyalty.TAIPEI_TZ)
    expires = datetime.fromisoformat(loyalty._coupon_expiry_iso(issued.isoformat()))
    assert expires - issued == timedelta(days=90)


def test_coupon_expiry_text_is_customer_friendly():
    assert loyalty._coupon_expiry_text("2027-01-08T12:00:00+08:00") == "2027/01/08"
