from services import order_payment_composition as composition


def test_order_payment_composition_binds_service_owned_dependencies(monkeypatch):
    captured = {}
    monkeypatch.setattr(
        composition,
        "configure_order_payment_runtime",
        lambda **kwargs: captured.update(kwargs),
    )

    claims = {}
    selections = {}
    staff_view = object()
    composition.configure_order_payment_composition(123, claims, selections, staff_view)

    from services.order_runtime import PaymentMethodView

    assert captured["dispatch_channel_id"] == 123
    assert captured["order_claims"] is claims
    assert captured["self_service_order_selections"] is selections
    assert captured["staff_order_operation_view"] is staff_view
    assert captured["payment_method_view"] is PaymentMethodView
    assert captured["dispatch_claim_view"] is composition.DispatchClaimView
    assert captured["wallet_adjuster"] is composition.adjust_customer_wallet_balance
    assert captured["wallet_log_sender"] is composition.send_wallet_log
    assert captured["receiver_text_builder"] is composition._build_receiver_text_from_claim_data
    assert captured["payment_receipt_ensurer"] is composition.ensure_payment_submit_receipt
