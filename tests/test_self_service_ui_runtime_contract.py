from services import self_service_ui_runtime


def test_ui_runtime_configuration_is_explicit_and_shares_canonical_state():
    order_selections = {}
    order_claims = {}

    def get_rule(data):
        return data

    def is_specify(value):
        return bool(value)

    async def create_waiting(*_args, **_kwargs):
        return "ok"

    self_service_ui_runtime.configure_self_service_ui_runtime(
        order_selections=order_selections,
        order_claims=order_claims,
        dispatch_channel_id=123,
        get_rule_from_data=get_rule,
        is_specify_preference=is_specify,
        create_waiting_order=create_waiting,
    )

    assert self_service_ui_runtime.SELF_SERVICE_ORDER_SELECTIONS is order_selections
    assert self_service_ui_runtime.ORDER_CLAIMS is order_claims
    assert self_service_ui_runtime.DISPATCH_CHANNEL_ID == 123
    assert self_service_ui_runtime._get_rule_from_self_service_data is get_rule
    assert self_service_ui_runtime._is_specify_preference is is_specify
    assert self_service_ui_runtime.create_waiting_acceptance_order_from_self_service is create_waiting
