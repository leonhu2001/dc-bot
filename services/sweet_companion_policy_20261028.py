from __future__ import annotations

from services.order_rules import (
    SWEET_COMPANION_ROLE_ID,
    SWEET_COMPANION_ROLE_KEY,
    SWEET_COMPANION_ROLE_LABEL,
)


def is_sweet_rule_key(rule_key: str) -> bool:
    key = str(rule_key or "")
    return key.endswith(("_sweet_female", "_sweet_male", "_sweet_any"))


def install_sweet_companion_policy_20261028() -> None:
    """Compatibility no-op: Sweet qualification now lives in services.order_rules."""
    return None


__all__ = [
    "SWEET_COMPANION_ROLE_ID",
    "SWEET_COMPANION_ROLE_KEY",
    "SWEET_COMPANION_ROLE_LABEL",
    "is_sweet_rule_key",
    "install_sweet_companion_policy_20261028",
]
