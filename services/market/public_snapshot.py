from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import datetime, timezone

from services.market.runtime import get_market_repository
from services.market.storage import MarketRepository


@dataclass(frozen=True)
class MarketItemSummary:
    item_key: str
    name: str
    current_price: int | None = None
    change_24h_pct: float | None = None
    recommendation_label: str | None = None
    category: str = ""
    tier: int | None = None


@dataclass(frozen=True)
class MarketSnapshot:
    game_key: str
    status: str
    updated_at: datetime | None = None
    recommended_item: MarketItemSummary | None = None
    items: tuple[MarketItemSummary, ...] = field(default_factory=tuple)
    message: str = ""


def _stale_seconds() -> int:
    try:
        return max(900, int(os.getenv("MARKET_STALE_SECONDS", "2700")))
    except (TypeError, ValueError):
        return 2700


def get_public_market_snapshot(
    game_key: str,
    *,
    repository: MarketRepository | None = None,
) -> MarketSnapshot:
    """Return trusted persisted market data for website/Discord presentation.

    Market failures are intentionally isolated from the existing site. A bad
    market connection must degrade this feature to an explicit status instead
    of turning unrelated order/customer pages into HTTP 500 responses.
    """
    clean_game_key = str(game_key or "").strip()
    if not clean_game_key:
        return MarketSnapshot(
            game_key="",
            status="source_pending",
            message="行情遊戲識別不存在。",
        )

    try:
        market_repository = repository or get_market_repository()
    except Exception:
        return MarketSnapshot(
            game_key=clean_game_key,
            status="source_error",
            message="行情資料庫暫時無法連線，其他網站功能不受影響。",
        )

    if market_repository is None:
        return MarketSnapshot(
            game_key=clean_game_key,
            status="source_pending",
            message="行情資料源正在接入中，啟用前不會顯示模擬價格。",
        )

    try:
        latest = market_repository.list_latest(clean_game_key)
    except Exception:
        return MarketSnapshot(
            game_key=clean_game_key,
            status="source_error",
            message="行情資料暫時讀取失敗，已停止顯示未確認的新價格。",
        )

    if not latest:
        return MarketSnapshot(
            game_key=clean_game_key,
            status="no_data",
            message="行情資料庫已啟用，但尚未收到可驗證的正式價格。",
        )

    updated_at = max(item.source_updated_at for item in latest)
    now = datetime.now(timezone.utc)
    age_seconds = max(0.0, (now - updated_at).total_seconds())
    stale = age_seconds > _stale_seconds()

    items = tuple(
        MarketItemSummary(
            item_key=item.source_item_id,
            name=item.name,
            current_price=item.current_price,
            category=item.category,
            tier=item.tier,
        )
        for item in latest
    )

    return MarketSnapshot(
        game_key=clean_game_key,
        status="stale" if stale else "ready",
        updated_at=updated_at,
        items=items,
        message=(
            "行情已超過安全更新時間，價格僅供參考；恢復更新前不觸發價格提醒。"
            if stale
            else "行情資料已由正式來源更新。"
        ),
    )
