from pathlib import Path


BOT_PATH = Path("bot.py")
ORDER_RUNTIME_PATH = Path("services/order_runtime.py")
PANEL_TEST_PATH = Path("tests/test_order_operation_panel_reposition_regression.py")


bot_source = BOT_PATH.read_text(encoding="utf-8")
import_anchor = (
    "from services.payment_review_runtime import ensure_payment_review_worker_started\n"
)
import_block = '''from services.order_operation_panel_runtime import (
    register_order_operation_panel_listener,
    validate_staff_order_operation_interaction,
)
'''
assert import_anchor in bot_source, "bot import anchor drifted"
if import_block not in bot_source:
    bot_source = bot_source.replace(import_anchor, import_anchor + import_block, 1)


def replace_method_prefix(source: str, method_marker: str, next_marker: str) -> str:
    assert source.count(method_marker) == 1, f"method marker drifted: {method_marker!r}"
    start = source.index(method_marker)
    body_start = start + len(method_marker)
    next_index = source.index(next_marker, body_start)
    replacement = method_marker + '''        if not await validate_staff_order_operation_interaction(
            interaction, is_customer_staff
        ):
            return

'''
    return source[:start] + replacement + source[next_index:]


bot_source = replace_method_prefix(
    bot_source,
    "    async def callback(self, interaction: discord.Interaction):\n",
    "        STAFF_ORDER_OPERATION_SELECTIONS[(interaction.channel.id, interaction.user.id)] = self.values[0]\n",
)
bot_source = replace_method_prefix(
    bot_source,
    "    async def confirm_button(self, interaction: discord.Interaction, button: discord.ui.Button):\n",
    "        selected = STAFF_ORDER_OPERATION_SELECTIONS.get((interaction.channel.id, interaction.user.id))\n",
)

block_start = "\n\n_ORDER_OPERATION_PANEL_REPOSITION_LOCKS: dict[int, asyncio.Lock] = {}\n"
block_end = "\n\nclass OrderControlView(discord.ui.View):\n"
assert bot_source.count(block_start) == 1, "panel block start drifted"
start_index = bot_source.index(block_start)
end_index = bot_source.index(block_end, start_index)
registration = '''

register_order_operation_panel_listener(
    bot,
    SELF_SERVICE_ORDER_SELECTIONS,
    is_customer_staff,
    StaffOrderOperationView,
)
'''
bot_source = bot_source[:start_index] + registration + bot_source[end_index:]
BOT_PATH.write_text(bot_source, encoding="utf-8")


runtime_source = ORDER_RUNTIME_PATH.read_text(encoding="utf-8")
function_start_marker = "\ndef configure_order_runtime_explicit("
function_end_marker = "\n\ndef configure_order_runtime(namespace: Mapping[str, Any]) -> None:"
assert runtime_source.count(function_start_marker) == 1, "explicit configure start drifted"
start_index = runtime_source.index(function_start_marker)
end_index = runtime_source.index(function_end_marker, start_index)
compact_function = '''
def configure_order_runtime_explicit(
    *,
    db_file,
    dispatch_channel_id,
    order_control_selections,
    order_selections,
    self_service_order_view_type,
    defer_and_refresh_self_service_panel,
    self_service_rule_getter,
    payment_method_embed_builder,
    self_service_panel_embed_builder,
    can_operate_self_service_order_func,
    amount_formatter,
    order_customer_id_getter,
    wallet_balance_getter,
    customer_staff_checker,
    remember_order,
    ticket_channel_renamer,
    order_log_sender,
) -> None:
    # Explicit args keep the transitional module-global binding allowlisted.
    globals().update(
        {
            "DB_FILE": db_file,
            "DISPATCH_CHANNEL_ID": dispatch_channel_id,
            "ORDER_CONTROL_SELECTIONS": order_control_selections,
            "SELF_SERVICE_ORDER_SELECTIONS": order_selections,
            "SelfServiceOrderView": self_service_order_view_type,
            "_defer_and_refresh_self_service_panel": defer_and_refresh_self_service_panel,
            "_get_rule_from_self_service_data": self_service_rule_getter,
            "build_payment_method_embed": payment_method_embed_builder,
            "build_self_service_panel_embed": self_service_panel_embed_builder,
            "can_operate_self_service_order": can_operate_self_service_order_func,
            "format_t_amount": amount_formatter,
            "get_order_customer_id_from_channel": order_customer_id_getter,
            "get_wallet_balance": wallet_balance_getter,
            "is_customer_staff": customer_staff_checker,
            "remember_order_data": remember_order,
            "rename_ticket_channel": ticket_channel_renamer,
            "send_order_log": order_log_sender,
        }
    )
'''
runtime_source = (
    runtime_source[:start_index]
    + compact_function
    + runtime_source[end_index:]
)
ORDER_RUNTIME_PATH.write_text(runtime_source, encoding="utf-8")


PANEL_TEST_PATH.write_text(
    '''from pathlib import Path


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
''',
    encoding="utf-8",
)


bot_size = BOT_PATH.stat().st_size
runtime_size = ORDER_RUNTIME_PATH.stat().st_size
print(f"bot.py bytes: {bot_size}")
print(f"services/order_runtime.py bytes: {runtime_size}")
assert bot_size <= 235000, bot_size
assert runtime_size <= 45000, runtime_size
