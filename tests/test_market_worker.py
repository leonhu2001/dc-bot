import asyncio
from datetime import datetime, timezone

from services.market.providers.base import (
    MarketSourceItem,
    MarketSourceSnapshot,
    MarketSourceUnavailable,
)
from services.market.storage import MarketRepository
from services.market.worker import run_market_cycle


class StableProvider:
    def __init__(self) -> None:
        self.at = datetime(2026, 10, 30, 12, 0, tzinfo=timezone.utc)

    async def fetch(self, game_key: str) -> MarketSourceSnapshot:
        return MarketSourceSnapshot(
            source_name="stable-provider",
            game_key=game_key,
            fetched_at=self.at,
            source_updated_at=self.at,
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


class UnavailableProvider:
    async def fetch(self, game_key: str) -> MarketSourceSnapshot:
        raise MarketSourceUnavailable("source offline")


def test_market_worker_cycle_deduplicates_same_snapshot(tmp_path):
    repository = MarketRepository(f"sqlite:///{tmp_path / 'market.db'}")
    repository.create_all()
    provider = StableProvider()

    first = asyncio.run(
        run_market_cycle(
            provider=provider,
            repository=repository,
            game_keys=("delta_force",),
        )
    )
    second = asyncio.run(
        run_market_cycle(
            provider=provider,
            repository=repository,
            game_keys=("delta_force",),
        )
    )

    assert first[0].status == "stored"
    assert first[0].inserted_price_count == 1
    assert second[0].status == "duplicate"
    assert second[0].inserted_price_count == 0


def test_market_worker_cycle_isolates_unavailable_source(tmp_path):
    repository = MarketRepository(f"sqlite:///{tmp_path / 'market.db'}")
    repository.create_all()

    results = asyncio.run(
        run_market_cycle(
            provider=UnavailableProvider(),
            repository=repository,
            game_keys=("delta_force",),
        )
    )

    assert results[0].status == "source_unavailable"
    assert "offline" in results[0].message
