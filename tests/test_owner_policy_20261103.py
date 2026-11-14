from services import order_rules
from services.order_discounts import FUNDING_SHARED, FUNDING_STORE, get_discount_funding_policy
from services.vip_monthly_store_funding_policy_20261103 import (
    apply_vip_monthly_store_funding,
)
from services.vip_monthly_store_funding_repair_20261103 import _monthly_evidence
from web.app.services import customer_portal


def test_aw_and_halfcoin_receiver_roles_are_separate_as_owner_approved():
    assert order_rules.AW_COLLISION_RECEIVER_ROLE_ID == "1571080769407942787"
    assert order_rules.HALFCOIN_RECEIVER_ROLE_ID == "1565369317929918554"
    assert (
        order_rules.ALL_ROLE_IDS[order_rules.AW_COLLISION_RECEIVER_ROLE_KEY]
        == "1571080769407942787"
    )
    assert (
        order_rules.ALL_ROLE_IDS[order_rules.HALFCOIN_RECEIVER_ROLE_KEY]
        == "1565369317929918554"
    )
    assert order_rules.SPECIAL_RECEIVER_ROLE_IDS_BY_KEY == {
        order_rules.AW_COLLISION_RECEIVER_ROLE_KEY: "1571080769407942787",
        order_rules.HALFCOIN_RECEIVER_ROLE_KEY: "1565369317929918554",
    }


def test_vip_monthly_cash_is_store_funded_without_changing_customer_payment():
    # 1800T at 96% => 1728T. The historical shared allocator then subtracted
    # the 200T monthly voucher from both payment and payout base => 1528T.
    # The owner-approved policy keeps customer payment 1528T but restores the
    # worker payout basis to 1728T and makes the store absorb the 200T.
    result = apply_vip_monthly_store_funding(
        {
            "payout_base_amount": 1528,
            "customer_pay_amount": 1528,
            "store_absorbed_amount": 0,
            "vip_monthly_benefit_key": "monthly_coupon_200",
            "vip_monthly_cash_amount": 200,
        }
    )

    assert result["payout_base_amount"] == 1728
    assert result["customer_pay_amount"] == 1528
    assert result["store_absorbed_amount"] == 200
    assert result["vip_monthly_funding"] == "store"
    assert get_discount_funding_policy("vip_monthly_cash") == FUNDING_STORE

    # Ordinary fixed/point discounts are not part of this owner correction.
    assert get_discount_funding_policy("manual_fixed") == FUNDING_SHARED
    assert get_discount_funding_policy("point_cash") == FUNDING_SHARED


def test_november_repair_requires_explicit_vip_monthly_evidence():
    key, amount, _ = _monthly_evidence(
        {
            "preview": {
                "finance": {
                    "vip_monthly_benefit_key": "monthly_coupon_200",
                    "vip_monthly_cash_amount": 200,
                }
            }
        }
    )
    assert key == "monthly_coupon_200"
    assert amount == 200

    # A generic 200T fixed discount must never be mistaken for a VIP monthly voucher.
    key, amount, _ = _monthly_evidence(
        {"preview": {"finance": {"fixed_discount_amount": 200}}}
    )
    assert key == ""
    assert amount == 0


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
