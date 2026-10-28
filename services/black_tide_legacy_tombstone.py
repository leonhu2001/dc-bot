from __future__ import annotations


_INSTALLED = False
_CANONICAL_BLACK_TIDE_KEYS = {
    "basic_black_tide_entertain",
    "basic_black_tide_tech",
}
_BLACK_TIDE_PREFIX = "basic_black_tide_"
_BLACK_TIDE_CATEGORY = "delta_desktop_basic"
_BLACK_TIDE_GROUP_LABEL = "黑潮爆破"


def _is_retired_black_tide_key(rule_key: str) -> bool:
    key = str(rule_key or "").strip()
    return (
        key.startswith(_BLACK_TIDE_PREFIX)
        and key not in _CANONICAL_BLACK_TIDE_KEYS
    )


def _effective_custom_group_label(rule, override_item) -> str:
    payload = (override_item or {}).get("payload") or {}
    if isinstance(payload, dict) and "catalog_group_label" in payload:
        return str(payload.get("catalog_group_label") or "").strip()
    return str(getattr(rule, "catalog_group_label", "") or "").strip()


def _is_retired_black_tide_custom_rule(rule_key: str, rule, override_item) -> bool:
    """Return True for any SQLite custom rule trying to occupy Black Tide checkout.

    Older production rows are not guaranteed to use the historical
    ``basic_black_tide_*`` keys. Products created from the Web manager receive
    ``admin_delta_desktop_basic_*`` keys and can still carry
    ``catalog_group_label=黑潮爆破``. Both Discord and Web dynamically merge those
    custom rules into the catalog, so key-only filtering is insufficient.
    """
    if _is_retired_black_tide_key(rule_key):
        return True

    if rule is None:
        return False

    category = str(getattr(rule, "category", "") or "").strip()
    if category != _BLACK_TIDE_CATEGORY:
        return False

    return _effective_custom_group_label(rule, override_item) == _BLACK_TIDE_GROUP_LABEL


def install_black_tide_legacy_tombstone() -> None:
    """Prevent removed Black Tide fixed-seat rules from reappearing via SQLite.

    Black Tide checkout is canonical now: the customer chooses only 娛樂陪/技術陪,
    then chooses 1-4 companions through the shared player-count selector. Historical
    custom_order_rules rows may still exist on production from older manager/runtime
    migrations. Some use old ``basic_black_tide_*`` keys while Web-created products
    use generated ``admin_*`` keys but still live under the 黑潮爆破 catalog group.

    Keep database history intact for audit purposes, but remove every non-canonical
    SQLite rule that can enter the live Black Tide group at the EffectiveOrderRules
    boundary. This protects both Discord and Web catalog generation without touching
    custom products in any other group.
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
            for key, rule in tuple(rules._custom_cache.items())
            if _is_retired_black_tide_custom_rule(
                key,
                rule,
                rules._override_cache.get(key),
            )
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
