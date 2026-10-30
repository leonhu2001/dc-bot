from __future__ import annotations

import asyncio
import logging
import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

from services.market.ingest import ingest_market_snapshot
from services.market.provider_registry import build_configured_provider, configured_provider_name
from services.market.providers.base import MarketPriceProvider, MarketSourceUnavailable
from services.market.storage import MarketRepository


logger = logging.getLogger("market.worker")
BASE_DIR = Path(__file__).resolve().parents[2]
load_dotenv(BASE_DIR / "web" / ".env")


@dataclass(frozen=True)
class MarketCycleResult:
    game_key: str
    status: str
    inserted_price_count: int = 0
    message: str = ""


def _game_keys() -> tuple[str, ...]:
    values = tuple(
        value.strip()
        for value in os.getenv("MARKET_GAME_KEYS", "delta_force").split(",")
        if value.strip()
    )
    return values or ("delta_force",)


def _poll_seconds() -> int:
    try:
        return max(180, int(os.getenv("MARKET_POLL_SECONDS", "300")))
    except (TypeError, ValueError):
        return 300


async def run_market_cycle(
    *,
    provider: MarketPriceProvider,
    repository: MarketRepository,
    game_keys: tuple[str, ...],
) -> tuple[MarketCycleResult, ...]:
    results: list[MarketCycleResult] = []
    for game_key in game_keys:
        try:
            ingest_result = await ingest_market_snapshot(
                provider=provider,
                repository=repository,
                game_key=game_key,
            )
        except MarketSourceUnavailable as exc:
            results.append(
                MarketCycleResult(
                    game_key=game_key,
                    status="source_unavailable",
                    message=str(exc),
                )
            )
        except Exception as exc:  # isolate one game/source failure from the loop
            logger.exception("market cycle failed for %s", game_key)
            results.append(
                MarketCycleResult(
                    game_key=game_key,
                    status="error",
                    message=str(exc),
                )
            )
        else:
            results.append(
                MarketCycleResult(
                    game_key=game_key,
                    status=("duplicate" if ingest_result.duplicate_snapshot else "stored"),
                    inserted_price_count=ingest_result.inserted_price_count,
                    message=ingest_result.source_name,
                )
            )
    return tuple(results)


async def run_worker(
    *,
    provider: MarketPriceProvider,
    repository: MarketRepository,
    game_keys: tuple[str, ...],
    poll_seconds: int,
) -> None:
    while True:
        results = await run_market_cycle(
            provider=provider,
            repository=repository,
            game_keys=game_keys,
        )
        for result in results:
            logger.info(
                "market cycle game=%s status=%s inserted=%s source_or_error=%s",
                result.game_key,
                result.status,
                result.inserted_price_count,
                result.message,
            )
        await asyncio.sleep(poll_seconds)


def main() -> int:
    logging.basicConfig(
        level=os.getenv("MARKET_LOG_LEVEL", "INFO").upper(),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )

    provider_name = configured_provider_name()
    if not provider_name:
        logger.info("MARKET_PROVIDER is not configured; market worker remains disabled")
        return 0

    database_url = os.getenv("MARKET_DATABASE_URL", "").strip()
    if not database_url:
        logger.error("MARKET_DATABASE_URL is required when MARKET_PROVIDER is enabled")
        return 2

    try:
        provider = build_configured_provider()
    except Exception:
        logger.exception("market provider configuration is invalid")
        return 2

    if provider is None:
        logger.info("no configured market provider; worker remains disabled")
        return 0

    repository = MarketRepository(database_url)
    repository.create_all()

    logger.info(
        "starting market worker provider=%s games=%s poll_seconds=%s",
        provider_name,
        ",".join(_game_keys()),
        _poll_seconds(),
    )
    asyncio.run(
        run_worker(
            provider=provider,
            repository=repository,
            game_keys=_game_keys(),
            poll_seconds=_poll_seconds(),
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
