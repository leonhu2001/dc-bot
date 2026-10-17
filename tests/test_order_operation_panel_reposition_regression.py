from pathlib import Path


BOT_SOURCE = (Path(__file__).resolve().parents[1] / "bot.py").read_text(encoding="utf-8")


def test_active_ticket_actions_reposition_existing_order_operation_panel():
    assert "async def _reposition_active_order_operation_panel(" in BOT_SOURCE
    assert '@bot.listen("on_interaction")' in BOT_SOURCE
    assert "interaction.type is not discord.InteractionType.component" in BOT_SOURCE
    assert "interaction.message.flags.ephemeral" in BOT_SOURCE
    assert '"staff_order_operation_select",' in BOT_SOURCE
    assert '"staff_order_operation_confirm",' in BOT_SOURCE
    assert 'str(order_data.get("status") or "").strip().lower() != "active"' in BOT_SOURCE
    assert "await old_panel.delete()" in BOT_SOURCE
    assert "view=StaffOrderOperationView()" in BOT_SOURCE
    assert 'order_data["operation_panel_message_id"] = new_panel.id' in BOT_SOURCE
