from typing import Any, Mapping

import discord

from services.web_sync import event_store
from services.web_sync import runtime as web_sync_runtime


EVENT_STORE_RUNTIME_BINDINGS = {
    "_web_order_created_load_bundle": event_store.load_order_created_bundle,
    "_web_order_created_mark_processing": event_store.mark_order_created_processing,
    "_web_order_created_update_links": event_store.update_order_created_links,
    "_web_sync_mark_event_done": event_store.mark_event_done,
    "_web_sync_mark_event_failed": event_store.mark_event_failed,
}


def test_web_sync_legacy_injection_cannot_shadow_module_owned_imports_or_add_unknowns():
    originals = {
        "Any": Any,
        "Mapping": Mapping,
        "discord": discord,
        **EVENT_STORE_RUNTIME_BINDINGS,
    }
    marker_name = "_web_sync_runtime_boundary_marker"
    allowed_name = "GUILD_ID"
    marker = object()
    allowed_value = object()
    had_allowed = hasattr(web_sync_runtime, allowed_name)
    original_allowed = getattr(web_sync_runtime, allowed_name, None)

    if hasattr(web_sync_runtime, marker_name):
        delattr(web_sync_runtime, marker_name)

    try:
        web_sync_runtime.configure_web_sync_runtime(
            {
                **{name: object() for name in originals},
                marker_name: marker,
                allowed_name: allowed_value,
            }
        )

        for name, original in originals.items():
            assert getattr(web_sync_runtime, name) is original
        assert not hasattr(web_sync_runtime, marker_name)
        assert getattr(web_sync_runtime, allowed_name) is allowed_value
    finally:
        if had_allowed:
            setattr(web_sync_runtime, allowed_name, original_allowed)
        elif hasattr(web_sync_runtime, allowed_name):
            delattr(web_sync_runtime, allowed_name)


def test_web_sync_owned_dependency_names_are_explicit():
    assert web_sync_runtime._MODULE_OWNED_RUNTIME_NAMES == frozenset(
        {
            "Any",
            "Mapping",
            "discord",
        }
    )


def test_web_sync_event_store_bindings_are_owned_by_event_store():
    for name, owner in EVENT_STORE_RUNTIME_BINDINGS.items():
        assert getattr(web_sync_runtime, name) is owner
        assert name not in web_sync_runtime._ALLOWED_RUNTIME_DEPENDENCY_NAMES


def test_web_sync_legacy_dependency_allowlist_is_explicit_and_separate_from_owned_names():
    assert web_sync_runtime._ALLOWED_RUNTIME_DEPENDENCY_NAMES == frozenset(
        {
            "CANCEL_REASON_OPTIONS",
            "CUSTOMER_CATEGORY_ID",
            "CUSTOMER_ROLE_ID",
            "DISPATCH_CHANNEL_ID",
            "GUILD_ID",
            "ORDER_CATEGORY_LABELS",
            "ORDER_CLAIMS",
            "ORDER_ITEM_GROUPS_BY_CATEGORY",
            "OrderCancellationReasonSelect",
            "OrderControlView",
            "SELF_SERVICE_ORDER_SELECTIONS",
            "SelfServiceOrderView",
            "_apply_acceptance_state_to_claim_data",
            "_format_plain_amount",
            "_to_int",
            "_web_order_created_details",
            "_web_order_created_find_ticket",
            "_web_order_created_get_channel",
            "_web_order_created_get_member",
            "_web_order_created_has_footer",
            "asyncio",
            "bot",
            "build_self_service_panel_embed",
            "build_ticket_channel_name",
            "create_smart_dispatch_plan",
            "delete_order_row_from_db",
            "format_t_amount",
            "get_order_item_details_for_group",
            "get_order_item_group_label",
            "get_smart_dispatch_plan",
            "get_taipei_now_iso",
            "is_customer_staff",
            "prepare_initial_smart_dispatch",
            "re",
            "refresh_acceptance_dispatch_from_web_order",
            "remember_claim_data",
            "remember_order_data",
            "save_bot_data",
            "send_initial_smart_dispatch_alert",
            "send_order_log",
            "send_specified_staff_dispatch_dms",
            "set_specified_dm_results",
            "sqlite3",
        }
    )
    assert web_sync_runtime._ALLOWED_RUNTIME_DEPENDENCY_NAMES.isdisjoint(
        web_sync_runtime._MODULE_OWNED_RUNTIME_NAMES
    )
