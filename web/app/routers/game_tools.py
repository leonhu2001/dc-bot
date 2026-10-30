from __future__ import annotations

from pathlib import Path
from urllib.parse import quote, urlencode

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates

from services.game_registry import (
    GameHub,
    get_game_feature_cards,
    get_game_hub,
    list_game_hubs,
)
from services.market.public_snapshot import (
    filter_market_snapshot,
    get_public_market_snapshot,
)
from services.market.runtime import get_market_repository
from web.app.services.seo import build_seo


router = APIRouter(tags=["game-tools"])

TEMPLATES_DIR = Path(__file__).resolve().parents[1] / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

_MARKET_SORTS = {"name", "price_desc", "price_asc", "change_desc", "change_asc"}


def _game_or_404(game_slug: str) -> GameHub:
    game = get_game_hub(game_slug)
    if game is None:
        raise HTTPException(status_code=404, detail="找不到這個遊戲。")
    return game


def _market_game_or_404(game_slug: str) -> GameHub:
    game = _game_or_404(game_slug)
    if not game.has_market:
        raise HTTPException(status_code=404, detail="這個遊戲目前沒有交易所行情。")
    return game


def _base_context(request: Request, game: GameHub, **extra) -> dict:
    context = {
        "user": request.session.get("user"),
        "game": game,
        "game_features": get_game_feature_cards(game),
    }
    context.update(extra)
    return context


def _item_payload(item) -> dict:
    return {
        "item_key": item.item_key,
        "name": item.name,
        "current_price": item.current_price,
        "change_24h_pct": item.change_24h_pct,
        "recommendation_label": item.recommendation_label,
        "category": item.category,
        "tier": item.tier,
        "low_24h": item.low_24h,
        "high_24h": item.high_24h,
        "avg_7d": item.avg_7d,
        "low_7d": item.low_7d,
        "high_7d": item.high_7d,
        "history_points_7d": item.history_points_7d,
        "coverage_hours": item.coverage_hours,
    }


def _snapshot_payload(snapshot) -> dict:
    return {
        "status": snapshot.status,
        "updated_at": snapshot.updated_at.isoformat() if snapshot.updated_at else None,
        "message": snapshot.message,
        "items": [_item_payload(item) for item in snapshot.items],
        "gainers": [_item_payload(item) for item in snapshot.gainers],
        "losers": [_item_payload(item) for item in snapshot.losers],
    }


def _safe_market_repository():
    try:
        return get_market_repository()
    except Exception:
        return None


def _market_tier(value: str | None) -> int | None:
    try:
        tier = int(str(value or "").strip())
    except (TypeError, ValueError):
        return None
    return tier if 1 <= tier <= 10 else None


def _market_sort(value: str | None) -> str:
    clean = str(value or "").strip().lower()
    return clean if clean in _MARKET_SORTS else "name"


def _market_query_state(request: Request) -> tuple[str, int | None, str]:
    query = str(request.query_params.get("q", "")).strip()[:80]
    tier = _market_tier(request.query_params.get("tier"))
    sort = _market_sort(request.query_params.get("sort"))
    return query, tier, sort


def _market_filter_href(
    game_slug: str,
    *,
    query: str,
    tier: int | None,
    sort: str,
) -> str:
    params: dict[str, str] = {}
    if query:
        params["q"] = query
    if tier is not None:
        params["tier"] = str(tier)
    if sort != "name":
        params["sort"] = sort
    encoded = urlencode(params)
    base = f"/games/{game_slug}/market"
    return f"{base}?{encoded}" if encoded else base


@router.get("/games")
async def games_directory(request: Request):
    seo = build_seo(
        path="/games",
        title="遊戲專區｜魔丸娛樂",
        description="依遊戲查看魔丸服務、行情工具、遊戲消息與通知。",
    )
    return templates.TemplateResponse(
        request=request,
        name="games_index.html",
        context={
            "request": request,
            "user": request.session.get("user"),
            "games": list_game_hubs(),
            "title": seo["title"],
            "seo": seo,
            "page_name": "games",
        },
    )


@router.get("/games/{game_slug}/market")
async def game_market(request: Request, game_slug: str):
    game = _market_game_or_404(game_slug)
    query, tier, sort = _market_query_state(request)
    snapshot = filter_market_snapshot(
        get_public_market_snapshot(game.key),
        query=query,
        tier=tier,
        sort=sort,
    )
    path = f"/games/{game.slug}/market"
    seo = build_seo(
        path=path,
        title=f"{game.market_title}｜魔丸娛樂",
        description=(
            game.market_description
            or f"查看{game.name}市場行情、價格走勢與通知功能。"
        ),
    )

    filter_links = {
        "all": _market_filter_href(game.slug, query=query, tier=None, sort=sort),
        "5": _market_filter_href(game.slug, query=query, tier=5, sort=sort),
        "6": _market_filter_href(game.slug, query=query, tier=6, sort=sort),
    }

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
            market_query=query,
            market_tier=tier,
            market_sort=sort,
            market_filter_links=filter_links,
            market_result_count=len(snapshot.items),
        ),
    )


@router.get("/games/{game_slug}/market/api/items")
async def game_market_items_api(request: Request, game_slug: str):
    game = _market_game_or_404(game_slug)
    query, tier, sort = _market_query_state(request)
    snapshot = filter_market_snapshot(
        get_public_market_snapshot(game.key),
        query=query,
        tier=tier,
        sort=sort,
    )
    return {
        "ok": True,
        "game": game.key,
        "filters": {"q": query, "tier": tier, "sort": sort},
        **_snapshot_payload(snapshot),
    }


@router.get("/games/{game_slug}/market/items/{source_item_id}")
async def game_market_item_detail(
    request: Request,
    game_slug: str,
    source_item_id: str,
):
    game = _market_game_or_404(game_slug)
    repository = _safe_market_repository()
    if repository is None:
        raise HTTPException(status_code=503, detail="行情資料目前尚未啟用。")

    try:
        item = repository.get_item(game.key, source_item_id)
        if item is None:
            raise HTTPException(status_code=404, detail="找不到這個行情品項。")
        points = repository.history(item.id, limit=2000)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=503, detail="行情資料暫時無法讀取。") from exc

    prices = [point.price for point in points]
    current_price = prices[-1] if prices else None
    latest_at = points[-1].source_updated_at if points else None
    path = f"/games/{game.slug}/market/items/{quote(item.source_item_id, safe='')}"
    seo = build_seo(
        path=path,
        title=f"{item.name} 價格走勢｜{game.market_title}｜魔丸娛樂",
        description=f"查看{game.name} {item.name} 的交易所價格與歷史走勢。",
    )

    return templates.TemplateResponse(
        request=request,
        name="game_market_item.html",
        context=_base_context(
            request,
            game,
            title=seo["title"],
            seo=seo,
            page_name=f"game_{game.key}_market_item",
            item=item,
            current_price=current_price,
            latest_at=latest_at,
            low_price=min(prices) if prices else None,
            high_price=max(prices) if prices else None,
            point_count=len(points),
        ),
    )


@router.get("/games/{game_slug}/market/api/items/{source_item_id}/history")
async def game_market_item_history_api(
    game_slug: str,
    source_item_id: str,
    limit: int = 500,
):
    game = _market_game_or_404(game_slug)
    repository = _safe_market_repository()
    if repository is None:
        return {
            "ok": True,
            "game": game.key,
            "status": "source_pending",
            "item": None,
            "points": [],
        }

    try:
        item = repository.get_item(game.key, source_item_id)
        if item is None:
            raise HTTPException(status_code=404, detail="找不到這個行情品項。")
        points = repository.history(item.id, limit=limit)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=503, detail="行情資料暫時無法讀取。") from exc

    return {
        "ok": True,
        "game": game.key,
        "status": "ready" if points else "no_data",
        "item": {
            "item_key": item.source_item_id,
            "name": item.name,
            "category": item.category,
            "tier": item.tier,
        },
        "points": [
            {
                "at": point.source_updated_at.isoformat(),
                "price": point.price,
            }
            for point in points
        ],
    }


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
