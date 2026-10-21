from __future__ import annotations

import threading
import time
from functools import wraps
from pathlib import Path
from types import ModuleType
from typing import Any, Callable

from services.order_rule_store import (
    load_active_overrides,
    load_custom_rule_definitions,
)


_RULE_CACHE_TTL_SECONDS = 15.0
_CATALOG_CACHE_TTL_SECONDS = 60.0
_lock = threading.RLock()
_rule_cache_expires_at = 0.0
_active_overrides: dict[str, dict[str, Any]] = {}
_custom_rules: dict[str, dict[str, Any]] = {}
_result_cache: dict[tuple[str, str], tuple[float, Any]] = {}


def _load_rule_snapshot() -> tuple[
    dict[str, dict[str, Any]],
    dict[str, dict[str, Any]],
]:
    global _rule_cache_expires_at, _active_overrides, _custom_rules

    now = time.monotonic()
    with _lock:
        if _rule_cache_expires_at > now:
            return _active_overrides, _custom_rules

        # Public storefront presentation can tolerate a very short delay after
        # a manager edit. Pricing/checkout still use the authoritative rule
        # path and are never served from this presentation cache.
        _active_overrides = load_active_overrides()
        _custom_rules = load_custom_rule_definitions()
        _rule_cache_expires_at = time.monotonic() + _RULE_CACHE_TTL_SECONDS
        return _active_overrides, _custom_rules


def get_active_override_cached(
    rule_key: str,
    db_file: str | Path | None = None,
) -> dict[str, Any] | None:
    if db_file is not None:
        return load_active_overrides(db_file).get(str(rule_key))

    overrides, _custom = _load_rule_snapshot()
    return overrides.get(str(rule_key))


def get_custom_rule_definition_cached(
    rule_key: str,
    db_file: str | Path | None = None,
) -> dict[str, Any] | None:
    if db_file is not None:
        return load_custom_rule_definitions(db_file).get(str(rule_key))

    _overrides, custom_rules = _load_rule_snapshot()
    return custom_rules.get(str(rule_key))


def _cached_result(
    namespace: str,
    key: str,
    builder: Callable[[], Any],
) -> Any:
    cache_key = (str(namespace), str(key))
    now = time.monotonic()

    with _lock:
        cached = _result_cache.get(cache_key)
        if cached and cached[0] > now:
            return cached[1]

    result = builder()

    with _lock:
        _result_cache[cache_key] = (
            time.monotonic() + _CATALOG_CACHE_TTL_SECONDS,
            result,
        )

    return result


def install_order_catalog_read_cache(order_groups: ModuleType) -> None:
    """Keep public catalog rendering off repeated SQLite/Python rebuild paths.

    The first implementation used a one-second cache. That only collapsed work
    inside one burst of requests, so normal navigation still rebuilt the whole
    storefront. Public presentation data now lives for up to one minute, while
    quote/checkout/order creation continue to revalidate against live rules.
    """
    order_groups.get_active_override = get_active_override_cached
    order_groups.get_custom_rule_definition = get_custom_rule_definition_cached

    original_get_catalog = order_groups.get_grouped_order_catalog

    @wraps(original_get_catalog)
    def cached_get_catalog(category: str = "all") -> list[dict]:
        key = str(category or "all").strip() or "all"
        return _cached_result(
            "catalog",
            key,
            lambda: original_get_catalog(key),
        )

    order_groups.get_grouped_order_catalog = cached_get_catalog

    original_get_cards = getattr(
        order_groups,
        "get_grouped_order_catalog_cards",
        None,
    )
    if callable(original_get_cards):
        @wraps(original_get_cards)
        def cached_get_cards(category: str = "all") -> list[dict]:
            key = str(category or "all").strip() or "all"
            return _cached_result(
                "cards",
                key,
                lambda: original_get_cards(key),
            )

        order_groups.get_grouped_order_catalog_cards = cached_get_cards

    original_get_group = getattr(
        order_groups,
        "get_order_group_detail",
        None,
    )
    if callable(original_get_group):
        @wraps(original_get_group)
        def cached_get_group(group_key: str) -> dict | None:
            key = str(group_key or "").strip()
            return _cached_result(
                "group",
                key,
                lambda: original_get_group(key),
            )

        order_groups.get_order_group_detail = cached_get_group

    original_get_categories = getattr(
        order_groups,
        "get_public_order_categories",
        None,
    )
    if callable(original_get_categories):
        @wraps(original_get_categories)
        def cached_get_categories() -> list[dict]:
            return _cached_result(
                "categories",
                "all",
                original_get_categories,
            )

        order_groups.get_public_order_categories = cached_get_categories


def clear_order_catalog_read_cache() -> None:
    global _rule_cache_expires_at, _active_overrides, _custom_rules

    with _lock:
        _rule_cache_expires_at = 0.0
        _active_overrides = {}
        _custom_rules = {}
        _result_cache.clear()
