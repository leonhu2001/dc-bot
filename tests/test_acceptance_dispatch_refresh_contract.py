from __future__ import annotations

import inspect

from services.acceptance import dispatch_refresh


def test_dispatch_refresh_configurator_is_keyword_only():
    signature = inspect.signature(dispatch_refresh.configure_acceptance_dispatch_refresh)
    assert list(signature.parameters) == [
        "dispatch_channel_id",
        "order_claims",
        "payment_method_view_type",
        "order_selections",
    ]
    assert all(
        parameter.kind is inspect.Parameter.KEYWORD_ONLY
        for parameter in signature.parameters.values()
    )


def test_dispatch_refresh_binds_only_canonical_shared_state(monkeypatch):
    claims = {}
    selections = {}
    payment_view = object()

    monkeypatch.setattr(dispatch_refresh, "_CONFIGURED", False)
    dispatch_refresh.configure_acceptance_dispatch_refresh(
        dispatch_channel_id=123,
        order_claims=claims,
        payment_method_view_type=payment_view,
        order_selections=selections,
    )

    assert dispatch_refresh._CONFIGURED is True
    assert dispatch_refresh.DISPATCH_CHANNEL_ID == 123
    assert dispatch_refresh.ORDER_CLAIMS is claims
    assert dispatch_refresh.PaymentMethodView is payment_view
    assert dispatch_refresh.SELF_SERVICE_ORDER_SELECTIONS is selections
