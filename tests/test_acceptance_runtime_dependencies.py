from __future__ import annotations

import pytest

import services.acceptance.runtime as runtime
import services.acceptance.sync_worker as sync_worker


def _dependency_namespace() -> dict[str, object]:
    async def refresh_existing_web_sync_dispatch(payload):
        return payload

    return {
        "DISPATCH_CHANNEL_ID": 123,
        "GUILD_ID": 456,
        "ORDER_CLAIMS": {},
        "PaymentMethodView": object(),
        "SELF_SERVICE_ORDER_SELECTIONS": {},
        "_refresh_existing_web_sync_dispatch": refresh_existing_web_sync_dispatch,
        "bot": object(),
    }


def test_configure_acceptance_runtime_binds_only_explicit_dependencies(monkeypatch):
    namespace = _dependency_namespace()
    unexpected = object()
    namespace["UNEXPECTED_ACCEPTANCE_INJECTION"] = unexpected

    monkeypatch.delattr(runtime, "UNEXPECTED_ACCEPTANCE_INJECTION", raising=False)
    for name in runtime._SYNC_WORKER_DEPENDENCY_NAMES:
        monkeypatch.delattr(runtime, name, raising=False)
    monkeypatch.setattr(runtime, "_CONFIGURED", False)
    monkeypatch.setattr(sync_worker, "_DEPS", None)

    runtime.configure_acceptance_runtime(namespace)

    assert runtime._CONFIGURED is True
    for name in runtime._DEPENDENCY_NAMES:
        assert getattr(runtime, name) is namespace[name]

    assert not hasattr(runtime, "UNEXPECTED_ACCEPTANCE_INJECTION")
    for name in runtime._SYNC_WORKER_DEPENDENCY_NAMES:
        assert not hasattr(runtime, name)

    deps = sync_worker._DEPS
    assert deps is not None
    assert deps.bot is namespace["bot"]
    assert deps.guild_id == namespace["GUILD_ID"]
    assert (
        deps.refresh_existing_web_sync_dispatch
        is namespace["_refresh_existing_web_sync_dispatch"]
    )
    assert deps.refresh_acceptance_dispatch is runtime.refresh_acceptance_dispatch_from_web_order
    assert deps.grant_ticket_access is runtime.grant_order_ticket_access
    assert deps.revoke_ticket_access is runtime.revoke_order_ticket_access


def test_configure_acceptance_runtime_rejects_missing_before_binding(monkeypatch):
    previous_dispatch_channel = object()
    previous_worker_deps = object()
    monkeypatch.setattr(
        runtime,
        "DISPATCH_CHANNEL_ID",
        previous_dispatch_channel,
        raising=False,
    )
    monkeypatch.setattr(runtime, "_CONFIGURED", False)
    monkeypatch.setattr(sync_worker, "_DEPS", previous_worker_deps)

    namespace = _dependency_namespace()
    namespace.pop("bot")

    with pytest.raises(RuntimeError, match="bot"):
        runtime.configure_acceptance_runtime(namespace)

    assert runtime.DISPATCH_CHANNEL_ID is previous_dispatch_channel
    assert runtime._CONFIGURED is False
    assert sync_worker._DEPS is previous_worker_deps


def test_acceptance_sync_worker_requires_configuration(monkeypatch):
    monkeypatch.setattr(sync_worker, "_DEPS", None)

    with pytest.raises(RuntimeError, match="not configured"):
        sync_worker._require_deps()
