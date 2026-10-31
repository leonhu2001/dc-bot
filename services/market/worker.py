from __future__ import annotations

import asyncio
import logging
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from functools import partial
from pathlib import Path

from dotenv import load_dotenv

from services.market.ingest import ingest_market_snapshot
from services.market.personalization import MarketPersonalizationRepository
from services.market.provider_registry import build_configured_provider, configured_provider_name
from services.market.providers.base import MarketPriceProvider, MarketSourceUnavailable
from services.market.push import MarketPushRepository
from services.market.push_dispatcher import dispatch_pending_pushes
from services.market.scope import market_item_enabled
from services.market.storage import MarketRepository


logger = logging.getLogger("market.worker")
BASE_DIR = Path(__file__).resolve().parents[2]
load_dotenv(BASE_DIR / "web" / ".env")


@dataclass(frozen=True)
class MarketCycleResult:
    game_key: str
    status: str
    inserted_price_count: int = 0
    alert_trigger_count: int = 0
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


def _stale_seconds() -> int:
    try:
        return max(900, int(os.getenv("MARKET_STALE_SECONDS", "2700")))
    except (TypeError, ValueError):
        return 2700


def _evaluate_fresh_alerts(
    *,
    repository: MarketRepository,
    personalization: MarketPersonalizationRepository | None,
    game_key: str,
) -> int:
    if personalization is None:
        return 0

    latest = tuple(
        item
        for item in repository.list_latest(game_key)
        if market_item_enabled(game_key, item.tier)
    )
    if not latest:
        return 0

    updated_at = max(item.source_updated_at for item in latest)
    if updated_at.tzinfo is None:
        updated_at = updated_at.replace(tzinfo=timezone.utc)
    else:
        updated_at = updated_at.astimezone(timezone.utc)

    now = datetime.now(timezone.utc)
    age_seconds = max(0.0, (now - updated_at).total_seconds())
    if age_seconds > _stale_seconds():
        logger.info(
            "skip alert evaluation for stale market game=%s age_seconds=%.0f",
            game_key,
            age_seconds,
        )
        return 0

    current_prices = {
        item.source_item_id: item.current_price
        for item in latest
        if item.current_price > 0
    }
    triggers = personalization.evaluate_alerts(
        game_key,
        current_prices,
        evaluated_at=now,
    )
    for trigger in triggers:
        logger.info(
            "market alert triggered alert_id=%s game=%s item=%s condition=%s target=%s price=%s",
            trigger.alert_id,
            trigger.game_key,
            trigger.item_key,
            trigger.condition_type,
            trigger.target_price,
            trigger.current_price,
        )
    return len(triggers)


async def run_market_cycle(
    *,
    provider: MarketPriceProvider,
    repository: MarketRepository,
    game_keys: tuple[str, ...],
    personalization: MarketPersonalizationRepository | None = None,
) -> tuple[MarketCycleResult, ...]:
    results: list[MarketCycleResult] = []
    for game_key in game_keys:
        try:
            ingest_result = await ingest_market_snapshot(
                provider=provider,
                repository=repository,
                game_key=game_key,
            )
            alert_trigger_count = _evaluate_fresh_alerts(
                repository=repository,
                personalization=personalization,
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
                    alert_trigger_count=alert_trigger_count,
                    message=ingest_result.source_name,
                )
            )
    return tuple(results)


async def run_worker(
    *,
    provider: MarketPriceProvider,
    repository: MarketRepository,
    personalization: MarketPersonalizationRepository | None,
    push_repository: MarketPushRepository | None,
    game_keys: tuple[str, ...],
    poll_seconds: int,
) -> None:
    while True:
        results = await run_market_cycle(
            provider=provider,
            repository=repository,
            personalization=personalization,
            game_keys=game_keys,
        )
        for result in results:
            logger.info(
                "market cycle game=%s status=%s inserted=%s alert_triggers=%s source_or_error=%s",
                result.game_key,
                result.status,
                result.inserted_price_count,
                result.alert_trigger_count,
                result.message,
            )

        if push_repository is not None:
            summary = await asyncio.to_thread(
                partial(
                    dispatch_pending_pushes,
                    market_repository=repository,
                    push_repository=push_repository,
                )
            )
            if summary.processed:
                logger.info(
                    "push dispatch processed=%s sent=%s retried=%s no_subscription=%s",
                    summary.processed,
                    summary.sent,
                    summary.retried,
                    summary.no_subscription,
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
    personalization = MarketPersonalizationRepository(repository)
    personalization.create_all()
    push_repository = MarketPushRepository(repository)
    push_repository.create_all()

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
            personalization=personalization,
            push_repository=push_repository,
            game_keys=_game_keys(),
            poll_seconds=_poll_seconds(),
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
