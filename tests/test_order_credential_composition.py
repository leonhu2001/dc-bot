from services import order_credential_composition as composition


def test_order_credential_composition_maps_dependencies(monkeypatch):
    captured = {}
    sentinels = {
        "to_int": object(),
        "fetch_member": object(),
        "taipei_now_iso": object(),
        "remember_data": object(),
        "save_data": object(),
    }
    monkeypatch.setattr(
        composition,
        "configure_order_credentials",
        lambda **kwargs: captured.update(kwargs),
    )
    monkeypatch.setattr(composition, "_to_int", sentinels["to_int"])
    monkeypatch.setattr(composition, "fetch_member_safely", sentinels["fetch_member"])
    monkeypatch.setattr(composition, "get_taipei_now_iso", sentinels["taipei_now_iso"])
    monkeypatch.setattr(composition, "remember_order_data", sentinels["remember_data"])
    monkeypatch.setattr(composition, "save_bot_data", sentinels["save_data"])

    selections = {}
    bot_instance = object()
    composition.configure_order_credential_composition(11, 22, selections, bot_instance)

    assert captured == {
        "credential_owner_user_id": 11,
        "guild_id": 22,
        "self_service_order_selections": selections,
        "to_int": sentinels["to_int"],
        "bot_instance": bot_instance,
        "fetch_member": sentinels["fetch_member"],
        "taipei_now_iso": sentinels["taipei_now_iso"],
        "remember_data": sentinels["remember_data"],
        "save_data": sentinels["save_data"],
    }
