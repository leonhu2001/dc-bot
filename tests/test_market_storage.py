from datetime import datetime, timedelta, timezone

from services.market.providers.base import MarketSourceItem, MarketSourceSnapshot
from services.market.public_snapshot import get_public_market_snapshot
from services.market.storage import MarketRepository


def _snapshot(
    at: datetime,
    *,
    m995: int,
    m61: int,
    source_name: str = "test-tw-source",
) -> MarketSourceSnapshot:
    return MarketSourceSnapshot(
        source_name=source_name,
        game_key="delta_force",
        fetched_at=at + timedelta(seconds=5),
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


def test_market_repository_deduplicates_source_snapshot_and_keeps_history(tmp_path):
    repository = MarketRepository(f"sqlite:///{tmp_path / 'market.db'}")
    repository.create_all()

    now = datetime.now(timezone.utc).replace(microsecond=0)
    first = _snapshot(now - timedelta(minutes=15), m995=4800, m61=5200)
    second = _snapshot(now, m995=4700, m61=5300)

    assert repository.store_snapshot(first) == 2
    assert repository.store_snapshot(first) == 0
    assert repository.store_snapshot(second) == 2

    latest = repository.list_latest("delta_force")
    assert len(latest) == 2
    latest_by_key = {item.source_item_id: item for item in latest}
    assert latest_by_key["m995"].current_price == 4700
    assert latest_by_key["m61"].current_price == 5300

    m995 = repository.get_item("delta_force", "m995")
    assert m995 is not None
    history = repository.history(m995.id)
    assert [point.price for point in history] == [4800, 4700]
    assert history[0].source_updated_at < history[1].source_updated_at


def test_market_repository_uses_only_the_freshest_provider_source(tmp_path):
    repository = MarketRepository(f"sqlite:///{tmp_path / 'market.db'}")
    repository.create_all()

    now = datetime.now(timezone.utc).replace(microsecond=0)
    old_source = _snapshot(
        now - timedelta(hours=1),
        m995=6100,
        m61=6200,
        source_name="old-provider",
    )
    new_source = _snapshot(
        now,
        m995=4700,
        m61=5300,
        source_name="new-provider",
    )

    repository.store_snapshot(old_source)
    repository.store_snapshot(new_source)

    assert repository.latest_source_name("delta_force") == "new-provider"
    latest = repository.list_latest("delta_force")
    assert {item.source_name for item in latest} == {"new-provider"}
    assert {item.current_price for item in latest} == {4700, 5300}

    m995 = repository.get_item("delta_force", "m995")
    assert m995 is not None
    assert m995.source_name == "new-provider"


def test_public_snapshot_switches_to_ready_when_real_market_rows_exist(tmp_path):
    repository = MarketRepository(f"sqlite:///{tmp_path / 'market.db'}")
    repository.create_all()

    now = datetime.now(timezone.utc).replace(microsecond=0)
    repository.store_snapshot(_snapshot(now, m995=4700, m61=5300))

    snapshot = get_public_market_snapshot("delta_force", repository=repository)

    assert snapshot.status == "ready"
    assert snapshot.updated_at is not None
    assert snapshot.recommended_item is None
    assert {item.item_key for item in snapshot.items} == {"m995", "m61"}
    assert all(item.current_price is not None for item in snapshot.items)
