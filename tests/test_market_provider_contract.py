from datetime import datetime, timezone

import pytest

from services.market.providers import (
    MarketSourceItem,
    MarketSourceSnapshot,
    MarketSourceUnavailable,
    normalize_source_snapshot,
)


def test_market_source_normalization_filters_invalid_prices_and_deduplicates():
    snapshot = MarketSourceSnapshot(
        source_name=" Taiwan Source ",
        game_key=" delta_force ",
        fetched_at=datetime(2026, 10, 30, 12, 0),
        source_updated_at=datetime(2026, 10, 30, 11, 45, tzinfo=timezone.utc),
        items=(
            MarketSourceItem("m995", "M995", 5000, "ammo", 5),
            MarketSourceItem("bad", "Broken", 0, "ammo", 5),
            MarketSourceItem("m995", "M995", 4900, "ammo", 5),
            MarketSourceItem("m62", "M62", 5600, "ammo", 99),
        ),
    )

    normalized = normalize_source_snapshot(snapshot)

    assert normalized.source_name == "Taiwan Source"
    assert normalized.game_key == "delta_force"
    assert normalized.fetched_at.tzinfo == timezone.utc
    assert [(item.source_item_id, item.price) for item in normalized.items] == [
        ("m995", 4900),
        ("m62", 5600),
    ]
    assert normalized.items[1].tier is None


def test_market_source_normalization_rejects_empty_valid_result():
    snapshot = MarketSourceSnapshot(
        source_name="source",
        game_key="delta_force",
        fetched_at=datetime.now(timezone.utc),
        source_updated_at=None,
        items=(MarketSourceItem("bad", "Broken", 0),),
    )

    with pytest.raises(MarketSourceUnavailable):
        normalize_source_snapshot(snapshot)
