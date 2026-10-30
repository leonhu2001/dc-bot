from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates

from pathlib import Path

from web.app.services.seo import build_seo


router = APIRouter(
    prefix="/games/delta-force/market",
    tags=["delta-market"],
)

TEMPLATES_DIR = Path(__file__).resolve().parents[1] / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


# 第一版先只建立網站與資料介面邊界，不在正式頁面顯示假價格。
# 等行情來源確認後，這裡改成呼叫 services/market/ 的 query service。
PREVIEW_ITEMS = [
    {
        "slug": "m995",
        "name": "M995",
        "caliber": "5.56x45mm",
        "tier": "高階彈藥",
    },
    {
        "slug": "m62",
        "name": "M62",
        "caliber": "7.62x51mm",
        "tier": "高階彈藥",
    },
    {
        "slug": "7n31",
        "name": "7N31",
        "caliber": "9x19mm",
        "tier": "高階彈藥",
    },
]


def _current_user(request: Request) -> dict | None:
    return request.session.get("user")


@router.get("")
async def delta_market_home(request: Request):
    seo = build_seo(
        path="/games/delta-force/market",
        title="台服子彈行情｜魔丸娛樂",
        description="查看三角洲行動台服子彈行情、價格趨勢、推薦品項與價格提醒。",
    )

    return templates.TemplateResponse(
        request=request,
        name="game_delta_market.html",
        context={
            "request": request,
            "user": _current_user(request),
            "title": seo["title"],
            "seo": seo,
            "page_name": "delta_market",
            "items": PREVIEW_ITEMS,
            "market_ready": False,
        },
    )


@router.get("/items/{item_slug}")
async def delta_market_item(request: Request, item_slug: str):
    item = next(
        (
            row
            for row in PREVIEW_ITEMS
            if row["slug"] == str(item_slug).strip().lower()
        ),
        None,
    )

    if item is None:
        return RedirectResponse(
            url="/games/delta-force/market",
            status_code=303,
        )

    seo = build_seo(
        path=f"/games/delta-force/market/items/{item['slug']}",
        title=f"{item['name']} 台服子彈行情｜魔丸娛樂",
        description=(
            f"查看三角洲行動台服 {item['caliber']} {item['name']} "
            "價格走勢、歷史區間與價格提醒。"
        ),
    )

    return templates.TemplateResponse(
        request=request,
        name="game_delta_market_item.html",
        context={
            "request": request,
            "user": _current_user(request),
            "title": seo["title"],
            "seo": seo,
            "page_name": "delta_market_item",
            "item": item,
            "market_ready": False,
        },
    )
