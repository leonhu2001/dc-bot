from typing import Any, Mapping

import discord
import pytest

from services import self_service_runtime


def test_self_service_legacy_injection_cannot_shadow_basic_imports_or_add_unknowns():
    originals = {
        "Any": Any,
        "Mapping": Mapping,
        "discord": discord,
    }
    marker_name = "_self_service_import_boundary_marker"
    if hasattr(self_service_runtime, marker_name):
        delattr(self_service_runtime, marker_name)

    with pytest.raises(RuntimeError, match="self-service runtime missing dependencies"):
        self_service_runtime.configure_self_service_runtime(
            {
                **{name: object() for name in originals},
                marker_name: object(),
            }
        )

    for name, original in originals.items():
        assert getattr(self_service_runtime, name) is original
    assert not hasattr(self_service_runtime, marker_name)


def test_self_service_basic_module_import_names_are_owned():
    for name in ("Any", "Mapping", "discord"):
        assert name in self_service_runtime._MODULE_OWNED_RUNTIME_NAMES
        assert name not in self_service_runtime._LEGACY_RUNTIME_NAMES
