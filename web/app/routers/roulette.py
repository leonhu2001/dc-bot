from __future__ import annotations

from pathlib import Path
from typing import Any
from urllib.parse import quote

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool

from web.app.services.roulette_service import (
    draw_roulette,
    ensure_roulette_feature,
    get_roulette_context,
)


router = APIRouter(tags=["roulette"])
TEMPLATES = Jinja2Templates(
    directory=str(Path(__file__).resolve().parents[1] / "templates")
)

# This router is imported while the Web app starts. The bootstrap is additive:
# it creates the draw table and the initial product only when they do not exist.
ensure_roulette_feature()


class RouletteDrawPayload(BaseModel):
    mode: str
    selection: Any


def _session_user(request: Request) -> dict | None:
    user = request.session.get("user")
    return user if isinstance(user, dict) else None


def _customer_id(user: dict | None) -> str:
    return str((user or {}).get("id") or "").strip()


@router.get("/me/orders/{order_id}/roulette")
async def member_roulette(request: Request, order_id: int):
    user = _session_user(request)
    customer_id = _customer_id(user)
    if not customer_id:
        next_path = quote(f"/me/orders/{int(order_id)}/roulette", safe="")
        return RedirectResponse(
            url=f"/auth/discord/login?next={next_path}",
            status_code=303,
        )

    try:
        context = await run_in_threadpool(
            get_roulette_context,
            customer_id,
            int(order_id),
        )
    except LookupError:
        raise HTTPException(status_code=404, detail="找不到這張訂單。")
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))

    return TEMPLATES.TemplateResponse(
        request=request,
        name="member_roulette.html",
        context={
            "title": "俄羅斯輪盤・保底抽取｜魔丸娛樂",
            "user": user,
            **context,
        },
    )


@router.post("/me/orders/{order_id}/roulette/draw")
async def member_roulette_draw(
    request: Request,
    order_id: int,
    payload: RouletteDrawPayload,
):
    user = _session_user(request)
    customer_id = _customer_id(user)
    if not customer_id:
        raise HTTPException(status_code=401, detail="請先登入。")

    try:
        result = await run_in_threadpool(
            draw_roulette,
            customer_id,
            int(order_id),
            mode=payload.mode,
            selection=payload.selection,
        )
    except LookupError:
        raise HTTPException(status_code=404, detail="找不到這張訂單。")
    except PermissionError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    return {
        "ok": True,
        "draw": result,
    }
