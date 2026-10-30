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
        market_title="三角洲交易所行情",
        market_description=(
            "查看台服交易所價格、歷史走勢與市場異動；"
            "後續將加入關注清單、推薦品項與價格提醒。"
        ),
        news_title="三角洲消息",
        notifications_title="三角洲通知",
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
                "description": "即時價格、歷史走勢、推薦品項與價格提醒。",
                "href": f"/games/{game.slug}/market",
                "status": "建置中",
                "enabled": True,
            }
        )

    if game.has_news:
        cards.append(
            {
                "key": "news",
                "title": str(game.news_title),
                "description": "集中整理更新、活動與值得注意的遊戲消息。",
                "href": f"/games/{game.slug}/news",
                "status": "準備中",
                "enabled": True,
            }
        )

    if game.has_notifications:
        cards.append(
            {
                "key": "notifications",
                "title": str(game.notifications_title),
                "description": "管理這款遊戲的網站與手機通知偏好。",
                "href": f"/games/{game.slug}/notifications",
                "status": "準備中",
                "enabled": True,
            }
        )

    return cards
