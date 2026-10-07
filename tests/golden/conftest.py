import pytest

from shared import order_acceptance


@pytest.fixture(autouse=True)
def _run_golden_flows_after_public_dispatch_unlock(monkeypatch):
    """Golden flows cover business lifecycle, not the dispatch wait window.

    Dedicated dispatch-lock tests verify the real 60-second gate. Golden flows
    run with the wait elapsed so they can continue exercising payment, payout,
    cancellation, wallet, VIP, and accounting behavior synchronously.
    """
    monkeypatch.setattr(order_acceptance, "PUBLIC_ACCEPTANCE_LOCK_SECONDS", 0)
