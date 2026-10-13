from __future__ import annotations

import json

from core import database, permissions, time_utils
from services import orders, self_service_runtime, smart_dispatch


def test_self_service_runtime_uses_canonical_module_owned_dependencies():
    assert self_service_runtime.json is json
    assert self_service_runtime.ORDER_CATEGORY_LABELS is orders.ORDER_CATEGORY_LABELS
    assert self_service_runtime._to_int is orders._to_int
    assert self_service_runtime.build_self_service_order_embed is orders.build_self_service_order_embed
    assert self_service_runtime.remember_claim_data is database.remember_claim_data
    assert self_service_runtime.remember_order_data is database.remember_order_data
    assert self_service_runtime.save_bot_data is database.save_bot_data
    assert self_service_runtime.is_customer_staff is permissions.is_customer_staff
    assert self_service_runtime.get_taipei_now_iso is time_utils.get_taipei_now_iso
    assert self_service_runtime.create_smart_dispatch_plan is smart_dispatch.create_smart_dispatch_plan
    assert self_service_runtime.set_specified_dm_results is smart_dispatch.set_specified_dm_results


def test_legacy_configurator_cannot_shadow_module_owned_dependencies():
    canonical_json = self_service_runtime.json
    marker = object()
    self_service_runtime.configure_self_service_runtime(
        {
            "json": object(),
            "_self_service_dependency_boundary_marker": marker,
        }
    )

    assert self_service_runtime.json is canonical_json
    assert self_service_runtime._self_service_dependency_boundary_marker is marker


def test_module_owned_dependency_names_are_explicitly_guarded():
    expected = {
        "json",
        "ORDER_CATEGORY_LABELS",
        "_to_int",
        "build_self_service_order_embed",
        "remember_claim_data",
        "remember_order_data",
        "save_bot_data",
        "is_customer_staff",
        "get_taipei_now_iso",
        "create_smart_dispatch_plan",
        "set_specified_dm_results",
    }
    assert expected <= self_service_runtime._MODULE_OWNED_RUNTIME_NAMES
