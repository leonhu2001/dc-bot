from __future__ import annotations

from pathlib import Path
from urllib.parse import urlencode

from fastapi import APIRouter, Form, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from starlette.concurrency import run_in_threadpool

from web.app.routers.admin_common import require_admin_user
from web.app.services.lottery_admin import (
    build_lottery_admin_snapshot,
    draw_campaign,
    publish_campaign,
    save_campaign_draft,
)


router = APIRouter(tags=["admin-lottery"])
TEMPLATES_DIR = Path(__file__).resolve().parents[1] / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


def _redirect(*, message: str = "", error: str = "") -> RedirectResponse:
    params: dict[str, str] = {}
    if message:
        params["message"] = message
    if error:
        params["error"] = error
    query = "?" + urlencode(params) if params else ""
    return RedirectResponse(url="/admin/lottery" + query, status_code=303)


def _actor_id(user: dict) -> str:
    return str(user.get("id") or "").strip()


@router.get("/admin/lottery")
async def admin_lottery(request: Request, message: str = "", error: str = ""):
    user = require_admin_user(request)
    if not user:
        return RedirectResponse(url="/service", status_code=303)

    snapshot = await run_in_threadpool(build_lottery_admin_snapshot)
    return templates.TemplateResponse(
        request=request,
        name="admin_lottery.html",
        context={
            "title": "抽獎管理｜魔丸娛樂",
            "user": user,
            "snapshot": snapshot,
            "message": str(message or ""),
            "error": str(error or ""),
        },
    )


@router.post("/admin/lottery/draft")
async def admin_save_lottery_draft(
    request: Request,
    title: str = Form(...),
    description: str = Form(default=""),
    template_id: list[int] = Form(...),
    winner_count: list[int] = Form(...),
):
    user = require_admin_user(request)
    if not user:
        return RedirectResponse(url="/service", status_code=303)
    try:
        campaign = await run_in_threadpool(
            save_campaign_draft,
            title=title,
            description=description,
            template_ids=[int(value) for value in template_id],
            winner_counts=[int(value) for value in winner_count],
            actor_discord_id=_actor_id(user),
        )
    except (ValueError, TypeError) as exc:
        return _redirect(error=str(exc))
    except Exception as exc:
        return _redirect(error=f"儲存抽獎設定失敗：{exc}")
    return _redirect(message=f"抽獎設定已儲存，共 {len(campaign['prizes'])} 個獎項。")


@router.post("/admin/lottery/publish")
async def admin_publish_lottery(request: Request):
    user = require_admin_user(request)
    if not user:
        return RedirectResponse(url="/service", status_code=303)
    try:
        campaign = await run_in_threadpool(
            publish_campaign,
            actor_discord_id=_actor_id(user),
        )
    except (ValueError, TypeError) as exc:
        return _redirect(error=str(exc))
    except Exception as exc:
        return _redirect(error=f"發布抽獎失敗：{exc}")
    return _redirect(message=f"抽獎已發布到指定頻道，訊息 ID：{campaign['message_id']}。")


@router.post("/admin/lottery/draw")
async def admin_draw_lottery(
    request: Request,
    prize_id: int = Form(default=0),
):
    user = require_admin_user(request)
    if not user:
        return RedirectResponse(url="/service", status_code=303)
    try:
        result = await run_in_threadpool(
            draw_campaign,
            actor_discord_id=_actor_id(user),
            prize_id=(int(prize_id) or None),
        )
    except (ValueError, TypeError) as exc:
        return _redirect(error=str(exc))
    except Exception as exc:
        return _redirect(error=f"開獎失敗：{exc}")

    winner_total = sum(len(row["winner_ids"]) for row in result["results"])
    return _redirect(
        message=(
            f"開獎完成：{result['participant_count']} 人參加，"
            f"本次共抽出 {winner_total} 位，福利券已自動發放。"
        )
    )


__all__ = ["router"]
