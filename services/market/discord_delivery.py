from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import Boolean, DateTime, Integer, String, and_, or_, select
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from services.market.personalization import MarketNotificationOutbox
from services.market.storage import MarketRepository


class MarketDiscordBase(DeclarativeBase):
    pass


class MarketDiscordPreference(MarketDiscordBase):
    __tablename__ = "market_discord_preferences"

    discord_user_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    dm_enabled: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )


class MarketDiscordDelivery(MarketDiscordBase):
    __tablename__ = "market_discord_deliveries"

    outbox_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    status: Mapped[str] = mapped_column(String(24), index=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    available_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        index=True,
    )
    attempted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    error_text: Mapped[str | None] = mapped_column(String(256), nullable=True)


@dataclass(frozen=True)
class DiscordOutboxEvent:
    outbox_id: int
    discord_user_id: str
    game_key: str
    alert_id: int
    item_key: str
    condition_type: str
    target_price: int
    current_price: int
    triggered_at: datetime


def _utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


class MarketDiscordRepository:
    """Discord-specific notification state backed by the isolated Market DB."""

    def __init__(self, market_repository: MarketRepository):
        self.market_repository = market_repository
        self.engine = market_repository.engine
        self.SessionLocal = market_repository.SessionLocal

    def create_all(self) -> None:
        MarketDiscordBase.metadata.create_all(self.engine)

    def dm_enabled(self, discord_user_id: str) -> bool:
        enabled, _enabled_at = self.dm_state(discord_user_id)
        return enabled

    def dm_state(self, discord_user_id: str) -> tuple[bool, datetime | None]:
        user_id = str(discord_user_id or "").strip()
        if not user_id:
            return False, None
        with self.SessionLocal() as db:
            row = db.get(MarketDiscordPreference, user_id)
            if row is None:
                return False, None
            return bool(row.dm_enabled), _utc(row.updated_at)

    def set_dm_enabled(self, discord_user_id: str, enabled: bool) -> bool:
        user_id = str(discord_user_id or "").strip()
        if not user_id:
            raise ValueError("discord user id is required")
        now = datetime.now(timezone.utc)
        with self.SessionLocal() as db:
            row = db.get(MarketDiscordPreference, user_id)
            if row is None:
                row = MarketDiscordPreference(
                    discord_user_id=user_id,
                    dm_enabled=bool(enabled),
                    updated_at=now,
                )
                db.add(row)
            else:
                row.dm_enabled = bool(enabled)
                row.updated_at = now
            db.commit()
        return bool(enabled)

    def list_pending_events(
        self,
        *,
        limit: int = 50,
        now: datetime | None = None,
    ) -> tuple[DiscordOutboxEvent, ...]:
        at = _utc(now or datetime.now(timezone.utc)) or datetime.now(timezone.utc)
        stmt = (
            select(MarketNotificationOutbox, MarketDiscordDelivery)
            .outerjoin(
                MarketDiscordDelivery,
                MarketDiscordDelivery.outbox_id == MarketNotificationOutbox.id,
            )
            .where(
                MarketNotificationOutbox.status != "cancelled",
                or_(
                    MarketDiscordDelivery.outbox_id.is_(None),
                    and_(
                        MarketDiscordDelivery.status == "retry",
                        MarketDiscordDelivery.available_at <= at,
                    ),
                ),
            )
            .order_by(MarketNotificationOutbox.id.asc())
            .limit(max(1, min(int(limit), 200)))
        )
        with self.SessionLocal() as db:
            rows = db.execute(stmt).all()

        events: list[DiscordOutboxEvent] = []
        for outbox, _delivery in rows:
            events.append(
                DiscordOutboxEvent(
                    outbox_id=int(outbox.id),
                    discord_user_id=str(outbox.discord_user_id),
                    game_key=str(outbox.game_key),
                    alert_id=int(outbox.alert_id),
                    item_key=str(outbox.item_key),
                    condition_type=str(outbox.condition_type),
                    target_price=int(outbox.target_price),
                    current_price=int(outbox.current_price),
                    triggered_at=_utc(outbox.triggered_at) or at,
                )
            )
        return tuple(events)

    def mark_sent(self, outbox_id: int) -> None:
        now = datetime.now(timezone.utc)
        self._upsert_delivery(
            outbox_id,
            status="sent",
            attempts=0,
            available_at=now,
            attempted_at=now,
            sent_at=now,
            error_text=None,
        )

    def mark_skipped(self, outbox_id: int, reason: str) -> None:
        now = datetime.now(timezone.utc)
        self._upsert_delivery(
            outbox_id,
            status="skipped",
            attempts=0,
            available_at=now,
            attempted_at=now,
            sent_at=None,
            error_text=str(reason or "discord dm disabled")[:256],
        )

    def mark_unavailable(self, outbox_id: int, reason: str) -> None:
        now = datetime.now(timezone.utc)
        self._upsert_delivery(
            outbox_id,
            status="unavailable",
            attempts=1,
            available_at=now,
            attempted_at=now,
            sent_at=None,
            error_text=str(reason or "discord dm unavailable")[:256],
        )

    def mark_retry(
        self,
        outbox_id: int,
        *,
        reason: str,
        max_attempts: int = 5,
    ) -> None:
        now = datetime.now(timezone.utc)
        with self.SessionLocal() as db:
            row = db.get(MarketDiscordDelivery, int(outbox_id))
            attempts = int(row.attempts or 0) + 1 if row is not None else 1
            final = attempts >= max(1, int(max_attempts))
            delay_seconds = min(3600, 60 * (2 ** max(0, attempts - 1)))
            if row is None:
                row = MarketDiscordDelivery(outbox_id=int(outbox_id))
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
        outbox_id: int,
        *,
        status: str,
        attempts: int,
        available_at: datetime,
        attempted_at: datetime | None,
        sent_at: datetime | None,
        error_text: str | None,
    ) -> None:
        with self.SessionLocal() as db:
            row = db.get(MarketDiscordDelivery, int(outbox_id))
            if row is None:
                row = MarketDiscordDelivery(outbox_id=int(outbox_id))
                db.add(row)
            row.status = str(status)[:24]
            row.attempts = int(attempts)
            row.available_at = available_at
            row.attempted_at = attempted_at
            row.sent_at = sent_at
            row.error_text = error_text
            db.commit()
