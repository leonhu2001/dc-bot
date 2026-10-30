from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Iterable

from sqlalchemy import BigInteger, DateTime, Integer, String, UniqueConstraint, create_engine, func, select
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker

from services.market.providers.base import MarketSourceSnapshot, normalize_source_snapshot


class MarketBase(DeclarativeBase):
    pass


class MarketItem(MarketBase):
    __tablename__ = "market_items"
    __table_args__ = (
        UniqueConstraint("game_key", "source_name", "source_item_id", name="uq_market_item_source"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    game_key: Mapped[str] = mapped_column(String(64), index=True)
    source_name: Mapped[str] = mapped_column(String(128), index=True)
    source_item_id: Mapped[str] = mapped_column(String(128))
    name: Mapped[str] = mapped_column(String(255), index=True)
    category: Mapped[str] = mapped_column(String(64), default="")
    tier: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )


class MarketPrice(MarketBase):
    __tablename__ = "market_prices"
    __table_args__ = (
        UniqueConstraint("item_id", "source_updated_at", name="uq_market_price_source_time"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    item_id: Mapped[int] = mapped_column(Integer, index=True)
    price: Mapped[int] = mapped_column(Integer)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    source_updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)


@dataclass(frozen=True)
class StoredMarketItem:
    item_id: int
    source_item_id: str
    name: str
    category: str
    tier: int | None
    current_price: int
    source_updated_at: datetime


class MarketRepository:
    """Independent persistence layer for game market data.

    Production should point this at a dedicated PostgreSQL database through
    MARKET_DATABASE_URL. Tests may use SQLite. The existing order/business
    database is intentionally not touched.
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
        self.SessionLocal = sessionmaker(bind=self.engine, expire_on_commit=False, future=True)

    def create_all(self) -> None:
        MarketBase.metadata.create_all(self.engine)

    def store_snapshot(self, snapshot: MarketSourceSnapshot) -> int:
        normalized = normalize_source_snapshot(snapshot)
        source_time = normalized.source_updated_at or normalized.fetched_at
        inserted_prices = 0

        with self.SessionLocal() as db:
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

                existing_price = db.scalar(
                    select(MarketPrice.id).where(
                        MarketPrice.item_id == item.id,
                        MarketPrice.source_updated_at == source_time,
                    )
                )
                if existing_price is not None:
                    continue

                db.add(
                    MarketPrice(
                        item_id=item.id,
                        price=source_item.price,
                        fetched_at=normalized.fetched_at,
                        source_updated_at=source_time,
                    )
                )
                inserted_prices += 1

            db.commit()

        return inserted_prices

    def list_latest(self, game_key: str, *, limit: int = 200) -> tuple[StoredMarketItem, ...]:
        clean_game_key = str(game_key or "").strip()
        if not clean_game_key:
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
            .where(MarketItem.game_key == clean_game_key)
            .order_by(MarketItem.tier.desc().nullslast(), MarketItem.name.asc())
            .limit(max(1, min(int(limit), 500)))
        )

        with self.SessionLocal() as db:
            rows: Iterable[tuple[MarketItem, MarketPrice]] = db.execute(stmt).all()
            return tuple(
                StoredMarketItem(
                    item_id=item.id,
                    source_item_id=item.source_item_id,
                    name=item.name,
                    category=item.category,
                    tier=item.tier,
                    current_price=price.price,
                    source_updated_at=price.source_updated_at,
                )
                for item, price in rows
            )

    def history(self, item_id: int, *, limit: int = 500) -> tuple[tuple[datetime, int], ...]:
        stmt = (
            select(MarketPrice.source_updated_at, MarketPrice.price)
            .where(MarketPrice.item_id == int(item_id))
            .order_by(MarketPrice.source_updated_at.desc())
            .limit(max(1, min(int(limit), 2000)))
        )
        with self.SessionLocal() as db:
            rows = db.execute(stmt).all()
            return tuple(reversed(tuple((when, price) for when, price in rows)))
