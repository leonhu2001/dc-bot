import asyncio
from datetime import datetime, timezone

from services.market.ingest import ingest_market_snapshot
from services.market.providers.base import MarketSourceItem, MarketSourceSnapshot
from services.market.storage import MarketRepository


class FakeProvider:
    async def fetch(self, game_key: str) -> MarketSourceSnapshot:
        now = datetime.now(timezone.utc).replace(microsecond=0)
        return MarketSourceSnapshot(
            source_name="fake-provider",
            game_key=game_key,
            fetched_at=now,
            source_updated_at=now,
            items=(
                MarketSourceItem(
                    source_item_id="m995",
                    name="5.56x45 M995",
                    price=4700,
                    category="ammo",
                    tier=6,
                ),
            ),
        )


def test_ingest_market_snapshot_is_idempotent_for_same_source_timestamp(tmp_path):
    repository = MarketRepository(f"sqlite:///{tmp_path / 'market.db'}")
    repository.create_all()
    provider = FakeProvider()

    first = asyncio.run(
        ingest_market_snapshot(
            provider=provider,
            repository=repository,
            game_key="delta_force",
        )
    )
    second = asyncio.run(
        ingest_market_snapshot(
            provider=provider,
            repository=repository,
            game_key="delta_force",
        )
    )

    assert first.source_name == "fake-provider"
    assert first.inserted_price_count == 1
    assert first.duplicate_snapshot is False
    assert second.inserted_price_count == 0
    assert second.duplicate_snapshot is True
