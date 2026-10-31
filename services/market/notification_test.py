from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from services.market.personalization import (
    MarketAlert,
    MarketNotificationOutbox,
    MarketPersonalizationRepository,
)
from services.market.storage import MarketRepository


TEST_CONDITION_PREFIX = "test_"
TEST_NOTIFICATION_COOLDOWN_SECONDS = 15


@dataclass(frozen=True)
class MarketTestNotification:
    outbox_id: int
    alert_id: int
    discord_user_id: str
    game_key: str
    item_key: str
    condition_type: str
    target_price: int
    current_price: int
    triggered_at: datetime


def split_notification_condition(condition_type: str) -> tuple[str, bool]:
    clean = str(condition_type or "").strip().lower()
    is_test = clean.startswith(TEST_CONDITION_PREFIX)
    base = clean[len(TEST_CONDITION_PREFIX) :] if is_test else clean
    if base not in {"below", "above"}:
        base = "above"
    return base, is_test


def enqueue_market_test_notification(
    *,
    market_repository: MarketRepository,
    personalization_repository: MarketPersonalizationRepository,
    discord_user_id: str,
    alert_id: int,
    triggered_at: datetime | None = None,
) -> MarketTestNotification:
    user_id = str(discord_user_id or "").strip()
    if not user_id:
        raise ValueError("discord user id is required")

    at = triggered_at or datetime.now(timezone.utc)
    if at.tzinfo is None:
        at = at.replace(tzinfo=timezone.utc)
    else:
        at = at.astimezone(timezone.utc)

    with personalization_repository.SessionLocal() as db:
        alert = db.scalar(
            select(MarketAlert).where(
                MarketAlert.id == int(alert_id),
                MarketAlert.discord_user_id == user_id,
            )
        )
        if alert is None:
            raise ValueError("alert not found")
        if not alert.enabled:
            raise ValueError("alert is paused")

        latest_test = db.scalar(
            select(MarketNotificationOutbox)
            .where(
                MarketNotificationOutbox.alert_id == alert.id,
                MarketNotificationOutbox.discord_user_id == user_id,
                MarketNotificationOutbox.condition_type.in_(
                    ("test_below", "test_above")
                ),
            )
            .order_by(
                MarketNotificationOutbox.triggered_at.desc(),
                MarketNotificationOutbox.id.desc(),
            )
            .limit(1)
        )
        if latest_test is not None:
            previous = latest_test.triggered_at
            if previous.tzinfo is None:
                previous = previous.replace(tzinfo=timezone.utc)
            else:
                previous = previous.astimezone(timezone.utc)
            if at - previous < timedelta(seconds=TEST_NOTIFICATION_COOLDOWN_SECONDS):
                raise ValueError("test notification cooldown")

        game_key = str(alert.game_key)
        item_key = str(alert.item_key)
        condition_type = str(alert.condition_type)
        target_price = int(alert.target_price)

    latest_items = market_repository.list_latest(game_key, limit=500)
    item = next(
        (row for row in latest_items if str(row.source_item_id) == item_key),
        None,
    )
    if item is None:
        raise ValueError("market item unavailable")

    test_condition = f"{TEST_CONDITION_PREFIX}{condition_type}"
    with personalization_repository.SessionLocal() as db:
        row = MarketNotificationOutbox(
            discord_user_id=user_id,
            game_key=game_key,
            alert_id=int(alert_id),
            item_key=item_key,
            condition_type=test_condition,
            target_price=target_price,
            current_price=int(item.current_price),
            triggered_at=at,
            status="pending",
            attempts=0,
            available_at=at,
        )
        db.add(row)
        db.commit()
        db.refresh(row)

        outbox_id = int(row.id)

    return MarketTestNotification(
        outbox_id=outbox_id,
        alert_id=int(alert_id),
        discord_user_id=user_id,
        game_key=game_key,
        item_key=item_key,
        condition_type=test_condition,
        target_price=target_price,
        current_price=int(item.current_price),
        triggered_at=at,
    )
