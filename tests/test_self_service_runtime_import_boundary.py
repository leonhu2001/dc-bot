from typing import Any, Mapping

import discord

from services import self_service_runtime


def test_self_service_legacy_injection_cannot_shadow_basic_module_imports():
    originals = {
        "Any": Any,
        "Mapping": Mapping,
        "discord": discord,
    }
    marker = object()

    self_service_runtime.configure_self_service_runtime(
        {
            **{name: object() for name in originals},
            "_self_service_import_boundary_marker": marker,
        }
    )

    for name, original in originals.items():
        assert getattr(self_service_runtime, name) is original
    assert self_service_runtime._self_service_import_boundary_marker is marker


def test_self_service_basic_module_import_names_are_owned():
    for name in ("Any", "Mapping", "discord"):
        assert name in self_service_runtime._MODULE_OWNED_RUNTIME_NAMES
