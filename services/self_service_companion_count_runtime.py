"""Compatibility aliases: the enhanced checkout View is natively defined in UI.

No class binding is overwritten at bot startup. Existing imports keep working.
"""
from __future__ import annotations

from services.self_service_ui_runtime import (
    SelfServiceOrderView as EnhancedSelfServiceOrderView,
    SelfServicePlayerCountView,
    SelfServicePlayerCountSelect,
    SelfServicePlayerCountButton,
)


def install_self_service_companion_count_runtime():
    """Legacy startup compatibility: native UI already has the final class."""
    return EnhancedSelfServiceOrderView


__all__ = [
    "EnhancedSelfServiceOrderView",
    "SelfServicePlayerCountView",
    "SelfServicePlayerCountSelect",
    "SelfServicePlayerCountButton",
    "install_self_service_companion_count_runtime",
]
