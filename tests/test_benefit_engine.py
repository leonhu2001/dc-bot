from __future__ import annotations

from services import issued_benefits
from services.benefit_selector import (
    SOURCE_ISSUED,
    SOURCE_LOYALTY,
    SOURCE_VIP_MONTHLY,
    decode_benefit_selector_id,
    encode_issued_benefit_id,
    encode_vip_monthly_benefit_id,
)
from services.financial_policy import FINANCIAL_POLICY_VERSION, uses_current_financial_policy
from web.app.services.checkout_preview import calculate_checkout_financials


def test_selector_namespaces_do_not_collide():
    assert decode_benefit_selector_id(17) == (SOURCE_LOYALTY, 17)
    assert decode_benefit_selector_id(encode_issued_benefit_id(17)) == (SOURCE_ISSUED, 17)
    assert decode_benefit_selector_id(encode_vip_monthly_benefit_id(17)) == (SOURCE_VIP_MONTHLY, 17)


def test_issued_benefit_snapshot_is_frozen(tmp_path):
    db = tmp_path / "benefits.db"
    template_id = issued_benefits.create_benefit_template(
        name="抽獎券",
        rules={
            "effect_type": "fixed_cash",
            "amount": 500,
            "funding": "store",
            "minimum_order_amount": 2000,
        },
        actor_id="manager",
        web_db=db,
    )
    benefit_id = issued_benefits.issue_benefit(
        customer_id="customer-1",
        actor_id="manager",
        template_id=template_id,
        web_db=db,
    )

    issued = issued_benefits.get_issued_benefit(benefit_id, web_db=db)
    assert issued is not None
    assert issued["rules"]["amount"] == 500
    assert issued["rules"]["minimum_order_amount"] == 2000


def test_store_funded_promo_can_make_customer_pay_zero_without_cutting_payout_base():
    finance = calculate_checkout_financials(
        service_amount=1200,
        vip_pay_rate=100,
        specify_fee=0,
        point_item=None,
        benefit={
            "selector_id": encode_issued_benefit_id(1),
            "title": "主播宣傳單 1500T",
            "source": SOURCE_ISSUED,
            "funding": "store",
            "service_discount": 1200,
            "specify_discount": 0,
            "note": "主播宣傳單 1500T",
        },
        wallet_balance=0,
        use_wallet=False,
    )

    assert finance["customer_pay_amount"] == 0
    assert finance["payout_base_amount"] == 1200
    assert finance["store_absorbed_amount"] == 1200


def test_shared_cash_benefit_reduces_customer_and_payout_base_together():
    finance = calculate_checkout_financials(
        service_amount=2000,
        vip_pay_rate=100,
        specify_fee=0,
        point_item=None,
        benefit={
            "selector_id": encode_issued_benefit_id(2),
            "title": "一般 200T 券",
            "source": SOURCE_ISSUED,
            "funding": "shared",
            "service_discount": 200,
            "specify_discount": 0,
            "note": "一般 200T 券",
        },
        wallet_balance=0,
        use_wallet=False,
    )

    assert finance["customer_pay_amount"] == 1800
    assert finance["payout_base_amount"] == 1800
    assert finance["store_absorbed_amount"] == 0


def test_policy_detection_preserves_old_orders_and_marks_new_snapshots():
    assert uses_current_financial_policy({"preview": {"finance": {"payout_base_amount": 1000}}}) is False
    assert uses_current_financial_policy(
        {"preview": {"finance": {"financial_policy_version": FINANCIAL_POLICY_VERSION}}}
    ) is True
    assert uses_current_financial_policy(
        {"preview": {"finance": {"issued_benefit_service_value": 0, "benefit_store_absorbed_amount": 0}}}
    ) is True
