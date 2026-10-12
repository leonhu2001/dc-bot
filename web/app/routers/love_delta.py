from __future__ import annotations

from pathlib import Path
from urllib.parse import quote

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

from web.app.services.love_delta_service import (
    apply_love_delta_event,
    clear_boss_guess,
    clear_companion_guess,
    ensure_love_delta_tables,
    get_love_delta_context,
    get_love_delta_entry_info,
    save_bans,
    save_boss_guess,
    save_companion_guess,
    save_next_loadout,
    save_unlock_text,
    settle_love_delta_round,
    start_love_delta,
    undo_last_love_delta_event,
)

router = APIRouter(tags=["love-delta"])
TEMPLATES = Jinja2Templates(
    directory=str(Path(__file__).resolve().parents[1] / "templates")
)

ensure_love_delta_tables()


class LoveDeltaEventPayload(BaseModel):
    event_type: str
    target_companion_id: str | None = None


class LoveDeltaBossGuessPayload(BaseModel):
    answer: str
    hint_category: str = ""
    hint_quality: str = ""


class LoveDeltaCompanionGuessPayload(BaseModel):
    guess: str


class LoveDeltaBansPayload(BaseModel):
    bans: list[str] = Field(min_length=3, max_length=3)


class LoveDeltaUnlockPayload(BaseModel):
    value: str


class LoveDeltaLoadoutPayload(BaseModel):
    agent: str
    weapon: str


class LoveDeltaSettlePayload(BaseModel):
    expected_round: int
    result: str
    extraction_tier: int = 0


def _session_user(request: Request) -> dict | None:
    user = request.session.get("user")
    return user if isinstance(user, dict) else None


def _user_id(user: dict | None) -> str:
    return str((user or {}).get("id") or "").strip()


def _json_error(exc: Exception) -> HTTPException:
    if isinstance(exc, LookupError):
        return HTTPException(status_code=404, detail=str(exc))
    if isinstance(exc, PermissionError):
        return HTTPException(status_code=403, detail=str(exc))
    if isinstance(exc, ValueError):
        return HTTPException(status_code=409, detail=str(exc))
    return HTTPException(status_code=500, detail="攻略面板發生錯誤。")


async def _context_for(request: Request, order_id: int) -> dict:
    user = _session_user(request)
    user_id = _user_id(user)
    if not user_id:
        raise HTTPException(status_code=401, detail="請先登入。")
    try:
        return await run_in_threadpool(
            get_love_delta_context,
            user_id,
            int(order_id),
        )
    except (LookupError, PermissionError, ValueError) as exc:
        raise _json_error(exc) from exc


def _public_payload(context: dict) -> dict:
    return {
        "ok": True,
        "order": context["order"],
        "plan": context["plan"],
        "viewer": context["viewer"],
        "state": context["state"],
        "events": context["events"],
        "read_only": context["read_only"],
    }


@router.get("/me/orders/{order_id}/love-delta/entry")
async def love_delta_entry(request: Request, order_id: int):
    user = _session_user(request)
    user_id = _user_id(user)
    if not user_id:
        raise HTTPException(status_code=401, detail="請先登入。")
    try:
        info = await run_in_threadpool(
            get_love_delta_entry_info,
            user_id,
            int(order_id),
        )
    except (LookupError, PermissionError, ValueError) as exc:
        raise _json_error(exc) from exc
    return {"ok": True, **info}


@router.get("/me/orders/{order_id}/love-delta")
async def love_delta_page(request: Request, order_id: int):
    user = _session_user(request)
    user_id = _user_id(user)
    if not user_id:
        next_path = quote(f"/me/orders/{int(order_id)}/love-delta", safe="")
        return RedirectResponse(
            url=f"/auth/discord/login?next={next_path}",
            status_code=303,
        )

    try:
        context = await run_in_threadpool(
            get_love_delta_context,
            user_id,
            int(order_id),
        )
    except LookupError:
        raise HTTPException(status_code=404, detail="找不到這張訂單。")
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc))

    return TEMPLATES.TemplateResponse(
        request=request,
        name="member_love_delta.html",
        context={
            "title": "戀與三角洲｜攻略進度",
            "user": user,
            "love_delta": context,
        },
    )


@router.get("/me/orders/{order_id}/love-delta/state")
async def love_delta_state(request: Request, order_id: int):
    context = await _context_for(request, order_id)
    return _public_payload(context)


@router.post("/me/orders/{order_id}/love-delta/start")
async def love_delta_start(request: Request, order_id: int):
    user_id = _user_id(_session_user(request))
    if not user_id:
        raise HTTPException(status_code=401, detail="請先登入。")
    try:
        context = await run_in_threadpool(start_love_delta, user_id, int(order_id))
    except (LookupError, PermissionError, ValueError) as exc:
        raise _json_error(exc) from exc
    return _public_payload(context)


@router.post("/me/orders/{order_id}/love-delta/event")
async def love_delta_event(
    request: Request,
    order_id: int,
    payload: LoveDeltaEventPayload,
):
    user_id = _user_id(_session_user(request))
    if not user_id:
        raise HTTPException(status_code=401, detail="請先登入。")
    try:
        context = await run_in_threadpool(
            apply_love_delta_event,
            user_id,
            int(order_id),
            payload.event_type,
            target_companion_id=payload.target_companion_id,
        )
    except (LookupError, PermissionError, ValueError) as exc:
        raise _json_error(exc) from exc
    return _public_payload(context)


@router.post("/me/orders/{order_id}/love-delta/guess/boss")
async def love_delta_boss_guess(
    request: Request,
    order_id: int,
    payload: LoveDeltaBossGuessPayload,
):
    user_id = _user_id(_session_user(request))
    if not user_id:
        raise HTTPException(status_code=401, detail="請先登入。")
    try:
        context = await run_in_threadpool(
            save_boss_guess,
            user_id,
            int(order_id),
            answer=payload.answer,
            hint_category=payload.hint_category,
            hint_quality=payload.hint_quality,
        )
    except (LookupError, PermissionError, ValueError) as exc:
        raise _json_error(exc) from exc
    return _public_payload(context)


@router.delete("/me/orders/{order_id}/love-delta/guess/boss")
async def love_delta_boss_guess_clear(request: Request, order_id: int):
    user_id = _user_id(_session_user(request))
    if not user_id:
        raise HTTPException(status_code=401, detail="請先登入。")
    try:
        context = await run_in_threadpool(clear_boss_guess, user_id, int(order_id))
    except (LookupError, PermissionError, ValueError) as exc:
        raise _json_error(exc) from exc
    return _public_payload(context)


@router.post("/me/orders/{order_id}/love-delta/guess/companion")
async def love_delta_companion_guess(
    request: Request,
    order_id: int,
    payload: LoveDeltaCompanionGuessPayload,
):
    user_id = _user_id(_session_user(request))
    if not user_id:
        raise HTTPException(status_code=401, detail="請先登入。")
    try:
        context = await run_in_threadpool(
            save_companion_guess,
            user_id,
            int(order_id),
            guess=payload.guess,
        )
    except (LookupError, PermissionError, ValueError) as exc:
        raise _json_error(exc) from exc
    return _public_payload(context)


@router.delete("/me/orders/{order_id}/love-delta/guess/companion")
async def love_delta_companion_guess_clear(request: Request, order_id: int):
    user_id = _user_id(_session_user(request))
    if not user_id:
        raise HTTPException(status_code=401, detail="請先登入。")
    try:
        context = await run_in_threadpool(clear_companion_guess, user_id, int(order_id))
    except (LookupError, PermissionError, ValueError) as exc:
        raise _json_error(exc) from exc
    return _public_payload(context)


@router.post("/me/orders/{order_id}/love-delta/bans")
async def love_delta_bans(
    request: Request,
    order_id: int,
    payload: LoveDeltaBansPayload,
):
    user_id = _user_id(_session_user(request))
    if not user_id:
        raise HTTPException(status_code=401, detail="請先登入。")
    try:
        context = await run_in_threadpool(
            save_bans,
            user_id,
            int(order_id),
            payload.bans,
        )
    except (LookupError, PermissionError, ValueError) as exc:
        raise _json_error(exc) from exc
    return _public_payload(context)


@router.post("/me/orders/{order_id}/love-delta/settings/{kind}")
async def love_delta_unlock_setting(
    request: Request,
    order_id: int,
    kind: str,
    payload: LoveDeltaUnlockPayload,
):
    if kind not in {"suffix", "nickname"}:
        raise HTTPException(status_code=404, detail="找不到此設定。")
    user_id = _user_id(_session_user(request))
    if not user_id:
        raise HTTPException(status_code=401, detail="請先登入。")
    try:
        context = await run_in_threadpool(
            save_unlock_text,
            user_id,
            int(order_id),
            kind=kind,
            value=payload.value,
        )
    except (LookupError, PermissionError, ValueError) as exc:
        raise _json_error(exc) from exc
    return _public_payload(context)


@router.post("/me/orders/{order_id}/love-delta/loadout")
async def love_delta_loadout(
    request: Request,
    order_id: int,
    payload: LoveDeltaLoadoutPayload,
):
    user_id = _user_id(_session_user(request))
    if not user_id:
        raise HTTPException(status_code=401, detail="請先登入。")
    try:
        context = await run_in_threadpool(
            save_next_loadout,
            user_id,
            int(order_id),
            agent=payload.agent,
            weapon=payload.weapon,
        )
    except (LookupError, PermissionError, ValueError) as exc:
        raise _json_error(exc) from exc
    return _public_payload(context)


@router.post("/me/orders/{order_id}/love-delta/settle")
async def love_delta_settle(
    request: Request,
    order_id: int,
    payload: LoveDeltaSettlePayload,
):
    user_id = _user_id(_session_user(request))
    if not user_id:
        raise HTTPException(status_code=401, detail="請先登入。")
    try:
        context = await run_in_threadpool(
            settle_love_delta_round,
            user_id,
            int(order_id),
            expected_round=payload.expected_round,
            result=payload.result,
            extraction_tier=payload.extraction_tier,
        )
    except (LookupError, PermissionError, ValueError) as exc:
        raise _json_error(exc) from exc
    return _public_payload(context)


@router.post("/me/orders/{order_id}/love-delta/undo")
async def love_delta_undo(request: Request, order_id: int):
    user_id = _user_id(_session_user(request))
    if not user_id:
        raise HTTPException(status_code=401, detail="請先登入。")
    try:
        context = await run_in_threadpool(
            undo_last_love_delta_event,
            user_id,
            int(order_id),
        )
    except (LookupError, PermissionError, ValueError) as exc:
        raise _json_error(exc) from exc
    return _public_payload(context)
