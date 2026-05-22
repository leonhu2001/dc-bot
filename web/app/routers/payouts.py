from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.templating import Jinja2Templates

from shared.db import SessionLocal
from web.app.services.payout_service import (
    build_payout_summary,
    list_customer_service_payouts_for_user,
    list_worker_payouts_for_user,
)

router = APIRouter(tags=["payouts"])

TEMPLATES_DIR = Path(__file__).resolve().parents[1] / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


def get_current_user(request: Request) -> dict | None:
    return request.session.get("user")


@router.get("/my/payouts")
async def my_payouts(request: Request):
    user = get_current_user(request)

    if not user:
        return templates.TemplateResponse(
            request=request,
            name="no_access.html",
            context={
                "title": "請先登入",
                "message": "請先使用 Discord 登入。",
                "user": None,
            },
            status_code=401,
        )

    if not user.get("is_worker") and not user.get("is_admin"):
        return templates.TemplateResponse(
            request=request,
            name="no_access.html",
            context={
                "title": "沒有權限",
                "message": "你沒有查看分潤頁面的權限。",
                "user": user,
            },
            status_code=403,
        )

    db = SessionLocal()

    try:
        worker_rows = list_worker_payouts_for_user(
            db,
            worker_discord_id=str(user["id"]),
        )
        customer_service_rows = list_customer_service_payouts_for_user(
            db,
            customer_service_discord_id=str(user["id"]),
        )
        summary = build_payout_summary(
            worker_rows=worker_rows,
            customer_service_rows=customer_service_rows,
        )
    finally:
        db.close()

    return templates.TemplateResponse(
        request=request,
        name="my_payouts.html",
        context={
            "title": "我的分潤",
            "user": user,
            "worker_rows": worker_rows,
            "customer_service_rows": customer_service_rows,
            "summary": summary,
        },
    )