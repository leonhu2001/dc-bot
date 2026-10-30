from __future__ import annotations


# Compatibility shim for imports from the 2026-10-29 rollout.
#
# Dynamic service-point eligibility and pricing now live directly in
# services.point_benefit_catalog / services.unified_service_point_policy, while
# checkout balance filtering and financial accounting live in their canonical
# self-service modules. This module intentionally does not rebind any functions.


def install_dynamic_game_point_policy() -> None:
    """Deprecated no-op; retained only for backward-compatible imports."""

    return None


__all__ = ["install_dynamic_game_point_policy"]
