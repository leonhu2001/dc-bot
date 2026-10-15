import asyncio
from pathlib import Path
from typing import Any, Mapping

import discord
import pytest

from core import database as core_database
from core import time_utils
from services import logging_service, order_flow, orders, self_service_financials
from services.acceptance import runtime as acceptance_runtime
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


def test_acceptance_runtime_owns_canonical_persistence_and_time_dependencies():
    assert acceptance_runtime.remember_claim_data is core_database.remember_claim_data
    assert acceptance_runtime.remember_order_data is core_database.remember_order_data
    assert acceptance_runtime.save_bot_data is core_database.save_bot_data
    assert acceptance_runtime.get_taipei_now_iso is time_utils.get_taipei_now_iso
    assert acceptance_runtime.utc_now_naive is time_utils.utc_now_naive


def test_acceptance_runtime_owns_stable_service_dependencies():
    assert acceptance_runtime._to_int is orders._to_int
    assert acceptance_runtime.ORDER_CATEGORY_LABELS is orders.ORDER_CATEGORY_LABELS
    assert acceptance_runtime.build_self_service_order_embed is orders.build_self_service_order_embed
    assert acceptance_runtime.build_payment_method_embed is order_flow.build_payment_method_embed
    assert acceptance_runtime.DispatchClaimView is order_dispatch_runtime.DispatchClaimView
    assert acceptance_runtime.send_order_log is logging_service.send_order_log
    assert acceptance_runtime._price_snapshot is self_service_financials._price_snapshot
    assert acceptance_runtime._price_int is self_service_financials._price_int
    assert acceptance_runtime._format_plain_amount is self_service_financials._format_plain_amount
    assert (
        acceptance_runtime.add_self_service_financial_breakdown_fields
        is self_service_financials.add_self_service_financial_breakdown_fields
    )


def test_acceptance_namespace_cannot_shadow_module_owned_dependencies():
    originals = {
        "Any": Any,
        "Mapping": Mapping,
        "Path": Path,
        "asyncio": asyncio,
        "discord": discord,
        "remember_claim_data": core_database.remember_claim_data,
        "remember_order_data": core_database.remember_order_data,
        "save_bot_data": core_database.save_bot_data,
        "get_taipei_now_iso": time_utils.get_taipei_now_iso,
        "utc_now_naive": time_utils.utc_now_naive,
        "_to_int": orders._to_int,
        "build_payment_method_embed": order_flow.build_payment_method_embed,
        "DispatchClaimView": order_dispatch_runtime.DispatchClaimView,
    }
    marker = object()

    acceptance_runtime.configure_acceptance_runtime(
        _required_namespace(
            **{name: object() for name in originals},
            _acceptance_runtime_boundary_marker=marker,
        )
    )

    for name, original in originals.items():
        assert getattr(acceptance_runtime, name) is original
    assert not hasattr(acceptance_runtime, "_acceptance_runtime_boundary_marker")


def test_acceptance_runtime_dependency_names_are_explicit():
    assert acceptance_runtime._DEPENDENCY_NAMES == (
        "DISPATCH_CHANNEL_ID",
        "GUILD_ID",
        "ORDER_CLAIMS",
        "PaymentMethodView",
        "SELF_SERVICE_ORDER_SELECTIONS",
        "_refresh_existing_web_sync_dispatch",
        "bot",
    )


def test_acceptance_runtime_fails_fast_when_required_dependency_is_missing():
    namespace = _required_namespace()
    namespace.pop("PaymentMethodView")

    with pytest.raises(RuntimeError, match="PaymentMethodView"):
        acceptance_runtime.configure_acceptance_runtime(namespace)
