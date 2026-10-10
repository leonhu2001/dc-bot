from types import SimpleNamespace

from web.app.services.order_service import _customer_service_payout_base


def test_customer_service_base_excludes_store_funded_extra_service():
    order = SimpleNamespace(
        payout_base_amount=1750,
        amount=1000,
        price_snapshot_json=(
            '{"preview":{"finance":{'
            '"point_service_value":750,'
            '"benefit_service_value":0}}}'
        ),
    )
    assert _customer_service_payout_base(order) == 1000


def test_customer_service_base_excludes_both_point_and_loyalty_extra_service():
    order = SimpleNamespace(
        payout_base_amount=1600,
        amount=1000,
        price_snapshot_json=(
            '{"preview":{"finance":{'
            '"point_service_value":200,'
            '"benefit_service_value":400}}}'
        ),
    )
    assert _customer_service_payout_base(order) == 1000
