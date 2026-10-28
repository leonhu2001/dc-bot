from __future__ import annotations


_INSTALLED = False
_CANONICAL_BLACK_TIDE_KEYS = {
    "basic_black_tide_entertain",
    "basic_black_tide_tech",
}
_BLACK_TIDE_PREFIX = "basic_black_tide_"


def _is_retired_black_tide_key(rule_key: str) -> bool:
    key = str(rule_key or "").strip()
    return (
        key.startswith(_BLACK_TIDE_PREFIX)
        and key not in _CANONICAL_BLACK_TIDE_KEYS
    )


def install_black_tide_legacy_tombstone() -> None:
    """Prevent removed Black Tide fixed-seat rules from reappearing via SQLite.

    Black Tide checkout is canonical now: the customer chooses only 娛樂陪/技術陪,
    then chooses 1-4 companions through the shared player-count selector. Historical
    custom_order_rules rows may still exist on production from older manager/runtime
    migrations. Once the code-defined legacy keys were removed, those rows could be
    mistaken for ordinary custom products and become visible again.

    Keep the database history intact for audit purposes, but tombstone every retired
    basic_black_tide_* key at the EffectiveOrderRules boundary so live Web/Discord
    catalog generation can never resurrect it.
    """
    global _INSTALLED
    if _INSTALLED:
        return

    from services import order_rules

    rules = order_rules.ORDER_RULES
    if getattr(rules, "_black_tide_legacy_tombstone_installed", False):
        _INSTALLED = True
        return

    original_refresh = rules._refresh_external

    def _refresh_external_without_retired_black_tide() -> None:
        original_refresh()
        stale_keys = [
            key
            for key in tuple(rules._custom_cache)
            if _is_retired_black_tide_key(key)
        ]
        for key in stale_keys:
            rules._custom_cache.pop(key, None)
            rules._override_cache.pop(key, None)

    rules._refresh_external = _refresh_external_without_retired_black_tide
    rules._black_tide_legacy_tombstone_installed = True
    rules.invalidate()
    rules._refresh_external()
    _INSTALLED = True


__all__ = [
    "install_black_tide_legacy_tombstone",
]
