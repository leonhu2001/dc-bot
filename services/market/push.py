from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from urllib.parse import urlsplit

from sqlalchemy import Boolean, DateTime, Integer, String, Text, select
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from services.market.personalization import MarketNotificationOutbox
from services.market.storage import MarketRepository


class MarketPushBase(DeclarativeBase):
    pass


class MarketPushSubscription(MarketPushBase):
    __tablename__ = "market_push_subscriptions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    discord_user_id: Mapped[str] = mapped_column(String(64), index=True)
    endpoint_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    endpoint: Mapped[str] = mapped_column(Text)
    p256dh: Mapped[str] = mapped_column(String(512))
    auth: Mapped[str] = mapped_column(String(256))
    user_agent: Mapped[str] = mapped_column(String(512), default="")
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )
    last_success_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    disabled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    disabled_reason: Mapped[str | None] = mapped_column(String(160), nullable=True)


class MarketPushDelivery(MarketPushBase):
    __tablename__ = "market_notification_deliveries"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    outbox_id: Mapped[int] = mapped_column(Integer, index=True)
    subscription_id: Mapped[int] = mapped_column(Integer, index=True)
    status: Mapped[str] = mapped_column(String(24), index=True)
    response_status: Mapped[int | None] = mapped_column(Integer, nullable=True)
    error_text: Mapped[str | None] = mapped_column(String(512), nullable=True)
    attempted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        index=True,
    )


@dataclass(frozen=True)
class StoredPushSubscription:
    id: int
    discord_user_id: str
    endpoint: str
    p256dh: str
    auth: str


@dataclass(frozen=True)
class StoredOutboxEvent:
    id: int
    discord_user_id: str
    game_key: str
    alert_id: int
    item_key: str
    condition_type: str
    target_price: int
    current_price: int
    triggered_at: datetime
    attempts: int


def _utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _endpoint_hash(endpoint: str) -> str:
    return hashlib.sha256(endpoint.encode("utf-8")).hexdigest()


def _validate_subscription(endpoint: str, p256dh: str, auth: str) -> tuple[str, str, str]:
    clean_endpoint = str(endpoint or "").strip()
    clean_p256dh = str(p256dh or "").strip()
    clean_auth = str(auth or "").strip()
    parsed = urlsplit(clean_endpoint)
    if parsed.scheme != "https" or not parsed.netloc:
        raise ValueError("push endpoint must be https")
    if len(clean_endpoint) > 4096:
        raise ValueError("push endpoint is too long")
    if not clean_p256dh or len(clean_p256dh) > 512:
        raise ValueError("invalid p256dh key")
    if not clean_auth or len(clean_auth) > 256:
        raise ValueError("invalid auth key")
    return clean_endpoint, clean_p256dh, clean_auth


class MarketPushRepository:
    def __init__(self, market_repository: MarketRepository):
        self.market_repository = market_repository
        self.engine = market_repository.engine
        self.SessionLocal = market_repository.SessionLocal

    def create_all(self) -> None:
        MarketPushBase.metadata.create_all(self.engine)

    def upsert_subscription(
        self,
        discord_user_id: str,
        *,
        endpoint: str,
        p256dh: str,
        auth: str,
        user_agent: str = "",
    ) -> StoredPushSubscription:
        user_id = str(discord_user_id or "").strip()
        if not user_id:
            raise ValueError("discord user id is required")
        endpoint, p256dh, auth = _validate_subscription(endpoint, p256dh, auth)
        now = datetime.now(timezone.utc)
        digest = _endpoint_hash(endpoint)

        with self.SessionLocal() as db:
            row = db.scalar(
                select(MarketPushSubscription).where(
                    MarketPushSubscription.endpoint_hash == digest
                )
            )
            if row is None:
                row = MarketPushSubscription(
                    discord_user_id=user_id,
                    endpoint_hash=digest,
                    endpoint=endpoint,
                    p256dh=p256dh,
                    auth=auth,
                    user_agent=str(user_agent or "")[:512],
                    enabled=True,
                    created_at=now,
                    updated_at=now,
                )
                db.add(row)
                db.flush()
            else:
                row.discord_user_id = user_id
                row.endpoint = endpoint
                row.p256dh = p256dh
                row.auth = auth
                row.user_agent = str(user_agent or "")[:512]
                row.enabled = True
                row.disabled_at = None
                row.disabled_reason = None
                row.updated_at = now
            db.commit()
            db.refresh(row)
            return self._stored_subscription(row)

    def unsubscribe(self, discord_user_id: str, endpoint: str) -> bool:
        user_id = str(discord_user_id or "").strip()
        clean_endpoint = str(endpoint or "").strip()
        if not user_id or not clean_endpoint:
            return False
        digest = _endpoint_hash(clean_endpoint)
        now = datetime.now(timezone.utc)
        with self.SessionLocal() as db:
            row = db.scalar(
                select(MarketPushSubscription).where(
                    MarketPushSubscription.endpoint_hash == digest,
                    MarketPushSubscription.discord_user_id == user_id,
                )
            )
            if row is None:
                return False
            row.enabled = False
            row.disabled_at = now
            row.disabled_reason = "user unsubscribed"
            row.updated_at = now
            db.commit()
        return True

    def disable_subscription(self, subscription_id: int, reason: str) -> None:
        now = datetime.now(timezone.utc)
        with self.SessionLocal() as db:
            row = db.get(MarketPushSubscription, int(subscription_id))
            if row is None:
                return
            row.enabled = False
            row.disabled_at = now
            row.disabled_reason = str(reason or "push endpoint invalid")[:160]
            row.updated_at = now
            db.commit()

    def mark_subscription_success(self, subscription_id: int) -> None:
        now = datetime.now(timezone.utc)
        with self.SessionLocal() as db:
            row = db.get(MarketPushSubscription, int(subscription_id))
            if row is None:
                return
            row.last_success_at = now
            row.updated_at = now
            db.commit()

    def list_active_subscriptions(self, discord_user_id: str) -> tuple[StoredPushSubscription, ...]:
        user_id = str(discord_user_id or "").strip()
        if not user_id:
            return ()
        stmt = (
            select(MarketPushSubscription)
            .where(
                MarketPushSubscription.discord_user_id == user_id,
                MarketPushSubscription.enabled.is_(True),
            )
            .order_by(MarketPushSubscription.id.asc())
        )
        with self.SessionLocal() as db:
            rows = db.scalars(stmt).all()
        return tuple(self._stored_subscription(row) for row in rows)

    def list_pending_outbox(
        self,
        *,
        limit: int = 50,
        now: datetime | None = None,
    ) -> tuple[StoredOutboxEvent, ...]:
        at = _utc(now or datetime.now(timezone.utc)) or datetime.now(timezone.utc)
        stmt = (
            select(MarketNotificationOutbox)
            .where(
                MarketNotificationOutbox.status == "pending",
                MarketNotificationOutbox.available_at <= at,
            )
            .order_by(MarketNotificationOutbox.id.asc())
            .limit(max(1, min(int(limit), 200)))
        )
        with self.SessionLocal() as db:
            rows = db.scalars(stmt).all()
        return tuple(
            StoredOutboxEvent(
                id=row.id,
                discord_user_id=row.discord_user_id,
                game_key=row.game_key,
                alert_id=row.alert_id,
                item_key=row.item_key,
                condition_type=row.condition_type,
                target_price=row.target_price,
                current_price=row.current_price,
                triggered_at=_utc(row.triggered_at) or at,
                attempts=row.attempts,
            )
            for row in rows
        )

    def successful_subscription_ids(self, outbox_id: int) -> set[int]:
        stmt = select(MarketPushDelivery.subscription_id).where(
            MarketPushDelivery.outbox_id == int(outbox_id),
            MarketPushDelivery.status == "success",
        )
        with self.SessionLocal() as db:
            return {int(value) for value in db.scalars(stmt).all()}

    def record_delivery(
        self,
        *,
        outbox_id: int,
        subscription_id: int,
        status: str,
        response_status: int | None = None,
        error_text: str | None = None,
    ) -> None:
        with self.SessionLocal() as db:
            db.add(
                MarketPushDelivery(
                    outbox_id=int(outbox_id),
                    subscription_id=int(subscription_id),
                    status=str(status or "unknown")[:24],
                    response_status=response_status,
                    error_text=(str(error_text)[:512] if error_text else None),
                    attempted_at=datetime.now(timezone.utc),
                )
            )
            db.commit()

    def mark_outbox_sent(self, outbox_id: int) -> None:
        now = datetime.now(timezone.utc)
        with self.SessionLocal() as db:
            row = db.get(MarketNotificationOutbox, int(outbox_id))
            if row is None:
                return
            row.status = "sent"
            row.sent_at = now
            row.last_error = None
            db.commit()

    def mark_outbox_no_subscription(self, outbox_id: int) -> None:
        with self.SessionLocal() as db:
            row = db.get(MarketNotificationOutbox, int(outbox_id))
            if row is None:
                return
            row.status = "no_subscription"
            row.last_error = "no active push subscription"
            db.commit()

    def mark_outbox_retry(
        self,
        outbox_id: int,
        *,
        error_text: str,
        max_attempts: int = 5,
    ) -> None:
        now = datetime.now(timezone.utc)
        with self.SessionLocal() as db:
            row = db.get(MarketNotificationOutbox, int(outbox_id))
            if row is None:
                return
            row.attempts = int(row.attempts or 0) + 1
            row.last_error = str(error_text or "push delivery failed")[:512]
            if row.attempts >= max(1, int(max_attempts)):
                row.status = "failed"
            else:
                delay_seconds = min(3600, 60 * (2 ** max(0, row.attempts - 1)))
                row.available_at = now + timedelta(seconds=delay_seconds)
                row.status = "pending"
            db.commit()

    @staticmethod
    def _stored_subscription(row: MarketPushSubscription) -> StoredPushSubscription:
        return StoredPushSubscription(
            id=row.id,
            discord_user_id=row.discord_user_id,
            endpoint=row.endpoint,
            p256dh=row.p256dh,
            auth=row.auth,
        )
