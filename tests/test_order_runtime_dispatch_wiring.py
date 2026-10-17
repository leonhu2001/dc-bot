from __future__ import annotations

from services import order_runtime


def _dispatch_namespace() -> dict[str, object]:
    async def async_noop(*_args, **_kwargs):
        return None

    return {
        "BOOSTER_RECEIVER_ROLE_ID": 1,
        "DISPATCH_CHANNEL_ID": 123,
        "ORDER_CLAIMS": {},
        "SELF_SERVICE_ORDER_SELECTIONS": {},
        "_apply_acceptance_state_to_claim_data": lambda *_args, **_kwargs: None,
        "_member_display_name": lambda member: str(getattr(member, "id", "worker")),
        "_member_role_id_texts": lambda _member: [],
        "_order_requires_credentials": lambda _data: False,
        "revoke_order_credential_messages": async_noop,
        "send_acceptance_payment_panel_if_ready": async_noop,
    }


def test_order_runtime_wires_dispatch_through_explicit_configurator(monkeypatch):
    namespace = _dispatch_namespace()
    captured: dict[str, object] = {}

    def explicit_configurator(**kwargs):
        captured.update(kwargs)

    def legacy_configurator(_namespace):
        raise AssertionError("order_runtime must not forward the whole namespace to dispatch")

    monkeypatch.setattr(
        order_runtime,
        "configure_order_dispatch_runtime_explicit",
        explicit_configurator,
    )
    monkeypatch.setattr(
        order_runtime,
        "configure_order_dispatch_runtime",
        legacy_configurator,
    )
    monkeypatch.setattr(order_runtime, "_CONFIGURED", False)

    order_runtime.configure_order_runtime(namespace)

    assert order_runtime._CONFIGURED is True
    assert captured == {
        "booster_receiver_role_id": namespace["BOOSTER_RECEIVER_ROLE_ID"],
        "dispatch_channel_id": namespace["DISPATCH_CHANNEL_ID"],
        "order_claims": namespace["ORDER_CLAIMS"],
        "order_selections": namespace["SELF_SERVICE_ORDER_SELECTIONS"],
        "acceptance_state_applier": namespace["_apply_acceptance_state_to_claim_data"],
        "member_display_name": namespace["_member_display_name"],
        "member_role_ids": namespace["_member_role_id_texts"],
        "order_requires_credentials": namespace["_order_requires_credentials"],
        "revoke_credential_messages": namespace["revoke_order_credential_messages"],
        "send_payment_panel": namespace["send_acceptance_payment_panel_if_ready"],
    }
