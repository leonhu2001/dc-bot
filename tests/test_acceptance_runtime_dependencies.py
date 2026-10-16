from __future__ import annotations

import pytest

import services.acceptance.runtime as runtime


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
    monkeypatch.setattr(runtime, "_CONFIGURED", False)

    runtime.configure_acceptance_runtime(namespace)

    assert runtime._CONFIGURED is True
    for name in runtime._DEPENDENCY_NAMES:
        assert getattr(runtime, name) is namespace[name]

    assert not hasattr(runtime, "UNEXPECTED_ACCEPTANCE_INJECTION")


def test_configure_acceptance_runtime_rejects_missing_before_binding(monkeypatch):
    previous_dispatch_channel = object()
    monkeypatch.setattr(
        runtime,
        "DISPATCH_CHANNEL_ID",
        previous_dispatch_channel,
        raising=False,
    )
    monkeypatch.setattr(runtime, "_CONFIGURED", False)

    namespace = _dependency_namespace()
    namespace.pop("bot")

    with pytest.raises(RuntimeError, match="bot"):
        runtime.configure_acceptance_runtime(namespace)

    assert runtime.DISPATCH_CHANNEL_ID is previous_dispatch_channel
    assert runtime._CONFIGURED is False
