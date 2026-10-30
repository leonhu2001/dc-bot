from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse

from services.game_registry import get_game_hub
from services.market.push_dispatcher import get_web_push_config
from services.market.runtime import (
    get_market_personalization_repository,
    get_market_push_repository,
)
from web.app.services.market_health import check_market_health


router = APIRouter(tags=["market-push"])
STATIC_DIR = Path(__file__).resolve().parents[1] / "static"
SERVICE_WORKER_PATH = STATIC_DIR / "js" / "site_sw.js"


def _game_or_404(game_slug: str):
    game = get_game_hub(game_slug)
    if game is None or not game.has_notifications:
        raise HTTPException(status_code=404, detail="找不到這個遊戲通知功能。")
    return game


def _user_id_or_401(request: Request) -> str:
    user = request.session.get("user") or {}
    user_id = str(user.get("id") or "").strip()
    if not user_id:
        raise HTTPException(status_code=401, detail="請先使用 Discord 登入。")
    return user_id


@router.get("/sw.js", include_in_schema=False)
async def site_service_worker():
    response = FileResponse(
        SERVICE_WORKER_PATH,
        media_type="application/javascript; charset=utf-8",
    )
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    response.headers["Service-Worker-Allowed"] = "/"
    return response


@router.get("/health/market", include_in_schema=False)
async def market_health():
    status = check_market_health()
    return JSONResponse(
        status_code=200 if status.ok else 503,
        content=status.as_dict(),
    )


@router.get("/games/{game_slug}/notifications/push/config")
async def market_push_config(request: Request, game_slug: str):
    game = _game_or_404(game_slug)
    _user_id_or_401(request)
    config = get_web_push_config()
    push_repository = get_market_push_repository()
    enabled = bool(config.enabled and push_repository is not None)
    return {
        "ok": True,
        "game": game.key,
        "enabled": enabled,
        "public_key": config.public_key if enabled else "",
    }


@router.post("/games/{game_slug}/notifications/push/subscribe")
async def market_push_subscribe(request: Request, game_slug: str):
    game = _game_or_404(game_slug)
    user_id = _user_id_or_401(request)
    config = get_web_push_config()
    if not config.enabled:
        raise HTTPException(status_code=503, detail="手機推播尚未設定完成。")

    personalization = get_market_personalization_repository()
    push_repository = get_market_push_repository()
    if personalization is None or push_repository is None:
        raise HTTPException(status_code=503, detail="推播資料庫尚未啟用。")

    # Permission is contextual: users must create at least one alert before a
    # browser subscription is accepted. The page never prompts on initial load.
    if not personalization.list_alerts(user_id, game.key):
        raise HTTPException(status_code=400, detail="請先建立至少一個價格提醒。")

    try:
        payload = await request.json()
    except Exception as exc:
        raise HTTPException(status_code=400, detail="推播訂閱格式不正確。") from exc
    subscription = payload.get("subscription") if isinstance(payload, dict) else None
    if not isinstance(subscription, dict):
        raise HTTPException(status_code=400, detail="缺少推播訂閱資料。")

    keys = subscription.get("keys")
    if not isinstance(keys, dict):
        raise HTTPException(status_code=400, detail="缺少推播加密金鑰。")

    try:
        stored = push_repository.upsert_subscription(
            user_id,
            endpoint=str(subscription.get("endpoint") or ""),
            p256dh=str(keys.get("p256dh") or ""),
            auth=str(keys.get("auth") or ""),
            user_agent=str(request.headers.get("user-agent") or ""),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="推播訂閱資料無效。") from exc

    return {"ok": True, "subscription_id": stored.id}


@router.post("/games/{game_slug}/notifications/push/unsubscribe")
async def market_push_unsubscribe(request: Request, game_slug: str):
    _game_or_404(game_slug)
    user_id = _user_id_or_401(request)
    push_repository = get_market_push_repository()
    if push_repository is None:
        raise HTTPException(status_code=503, detail="推播資料庫尚未啟用。")

    try:
        payload = await request.json()
    except Exception as exc:
        raise HTTPException(status_code=400, detail="推播訂閱格式不正確。") from exc
    endpoint = str(payload.get("endpoint") or "") if isinstance(payload, dict) else ""
    if not endpoint:
        raise HTTPException(status_code=400, detail="缺少推播 endpoint。")

    push_repository.unsubscribe(user_id, endpoint)
    return {"ok": True}
