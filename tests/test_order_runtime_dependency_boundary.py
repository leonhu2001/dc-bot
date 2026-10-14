from typing import Any, Mapping

import discord

from services import order_runtime


def test_order_runtime_legacy_injection_cannot_shadow_module_owned_imports():
    originals = {
        "Any": Any,
        "Mapping": Mapping,
        "discord": discord,
    }
    marker = object()

    order_runtime.configure_order_runtime(
        {
            **{name: object() for name in originals},
            "_order_runtime_boundary_marker": marker,
        }
    )

    for name, original in originals.items():
        assert getattr(order_runtime, name) is original
    assert order_runtime._order_runtime_boundary_marker is marker


def test_order_runtime_owned_dependency_names_are_explicit():
    assert order_runtime._MODULE_OWNED_RUNTIME_NAMES == frozenset(
        {
            "Any",
            "Mapping",
            "discord",
        }
    )
