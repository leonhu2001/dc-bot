from services import order_runtime


EXPECTED_STATE_FIELDS = {
    "db_file": object(),
    "dispatch_channel_id": 987654,
    "order_control_selections": object(),
    "order_selections": object(),
    "self_service_order_view_type": object(),
    "defer_and_refresh_self_service_panel": object(),
    "self_service_rule_getter": object(),
    "payment_method_embed_builder": object(),
    "self_service_panel_embed_builder": object(),
    "can_operate_self_service_order": object(),
    "amount_formatter": object(),
    "order_customer_id_getter": object(),
    "wallet_balance_getter": object(),
    "customer_staff_checker": object(),
    "remember_order": object(),
    "ticket_channel_renamer": object(),
    "order_log_sender": object(),
}


def test_order_runtime_explicit_binding_assigns_runtime_state(monkeypatch):
    monkeypatch.setattr(order_runtime, "_RUNTIME_STATE", None)

    order_runtime.configure_order_runtime_explicit(
        db_file=EXPECTED_STATE_FIELDS["db_file"],
        dispatch_channel_id=EXPECTED_STATE_FIELDS["dispatch_channel_id"],
        order_control_selections=EXPECTED_STATE_FIELDS["order_control_selections"],
        order_selections=EXPECTED_STATE_FIELDS["order_selections"],
        self_service_order_view_type=EXPECTED_STATE_FIELDS["self_service_order_view_type"],
        defer_and_refresh_self_service_panel=EXPECTED_STATE_FIELDS["defer_and_refresh_self_service_panel"],
        self_service_rule_getter=EXPECTED_STATE_FIELDS["self_service_rule_getter"],
        payment_method_embed_builder=EXPECTED_STATE_FIELDS["payment_method_embed_builder"],
        self_service_panel_embed_builder=EXPECTED_STATE_FIELDS["self_service_panel_embed_builder"],
        can_operate_self_service_order_func=EXPECTED_STATE_FIELDS["can_operate_self_service_order"],
        amount_formatter=EXPECTED_STATE_FIELDS["amount_formatter"],
        order_customer_id_getter=EXPECTED_STATE_FIELDS["order_customer_id_getter"],
        wallet_balance_getter=EXPECTED_STATE_FIELDS["wallet_balance_getter"],
        customer_staff_checker=EXPECTED_STATE_FIELDS["customer_staff_checker"],
        remember_order=EXPECTED_STATE_FIELDS["remember_order"],
        ticket_channel_renamer=EXPECTED_STATE_FIELDS["ticket_channel_renamer"],
        order_log_sender=EXPECTED_STATE_FIELDS["order_log_sender"],
    )

    state = order_runtime._require_runtime_state()
    for name, value in EXPECTED_STATE_FIELDS.items():
        assert getattr(state, name) is value


def test_order_runtime_legacy_namespace_adapter_is_removed():
    assert callable(order_runtime.configure_order_runtime_explicit)
    assert not hasattr(order_runtime, "configure_order_runtime")
    assert not hasattr(order_runtime, "_ORDER_RUNTIME_BINDING_NAMES")
    assert not hasattr(order_runtime, "_MODULE_OWNED_RUNTIME_NAMES")
    assert not hasattr(order_runtime, "_CONFIGURED")
