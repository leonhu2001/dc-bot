import discord

from services import self_service_runtime


def test_self_service_basic_module_import_is_canonical():
    assert self_service_runtime.discord is discord
    assert "discord" in self_service_runtime._MODULE_OWNED_RUNTIME_NAMES


def test_self_service_legacy_namespace_surface_is_removed():
    assert not hasattr(self_service_runtime, "Any")
    assert not hasattr(self_service_runtime, "Mapping")
    assert not hasattr(self_service_runtime, "configure_self_service_runtime")
    assert not hasattr(self_service_runtime, "_LEGACY_RUNTIME_NAMES")
