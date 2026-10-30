from __future__ import annotations

from pathlib import Path
from urllib.parse import quote

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates

from services.game_registry import GameHub, get_game_feature_cards, get_game_hub
from services.market.public_snapshot import get_public_market_snapshot
from web.app.services.seo import build_seo


router = APIRouter(tags=["game-tools"])

TEMPLATES_DIR = Path(__file__).resolve().parents[1] / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


def _game_or_404(game_slug: str) -> GameHub:
    game = get_game_hub(game_slug)
    if game is None:
        raise HTTPException(status_code=404, detail="找不到這個遊戲。")
    return game


def _base_context(request: Request, game: GameHub, **extra) -> dict:
    context = {
        "user": request.session.get("user"),
        "game": game,
        "game_features": get_game_feature_cards(game),
    }
    context.update(extra)
    return context


@router.get("/games/{game_slug}/market")
async def game_market(request: Request, game_slug: str):
    game = _game_or_404(game_slug)
    if not game.has_market:
        raise HTTPException(status_code=404, detail="這個遊戲目前沒有交易所行情。")

    snapshot = get_public_market_snapshot(game.key)
    path = f"/games/{game.slug}/market"
    seo = build_seo(
        path=path,
        title=f"{game.market_title}｜魔丸娛樂",
        description=(
            game.market_description
            or f"查看{game.name}市場行情、價格走勢與通知功能。"
        ),
    )

    return templates.TemplateResponse(
        request=request,
        name="game_market.html",
        context=_base_context(
            request,
            game,
            title=seo["title"],
            seo=seo,
            page_name=f"game_{game.key}_market",
            snapshot=snapshot,
        ),
    )


@router.get("/games/{game_slug}/news")
async def game_news(request: Request, game_slug: str):
    game = _game_or_404(game_slug)
    if not game.has_news:
        raise HTTPException(status_code=404, detail="這個遊戲目前沒有消息中心。")

    path = f"/games/{game.slug}/news"
    seo = build_seo(
        path=path,
        title=f"{game.news_title}｜魔丸娛樂",
        description=f"集中查看{game.name}更新、活動與重要遊戲消息。",
    )

    return templates.TemplateResponse(
        request=request,
        name="game_tool_placeholder.html",
        context=_base_context(
            request,
            game,
            title=seo["title"],
            seo=seo,
            page_name=f"game_{game.key}_news",
            tool_key="news",
            tool_title=game.news_title,
            tool_description="消息來源正在整理中，正式接入前不會填入未驗證內容。",
        ),
    )


@router.get("/games/{game_slug}/notifications")
async def game_notifications(request: Request, game_slug: str):
    game = _game_or_404(game_slug)
    if not game.has_notifications:
        raise HTTPException(status_code=404, detail="這個遊戲目前沒有通知中心。")

    path = f"/games/{game.slug}/notifications"
    user = request.session.get("user")
    if not user:
        return RedirectResponse(
            url="/auth/discord/login?next=" + quote(path, safe=""),
            status_code=303,
        )

    seo = build_seo(
        path=path,
        title=f"{game.notifications_title}｜魔丸娛樂",
        description=f"管理{game.name}的網站與手機通知設定。",
        noindex=True,
    )

    return templates.TemplateResponse(
        request=request,
        name="game_tool_placeholder.html",
        context=_base_context(
            request,
            game,
            title=seo["title"],
            seo=seo,
            page_name=f"game_{game.key}_notifications",
            tool_key="notifications",
            tool_title=game.notifications_title,
            tool_description="通知設定會在行情資料與 Web Push 接好後於此開放。",
        ),
    )


@router.get("/games/{game_slug}")
async def generic_game_hub(request: Request, game_slug: str):
    """Fallback landing page for games without a bespoke website surface.

    Existing dedicated game routes keep precedence because the site router is
    registered before this router. New registry entries can therefore launch a
    usable hub immediately and be upgraded to a custom page later.
    """
    game = _game_or_404(game_slug)
    path = f"/games/{game.slug}"
    seo = build_seo(
        path=path,
        title=f"{game.name}｜魔丸娛樂",
        description=f"查看{game.name}的魔丸服務、遊戲消息、行情與通知。",
    )

    return templates.TemplateResponse(
        request=request,
        name="game_hub.html",
        context=_base_context(
            request,
            game,
            title=seo["title"],
            seo=seo,
            page_name=f"game_{game.key}",
        ),
    )
