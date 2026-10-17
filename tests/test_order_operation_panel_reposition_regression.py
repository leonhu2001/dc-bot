from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BOT_SOURCE = (ROOT / "bot.py").read_text(encoding="utf-8")
RUNTIME_SOURCE = (ROOT / "services" / "order_operation_panel_runtime.py").read_text(
    encoding="utf-8"
)


def test_active_ticket_actions_delegate_panel_reposition_to_runtime():
    assert "register_order_operation_panel_listener" in BOT_SOURCE
    assert "validate_staff_order_operation_interaction" in BOT_SOURCE
    assert "SELF_SERVICE_ORDER_SELECTIONS" in BOT_SOURCE
    assert "StaffOrderOperationView" in BOT_SOURCE
    assert 'bot.add_listener(_listener, "on_interaction")' in RUNTIME_SOURCE


def test_panel_runtime_skips_terminal_and_ephemeral_operation_flow():
    assert "interaction.type is not discord.InteractionType.component" in RUNTIME_SOURCE
    assert "interaction.message.flags.ephemeral" in RUNTIME_SOURCE
    assert '"staff_order_operation_select",' in RUNTIME_SOURCE
    assert '"staff_order_operation_confirm",' in RUNTIME_SOURCE
    assert 'str(order_data.get("status") or "").strip().lower() == "active"' in RUNTIME_SOURCE
    assert "await old_panel.delete()" in RUNTIME_SOURCE
    assert "view=operation_view_factory()" in RUNTIME_SOURCE
    assert 'order_data["operation_panel_message_id"] = new_panel.id' in RUNTIME_SOURCE
    assert "remember_order_data(channel.id, order_data)" in RUNTIME_SOURCE
    assert "save_data" not in RUNTIME_SOURCE
