from __future__ import annotations

import inspect

from core import database as core_database
from core import time_utils
from services import logging_service, order_flow, orders, self_service_financials
from services.acceptance import payment_panel as acceptance_payment_panel
from services.acceptance import repair_runtime as acceptance_repair_runtime
from services.acceptance import runtime as acceptance_runtime
from services.acceptance import sync_worker as acceptance_sync_worker
from services import order_dispatch_runtime


def test_acceptance_runtime_owns_orchestration_persistence_dependencies():
    assert acceptance_runtime.remember_claim_data is core_database.remember_claim_data
    assert acceptance_runtime.remember_order_data is core_database.remember_order_data
    assert acceptance_runtime.save_bot_data is core_database.save_bot_data
    assert acceptance_sync_worker.utc_now_naive is time_utils.utc_now_naive
    assert not hasattr(acceptance_runtime, "utc_now_naive")
    assert not hasattr(acceptance_runtime, "get_taipei_now_iso")


def test_acceptance_runtime_owns_stable_orchestration_dependencies():
    assert acceptance_runtime._to_int is orders._to_int
    assert acceptance_runtime.ORDER_CATEGORY_LABELS is orders.ORDER_CATEGORY_LABELS
    assert acceptance_runtime.build_self_service_order_embed is orders.build_self_service_order_embed
    assert acceptance_runtime.DispatchClaimView is order_dispatch_runtime.DispatchClaimView
    assert acceptance_runtime._price_snapshot is self_service_financials._price_snapshot
    assert acceptance_runtime._price_int is self_service_financials._price_int
    assert acceptance_runtime._format_plain_amount is self_service_financials._format_plain_amount
    assert (
        acceptance_runtime.add_self_service_financial_breakdown_fields
        is self_service_financials.add_self_service_financial_breakdown_fields
    )
    assert not hasattr(acceptance_runtime, "build_payment_method_embed")
    assert not hasattr(acceptance_runtime, "send_order_log")


def test_acceptance_payment_panel_owns_payment_ui_time_and_persistence():
    assert acceptance_payment_panel.remember_order_data is core_database.remember_order_data
    assert acceptance_payment_panel.save_bot_data is core_database.save_bot_data
    assert acceptance_payment_panel.get_taipei_now_iso is time_utils.get_taipei_now_iso
    assert acceptance_payment_panel._to_int is orders._to_int
    assert acceptance_payment_panel.build_payment_method_embed is order_flow.build_payment_method_embed
    assert acceptance_payment_panel.send_order_log is logging_service.send_order_log


def test_acceptance_repair_runtime_delegates_payment_surface_dependencies():
    assert acceptance_repair_runtime._to_int is orders._to_int
    assert not hasattr(acceptance_repair_runtime, "remember_order_data")
    assert not hasattr(acceptance_repair_runtime, "save_bot_data")
    assert not hasattr(acceptance_repair_runtime, "get_taipei_now_iso")
    assert not hasattr(acceptance_repair_runtime, "build_payment_method_embed")
    assert not hasattr(acceptance_repair_runtime, "send_order_log")
    assert not hasattr(acceptance_repair_runtime, "sqlite3")
    assert not hasattr(acceptance_repair_runtime, "Path")


def test_acceptance_explicit_configurator_is_keyword_only():
    signature = inspect.signature(
        acceptance_runtime.configure_acceptance_runtime_explicit
    )
    assert list(signature.parameters) == [
        "dispatch_channel_id",
        "order_claims",
        "payment_method_view_type",
        "order_selections",
        "bot_instance",
        "guild_id",
        "refresh_existing_web_sync_dispatch",
    ]
    assert all(
        parameter.kind is inspect.Parameter.KEYWORD_ONLY
        for parameter in signature.parameters.values()
    )


def test_acceptance_legacy_namespace_startup_boundary_is_retired():
    assert not hasattr(acceptance_runtime, "configure_acceptance_runtime")
    assert not hasattr(acceptance_runtime, "_DEPENDENCY_NAMES")
    assert not hasattr(acceptance_runtime, "_SYNC_WORKER_DEPENDENCY_NAMES")
    assert not hasattr(acceptance_runtime, "_REQUIRED_DEPENDENCY_NAMES")
