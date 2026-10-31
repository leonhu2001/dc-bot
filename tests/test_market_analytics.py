from datetime import datetime, timedelta, timezone

from services.market.providers.base import MarketSourceItem, MarketSourceSnapshot
from services.market.public_snapshot import filter_market_snapshot, get_public_market_snapshot
from services.market.storage import MarketRepository


def _store(repository: MarketRepository, at: datetime, *, m995: int, m61: int) -> None:
    repository.store_snapshot(
        MarketSourceSnapshot(
            source_name="test-tw-source",
            game_key="delta_force",
            fetched_at=at + timedelta(seconds=3),
            source_updated_at=at,
            items=(
                MarketSourceItem(
                    source_item_id="m995",
                    name="5.56x45 M995",
                    price=m995,
                    category="ammo",
                    tier=4,
                ),
                MarketSourceItem(
                    source_item_id="m61",
                    name="7.62x51 M61",
                    price=m61,
                    category="ammo",
                    tier=5,
                ),
            ),
        )
    )


def test_market_analytics_withholds_partial_windows(tmp_path):
    repository = MarketRepository(f"sqlite:///{tmp_path / 'market.db'}")
    repository.create_all()
    now = datetime.now(timezone.utc).replace(microsecond=0)

    _store(repository, now - timedelta(hours=2), m995=100, m61=200)
    _store(repository, now, m995=120, m61=180)

    snapshot = get_public_market_snapshot("delta_force", repository=repository)
    by_key = {item.item_key: item for item in snapshot.items}

    assert by_key["m995"].change_24h_pct is None
    assert by_key["m995"].avg_7d is None
    assert by_key["m995"].vs_7d_avg_pct is None
    assert snapshot.gainers == ()
    assert snapshot.losers == ()
    assert snapshot.recommended_item is None


def test_market_analytics_reports_mature_24h_and_7d_stats(tmp_path):
    repository = MarketRepository(f"sqlite:///{tmp_path / 'market.db'}")
    repository.create_all()
    now = datetime.now(timezone.utc).replace(microsecond=0)

    # Keep the first point slightly inside the seven-day window so wall-clock
    # drift between fixture creation and snapshot calculation cannot exclude it.
    _store(repository, now - timedelta(days=6, hours=23), m995=100, m61=200)
    _store(repository, now - timedelta(hours=24), m995=120, m61=180)
    _store(repository, now - timedelta(hours=12), m995=130, m61=170)
    _store(repository, now, m995=150, m61=160)

    snapshot = get_public_market_snapshot("delta_force", repository=repository)
    by_key = {item.item_key: item for item in snapshot.items}

    assert by_key["m995"].change_24h_pct == 25.0
    assert by_key["m995"].low_24h == 120
    assert by_key["m995"].high_24h == 150
    assert by_key["m995"].avg_7d == 125.0
    assert by_key["m995"].vs_7d_avg_pct == 20.0
    assert by_key["m995"].low_7d == 100
    assert by_key["m995"].high_7d == 150

    assert by_key["m61"].change_24h_pct == -11.11
    assert by_key["m61"].vs_7d_avg_pct == -9.86
    assert snapshot.gainers[0].item_key == "m995"
    assert snapshot.losers[0].item_key == "m61"
    assert snapshot.recommended_item is not None
    assert snapshot.recommended_item.item_key == "m61"
    assert snapshot.recommended_item.recommendation_label == "低於 7D 均價 9.9%"

    value_low_first = filter_market_snapshot(snapshot, sort="value_asc")
    assert [item.item_key for item in value_low_first.items] == ["m61", "m995"]

    value_high_first = filter_market_snapshot(snapshot, sort="value_desc")
    assert [item.item_key for item in value_high_first.items] == ["m995", "m61"]


def test_market_price_opportunity_requires_meaningful_discount(tmp_path):
    repository = MarketRepository(f"sqlite:///{tmp_path / 'market.db'}")
    repository.create_all()
    now = datetime.now(timezone.utc).replace(microsecond=0)

    _store(repository, now - timedelta(days=6, hours=23), m995=100, m61=200)
    _store(repository, now - timedelta(days=4), m995=101, m61=201)
    _store(repository, now - timedelta(days=2), m995=100, m61=199)
    _store(repository, now, m995=99, m61=198)

    snapshot = get_public_market_snapshot("delta_force", repository=repository)

    assert all(item.avg_7d is not None for item in snapshot.items)
    assert snapshot.recommended_item is None


def test_market_snapshot_search_tier_and_sort(tmp_path):
    repository = MarketRepository(f"sqlite:///{tmp_path / 'market.db'}")
    repository.create_all()
    now = datetime.now(timezone.utc).replace(microsecond=0)
    _store(repository, now, m995=150, m61=160)

    snapshot = get_public_market_snapshot("delta_force", repository=repository)

    searched = filter_market_snapshot(snapshot, query="M995")
    assert [item.item_key for item in searched.items] == ["m995"]

    tiered = filter_market_snapshot(snapshot, tier=5)
    assert [item.item_key for item in tiered.items] == ["m61"]

    sorted_snapshot = filter_market_snapshot(snapshot, sort="price_desc")
    assert [item.item_key for item in sorted_snapshot.items] == ["m61", "m995"]
