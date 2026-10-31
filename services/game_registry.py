from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class GameHub:
    key: str
    slug: str
    name: str
    short_name: str
    eyebrow: str
    market_title: str | None = None
    market_description: str | None = None
    news_title: str | None = None
    notifications_title: str | None = None

    @property
    def has_market(self) -> bool:
        return bool(self.market_title)

    @property
    def has_news(self) -> bool:
        return bool(self.news_title)

    @property
    def has_notifications(self) -> bool:
        return bool(self.notifications_title)


_GAME_HUBS: dict[str, GameHub] = {
    "delta-force": GameHub(
        key="delta_force",
        slug="delta-force",
        name="三角洲行動",
        short_name="三角洲",
        eyebrow="DELTA FORCE · MOWAN",
        market_title="三角洲子彈行情",
        market_description="台服 4、5 級子彈價格、24H / 7D 走勢、收藏與價格提醒。",
    ),
}


def get_game_hub(slug: str) -> GameHub | None:
    return _GAME_HUBS.get(str(slug or "").strip().lower())


def list_game_hubs() -> tuple[GameHub, ...]:
    return tuple(_GAME_HUBS.values())


def get_game_feature_cards(game: GameHub) -> list[dict[str, str | bool]]:
    cards: list[dict[str, str | bool]] = []

    if game.has_market:
        cards.append(
            {
                "key": "market",
                "title": str(game.market_title),
                "description": "追蹤台服 4、5 級子彈價格、歷史走勢與補貨預測。",
                "href": f"/games/{game.slug}/market",
                "status": "已上線",
                "enabled": True,
            }
        )

    return cards
