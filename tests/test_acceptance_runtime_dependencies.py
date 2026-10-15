import inspect

import pytest

import services.acceptance.runtime as acceptance_runtime


def _minimal_namespace():
    return {
        "DISPATCH_CHANNEL_ID": 123,
        "GUILD_ID": 456,
        "ORDER_CLAIMS": {},
        "PaymentMethodView": object,
        "SELF_SERVICE_ORDER_SELECTIONS": {},
        "_refresh_existing_web_sync_dispatch": lambda *_args, **_kwargs: None,
        "bot": object(),
    }


def test_acceptance_runtime_binds_only_explicit_dependencies():
    source = inspect.getsource(acceptance_runtime.configure_acceptance_runtime)

    assert "for name, value in namespace.items()" not in source
    assert "for name in _DEPENDENCY_NAMES" in source


def test_acceptance_runtime_fails_fast_when_dependency_missing():
    namespace = _minimal_namespace()
    namespace.pop("PaymentMethodView")

    with pytest.raises(RuntimeError, match="PaymentMethodView"):
        acceptance_runtime.configure_acceptance_runtime(namespace)


def test_acceptance_runtime_does_not_replace_module_owned_helpers():
    original_to_int = acceptance_runtime._to_int
    namespace = _minimal_namespace()
    namespace["_to_int"] = lambda *_args, **_kwargs: -999
    namespace["build_payment_method_embed"] = lambda *_args, **_kwargs: None

    acceptance_runtime.configure_acceptance_runtime(namespace)

    assert acceptance_runtime._to_int is original_to_int
