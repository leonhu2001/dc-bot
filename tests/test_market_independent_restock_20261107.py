from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from services.market.providers.base import MarketSourceItem, MarketSourceSnapshot
from services.market.restock_prediction import predict_item_restocks
from services.market.restock_runtime import _source_data_fresh
from services.market.storage import MarketRepository
from views.market_v2 import _prediction_text


def _store(market: MarketRepository, at: datetime, a: int, b: int) -> None:
    market.store_snapshot(
        MarketSourceSnapshot(
            source_name="independent-source",
            game_key="delta_force",
            fetched_at=at,
            source_updated_at=at,
            items=(
                MarketSourceItem(
                    source_item_id="ammo-a",
                    name="Ammo A",
                    price=a,
                    category="rifle",
                    tier=5,
                ),
                MarketSourceItem(
                    source_item_id="ammo-b",
                    name="Ammo B",
                    price=b,
                    category="rifle",
                    tier=5,
                ),
            ),
        )
    )


def test_one_item_can_forecast_without_any_other_item_falling(tmp_path):
    market = MarketRepository(f"sqlite:///{tmp_path / 'independent.db'}")
    market.create_all()
    at = datetime(2026, 11, 7, 1, 0, tzinfo=timezone.utc)
    for minute, a in (
        (0, 100), (15, 85), (60, 100), (120, 85),
        (165, 100), (240, 85),
    ):
        _store(market, at + timedelta(minutes=minute), a, 100)

    rows = predict_item_restocks(
        market,
        "delta_force",
        now=at + timedelta(minutes=250),
    )

    assert len(rows) == 1
    assert rows[0].item_key == "ammo-a"
    assert rows[0].event_count == 3
    assert rows[0].predicted_at > at + timedelta(minutes=250)


def test_stale_source_suppresses_forecast_delivery():
    clock = datetime(2026, 11, 7, 12, 0, tzinfo=timezone.utc)
    assert _source_data_fresh(
        [SimpleNamespace(source_updated_at=clock - timedelta(minutes=10))],
        now=clock,
    )
    assert not _source_data_fresh(
        [SimpleNamespace(source_updated_at=clock - timedelta(hours=4))],
        now=clock,
    )
    assert not _source_data_fresh([], now=clock)


def test_discord_restock_copy_is_individual_and_explains_staleness():
    assert "暫停補貨預測" in _prediction_text(
        SimpleNamespace(status="stale")
    )
    item = SimpleNamespace(
        name="Ammo A",
        restock_predicted_at=datetime(2026, 11, 7, 13, 0, tzinfo=timezone.utc),
        restock_event_count=3,
        restock_confidence=82,
    )
    text = _prediction_text(
        SimpleNamespace(status="ready", next_restock_item=item)
    )
    assert "Ammo A" in text
    assert "3 次歷史降價樣本" in text
    assert "同步" not in text
