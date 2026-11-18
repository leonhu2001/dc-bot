"""Private paid-order affection pages, shared UI with separate game themes."""
from __future__ import annotations

from pathlib import Path
from urllib.parse import quote

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool

from web.app.services.affection_game_service import (
    ensure_tables, get_context, get_entry_info, mutate,
    legacy_romance_session_exists,
)

router = APIRouter(tags=["affection-games"])
TEMPLATES = Jinja2Templates(
    directory=str(Path(__file__).resolve().parents[1] / "templates")
)
ensure_tables()


class AffectionEventPayload(BaseModel):
    event_key: str
    expected_round: int


class AffectionSettlePayload(BaseModel):
    result: str
    extra: bool = False
    expected_round: int


def _id(request: Request) -> str:
    u = request.session.get("user")
    return str((u or {}).get("id") or "").strip() if isinstance(u, dict) else ""


def _error(exc: Exception) -> HTTPException:
    if isinstance(exc, PermissionError):
        return HTTPException(status_code=403, detail=str(exc))
    if isinstance(exc, LookupError):
        return HTTPException(status_code=404, detail=str(exc))
    if isinstance(exc, ValueError):
        return HTTPException(status_code=409, detail=str(exc))
    return HTTPException(status_code=500, detail="專屬網站暫時無法使用。")


async def _context(request: Request, order_id: int, game: str | None = None):
    user_id = _id(request)
    if not user_id:
        raise HTTPException(status_code=401, detail="請先登入 Discord。")
    try:
        return await run_in_threadpool(get_context, user_id, order_id, game=game)
    except (PermissionError, LookupError, ValueError) as exc:
        raise _error(exc) from exc


async def _page(request: Request, order_id: int, game: str):
    slug = "our-love" if game == "our_love" else "romance-delta"
    if not _id(request):
        nxt = quote(f"/me/orders/{int(order_id)}/{slug}", safe="")
        return RedirectResponse(url=f"/auth/discord/login?next={nxt}", status_code=303)
    context = await _context(request, order_id, game)
    return TEMPLATES.TemplateResponse(
        request=request,
        name="member_affection_game.html",
        context={
            "user": request.session.get("user"),
            "title": context["plan"]["title"] + "｜專屬攻略",
            "affection": context,
        },
    )


@router.get("/me/orders/{order_id}/our-love/entry")
async def our_love_entry(request: Request, order_id: int):
    if not _id(request):
        raise HTTPException(status_code=401, detail="請先登入。")
    try:
        return await run_in_threadpool(get_entry_info, _id(request), order_id, game="our_love")
    except (LookupError, PermissionError, ValueError) as exc:
        raise _error(exc) from exc


@router.get("/me/orders/{order_id}/our-love")
async def our_love_page(request: Request, order_id: int):
    return await _page(request, order_id, "our_love")


@router.get("/me/orders/{order_id}/romance-delta")
async def romance_v2_page(request: Request, order_id: int):
    if legacy_romance_session_exists(order_id):
        return RedirectResponse(url=f"/me/orders/{int(order_id)}/love-delta", status_code=303)
    return await _page(request, order_id, "romance")


@router.get("/me/orders/{order_id}/affection-game/state")
async def affection_state(request: Request, order_id: int):
    return await _context(request, order_id)


@router.post("/me/orders/{order_id}/affection-game/start")
async def affection_start(request: Request, order_id: int):
    if not _id(request):
        raise HTTPException(status_code=401, detail="請先登入。")
    try:
        return await run_in_threadpool(mutate, _id(request), order_id, "start")
    except (LookupError, PermissionError, ValueError) as exc:
        raise _error(exc) from exc


@router.post("/me/orders/{order_id}/affection-game/event")
async def affection_event(request: Request, order_id: int, payload: AffectionEventPayload):
    if not _id(request):
        raise HTTPException(status_code=401, detail="請先登入。")
    try:
        return await run_in_threadpool(
            mutate, _id(request), order_id, "event",
            event_key=payload.event_key, expected_round=payload.expected_round,
        )
    except (LookupError, PermissionError, ValueError) as exc:
        raise _error(exc) from exc


@router.post("/me/orders/{order_id}/affection-game/settle")
async def affection_settle(request: Request, order_id: int, payload: AffectionSettlePayload):
    if not _id(request):
        raise HTTPException(status_code=401, detail="請先登入。")
    try:
        return await run_in_threadpool(
            mutate, _id(request), order_id, "settle",
            result=payload.result, extra=payload.extra,
            expected_round=payload.expected_round,
        )
    except (LookupError, PermissionError, ValueError) as exc:
        raise _error(exc) from exc


@router.post("/me/orders/{order_id}/affection-game/undo")
async def affection_undo(request: Request, order_id: int):
    if not _id(request):
        raise HTTPException(status_code=401, detail="請先登入。")
    try:
        return await run_in_threadpool(mutate, _id(request), order_id, "undo")
    except (LookupError, PermissionError, ValueError) as exc:
        raise _error(exc) from exc
