from __future__ import annotations

from collections.abc import Iterator, Mapping
from typing import Any


_APEX_SERVICE_PREFIXES = (
    "apex_entertain",
    "apex_diamond",
    "apex_master",
    "apex_predator",
)
_APEX_LEGACY_CUSTOMER_RANKS = ("platinum", "diamond", "master")

LEGACY_APEX_CUSTOMER_RANK_RULE_KEYS = frozenset(
    f"{service_prefix}_{customer_rank}{ranked_suffix}"
    for service_prefix in _APEX_SERVICE_PREFIXES
    for customer_rank in _APEX_LEGACY_CUSTOMER_RANKS
    for ranked_suffix in ("", "_ranked")
)


class _AdminVisibleOrderRules(Mapping[str, Any]):
    """Read-only admin view that hides retired APEX customer-rank rules.

    The underlying registry stays untouched so historical orders and snapshots can
    still resolve their original rule keys. Only the 商品與規則 admin module gets
    this filtered view, which also makes direct legacy ?edit= links non-editable.
    """

    def __init__(self, source: Mapping[str, Any]):
        self._source = source

    def __getitem__(self, key: str) -> Any:
        normalized = str(key)
        if normalized in LEGACY_APEX_CUSTOMER_RANK_RULE_KEYS:
            raise KeyError(normalized)
        return self._source[normalized]

    def __iter__(self) -> Iterator[str]:
        return (
            str(key)
            for key in self._source
            if str(key) not in LEGACY_APEX_CUSTOMER_RANK_RULE_KEYS
        )

    def __len__(self) -> int:
        return sum(
            1
            for key in self._source
            if str(key) not in LEGACY_APEX_CUSTOMER_RANK_RULE_KEYS
        )


def install_admin_order_rules_policy(admin_order_rules_module) -> None:
    current = getattr(admin_order_rules_module, "ORDER_RULES", None)
    if current is None or isinstance(current, _AdminVisibleOrderRules):
        return
    admin_order_rules_module.ORDER_RULES = _AdminVisibleOrderRules(current)


__all__ = [
    "LEGACY_APEX_CUSTOMER_RANK_RULE_KEYS",
    "install_admin_order_rules_policy",
]
