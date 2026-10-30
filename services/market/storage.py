from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import DateTime, Integer, String, UniqueConstraint, create_engine, func, select
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker

from services.market.providers.base import MarketSourceSnapshot, normalize_source_snapshot


class MarketBase(DeclarativeBase):
    pass


class MarketItem(MarketBase):
    __tablename__ = "market_items"
    __table_args__ = (
        UniqueConstraint(
            "game_key",
            "source_name",
            "source_item_id",
            name="uq_market_item_source",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    game_key: Mapped[str] = mapped_column(String(64), index=True)
    source_name: Mapped[str] = mapped_column(String(128), index=True)
    source_item_id: Mapped[str] = mapped_column(String(128))
    name: Mapped[str] = mapped_column(String(255), index=True)
    category: Mapped[str] = mapped_column(String(64), default="")
    tier: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )


class MarketPrice(MarketBase):
    __tablename__ = "market_prices"
    __table_args__ = (
        UniqueConstraint(
            "item_id",
            "source_updated_at",
            name="uq_market_price_source_time",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    item_id: Mapped[int] = mapped_column(Integer, index=True)
    price: Mapped[int] = mapped_column(Integer)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    source_updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)


class MarketSourceRun(MarketBase):
    __tablename__ = "market_source_runs"
    __table_args__ = (
        UniqueConstraint(
            "source_name",
            "game_key",
            "source_updated_at",
            name="uq_market_source_run",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    source_name: Mapped[str] = mapped_column(String(128), index=True)
    game_key: Mapped[str] = mapped_column(String(64), index=True)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    source_updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    item_count: Mapped[int] = mapped_column(Integer, default=0)


@dataclass(frozen=True)
class StoredMarketItem:
    item_id: int
    source_name: str
    source_item_id: str
    name: str
    category: str
    tier: int | None
    current_price: int
    source_updated_at: datetime


@dataclass(frozen=True)
class StoredMarketPoint:
    source_updated_at: datetime
    price: int


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


class MarketRepository:
    """Independent persistence layer for game market history.

    Production should use a dedicated PostgreSQL database through
    MARKET_DATABASE_URL. This layer never touches the existing order/business
    database. SQLite remains supported for local tests only.
    """

    def __init__(self, database_url: str):
        clean_url = str(database_url or "").strip()
        if not clean_url:
            raise ValueError("market database url is required")

        connect_args = {}
        if clean_url.startswith("sqlite"):
            connect_args = {"check_same_thread": False}

        self.engine = create_engine(
            clean_url,
            pool_pre_ping=True,
            future=True,
            connect_args=connect_args,
        )
        self.SessionLocal = sessionmaker(
            bind=self.engine,
            expire_on_commit=False,
            future=True,
        )

    def create_all(self) -> None:
        MarketBase.metadata.create_all(self.engine)

    def store_snapshot(self, snapshot: MarketSourceSnapshot) -> int:
        normalized = normalize_source_snapshot(snapshot)
        source_time = normalized.source_updated_at or normalized.fetched_at
        inserted_prices = 0

        with self.SessionLocal() as db:
            existing_run = db.scalar(
                select(MarketSourceRun.id).where(
                    MarketSourceRun.source_name == normalized.source_name,
                    MarketSourceRun.game_key == normalized.game_key,
                    MarketSourceRun.source_updated_at == source_time,
                )
            )
            if existing_run is not None:
                return 0

            for source_item in normalized.items:
                item = db.scalar(
                    select(MarketItem).where(
                        MarketItem.game_key == normalized.game_key,
                        MarketItem.source_name == normalized.source_name,
                        MarketItem.source_item_id == source_item.source_item_id,
                    )
                )

                if item is None:
                    item = MarketItem(
                        game_key=normalized.game_key,
                        source_name=normalized.source_name,
                        source_item_id=source_item.source_item_id,
                        name=source_item.name,
                        category=source_item.category,
                        tier=source_item.tier,
                    )
                    db.add(item)
                    db.flush()
                else:
                    item.name = source_item.name
                    item.category = source_item.category
                    item.tier = source_item.tier

                db.add(
                    MarketPrice(
                        item_id=item.id,
                        price=source_item.price,
                        fetched_at=normalized.fetched_at,
                        source_updated_at=source_time,
                    )
                )
                inserted_prices += 1

            db.add(
                MarketSourceRun(
                    source_name=normalized.source_name,
                    game_key=normalized.game_key,
                    fetched_at=normalized.fetched_at,
                    source_updated_at=source_time,
                    item_count=inserted_prices,
                )
            )
            db.commit()

        return inserted_prices

    def latest_source_name(self, game_key: str) -> str | None:
        clean_game_key = str(game_key or "").strip()
        if not clean_game_key:
            return None

        stmt = (
            select(MarketSourceRun.source_name)
            .where(MarketSourceRun.game_key == clean_game_key)
            .order_by(
                MarketSourceRun.source_updated_at.desc(),
                MarketSourceRun.id.desc(),
            )
            .limit(1)
        )
        with self.SessionLocal() as db:
            value = db.scalar(stmt)
        return str(value).strip() if value else None

    def list_latest(
        self,
        game_key: str,
        *,
        source_name: str | None = None,
        limit: int = 200,
    ) -> tuple[StoredMarketItem, ...]:
        clean_game_key = str(game_key or "").strip()
        if not clean_game_key:
            return ()

        clean_source_name = str(source_name or "").strip() or self.latest_source_name(clean_game_key)
        if not clean_source_name:
            return ()

        latest_price = (
            select(
                MarketPrice.item_id,
                func.max(MarketPrice.source_updated_at).label("max_source_updated_at"),
            )
            .group_by(MarketPrice.item_id)
            .subquery()
        )

        stmt = (
            select(MarketItem, MarketPrice)
            .join(latest_price, latest_price.c.item_id == MarketItem.id)
            .join(
                MarketPrice,
                (MarketPrice.item_id == latest_price.c.item_id)
                & (MarketPrice.source_updated_at == latest_price.c.max_source_updated_at),
            )
            .where(
                MarketItem.game_key == clean_game_key,
                MarketItem.source_name == clean_source_name,
            )
            .order_by(
                MarketItem.tier.is_(None),
                MarketItem.tier.desc(),
                MarketItem.name.asc(),
            )
            .limit(max(1, min(int(limit), 500)))
        )

        with self.SessionLocal() as db:
            rows = db.execute(stmt).all()

        return tuple(
            StoredMarketItem(
                item_id=item.id,
                source_name=item.source_name,
                source_item_id=item.source_item_id,
                name=item.name,
                category=item.category,
                tier=item.tier,
                current_price=price.price,
                source_updated_at=_as_utc(price.source_updated_at),
            )
            for item, price in rows
        )

    def get_item(
        self,
        game_key: str,
        source_item_id: str,
        *,
        source_name: str | None = None,
    ) -> MarketItem | None:
        clean_game_key = str(game_key or "").strip()
        clean_source_item_id = str(source_item_id or "").strip()
        if not clean_game_key or not clean_source_item_id:
            return None

        clean_source_name = str(source_name or "").strip() or self.latest_source_name(clean_game_key)
        if not clean_source_name:
            return None

        with self.SessionLocal() as db:
            item = db.scalar(
                select(MarketItem).where(
                    MarketItem.game_key == clean_game_key,
                    MarketItem.source_name == clean_source_name,
                    MarketItem.source_item_id == clean_source_item_id,
                )
            )
            if item is None:
                return None
            db.expunge(item)
            return item

    def history(
        self,
        item_id: int,
        *,
        limit: int = 500,
    ) -> tuple[StoredMarketPoint, ...]:
        stmt = (
            select(MarketPrice.source_updated_at, MarketPrice.price)
            .where(MarketPrice.item_id == int(item_id))
            .order_by(MarketPrice.source_updated_at.desc())
            .limit(max(1, min(int(limit), 2000)))
        )
        with self.SessionLocal() as db:
            rows = db.execute(stmt).all()

        points = tuple(
            StoredMarketPoint(
                source_updated_at=_as_utc(when),
                price=price,
            )
            for when, price in rows
        )
        return tuple(reversed(points))
