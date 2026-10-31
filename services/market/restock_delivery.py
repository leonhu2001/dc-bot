from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import DateTime, Integer, String, UniqueConstraint, and_, or_, select, update
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from services.market.discord_delivery import MarketDiscordPreference
from services.market.personalization import MarketWatchlist
from services.market.restock_prediction import ItemRestockPrediction
from services.market.storage import MarketRepository


class MarketRestockBase(DeclarativeBase):
    pass


class MarketRestockForecast(MarketRestockBase):
    __tablename__ = "market_restock_forecasts"
    __table_args__ = (
        UniqueConstraint(
            "game_key",
            "item_key",
            "predicted_at",
            name="uq_market_restock_forecast_item_time",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    game_key: Mapped[str] = mapped_column(String(64), index=True)
    item_key: Mapped[str] = mapped_column(String(128), index=True)
    predicted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    generated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    confidence: Mapped[int] = mapped_column(Integer)
    event_count: Mapped[int] = mapped_column(Integer)
    interval_minutes: Mapped[int] = mapped_column(Integer)
    jitter_minutes: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(24), default="scheduled", index=True)
    actual_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    error_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)


class MarketRestockDelivery(MarketRestockBase):
    __tablename__ = "market_restock_deliveries"
    __table_args__ = (
        UniqueConstraint(
            "forecast_id",
            "discord_user_id",
            name="uq_market_restock_delivery_user_forecast",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    forecast_id: Mapped[int] = mapped_column(Integer, index=True)
    discord_user_id: Mapped[str] = mapped_column(String(64), index=True)
    status: Mapped[str] = mapped_column(String(24), default="pending", index=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    available_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    attempted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    error_text: Mapped[str | None] = mapped_column(String(256), nullable=True)


@dataclass(frozen=True)
class DueRestockDelivery:
    forecast_id: int
    discord_user_id: str
    game_key: str
    item_key: str
    predicted_at: datetime
    confidence: int
    event_count: int
    jitter_minutes: int


def _utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


class MarketRestockRepository:
    def __init__(self, market_repository: MarketRepository):
        self.market_repository = market_repository
        self.engine = market_repository.engine
        self.SessionLocal = market_repository.SessionLocal

    def create_all(self) -> None:
        MarketRestockBase.metadata.create_all(self.engine)

    def sync_predictions(
        self,
        game_key: str,
        predictions: tuple[ItemRestockPrediction, ...],
        *,
        now: datetime | None = None,
    ) -> None:
        game = str(game_key or "").strip()
        if not game:
            return
        at = _utc(now or datetime.now(timezone.utc)) or datetime.now(timezone.utc)

        with self.SessionLocal() as db:
            db.execute(
                update(MarketRestockForecast)
                .where(
                    MarketRestockForecast.game_key == game,
                    MarketRestockForecast.status == "scheduled",
                    MarketRestockForecast.predicted_at < at - timedelta(hours=2),
                )
                .values(status="expired")
            )

            for prediction in predictions:
                predicted_at = _utc(prediction.predicted_at) or at
                last_event_at = _utc(prediction.last_event_at) or at

                candidates = db.scalars(
                    select(MarketRestockForecast).where(
                        MarketRestockForecast.game_key == game,
                        MarketRestockForecast.item_key == prediction.item_key,
                        MarketRestockForecast.status == "scheduled",
                        MarketRestockForecast.generated_at < last_event_at,
                        MarketRestockForecast.predicted_at >= last_event_at - timedelta(hours=3),
                        MarketRestockForecast.predicted_at <= last_event_at + timedelta(hours=3),
                    )
                ).all()
                if candidates:
                    resolved = min(
                        candidates,
                        key=lambda row: abs(((_utc(row.predicted_at) or at) - last_event_at).total_seconds()),
                    )
                    resolved.status = "resolved"
                    resolved.actual_at = last_event_at
                    resolved.error_minutes = round(
                        (last_event_at - (_utc(resolved.predicted_at) or last_event_at)).total_seconds()
                        / 60.0
                    )

                nearby = db.scalar(
                    select(MarketRestockForecast)
                    .where(
                        MarketRestockForecast.game_key == game,
                        MarketRestockForecast.item_key == prediction.item_key,
                        MarketRestockForecast.status == "scheduled",
                        MarketRestockForecast.predicted_at >= predicted_at - timedelta(minutes=30),
                        MarketRestockForecast.predicted_at <= predicted_at + timedelta(minutes=30),
                    )
                    .order_by(MarketRestockForecast.id.desc())
                    .limit(1)
                )
                if nearby is not None:
                    nearby.predicted_at = predicted_at
                    nearby.generated_at = at
                    nearby.confidence = int(prediction.confidence)
                    nearby.event_count = int(prediction.event_count)
                    nearby.interval_minutes = int(prediction.median_interval_minutes)
                    nearby.jitter_minutes = int(prediction.jitter_minutes)
                    continue

                db.execute(
                    update(MarketRestockForecast)
                    .where(
                        MarketRestockForecast.game_key == game,
                        MarketRestockForecast.item_key == prediction.item_key,
                        MarketRestockForecast.status == "scheduled",
                        MarketRestockForecast.predicted_at > at,
                    )
                    .values(status="superseded")
                )
                db.add(
                    MarketRestockForecast(
                        game_key=game,
                        item_key=prediction.item_key,
                        predicted_at=predicted_at,
                        generated_at=at,
                        confidence=int(prediction.confidence),
                        event_count=int(prediction.event_count),
                        interval_minutes=int(prediction.median_interval_minutes),
                        jitter_minutes=int(prediction.jitter_minutes),
                        status="scheduled",
                    )
                )
            db.commit()

    def list_due_deliveries(
        self,
        game_key: str,
        *,
        now: datetime | None = None,
        lead_minutes: int = 15,
        grace_minutes: int = 10,
        min_confidence: int = 65,
        limit: int = 100,
    ) -> tuple[DueRestockDelivery, ...]:
        game = str(game_key or "").strip()
        if not game:
            return ()
        at = _utc(now or datetime.now(timezone.utc)) or datetime.now(timezone.utc)
        lead = max(1, min(int(lead_minutes), 120))
        grace = max(0, min(int(grace_minutes), 60))

        stmt = (
            select(MarketRestockForecast, MarketWatchlist, MarketRestockDelivery)
            .join(
                MarketWatchlist,
                and_(
                    MarketWatchlist.game_key == MarketRestockForecast.game_key,
                    MarketWatchlist.item_key == MarketRestockForecast.item_key,
                ),
            )
            .join(
                MarketDiscordPreference,
                MarketDiscordPreference.discord_user_id == MarketWatchlist.discord_user_id,
            )
            .outerjoin(
                MarketRestockDelivery,
                and_(
                    MarketRestockDelivery.forecast_id == MarketRestockForecast.id,
                    MarketRestockDelivery.discord_user_id == MarketWatchlist.discord_user_id,
                ),
            )
            .where(
                MarketRestockForecast.game_key == game,
                MarketRestockForecast.status == "scheduled",
                MarketRestockForecast.confidence >= max(0, min(int(min_confidence), 100)),
                MarketRestockForecast.predicted_at <= at + timedelta(minutes=lead),
                MarketRestockForecast.predicted_at >= at - timedelta(minutes=grace),
                MarketDiscordPreference.dm_enabled.is_(True),
                or_(
                    MarketRestockDelivery.id.is_(None),
                    and_(
                        MarketRestockDelivery.status == "retry",
                        MarketRestockDelivery.available_at <= at,
                    ),
                ),
            )
            .order_by(MarketRestockForecast.predicted_at.asc(), MarketWatchlist.id.asc())
            .limit(max(1, min(int(limit), 500)))
        )
        with self.SessionLocal() as db:
            rows = db.execute(stmt).all()

        return tuple(
            DueRestockDelivery(
                forecast_id=int(forecast.id),
                discord_user_id=str(watch.discord_user_id),
                game_key=str(forecast.game_key),
                item_key=str(forecast.item_key),
                predicted_at=_utc(forecast.predicted_at) or at,
                confidence=int(forecast.confidence),
                event_count=int(forecast.event_count),
                jitter_minutes=int(forecast.jitter_minutes),
            )
            for forecast, watch, _delivery in rows
        )

    def mark_sent(self, forecast_id: int, discord_user_id: str) -> None:
        now = datetime.now(timezone.utc)
        self._upsert_delivery(
            forecast_id,
            discord_user_id,
            status="sent",
            attempts=0,
            available_at=now,
            attempted_at=now,
            sent_at=now,
            error_text=None,
        )

    def mark_unavailable(self, forecast_id: int, discord_user_id: str, reason: str) -> None:
        now = datetime.now(timezone.utc)
        self._upsert_delivery(
            forecast_id,
            discord_user_id,
            status="unavailable",
            attempts=1,
            available_at=now,
            attempted_at=now,
            sent_at=None,
            error_text=str(reason or "discord dm unavailable")[:256],
        )

    def mark_retry(
        self,
        forecast_id: int,
        discord_user_id: str,
        *,
        reason: str,
        max_attempts: int = 5,
    ) -> None:
        now = datetime.now(timezone.utc)
        with self.SessionLocal() as db:
            row = db.scalar(
                select(MarketRestockDelivery).where(
                    MarketRestockDelivery.forecast_id == int(forecast_id),
                    MarketRestockDelivery.discord_user_id == str(discord_user_id),
                )
            )
            attempts = int(row.attempts or 0) + 1 if row is not None else 1
            final = attempts >= max(1, int(max_attempts))
            delay_seconds = min(3600, 60 * (2 ** max(0, attempts - 1)))
            if row is None:
                row = MarketRestockDelivery(
                    forecast_id=int(forecast_id),
                    discord_user_id=str(discord_user_id),
                    available_at=now,
                )
                db.add(row)
            row.status = "failed" if final else "retry"
            row.attempts = attempts
            row.available_at = now if final else now + timedelta(seconds=delay_seconds)
            row.attempted_at = now
            row.sent_at = None
            row.error_text = str(reason or "discord dm failed")[:256]
            db.commit()

    def _upsert_delivery(
        self,
        forecast_id: int,
        discord_user_id: str,
        *,
        status: str,
        attempts: int,
        available_at: datetime,
        attempted_at: datetime | None,
        sent_at: datetime | None,
        error_text: str | None,
    ) -> None:
        user_id = str(discord_user_id or "").strip()
        with self.SessionLocal() as db:
            row = db.scalar(
                select(MarketRestockDelivery).where(
                    MarketRestockDelivery.forecast_id == int(forecast_id),
                    MarketRestockDelivery.discord_user_id == user_id,
                )
            )
            if row is None:
                row = MarketRestockDelivery(
                    forecast_id=int(forecast_id),
                    discord_user_id=user_id,
                    available_at=available_at,
                )
                db.add(row)
            row.status = str(status)[:24]
            row.attempts = int(attempts)
            row.available_at = available_at
            row.attempted_at = attempted_at
            row.sent_at = sent_at
            row.error_text = error_text
            db.commit()
