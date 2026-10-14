from __future__ import annotations

from services import order_payment_runtime, payment_review_runtime


def test_payment_review_runtime_does_not_guess_unconfigured_bot_module(monkeypatch):
    monkeypatch.setattr(order_payment_runtime, "_CONFIGURED", False)

    assert payment_review_runtime._target_bot_module() is None


def test_payment_review_runtime_reuses_explicit_order_payment_adapter(monkeypatch):
    monkeypatch.setattr(order_payment_runtime, "_CONFIGURED", True)

    assert payment_review_runtime._target_bot_module() is order_payment_runtime
