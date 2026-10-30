from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from fastapi.templating import Jinja2Templates

from services.game_registry import get_game_feature_cards, get_game_hub
from services.news import get_game_news_feed
from web.app.services.seo import build_seo

router = APIRouter(tags=["game-news"])
templates = Jinja2Templates(directory=str(Path(__file__).resolve().parents[1] / "templates"))
_ALLOWED_CATEGORIES = {"all", "system", "announcement", "event"}


@router.get("/games/{game_slug}/news")
async def game_news(request: Request, game_slug: str):
    game = get_game_hub(game_slug)
    if game is None or not game.has_news:
        raise HTTPException(status_code=404, detail="這個遊戲目前沒有消息中心。")

    feed = await get_game_news_feed(game.key)
    query = str(request.query_params.get("q") or "").strip()[:80]
    category = str(request.query_params.get("category") or "all").strip().lower()
    if category not in _ALLOWED_CATEGORIES:
        category = "all"

    clean_query = query.casefold()
    articles = tuple(
        article
        for article in feed.articles
        if (category == "all" or article.category_key == category)
        and (
            not clean_query
            or clean_query in article.title.casefold()
            or clean_query in article.excerpt.casefold()
        )
    )

    path = f"/games/{game.slug}/news"
    seo = build_seo(
        path=path,
        title=f"{game.news_title}｜魔丸娛樂",
        description=f"查看 {game.name} Garena 台灣官方更新、公告與活動消息。",
    )
    return templates.TemplateResponse(
        request=request,
        name="game_news.html",
        context={
            "request": request,
            "user": request.session.get("user"),
            "game": game,
            "game_features": get_game_feature_cards(game),
            "title": seo["title"],
            "seo": seo,
            "page_name": f"game_{game.key}_news",
            "news_feed": feed,
            "news_articles": articles,
            "news_query": query,
            "news_category": category,
            "news_result_count": len(articles),
        },
    )
