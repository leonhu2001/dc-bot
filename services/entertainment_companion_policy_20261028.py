from __future__ import annotations


# Compatibility shims for the 2026-10-28 rollout.
#
# Entertainment companion variants, player-count pricing, point-benefit catalog
# metadata and loyalty aliases now live in their canonical modules. Point-service
# funding is calculated directly by services.self_service_financials. These dated
# installers intentionally perform no runtime mutation.


def install_entertainment_companion_policy_20261028() -> None:
    """Deprecated no-op; formal rules/catalog now own this behavior."""

    return None


def install_point_service_financial_runtime_20261028() -> None:
    """Deprecated no-op; point funding now lives in self_service_financials."""

    return None


__all__ = [
    "install_entertainment_companion_policy_20261028",
    "install_point_service_financial_runtime_20261028",
]
