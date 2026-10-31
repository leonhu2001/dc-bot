from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from services.market.public_snapshot import (
    MarketItemSummary,
    MarketSnapshot,
    _restock_prediction_label,
    _with_restock_prediction,
    filter_market_snapshot,
)
from services.market.restock_prediction import ItemRestockPrediction


UTC = timezone.utc


def test_restock_prediction_label_uses_taipei_day_and_time() -> None:
    now = datetime(2026, 11, 1, 8, 0, tzinfo=UTC)
    predicted = datetime(2026, 11, 1, 10, 30, tzinfo=UTC)

    assert _restock_prediction_label(predicted, now=now) == "今天 18:30"


def test_item_summary_exposes_prediction_confidence_and_sample_shape() -> None:
    now = datetime(2026, 11, 1, 8, 0, tzinfo=UTC)
    prediction = ItemRestockPrediction(
        item_key="ammo-a",
        predicted_at=datetime(2026, 11, 1, 10, 30, tzinfo=UTC),
        confidence=78,
        event_count=5,
        median_interval_minutes=360,
        jitter_minutes=22,
        last_event_at=datetime(2026, 11, 1, 4, 30, tzinfo=UTC),
    )

    item = _with_restock_prediction(
        MarketItemSummary(item_key="ammo-a", name="Ammo A"),
        prediction,
        now=now,
    )

    assert item.restock_prediction_label == "今天 18:30"
    assert item.restock_confidence == 78
    assert item.restock_event_count == 5
    assert item.restock_jitter_minutes == 22


def test_restock_sort_puts_nearest_prediction_first_and_unknown_last() -> None:
    snapshot = MarketSnapshot(
        game_key="delta-force",
        status="ready",
        items=(
            MarketItemSummary(
                item_key="later",
                name="Later",
                restock_predicted_at=datetime(2026, 11, 1, 13, 0, tzinfo=UTC),
                restock_confidence=90,
            ),
            MarketItemSummary(item_key="unknown", name="Unknown"),
            MarketItemSummary(
                item_key="soon",
                name="Soon",
                restock_predicted_at=datetime(2026, 11, 1, 12, 0, tzinfo=UTC),
                restock_confidence=70,
            ),
        ),
    )

    filtered = filter_market_snapshot(snapshot, sort="restock_asc")

    assert [item.item_key for item in filtered.items] == ["soon", "later", "unknown"]


def test_market_template_renders_web_restock_radar_contract() -> None:
    template = (
        Path(__file__).resolve().parents[1]
        / "web"
        / "app"
        / "templates"
        / "game_market.html"
    ).read_text(encoding="utf-8")

    assert 'value="restock_asc"' in template
    assert "預估補貨：最近優先" in template
    assert "snapshot.next_restock_item" in template
    assert "item.restock_prediction_label" in template
    assert "item.restock_event_count" in template
    assert "item.restock_jitter_minutes" in template
