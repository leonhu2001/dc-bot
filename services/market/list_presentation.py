from __future__ import annotations

from typing import Iterable, TypeVar

from services.market.event_detector import MarketEventSignal


T = TypeVar("T")


def pin_market_items(
    items: Iterable[T],
    *,
    market_event: MarketEventSignal | None,
    watched_item_keys: Iterable[str] = (),
) -> tuple[T, ...]:
    """Stable-sort market rows so watched and signalled bullets stay visible.

    The caller may pre-sort by price/change/value first. This function only adds
    the pinning tiers and preserves the caller's order within equal tiers.
    """
    watched = {str(value) for value in watched_item_keys}
    restock = set(market_event.restock_item_keys) if market_event else set()
    abnormal_down = set(market_event.abnormal_down_item_keys) if market_event else set()
    abnormal_up = set(market_event.abnormal_up_item_keys) if market_event else set()

    def priority(item: T) -> tuple[int, int]:
        key = str(getattr(item, "item_key", ""))
        is_watched = key in watched
        is_restock = key in restock
        is_down = key in abnormal_down
        is_up = key in abnormal_up
        is_signalled = is_restock or is_down or is_up

        if is_watched and is_signalled:
            group = 0
        elif is_watched:
            group = 1
        elif is_signalled:
            group = 2
        else:
            group = 3

        if is_down:
            signal = 0
        elif is_restock:
            signal = 1
        elif is_up:
            signal = 2
        else:
            signal = 3
        return group, signal

    return tuple(sorted(tuple(items), key=priority))
