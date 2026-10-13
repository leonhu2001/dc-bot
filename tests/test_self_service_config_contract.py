from __future__ import annotations

import inspect

from services import self_service_runtime


def test_subruntime_configurators_use_module_owned_dependencies_directly():
    source = inspect.getsource(self_service_runtime.configure_self_service_runtime)

    forbidden_namespace_lookups = (
        'namespace["ORDER_CATEGORY_LABELS"]',
        'namespace["_to_int"]',
        'namespace["get_taipei_now_iso"]',
        'namespace["remember_order_data"]',
        'namespace["save_bot_data"]',
    )
    for lookup in forbidden_namespace_lookups:
        assert lookup not in source

    expected_direct_bindings = (
        "order_category_labels=ORDER_CATEGORY_LABELS",
        "to_int=_to_int",
        "taipei_now_iso=get_taipei_now_iso",
        "remember_data=remember_order_data",
        "save_data=save_bot_data",
    )
    for binding in expected_direct_bindings:
        assert binding in source


def test_runtime_owned_quantity_helper_stays_on_legacy_boundary_for_now():
    source = inspect.getsource(self_service_runtime.configure_self_service_runtime)

    assert '"get_self_service_quantity_unit"' in source
    assert 'self_service_quantity_unit=namespace["get_self_service_quantity_unit"]' in source
