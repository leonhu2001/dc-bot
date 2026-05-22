from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware

from web.app.config import config
from web.app.routers.auth import router as auth_router

APP_DIR = Path(__file__).resolve().parent
TEMPLATES_DIR = APP_DIR / "templates"
STATIC_DIR = APP_DIR / "static"

app = FastAPI(title="MW Worker Dashboard")

app.add_middleware(
    SessionMiddleware,
    secret_key=config.WEB_SECRET_KEY,
    same_site="lax",
    https_only=False,
)

app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

app.include_router(auth_router)


@app.get("/")
async def index(request: Request):
    return templates.TemplateResponse(
        request=request,
        name="login.html",
        context={
            "title": "魔丸打手系統",
            "user": request.session.get("user"),
        },
    )


@app.get("/admin")
async def admin_dashboard(request: Request):
    user = request.session.get("user")

    if not user:
        return templates.TemplateResponse(
            request=request,
            name="no_access.html",
            context={
                "title": "請先登入",
                "message": "請先使用 Discord 登入。",
            },
            status_code=401,
        )

    if not user.get("is_admin"):
        return templates.TemplateResponse(
            request=request,
            name="no_access.html",
            context={
                "title": "沒有權限",
                "message": "你沒有總控後台權限。",
            },
            status_code=403,
        )

    return templates.TemplateResponse(
        request=request,
        name="admin.html",
        context={
            "title": "總控後台",
            "user": user,
        },
    )


@app.get("/dispatch")
async def dispatch_dashboard(request: Request):
    user = request.session.get("user")

    if not user:
        return templates.TemplateResponse(
            request=request,
            name="no_access.html",
            context={
                "title": "請先登入",
                "message": "請先使用 Discord 登入。",
            },
            status_code=401,
        )

    if not user.get("is_worker") and not user.get("is_admin"):
        return templates.TemplateResponse(
            request=request,
            name="no_access.html",
            context={
                "title": "沒有權限",
                "message": "你沒有派單頁面權限。",
            },
            status_code=403,
        )

    return templates.TemplateResponse(
        request=request,
        name="dispatch.html",
        context={
            "title": "派單頁面",
            "user": user,
        },
    )


@app.get("/no-access")
async def no_access(request: Request):
    return templates.TemplateResponse(
        request=request,
        name="no_access.html",
        context={
            "title": "沒有權限",
            "message": "你的 Discord 身分組目前沒有網站使用權限。",
        },
        status_code=403,
    )


@app.get("/health")
async def health():
    return {
        "ok": True,
        "service": "mw-worker-dashboard",
    }