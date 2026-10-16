from __future__ import annotations

import inspect

import pytest

import services.acceptance.repair_runtime as repair_runtime
import services.acceptance.runtime as runtime
import services.acceptance.sync_worker as sync_worker


def _dependency_namespace() -> dict[str, object]:
    async def refresh_existing_web_sync_dispatch(payload):
        return payload

    return {
        "DISPATCH_CHANNEL_ID": 123,
        "GUILD_ID": 456,
        "ORDER_CLAIMS": {},
        "PaymentMethodView": object,
        "SELF_SERVICE_ORDER_SELECTIONS": {},
        "_refresh_existing_web_sync_dispatch": refresh_existing_web_sync_dispatch,
        "bot": object(),
    }


def _configure_explicit(namespace: dict[str, object]) -> None:
    runtime.configure_acceptance_runtime_explicit(
        dispatch_channel_id=namespace["DISPATCH_CHANNEL_ID"],
        order_claims=namespace["ORDER_CLAIMS"],
        payment_method_view_type=namespace["PaymentMethodView"],
        order_selections=namespace["SELF_SERVICE_ORDER_SELECTIONS"],
        bot_instance=namespace["bot"],
        guild_id=namespace["GUILD_ID"],
        refresh_existing_web_sync_dispatch=namespace[
            "_refresh_existing_web_sync_dispatch"
        ],
    )


def test_explicit_acceptance_runtime_binds_only_declared_dependencies(monkeypatch):
    namespace = _dependency_namespace()

    monkeypatch.setattr(runtime, "_CONFIGURED", False)
    monkeypatch.setattr(sync_worker, "_DEPS", None)
    monkeypatch.setattr(repair_runtime, "_DEPS", None)

    _configure_explicit(namespace)

    assert runtime._CONFIGURED is True
    assert runtime.DISPATCH_CHANNEL_ID == namespace["DISPATCH_CHANNEL_ID"]
    assert runtime.ORDER_CLAIMS is namespace["ORDER_CLAIMS"]
    assert runtime.PaymentMethodView is namespace["PaymentMethodView"]
    assert runtime.SELF_SERVICE_ORDER_SELECTIONS is namespace["SELF_SERVICE_ORDER_SELECTIONS"]

    sync_deps = sync_worker._DEPS
    assert sync_deps is not None
    assert sync_deps.bot is namespace["bot"]
    assert sync_deps.guild_id == namespace["GUILD_ID"]
    assert (
        sync_deps.refresh_existing_web_sync_dispatch
        is namespace["_refresh_existing_web_sync_dispatch"]
    )
    assert (
        sync_deps.refresh_acceptance_dispatch
        is runtime.refresh_acceptance_dispatch_from_web_order
    )
    assert sync_deps.grant_ticket_access is runtime.grant_order_ticket_access
    assert sync_deps.revoke_ticket_access is runtime.revoke_order_ticket_access

    repair_deps = repair_runtime._DEPS
    assert repair_deps is not None
    assert repair_deps.order_selections is namespace["SELF_SERVICE_ORDER_SELECTIONS"]
    assert repair_deps.payment_method_view_type is namespace["PaymentMethodView"]
    assert (
        repair_deps.refresh_acceptance_dispatch
        is runtime.refresh_acceptance_dispatch_from_web_order
    )
    assert (
        repair_deps.sync_ticket_access_from_state
        is runtime.sync_acceptance_ticket_access_from_state
    )
    assert not hasattr(repair_deps, "acceptance_staff_display_text")


def test_namespace_adapter_rejects_unknown_injection_and_delegates(monkeypatch):
    namespace = _dependency_namespace()
    namespace["UNEXPECTED_ACCEPTANCE_INJECTION"] = object()

    monkeypatch.delattr(runtime, "UNEXPECTED_ACCEPTANCE_INJECTION", raising=False)
    monkeypatch.setattr(runtime, "_CONFIGURED", False)
    monkeypatch.setattr(sync_worker, "_DEPS", None)
    monkeypatch.setattr(repair_runtime, "_DEPS", None)

    runtime.configure_acceptance_runtime(namespace)

    assert runtime._CONFIGURED is True
    assert not hasattr(runtime, "UNEXPECTED_ACCEPTANCE_INJECTION")

    source = inspect.getsource(runtime.configure_acceptance_runtime)
    assert "configure_acceptance_runtime_explicit(" in source
    assert "globals()[" not in source


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

    namespace = _dependency_namespace()
    namespace.pop("bot")

    with pytest.raises(RuntimeError, match="bot"):
        runtime.configure_acceptance_runtime(namespace)

    assert runtime.DISPATCH_CHANNEL_ID is previous_dispatch_channel
    assert runtime._CONFIGURED is False
    assert sync_worker._DEPS is previous_worker_deps
    assert repair_runtime._DEPS is previous_repair_deps


def test_acceptance_sync_worker_requires_configuration(monkeypatch):
    monkeypatch.setattr(sync_worker, "_DEPS", None)

    with pytest.raises(RuntimeError, match="not configured"):
        sync_worker._require_deps()


def test_acceptance_repair_runtime_requires_configuration(monkeypatch):
    monkeypatch.setattr(repair_runtime, "_DEPS", None)

    with pytest.raises(RuntimeError, match="not configured"):
        repair_runtime._require_deps()
