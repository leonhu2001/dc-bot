import inspect

from services.web_sync import runtime as web_sync_runtime


ENTRYPOINT_DEPENDENCIES = {
    "customer_category_id",
    "customer_role_id",
    "dispatch_channel_id",
    "guild_id",
    "order_claims",
    "order_control_view_type",
    "order_selections",
    "bot_instance",
}


def test_web_sync_runtime_uses_explicit_entrypoint_dependencies():
    signature = inspect.signature(web_sync_runtime.configure_web_sync_runtime_explicit)
    assert set(signature.parameters) == ENTRYPOINT_DEPENDENCIES
    assert all(
        parameter.kind is inspect.Parameter.KEYWORD_ONLY
        for parameter in signature.parameters.values()
    )


def test_web_sync_legacy_namespace_bridge_is_removed():
    assert not hasattr(web_sync_runtime, "configure_web_sync_runtime")
    assert not hasattr(web_sync_runtime, "_ALLOWED_RUNTIME_DEPENDENCY_NAMES")
    assert not hasattr(web_sync_runtime, "_MODULE_OWNED_RUNTIME_NAMES")
    source = inspect.getsource(web_sync_runtime)
    assert "globals().update" not in source
    assert "globals()[name]" not in source
    assert "Mapping[str, Any]" not in source


def test_web_sync_module_owned_dependencies_are_not_entrypoint_parameters():
    module_owned_names = {
        "asyncio", "re", "sqlite3", "CANCEL_REASON_OPTIONS",
        "ORDER_CATEGORY_LABELS", "ORDER_ITEM_GROUPS_BY_CATEGORY",
        "OrderCancellationReasonSelect", "SelfServiceOrderView",
        "_apply_acceptance_state_to_claim_data", "_format_plain_amount",
        "_to_int", "_web_order_created_details",
        "_web_order_created_find_ticket", "_web_order_created_get_channel",
        "_web_order_created_get_member", "_web_order_created_has_footer",
        "build_self_service_panel_embed", "build_ticket_channel_name",
        "create_smart_dispatch_plan", "delete_order_row_from_db",
        "format_t_amount", "get_order_item_details_for_group",
        "get_order_item_group_label", "get_smart_dispatch_plan",
        "get_taipei_now_iso", "is_customer_staff",
        "prepare_initial_smart_dispatch",
        "refresh_acceptance_dispatch_from_web_order", "remember_claim_data",
        "remember_order_data", "save_bot_data",
        "send_initial_smart_dispatch_alert", "send_order_log",
        "send_specified_staff_dispatch_dms", "set_specified_dm_results",
    }
    signature = inspect.signature(web_sync_runtime.configure_web_sync_runtime_explicit)
    assert module_owned_names.isdisjoint(signature.parameters)
