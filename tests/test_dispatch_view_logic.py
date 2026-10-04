from types import SimpleNamespace

from web.app.services.order_service import partition_dispatch_orders


def test_split_dispatch_orders_excludes_locked_orders_from_available_count():
    waiting = SimpleNamespace(id=1, status="waiting_acceptance")
    pending_pay = SimpleNamespace(id=2, status="accepted_pending_pay")
    active = SimpleNamespace(id=3, status="active")

    claimable, non_claimable = partition_dispatch_orders(
        [waiting, pending_pay, active]
    )

    assert [order.id for order in claimable] == [1, 2]
    assert [order.id for order in non_claimable] == [3]
