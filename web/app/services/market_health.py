from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime, timezone

from services.market.provider_registry import configured_provider_name
from services.market.push_dispatcher import get_web_push_config
from services.market.runtime import get_market_repository


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
        latest = repository.list_latest(game_key, limit=500)
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
        message=(
            f"latest market snapshot is {age_seconds}s old"
            if is_stale
            else ""
        ),
    )
