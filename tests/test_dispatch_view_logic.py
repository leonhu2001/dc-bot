from types import SimpleNamespace

from web.app.services.order_service import (
    attach_dispatch_operational_context,
    get_worker_dispatch_payout_preview,
    partition_dispatch_orders,
)


def test_split_dispatch_orders_excludes_full_and_paid_orders_from_available_count():
    waiting = SimpleNamespace(
        id=1,
        status="waiting_acceptance",
        dispatch_missing_staff_count=1,
    )
    pending_pay = SimpleNamespace(
        id=2,
        status="accepted_pending_pay",
        dispatch_missing_staff_count=0,
    )
    active = SimpleNamespace(
        id=3,
        status="active",
        dispatch_missing_staff_count=0,
    )

    claimable, non_claimable = partition_dispatch_orders(
        [waiting, pending_pay, active]
    )

    assert [order.id for order in claimable] == [1]
    assert [order.id for order in non_claimable] == [2, 3]


def test_dispatch_operational_context_tracks_missing_staff():
    order = SimpleNamespace(
        status="waiting_acceptance",
        assignments=[],
        prepay_claim_count=1,
        prepay_required_count=3,
    )

    attach_dispatch_operational_context([order])

    assert order.dispatch_current_staff_count == 1
    assert order.dispatch_required_staff_count == 3
    assert order.dispatch_missing_staff_count == 2
    assert order.dispatch_claim_open is True
    assert order.dispatch_status_label == "可接單"


def test_pending_pay_is_full_and_not_open_for_claim():
    order = SimpleNamespace(
        status="accepted_pending_pay",
        assignments=[],
        prepay_claim_count=2,
        prepay_required_count=2,
    )

    attach_dispatch_operational_context([order])

    assert order.dispatch_missing_staff_count == 0
    assert order.dispatch_claim_open is False
    assert order.dispatch_status_label == "待付款（已滿）"


def test_prepay_worker_payout_preview_uses_required_staff_count():
    order = SimpleNamespace(
        status="waiting_acceptance",
        payouts=[],
        payout_base_amount=1000,
        customer_pay_amount=1000,
        amount=1000,
        dispatch_required_staff_count=2,
        prepay_required_count=2,
    )

    preview = get_worker_dispatch_payout_preview(order, "100")

    assert preview["label"] == "預估分潤"
    assert preview["amount"] == 400
    assert preview["is_estimate"] is True
