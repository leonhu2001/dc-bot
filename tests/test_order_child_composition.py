from pathlib import Path

from services import order_child_composition as composition


ROOT = Path(__file__).resolve().parents[1]
ORDER_RUNTIME_SOURCE = (ROOT / "services" / "order_runtime.py").read_text(encoding="utf-8")
BOT_SOURCE = (ROOT / "bot.py").read_text(encoding="utf-8")


def test_order_child_composition_wires_extracted_children(monkeypatch):
    dispatch_calls = []
    credential_calls = []
    point_kwargs = {}
    sentinels = {
        "to_int": object(),
        "current_reward_points": object(),
        "customer_reward_data": object(),
        "order_point_item": object(),
        "taipei_now_iso": object(),
        "remember_data": object(),
        "save_data": object(),
        "order_log_sender": object(),
    }
    monkeypatch.setattr(
        composition,
        "configure_order_dispatch_composition",
        lambda *args: dispatch_calls.append(args),
    )
    monkeypatch.setattr(
        composition,
        "configure_order_point_redemption",
        lambda **kwargs: point_kwargs.update(kwargs),
    )
    monkeypatch.setattr(
        composition,
        "configure_order_credential_composition",
        lambda *args: credential_calls.append(args),
    )
    monkeypatch.setattr(composition, "_to_int", sentinels["to_int"])
    monkeypatch.setattr(composition, "get_current_reward_points", sentinels["current_reward_points"])
    monkeypatch.setattr(composition, "get_customer_reward_data", sentinels["customer_reward_data"])
    monkeypatch.setattr(composition, "get_order_point_item", sentinels["order_point_item"])
    monkeypatch.setattr(composition, "get_taipei_now_iso", sentinels["taipei_now_iso"])
    monkeypatch.setattr(composition, "remember_order_data", sentinels["remember_data"])
    monkeypatch.setattr(composition, "save_bot_data", sentinels["save_data"])
    monkeypatch.setattr(composition, "send_order_log", sentinels["order_log_sender"])

    claims = {}
    selections = {}
    rewards = {}
    bot_instance = object()
    composition.configure_order_children(
        11, 22, claims, selections, rewards, 33, 44, bot_instance
    )

    assert dispatch_calls == [(11, 22, claims, selections)]
    assert point_kwargs == {"customer_rewards": rewards, **sentinels}
    assert credential_calls == [(33, 44, selections, bot_instance)]


def test_extracted_child_composition_is_outside_legacy_order_runtime():
    assert "configure_order_point_redemption" not in ORDER_RUNTIME_SOURCE
    assert "redemption_keys" not in ORDER_RUNTIME_SOURCE
    assert "configure_order_credentials(" not in ORDER_RUNTIME_SOURCE
    assert "credential_keys =" not in ORDER_RUNTIME_SOURCE
    assert "configure_order_children" in BOT_SOURCE
    assert "CUSTOMER_REWARDS" in BOT_SOURCE
    assert "CREDENTIAL_OWNER_USER_ID" in BOT_SOURCE
