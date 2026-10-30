from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, Integer, String, UniqueConstraint, delete, select
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from services.market.storage import MarketRepository


class MarketPersonalizationBase(DeclarativeBase):
    pass


class MarketWatchlist(MarketPersonalizationBase):
    __tablename__ = "market_watchlists"
    __table_args__ = (
        UniqueConstraint(
            "discord_user_id",
            "game_key",
            "item_key",
            name="uq_market_watchlist_user_item",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    discord_user_id: Mapped[str] = mapped_column(String(64), index=True)
    game_key: Mapped[str] = mapped_column(String(64), index=True)
    item_key: Mapped[str] = mapped_column(String(128), index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
    )


class MarketAlert(MarketPersonalizationBase):
    __tablename__ = "market_alerts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    discord_user_id: Mapped[str] = mapped_column(String(64), index=True)
    game_key: Mapped[str] = mapped_column(String(64), index=True)
    item_key: Mapped[str] = mapped_column(String(128), index=True)
    condition_type: Mapped[str] = mapped_column(String(16))
    target_price: Mapped[int] = mapped_column(Integer)
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


class MarketAlertState(MarketPersonalizationBase):
    __tablename__ = "market_alert_states"

    alert_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    condition_met: Mapped[bool] = mapped_column(Boolean, default=False)
    last_price: Mapped[int | None] = mapped_column(Integer, nullable=True)
    last_evaluated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_triggered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


@dataclass(frozen=True)
class StoredWatchlistItem:
    item_key: str
    created_at: datetime


@dataclass(frozen=True)
class StoredMarketAlert:
    id: int
    discord_user_id: str
    game_key: str
    item_key: str
    condition_type: str
    target_price: int
    enabled: bool
    created_at: datetime
    updated_at: datetime
    condition_met: bool = False
    last_price: int | None = None
    last_evaluated_at: datetime | None = None
    last_triggered_at: datetime | None = None


@dataclass(frozen=True)
class MarketAlertTrigger:
    alert_id: int
    discord_user_id: str
    game_key: str
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


def _clean_user_id(value: str) -> str:
    clean = str(value or "").strip()
    if not clean:
        raise ValueError("discord user id is required")
    return clean


def _clean_key(value: str, label: str) -> str:
    clean = str(value or "").strip()
    if not clean:
        raise ValueError(f"{label} is required")
    return clean


def _clean_condition(value: str) -> str:
    clean = str(value or "").strip().lower()
    if clean not in {"below", "above"}:
        raise ValueError("condition_type must be below or above")
    return clean


class MarketPersonalizationRepository:
    """User market preferences stored in the independent Market database.

    User identity is the Discord user id from the existing OAuth session. The
    records intentionally use game_key + item_key rather than a MarketItem DB
    id so provider changes do not destroy a user's watch/alert configuration.
    """

    def __init__(self, market_repository: MarketRepository):
        self.market_repository = market_repository
        self.engine = market_repository.engine
        self.SessionLocal = market_repository.SessionLocal

    def create_all(self) -> None:
        MarketPersonalizationBase.metadata.create_all(self.engine)

    def is_watched(self, discord_user_id: str, game_key: str, item_key: str) -> bool:
        user_id = _clean_user_id(discord_user_id)
        game = _clean_key(game_key, "game key")
        item = _clean_key(item_key, "item key")
        with self.SessionLocal() as db:
            value = db.scalar(
                select(MarketWatchlist.id).where(
                    MarketWatchlist.discord_user_id == user_id,
                    MarketWatchlist.game_key == game,
                    MarketWatchlist.item_key == item,
                )
            )
        return value is not None

    def set_watched(
        self,
        discord_user_id: str,
        game_key: str,
        item_key: str,
        *,
        watched: bool,
    ) -> bool:
        user_id = _clean_user_id(discord_user_id)
        game = _clean_key(game_key, "game key")
        item = _clean_key(item_key, "item key")

        with self.SessionLocal() as db:
            existing = db.scalar(
                select(MarketWatchlist).where(
                    MarketWatchlist.discord_user_id == user_id,
                    MarketWatchlist.game_key == game,
                    MarketWatchlist.item_key == item,
                )
            )
            if watched and existing is None:
                db.add(
                    MarketWatchlist(
                        discord_user_id=user_id,
                        game_key=game,
                        item_key=item,
                    )
                )
            elif not watched and existing is not None:
                db.delete(existing)
            db.commit()
        return watched

    def list_watchlist(
        self,
        discord_user_id: str,
        game_key: str,
    ) -> tuple[StoredWatchlistItem, ...]:
        user_id = _clean_user_id(discord_user_id)
        game = _clean_key(game_key, "game key")
        stmt = (
            select(MarketWatchlist)
            .where(
                MarketWatchlist.discord_user_id == user_id,
                MarketWatchlist.game_key == game,
            )
            .order_by(MarketWatchlist.created_at.desc(), MarketWatchlist.id.desc())
        )
        with self.SessionLocal() as db:
            rows = db.scalars(stmt).all()
        return tuple(
            StoredWatchlistItem(
                item_key=row.item_key,
                created_at=_utc(row.created_at) or datetime.now(timezone.utc),
            )
            for row in rows
        )

    def create_alert(
        self,
        discord_user_id: str,
        game_key: str,
        item_key: str,
        *,
        condition_type: str,
        target_price: int,
    ) -> StoredMarketAlert:
        user_id = _clean_user_id(discord_user_id)
        game = _clean_key(game_key, "game key")
        item = _clean_key(item_key, "item key")
        condition = _clean_condition(condition_type)
        price = int(target_price)
        if price <= 0:
            raise ValueError("target price must be positive")

        now = datetime.now(timezone.utc)
        with self.SessionLocal() as db:
            row = MarketAlert(
                discord_user_id=user_id,
                game_key=game,
                item_key=item,
                condition_type=condition,
                target_price=price,
                enabled=True,
                created_at=now,
                updated_at=now,
            )
            db.add(row)
            db.flush()
            db.add(MarketAlertState(alert_id=row.id, condition_met=False))
            db.commit()
            db.refresh(row)
            return StoredMarketAlert(
                id=row.id,
                discord_user_id=row.discord_user_id,
                game_key=row.game_key,
                item_key=row.item_key,
                condition_type=row.condition_type,
                target_price=row.target_price,
                enabled=row.enabled,
                created_at=_utc(row.created_at) or now,
                updated_at=_utc(row.updated_at) or now,
            )

    def list_alerts(
        self,
        discord_user_id: str,
        game_key: str,
    ) -> tuple[StoredMarketAlert, ...]:
        user_id = _clean_user_id(discord_user_id)
        game = _clean_key(game_key, "game key")
        stmt = (
            select(MarketAlert, MarketAlertState)
            .outerjoin(MarketAlertState, MarketAlertState.alert_id == MarketAlert.id)
            .where(
                MarketAlert.discord_user_id == user_id,
                MarketAlert.game_key == game,
            )
            .order_by(MarketAlert.created_at.desc(), MarketAlert.id.desc())
        )
        with self.SessionLocal() as db:
            rows = db.execute(stmt).all()

        return tuple(self._stored_alert(alert, state) for alert, state in rows)

    def list_enabled_alerts(self, game_key: str) -> tuple[StoredMarketAlert, ...]:
        game = _clean_key(game_key, "game key")
        stmt = (
            select(MarketAlert, MarketAlertState)
            .outerjoin(MarketAlertState, MarketAlertState.alert_id == MarketAlert.id)
            .where(MarketAlert.game_key == game, MarketAlert.enabled.is_(True))
            .order_by(MarketAlert.id.asc())
        )
        with self.SessionLocal() as db:
            rows = db.execute(stmt).all()
        return tuple(self._stored_alert(alert, state) for alert, state in rows)

    def set_alert_enabled(
        self,
        discord_user_id: str,
        alert_id: int,
        *,
        enabled: bool,
    ) -> bool:
        user_id = _clean_user_id(discord_user_id)
        with self.SessionLocal() as db:
            row = db.scalar(
                select(MarketAlert).where(
                    MarketAlert.id == int(alert_id),
                    MarketAlert.discord_user_id == user_id,
                )
            )
            if row is None:
                return False
            row.enabled = bool(enabled)
            row.updated_at = datetime.now(timezone.utc)
            db.commit()
        return True

    def delete_alert(self, discord_user_id: str, alert_id: int) -> bool:
        user_id = _clean_user_id(discord_user_id)
        with self.SessionLocal() as db:
            row = db.scalar(
                select(MarketAlert).where(
                    MarketAlert.id == int(alert_id),
                    MarketAlert.discord_user_id == user_id,
                )
            )
            if row is None:
                return False
            db.execute(delete(MarketAlertState).where(MarketAlertState.alert_id == row.id))
            db.delete(row)
            db.commit()
        return True

    def evaluate_alerts(
        self,
        game_key: str,
        current_prices: dict[str, int],
        *,
        evaluated_at: datetime | None = None,
    ) -> tuple[MarketAlertTrigger, ...]:
        """Evaluate fresh prices and emit only false->true threshold crossings."""
        game = _clean_key(game_key, "game key")
        at = _utc(evaluated_at or datetime.now(timezone.utc)) or datetime.now(timezone.utc)
        triggers: list[MarketAlertTrigger] = []

        with self.SessionLocal() as db:
            rows = db.execute(
                select(MarketAlert, MarketAlertState)
                .outerjoin(MarketAlertState, MarketAlertState.alert_id == MarketAlert.id)
                .where(MarketAlert.game_key == game, MarketAlert.enabled.is_(True))
                .order_by(MarketAlert.id.asc())
            ).all()

            for alert, state in rows:
                price = current_prices.get(alert.item_key)
                if price is None or int(price) <= 0:
                    continue
                price = int(price)
                condition_met = (
                    price <= alert.target_price
                    if alert.condition_type == "below"
                    else price >= alert.target_price
                )
                if state is None:
                    state = MarketAlertState(alert_id=alert.id, condition_met=False)
                    db.add(state)

                previously_met = bool(state.condition_met)
                state.condition_met = condition_met
                state.last_price = price
                state.last_evaluated_at = at

                if condition_met and not previously_met:
                    state.last_triggered_at = at
                    triggers.append(
                        MarketAlertTrigger(
                            alert_id=alert.id,
                            discord_user_id=alert.discord_user_id,
                            game_key=alert.game_key,
                            item_key=alert.item_key,
                            condition_type=alert.condition_type,
                            target_price=alert.target_price,
                            current_price=price,
                            triggered_at=at,
                        )
                    )

            db.commit()

        return tuple(triggers)

    @staticmethod
    def _stored_alert(alert: MarketAlert, state: MarketAlertState | None) -> StoredMarketAlert:
        created = _utc(alert.created_at) or datetime.now(timezone.utc)
        updated = _utc(alert.updated_at) or created
        return StoredMarketAlert(
            id=alert.id,
            discord_user_id=alert.discord_user_id,
            game_key=alert.game_key,
            item_key=alert.item_key,
            condition_type=alert.condition_type,
            target_price=alert.target_price,
            enabled=bool(alert.enabled),
            created_at=created,
            updated_at=updated,
            condition_met=bool(state.condition_met) if state is not None else False,
            last_price=(state.last_price if state is not None else None),
            last_evaluated_at=(_utc(state.last_evaluated_at) if state is not None else None),
            last_triggered_at=(_utc(state.last_triggered_at) if state is not None else None),
        )
