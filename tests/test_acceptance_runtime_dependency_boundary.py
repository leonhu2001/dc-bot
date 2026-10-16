from __future__ import annotations

import inspect
from typing import Any, Mapping

import discord
import pytest

from core import database as core_database
from core import time_utils
from services import logging_service, order_flow, orders, self_service_financials
from services.acceptance import payment_panel as acceptance_payment_panel
from services.acceptance import repair_runtime as acceptance_repair_runtime
from services.acceptance import runtime as acceptance_runtime
from services.acceptance import sync_worker as acceptance_sync_worker
from services import order_dispatch_runtime


def _required_namespace(**overrides):
    namespace = {
        "DISPATCH_CHANNEL_ID": 123,
        "GUILD_ID": 456,
        "ORDER_CLAIMS": {},
        "PaymentMethodView": object,
        "SELF_SERVICE_ORDER_SELECTIONS": {},
        "_refresh_existing_web_sync_dispatch": lambda *_args, **_kwargs: None,
        "bot": object(),
    }
    namespace.update(overrides)
    return namespace


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


def test_acceptance_namespace_cannot_shadow_module_owned_dependencies():
    runtime_owned = {
        "Any": Any,
        "Mapping": Mapping,
        "discord": discord,
        "remember_claim_data": core_database.remember_claim_data,
        "remember_order_data": core_database.remember_order_data,
        "save_bot_data": core_database.save_bot_data,
        "_to_int": orders._to_int,
        "DispatchClaimView": order_dispatch_runtime.DispatchClaimView,
    }
    moved_to_payment_panel = (
        "get_taipei_now_iso",
        "build_payment_method_embed",
        "send_order_log",
    )
    marker = object()

    acceptance_runtime.configure_acceptance_runtime(
        _required_namespace(
            **{name: object() for name in runtime_owned},
            **{name: object() for name in moved_to_payment_panel},
            _acceptance_runtime_boundary_marker=marker,
        )
    )

    for name, original in runtime_owned.items():
        assert getattr(acceptance_runtime, name) is original

    for name in moved_to_payment_panel:
        assert not hasattr(acceptance_runtime, name)

    assert not hasattr(acceptance_runtime, "_acceptance_runtime_boundary_marker")


def test_acceptance_legacy_adapter_only_validates_and_delegates():
    source = inspect.getsource(acceptance_runtime.configure_acceptance_runtime)
    assert "globals()[" not in source
    assert "configure_acceptance_runtime_explicit(" in source
    assert "configure_acceptance_sync_worker(" not in source
    assert "configure_acceptance_repair_runtime(" not in source


def test_acceptance_runtime_dependency_names_are_explicit():
    assert acceptance_runtime._DEPENDENCY_NAMES == (
        "DISPATCH_CHANNEL_ID",
        "ORDER_CLAIMS",
        "PaymentMethodView",
        "SELF_SERVICE_ORDER_SELECTIONS",
    )
    assert acceptance_runtime._SYNC_WORKER_DEPENDENCY_NAMES == (
        "GUILD_ID",
        "_refresh_existing_web_sync_dispatch",
        "bot",
    )
    assert acceptance_runtime._REQUIRED_DEPENDENCY_NAMES == (
        "DISPATCH_CHANNEL_ID",
        "ORDER_CLAIMS",
        "PaymentMethodView",
        "SELF_SERVICE_ORDER_SELECTIONS",
        "GUILD_ID",
        "_refresh_existing_web_sync_dispatch",
        "bot",
    )


def test_acceptance_runtime_fails_fast_when_required_dependency_is_missing():
    namespace = _required_namespace()
    namespace.pop("PaymentMethodView")

    with pytest.raises(RuntimeError, match="PaymentMethodView"):
        acceptance_runtime.configure_acceptance_runtime(namespace)
