from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BOT_SOURCE = (ROOT / "bot.py").read_text(encoding="utf-8")
RUNTIME_SOURCE = (ROOT / "services" / "order_runtime.py").read_text(encoding="utf-8")


def test_bot_uses_explicit_order_runtime_startup():
    assert "configure_order_runtime_explicit(" in BOT_SOURCE
    assert "configure_order_runtime(globals())" not in BOT_SOURCE
    assert "configure_order_runtime_explicit," in BOT_SOURCE
    assert "    configure_order_runtime," not in BOT_SOURCE
    for keyword in (
        "db_file=DB_FILE",
        "dispatch_channel_id=DISPATCH_CHANNEL_ID",
        "order_control_selections=ORDER_CONTROL_SELECTIONS",
        "order_selections=SELF_SERVICE_ORDER_SELECTIONS",
        "self_service_order_view_type=SelfServiceOrderView",
        "defer_and_refresh_self_service_panel=_defer_and_refresh_self_service_panel",
        "self_service_rule_getter=_get_rule_from_self_service_data",
        "payment_method_embed_builder=build_payment_method_embed",
        "self_service_panel_embed_builder=build_self_service_panel_embed",
        "can_operate_self_service_order_func=can_operate_self_service_order",
        "amount_formatter=format_t_amount",
        "order_customer_id_getter=get_order_customer_id_from_channel",
        "wallet_balance_getter=get_wallet_balance",
        "customer_staff_checker=is_customer_staff",
        "remember_order=remember_order_data",
        "ticket_channel_renamer=rename_ticket_channel",
        "order_log_sender=send_order_log",
    ):
        assert keyword in BOT_SOURCE


def test_legacy_adapter_is_removed_after_explicit_startup_rollout():
    assert "def configure_order_runtime(" not in RUNTIME_SOURCE
    assert "from typing import Any, Mapping" not in RUNTIME_SOURCE
    assert "_ORDER_RUNTIME_BINDING_NAMES" not in RUNTIME_SOURCE
    assert "_MODULE_OWNED_RUNTIME_NAMES" not in RUNTIME_SOURCE
    assert "_CONFIGURED" not in RUNTIME_SOURCE
    assert "configure_order_runtime(globals())" not in BOT_SOURCE
