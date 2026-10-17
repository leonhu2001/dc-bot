from __future__ import annotations

from services import order_runtime


def test_order_runtime_no_longer_owns_dispatch_composition():
    assert not hasattr(order_runtime, "configure_order_dispatch_runtime")
    assert not hasattr(order_runtime, "configure_order_dispatch_runtime_explicit")
