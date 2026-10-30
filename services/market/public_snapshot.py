from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


@dataclass(frozen=True)
class MarketItemSummary:
    item_key: str
    name: str
    current_price: int | None = None
    change_24h_pct: float | None = None
    recommendation_label: str | None = None


@dataclass(frozen=True)
class MarketSnapshot:
    game_key: str
    status: str
    updated_at: datetime | None = None
    recommended_item: MarketItemSummary | None = None
    items: tuple[MarketItemSummary, ...] = field(default_factory=tuple)
    message: str = ""


def get_public_market_snapshot(game_key: str) -> MarketSnapshot:
    """Return the public market state for a game.

    The first website milestone intentionally exposes an explicit unavailable
    state until a verified Taiwan-server source and persistence layer are
    connected. Do not fabricate prices in the presentation layer.
    """
    clean_game_key = str(game_key or "").strip()

    return MarketSnapshot(
        game_key=clean_game_key,
        status="source_pending",
        message="行情資料源正在接入中，啟用前不會顯示模擬價格。",
    )
