from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import func, select

from services.market.provider_registry import configured_provider_name
from services.market.push_dispatcher import get_web_push_config
from services.market.restock_delivery import MarketRestockDelivery, MarketRestockForecast
from services.market.restock_prediction import get_cached_item_restock_predictions
from services.market.runtime import get_market_repository
from services.market.scope import market_item_enabled


@dataclass(frozen=True)
class MarketHealthStatus:
    ok: bool
    status: str
    configured: bool
    database: bool
    provider: str
    source_name: str
    latest_source_updated_at: datetime | None
    age_seconds: int | None
    item_count: int
    stale_seconds: int
    web_push_enabled: bool
    prediction_count: int = 0
    scheduled_forecasts: int = 0
    resolved_forecasts: int = 0
    forecast_mae_minutes: float | None = None
    restock_dm_sent: int = 0
    restock_dm_retry: int = 0
    restock_dm_failed: int = 0
    message: str = ""

    def as_dict(self) -> dict[str, object]:
        updated_at = self.latest_source_updated_at
        return {
            "ok": self.ok,
            "service": "market",
            "status": self.status,
            "configured": self.configured,
            "database": self.database,
            "provider": self.provider,
            "source_name": self.source_name,
            "latest_source_updated_at": updated_at.isoformat() if updated_at else None,
            "age_seconds": self.age_seconds,
            "item_count": self.item_count,
            "stale_seconds": self.stale_seconds,
            "web_push_enabled": self.web_push_enabled,
            "prediction_count": self.prediction_count,
            "scheduled_forecasts": self.scheduled_forecasts,
            "resolved_forecasts": self.resolved_forecasts,
            "forecast_mae_minutes": self.forecast_mae_minutes,
            "restock_dm": {
                "sent": self.restock_dm_sent,
                "retry": self.restock_dm_retry,
                "failed": self.restock_dm_failed,
            },
            "message": self.message,
        }


def _stale_seconds() -> int:
    try:
        return max(900, int(os.getenv("MARKET_STALE_SECONDS", "2700")))
    except (TypeError, ValueError):
        return 2700


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _database_error_status(
    *,
    provider: str,
    stale_seconds: int,
    push_enabled: bool,
) -> MarketHealthStatus:
    return MarketHealthStatus(
        ok=False,
        status="database_error",
        configured=bool(provider),
        database=False,
        provider=provider,
        source_name="",
        latest_source_updated_at=None,
        age_seconds=None,
        item_count=0,
        stale_seconds=stale_seconds,
        web_push_enabled=push_enabled,
        message="market database query failed",
    )


def _restock_health(repository, game_key: str) -> dict[str, int | float | None]:
    metrics: dict[str, int | float | None] = {
        "prediction_count": 0,
        "scheduled_forecasts": 0,
        "resolved_forecasts": 0,
        "forecast_mae_minutes": None,
        "restock_dm_sent": 0,
        "restock_dm_retry": 0,
        "restock_dm_failed": 0,
    }

    try:
        metrics["prediction_count"] = len(
            get_cached_item_restock_predictions(repository, game_key)
        )
    except Exception:
        pass

    try:
        with repository.SessionLocal() as db:
            metrics["scheduled_forecasts"] = int(
                db.scalar(
                    select(func.count(MarketRestockForecast.id)).where(
                        MarketRestockForecast.game_key == game_key,
                        MarketRestockForecast.status == "scheduled",
                    )
                )
                or 0
            )
            metrics["resolved_forecasts"] = int(
                db.scalar(
                    select(func.count(MarketRestockForecast.id)).where(
                        MarketRestockForecast.game_key == game_key,
                        MarketRestockForecast.status == "resolved",
                    )
                )
                or 0
            )
            mae = db.scalar(
                select(func.avg(func.abs(MarketRestockForecast.error_minutes))).where(
                    MarketRestockForecast.game_key == game_key,
                    MarketRestockForecast.status == "resolved",
                    MarketRestockForecast.error_minutes.is_not(None),
                )
            )
            metrics["forecast_mae_minutes"] = round(float(mae), 1) if mae is not None else None

            for status, key in (
                ("sent", "restock_dm_sent"),
                ("retry", "restock_dm_retry"),
                ("failed", "restock_dm_failed"),
            ):
                metrics[key] = int(
                    db.scalar(
                        select(func.count(MarketRestockDelivery.id))
                        .join(
                            MarketRestockForecast,
                            MarketRestockForecast.id == MarketRestockDelivery.forecast_id,
                        )
                        .where(
                            MarketRestockForecast.game_key == game_key,
                            MarketRestockDelivery.status == status,
                        )
                    )
                    or 0
                )
    except Exception:
        # Older databases may not have the V2 restock tables yet. Market price
        # health remains useful and deployment startup will create the tables.
        pass

    return metrics


def check_market_health(
    game_key: str = "delta_force",
    *,
    now: datetime | None = None,
) -> MarketHealthStatus:
    provider = configured_provider_name()
    stale_seconds = _stale_seconds()
    push_enabled = get_web_push_config().enabled

    try:
        repository = get_market_repository()
    except Exception:
        return _database_error_status(
            provider=provider,
            stale_seconds=stale_seconds,
            push_enabled=push_enabled,
        )

    if not provider or repository is None:
        missing = []
        if not provider:
            missing.append("MARKET_PROVIDER")
        if repository is None:
            missing.append("MARKET_DATABASE_URL")
        return MarketHealthStatus(
            ok=False,
            status="unconfigured",
            configured=False,
            database=repository is not None,
            provider=provider,
            source_name="",
            latest_source_updated_at=None,
            age_seconds=None,
            item_count=0,
            stale_seconds=stale_seconds,
            web_push_enabled=push_enabled,
            message=f"missing market configuration: {', '.join(missing)}",
        )

    try:
        latest = tuple(
            item
            for item in repository.list_latest(game_key, limit=500)
            if market_item_enabled(game_key, item.tier)
        )
    except Exception:
        return _database_error_status(
            provider=provider,
            stale_seconds=stale_seconds,
            push_enabled=push_enabled,
        )

    if not latest:
        return MarketHealthStatus(
            ok=False,
            status="no_data",
            configured=True,
            database=True,
            provider=provider,
            source_name="",
            latest_source_updated_at=None,
            age_seconds=None,
            item_count=0,
            stale_seconds=stale_seconds,
            web_push_enabled=push_enabled,
            message="market database has no successful price snapshot",
        )

    latest_at = max(_as_utc(item.source_updated_at) for item in latest)
    current = _as_utc(now or datetime.now(timezone.utc))
    age_seconds = max(0, int((current - latest_at).total_seconds()))
    is_stale = age_seconds > stale_seconds
    restock = _restock_health(repository, game_key)

    return MarketHealthStatus(
        ok=not is_stale,
        status="stale" if is_stale else "ready",
        configured=True,
        database=True,
        provider=provider,
        source_name=latest[0].source_name,
        latest_source_updated_at=latest_at,
        age_seconds=age_seconds,
        item_count=len(latest),
        stale_seconds=stale_seconds,
        web_push_enabled=push_enabled,
        prediction_count=int(restock["prediction_count"] or 0),
        scheduled_forecasts=int(restock["scheduled_forecasts"] or 0),
        resolved_forecasts=int(restock["resolved_forecasts"] or 0),
        forecast_mae_minutes=(
            float(restock["forecast_mae_minutes"])
            if restock["forecast_mae_minutes"] is not None
            else None
        ),
        restock_dm_sent=int(restock["restock_dm_sent"] or 0),
        restock_dm_retry=int(restock["restock_dm_retry"] or 0),
        restock_dm_failed=int(restock["restock_dm_failed"] or 0),
        message=(
            f"latest market snapshot is {age_seconds}s old"
            if is_stale
            else ""
        ),
    )
