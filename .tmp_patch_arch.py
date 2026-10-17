from pathlib import Path


BOT_PATH = Path("bot.py")
ORDER_RUNTIME_PATH = Path("services/order_runtime.py")
PANEL_RUNTIME_PATH = Path("services/order_operation_panel_runtime.py")
PANEL_TEST_PATH = Path("tests/test_order_operation_panel_reposition_regression.py")


bot_source = BOT_PATH.read_text(encoding="utf-8")
import_anchor = (
    "from services.payment_review_runtime import ensure_payment_review_worker_started\n"
)
import_line = (
    "from services.order_operation_panel_runtime import "
    "register_order_operation_panel_listener\n"
)
assert import_anchor in bot_source, "bot import anchor drifted"
if import_line not in bot_source:
    bot_source = bot_source.replace(import_anchor, import_anchor + import_line, 1)

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
    _to_int,
    StaffOrderOperationView,
    remember_order_data,
    save_bot_data,
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


panel_source = PANEL_RUNTIME_PATH.read_text(encoding="utf-8")
register_marker = "\ndef register_order_operation_panel_listener("
if register_marker not in panel_source:
    panel_source = panel_source.rstrip() + '''


def register_order_operation_panel_listener(
    bot: discord.Client,
    order_selections: dict[int, dict[str, Any]],
    is_staff: Callable[[discord.Member], bool],
    to_int: Callable[[Any], int | None],
    operation_view_factory: Callable[[], discord.ui.View],
    remember_order: Callable[[int, dict[str, Any]], None],
    save_data: Callable[[], None],
) -> None:
    async def _listener(interaction: discord.Interaction) -> None:
        await handle_order_operation_panel_interaction(
            interaction,
            order_selections=order_selections,
            is_staff=is_staff,
            to_int=to_int,
            operation_view_factory=operation_view_factory,
            remember_order=remember_order,
            save_data=save_data,
        )

    bot.add_listener(_listener, "on_interaction")
'''
PANEL_RUNTIME_PATH.write_text(panel_source, encoding="utf-8")


test_source = PANEL_TEST_PATH.read_text(encoding="utf-8")
test_source = test_source.replace(
    'assert "handle_order_operation_panel_interaction" in BOT_SOURCE',
    'assert "register_order_operation_panel_listener" in BOT_SOURCE',
)
PANEL_TEST_PATH.write_text(test_source, encoding="utf-8")


bot_size = BOT_PATH.stat().st_size
runtime_size = ORDER_RUNTIME_PATH.stat().st_size
print(f"bot.py bytes: {bot_size}")
print(f"services/order_runtime.py bytes: {runtime_size}")
assert bot_size <= 235000, bot_size
assert runtime_size <= 45000, runtime_size
