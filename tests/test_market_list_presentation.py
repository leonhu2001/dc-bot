from dataclasses import dataclass

from services.market.event_detector import MarketEventSignal
from services.market.list_presentation import pin_market_items


@dataclass(frozen=True)
class Item:
    item_key: str


def _signal() -> MarketEventSignal:
    return MarketEventSignal(
        state="normal",
        label="test",
        restock_item_keys=("restock", "watched-restock"),
        abnormal_down_item_keys=("dump", "watched-dump"),
        abnormal_up_item_keys=("spike",),
    )


def test_watched_and_signalled_are_pinned_before_watched_then_signalled():
    items = tuple(
        Item(key)
        for key in (
            "normal-a",
            "spike",
            "watched-only",
            "restock",
            "watched-restock",
            "dump",
            "watched-dump",
            "normal-b",
        )
    )

    ordered = pin_market_items(
        items,
        market_event=_signal(),
        watched_item_keys=("watched-only", "watched-restock", "watched-dump"),
    )

    assert tuple(item.item_key for item in ordered) == (
        "watched-dump",
        "watched-restock",
        "watched-only",
        "dump",
        "restock",
        "spike",
        "normal-a",
        "normal-b",
    )


def test_original_sort_is_preserved_inside_equal_priority_group():
    items = (Item("normal-c"), Item("normal-a"), Item("normal-b"))
    ordered = pin_market_items(items, market_event=None)
    assert tuple(item.item_key for item in ordered) == (
        "normal-c",
        "normal-a",
        "normal-b",
    )
