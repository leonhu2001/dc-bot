from __future__ import annotations

import asyncio
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse

from services.game_registry import get_game_hub
from services.market.notification_test import enqueue_market_test_notification
from services.market.push_dispatcher import dispatch_pending_pushes, get_web_push_config
from services.market.push_test import send_test_push
from services.market.runtime import (
    get_market_personalization_repository,
    get_market_push_repository,
    get_market_repository,
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


@router.post("/games/{game_slug}/notifications/push/test")
async def market_push_test(request: Request, game_slug: str):
    game = _game_or_404(game_slug)
    user_id = _user_id_or_401(request)
    config = get_web_push_config()
    if not config.enabled:
        raise HTTPException(status_code=503, detail="手機推播尚未設定完成。")

    push_repository = get_market_push_repository()
    if push_repository is None:
        raise HTTPException(status_code=503, detail="推播資料庫尚未啟用。")

    try:
        payload = await request.json()
    except Exception as exc:
        raise HTTPException(status_code=400, detail="推播測試格式不正確。") from exc
    endpoint = str(payload.get("endpoint") or "") if isinstance(payload, dict) else ""
    if not endpoint:
        raise HTTPException(status_code=400, detail="缺少推播 endpoint。")

    subscription = next(
        (
            row
            for row in push_repository.list_active_subscriptions(user_id)
            if row.endpoint == endpoint
        ),
        None,
    )
    if subscription is None:
        raise HTTPException(status_code=404, detail="這台裝置的推播訂閱不存在或已停用。")

    result = send_test_push(
        push_repository=push_repository,
        subscription=subscription,
        game_slug=game.slug,
        config=config,
    )
    if result.status == "expired":
        raise HTTPException(status_code=410, detail="這台裝置的推播訂閱已失效，請重新開啟推播。")
    if result.status == "unconfigured":
        raise HTTPException(status_code=503, detail="手機推播尚未設定完成。")
    if not result.ok:
        raise HTTPException(status_code=502, detail="測試通知暫時無法送達，請稍後再試。")

    return {"ok": True, "status": "sent"}


@router.post("/games/{game_slug}/notifications/alerts/{alert_id}/test-delivery")
async def market_alert_delivery_test(
    request: Request,
    game_slug: str,
    alert_id: int,
):
    game = _game_or_404(game_slug)
    user_id = _user_id_or_401(request)
    market_repository = get_market_repository()
    personalization = get_market_personalization_repository()
    push_repository = get_market_push_repository()
    if market_repository is None or personalization is None:
        raise HTTPException(status_code=503, detail="價格通知目前尚未啟用。")

    try:
        enqueue_market_test_notification(
            market_repository=market_repository,
            personalization_repository=personalization,
            discord_user_id=user_id,
            game_key=game.key,
            alert_id=alert_id,
        )
    except ValueError as exc:
        reason = str(exc)
        if reason == "alert not found":
            raise HTTPException(status_code=404, detail="找不到這個價格提醒。") from exc
        if reason == "alert is paused":
            raise HTTPException(status_code=400, detail="請先啟用這個價格提醒。") from exc
        if reason == "test notification cooldown":
            raise HTTPException(status_code=429, detail="測試通知剛送出，請稍後再試。") from exc
        if reason == "market item unavailable":
            raise HTTPException(status_code=503, detail="目前無法讀取這個品項的行情。") from exc
        raise HTTPException(status_code=400, detail="無法建立測試通知。") from exc

    # Production push delivery normally follows the Market polling cycle. For
    # an explicit user test, run the same durable dispatcher immediately so a
    # browser subscription can be verified without waiting for the next poll.
    config = get_web_push_config()
    if push_repository is not None and config.enabled:
        await asyncio.to_thread(
            dispatch_pending_pushes,
            market_repository=market_repository,
            push_repository=push_repository,
            config=config,
            limit=50,
        )

    return RedirectResponse(
        url=f"/games/{game.slug}/notifications?delivery_test=queued#price-alerts",
        status_code=303,
    )


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
