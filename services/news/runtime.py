from __future__ import annotations

from services.news.base import GameNewsFeed
from services.news.garena_delta import SOURCE_NAME, SOURCE_URL, get_delta_force_news


async def get_game_news_feed(game_key: str) -> GameNewsFeed:
    clean_game_key = str(game_key or "").strip()
    if clean_game_key == "delta_force":
        return await get_delta_force_news()
    return GameNewsFeed(
        game_key=clean_game_key,
        status="unavailable",
        source_name=SOURCE_NAME,
        source_url=SOURCE_URL,
        message="這個遊戲目前尚未設定官方消息來源。",
    )
