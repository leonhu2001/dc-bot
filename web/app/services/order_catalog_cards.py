from __future__ import annotations

import threading
import time
from typing import Any

from services.order_rules import CATEGORY_LABELS, ORDER_RULES
from web.app.services.order_groups import (
    HIDDEN_PUBLIC_RULE_KEYS,
    _current_group_specs,
    _group_data,
    _price_text,
    _to_int,
)


_CACHE_TTL_SECONDS = 60.0
_lock = threading.RLock()
_cache: dict[tuple[str, str], tuple[float, Any]] = {}


def _cached(namespace: str, key: str, builder):
    cache_key = (str(namespace), str(key))
    now = time.monotonic()

    with _lock:
        cached = _cache.get(cache_key)
        if cached and cached[0] > now:
            return cached[1]

    value = builder()

    with _lock:
        _cache[cache_key] = (
            time.monotonic() + _CACHE_TTL_SECONDS,
            value,
        )

    return value


def _visible_variant_summaries(spec: dict) -> list[dict]:
    variants: list[dict] = []

    for rule_key, _public_label in spec.get("variants", []):
        key = str(rule_key or "").strip()
        if not key or key in HIDDEN_PUBLIC_RULE_KEYS:
            continue

        rule = ORDER_RULES.get(key)
        if rule is None:
            continue

        price = _to_int(getattr(rule, "price", 0))
        pricing_type = str(getattr(rule, "pricing_type", "fixed") or "fixed")
        unit_label = str(getattr(rule, "unit_label", "單") or "單")

        variants.append(
            {
                "price": price,
                "pricing_type": pricing_type,
                "price_text": _price_text(
                    price,
                    pricing_type,
                    unit_label,
                ),
            }
        )

    return variants


def _group_card_data(spec: dict) -> dict | None:
    variants = _visible_variant_summaries(spec)
    if not variants:
        return None

    numeric_prices = [
        int(variant["price"])
        for variant in variants
        if int(variant["price"]) > 0
    ]
    starting_price = min(numeric_prices) if numeric_prices else 0
    manual_only = all(
        variant["pricing_type"] == "manual"
        for variant in variants
    )

    if manual_only:
        starting_price_text = "客服報價"
    elif len(variants) == 1:
        starting_price_text = str(variants[0]["price_text"])
    else:
        starting_price_text = f"{starting_price:,}T 起"

    category = str(spec.get("category") or "")
    return {
        "key": str(spec.get("key") or ""),
        "category": category,
        "category_label": CATEGORY_LABELS.get(category, category),
        "label": str(spec.get("label") or ""),
        "selector_label": str(spec.get("selector_label") or "方案"),
        "description": str(spec.get("description") or ""),
        "starting_price": starting_price,
        "starting_price_text": starting_price_text,
        "variant_count": len(variants),
    }


def _build_cards(category: str) -> list[dict]:
    requested = str(category or "all").strip() or "all"
    specs = _current_group_specs()
    valid = {
        "all",
        *{
            str(spec.get("category") or "")
            for spec in specs
            if str(spec.get("category") or "")
        },
    }
    if requested not in valid:
        requested = "all"

    groups: list[dict] = []
    for spec in specs:
        if requested != "all" and str(spec.get("category") or "") != requested:
            continue
        group = _group_card_data(spec)
        if group:
            groups.append(group)

    return groups


def get_grouped_order_catalog_cards(category: str = "all") -> list[dict]:
    key = str(category or "all").strip() or "all"
    return _cached(
        "cards",
        key,
        lambda: _build_cards(key),
    )


def _build_group_detail(group_key: str) -> dict | None:
    key = str(group_key or "").strip()
    if not key:
        return None

    for spec in _current_group_specs():
        if str(spec.get("key") or "") != key:
            continue
        return _group_data(spec)

    return None


def get_order_group_detail(group_key: str) -> dict | None:
    key = str(group_key or "").strip()
    if not key:
        return None

    return _cached(
        "group",
        key,
        lambda: _build_group_detail(key),
    )


def clear_order_catalog_cards_cache() -> None:
    with _lock:
        _cache.clear()
