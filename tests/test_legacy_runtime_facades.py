from __future__ import annotations

import importlib


def _assert_facade_identity(canonical_name: str, legacy_name: str) -> None:
    canonical = importlib.import_module(canonical_name)
    legacy = importlib.import_module(legacy_name)

    assert canonical is legacy

    sentinel_name = "__mawan_facade_identity_test__"
    sentinel = object()
    setattr(canonical, sentinel_name, sentinel)
    try:
        assert getattr(legacy, sentinel_name) is sentinel
        assert importlib.import_module(canonical_name) is legacy
    finally:
        delattr(legacy, sentinel_name)


def test_order_runtime_facade_preserves_module_identity() -> None:
    _assert_facade_identity(
        "services.order_runtime",
        "services.order_runtime_legacy",
    )


def test_self_service_runtime_facade_preserves_module_identity() -> None:
    _assert_facade_identity(
        "services.self_service_runtime",
        "services.self_service_runtime_legacy",
    )


def test_admin_router_facade_preserves_module_identity() -> None:
    _assert_facade_identity(
        "web.app.routers.admin",
        "web.app.routers.admin_legacy",
    )
