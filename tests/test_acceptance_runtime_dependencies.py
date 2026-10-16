from __future__ import annotations

import inspect

import pytest

import services.acceptance.repair_runtime as repair_runtime
import services.acceptance.runtime as runtime
import services.acceptance.sync_worker as sync_worker


def _dependency_kwargs() -> dict[str, object]:
    async def refresh_existing_web_sync_dispatch(payload):
        return payload

    return {
        "dispatch_channel_id": 123,
        "order_claims": {},
        "payment_method_view_type": object,
        "order_selections": {},
        "bot_instance": object(),
        "guild_id": 456,
        "refresh_existing_web_sync_dispatch": refresh_existing_web_sync_dispatch,
    }


def test_configure_acceptance_runtime_has_keyword_only_explicit_signature():
    signature = inspect.signature(runtime.configure_acceptance_runtime)
    parameters = signature.parameters

    assert list(parameters) == [
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
        for parameter in parameters.values()
    )
    assert not any(
        parameter.kind is inspect.Parameter.VAR_KEYWORD
        for parameter in parameters.values()
    )


def test_configure_acceptance_runtime_binds_explicit_dependencies(monkeypatch):
    deps = _dependency_kwargs()

    monkeypatch.setattr(runtime, "_CONFIGURED", False)
    monkeypatch.setattr(sync_worker, "_DEPS", None)
    monkeypatch.setattr(repair_runtime, "_DEPS", None)

    runtime.configure_acceptance_runtime(**deps)

    assert runtime._CONFIGURED is True
    assert runtime.DISPATCH_CHANNEL_ID == deps["dispatch_channel_id"]
    assert runtime.ORDER_CLAIMS is deps["order_claims"]
    assert runtime.PaymentMethodView is deps["payment_method_view_type"]
    assert runtime.SELF_SERVICE_ORDER_SELECTIONS is deps["order_selections"]

    sync_deps = sync_worker._DEPS
    assert sync_deps is not None
    assert sync_deps.bot is deps["bot_instance"]
    assert sync_deps.guild_id == deps["guild_id"]
    assert (
        sync_deps.refresh_existing_web_sync_dispatch
        is deps["refresh_existing_web_sync_dispatch"]
    )
    assert (
        sync_deps.refresh_acceptance_dispatch
        is runtime.refresh_acceptance_dispatch_from_web_order
    )
    assert sync_deps.grant_ticket_access is runtime.grant_order_ticket_access
    assert sync_deps.revoke_ticket_access is runtime.revoke_order_ticket_access

    repair_deps = repair_runtime._DEPS
    assert repair_deps is not None
    assert repair_deps.order_selections is deps["order_selections"]
    assert repair_deps.payment_method_view_type is deps["payment_method_view_type"]
    assert (
        repair_deps.refresh_acceptance_dispatch
        is runtime.refresh_acceptance_dispatch_from_web_order
    )
    assert (
        repair_deps.sync_ticket_access_from_state
        is runtime.sync_acceptance_ticket_access_from_state
    )
    assert (
        repair_deps.acceptance_staff_display_text
        is runtime._acceptance_staff_display_text
    )


def test_configure_acceptance_runtime_rejects_missing_before_binding(monkeypatch):
    previous_dispatch_channel = object()
    previous_worker_deps = object()
    previous_repair_deps = object()
    monkeypatch.setattr(
        runtime,
        "DISPATCH_CHANNEL_ID",
        previous_dispatch_channel,
        raising=False,
    )
    monkeypatch.setattr(runtime, "_CONFIGURED", False)
    monkeypatch.setattr(sync_worker, "_DEPS", previous_worker_deps)
    monkeypatch.setattr(repair_runtime, "_DEPS", previous_repair_deps)

    deps = _dependency_kwargs()
    deps.pop("bot_instance")

    with pytest.raises(TypeError, match="bot_instance"):
        runtime.configure_acceptance_runtime(**deps)

    assert runtime.DISPATCH_CHANNEL_ID is previous_dispatch_channel
    assert runtime._CONFIGURED is False
    assert sync_worker._DEPS is previous_worker_deps
    assert repair_runtime._DEPS is previous_repair_deps


def test_configure_acceptance_runtime_rejects_unknown_keyword_before_binding(monkeypatch):
    previous_dispatch_channel = object()
    monkeypatch.setattr(
        runtime,
        "DISPATCH_CHANNEL_ID",
        previous_dispatch_channel,
        raising=False,
    )
    monkeypatch.setattr(runtime, "_CONFIGURED", False)

    deps = _dependency_kwargs()
    deps["unexpected_acceptance_injection"] = object()

    with pytest.raises(TypeError, match="unexpected_acceptance_injection"):
        runtime.configure_acceptance_runtime(**deps)

    assert runtime.DISPATCH_CHANNEL_ID is previous_dispatch_channel
    assert runtime._CONFIGURED is False


def test_acceptance_sync_worker_requires_configuration(monkeypatch):
    monkeypatch.setattr(sync_worker, "_DEPS", None)

    with pytest.raises(RuntimeError, match="not configured"):
        sync_worker._require_deps()


def test_acceptance_repair_runtime_requires_configuration(monkeypatch):
    monkeypatch.setattr(repair_runtime, "_DEPS", None)

    with pytest.raises(RuntimeError, match="not configured"):
        repair_runtime._require_deps()
