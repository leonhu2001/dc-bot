from __future__ import annotations

import inspect

from services import self_service_runtime


def test_subruntime_configurators_use_module_owned_dependencies_directly():
    source = inspect.getsource(
        self_service_runtime.configure_self_service_runtime_explicit
    )

    forbidden_namespace_lookups = (
        'namespace["ORDER_CATEGORY_LABELS"]',
        'namespace["ORDER_ITEM_GROUPS_BY_CATEGORY"]',
        'namespace["_get_order_rule_by_item_label"]',
        'namespace["_to_int"]',
        'namespace["get_order_item_details_for_group"]',
        'namespace["get_order_item_group_label"]',
        'namespace["get_self_service_quantity_meta"]',
        'namespace["get_self_service_quantity_unit"]',
        'namespace["get_taipei_now_iso"]',
        'namespace["remember_order_data"]',
        'namespace["save_bot_data"]',
        'namespace["send_order_log"]',
    )
    for lookup in forbidden_namespace_lookups:
        assert lookup not in source

    expected_direct_bindings = (
        "order_category_labels=ORDER_CATEGORY_LABELS",
        "order_item_groups_by_category=ORDER_ITEM_GROUPS_BY_CATEGORY",
        "get_order_rule_by_item_label=_get_order_rule_by_item_label",
        "to_int=_to_int",
        "order_item_details_for_group=get_order_item_details_for_group",
        "order_item_group_label=get_order_item_group_label",
        "self_service_quantity_meta=get_self_service_quantity_meta",
        "self_service_quantity_unit=get_self_service_quantity_unit",
        "taipei_now_iso=get_taipei_now_iso",
        "remember_data=remember_order_data",
        "save_data=save_bot_data",
        "order_log_sender=send_order_log",
    )
    for binding in expected_direct_bindings:
        assert binding in source


def test_self_service_runtime_is_explicit_only_startup_boundary():
    assert callable(self_service_runtime.configure_self_service_runtime_explicit)
    assert not hasattr(self_service_runtime, "configure_self_service_runtime")
    assert not hasattr(self_service_runtime, "_LEGACY_RUNTIME_NAMES")
