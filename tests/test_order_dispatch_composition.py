from services import order_dispatch_composition as composition


def test_dispatch_composition_passes_bot_state_and_service_dependencies(monkeypatch):
    sentinels = {
        "acceptance_state_applier": object(),
        "member_display_name": object(),
        "member_role_ids": object(),
        "order_requires_credentials": object(),
        "revoke_credential_messages": object(),
        "send_payment_panel": object(),
    }
    monkeypatch.setattr(
        composition,
        "_apply_acceptance_state_to_claim_data",
        sentinels["acceptance_state_applier"],
    )
    monkeypatch.setattr(composition, "_member_display_name", sentinels["member_display_name"])
    monkeypatch.setattr(composition, "_member_role_id_texts", sentinels["member_role_ids"])
    monkeypatch.setattr(
        composition,
        "_order_requires_credentials",
        sentinels["order_requires_credentials"],
    )
    monkeypatch.setattr(
        composition,
        "revoke_order_credential_messages",
        sentinels["revoke_credential_messages"],
    )
    monkeypatch.setattr(
        composition,
        "send_acceptance_payment_panel_if_ready",
        sentinels["send_payment_panel"],
    )

    captured = {}
    monkeypatch.setattr(
        composition,
        "configure_order_dispatch_runtime_explicit",
        lambda **kwargs: captured.update(kwargs),
    )

    claims = {}
    selections = {}
    composition.configure_order_dispatch_composition(11, 22, claims, selections)

    assert captured == {
        "booster_receiver_role_id": 11,
        "dispatch_channel_id": 22,
        "order_claims": claims,
        "order_selections": selections,
        **sentinels,
    }
