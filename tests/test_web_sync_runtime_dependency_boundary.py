from typing import Any, Mapping

import discord

from services.web_sync import runtime as web_sync_runtime


def test_web_sync_legacy_injection_cannot_shadow_module_owned_imports():
    originals = {
        "Any": Any,
        "Mapping": Mapping,
        "discord": discord,
    }
    marker = object()

    web_sync_runtime.configure_web_sync_runtime(
        {
            **{name: object() for name in originals},
            "_web_sync_runtime_boundary_marker": marker,
        }
    )

    for name, original in originals.items():
        assert getattr(web_sync_runtime, name) is original
    assert web_sync_runtime._web_sync_runtime_boundary_marker is marker


def test_web_sync_owned_dependency_names_are_explicit():
    assert web_sync_runtime._MODULE_OWNED_RUNTIME_NAMES == frozenset(
        {
            "Any",
            "Mapping",
            "discord",
        }
    )
