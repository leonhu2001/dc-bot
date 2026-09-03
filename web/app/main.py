from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware

from shared.db import create_all_tables
from services.topups import ensure_topup_tables
from web.app.config import config
from web.app.routers.admin import router as admin_router
from web.app.routers.admin_staff import router as admin_staff_router
from web.app.routers.admin_audit import router as admin_audit_router
from web.app.routers.admin_payouts import router as admin_payouts_router
from web.app.routers.admin_payout_summary import router as admin_payout_summary_router
from web.app.routers.admin_payout_exports import router as admin_payout_exports_router
from web.app.routers.auth import router as auth_router
from web.app.routers.site import router as site_router
from web.app.routers.dispatch import router as dispatch_router
from web.app.routers.payouts import router as payouts_router
from web.app.routers.order_history import router as order_history_router
from web.app.routers.topups import router as topups_router
from web.app.routers import admin_staff_profiles
from web.app.routers import admin_payouts_grouped

APP_DIR = Path(__file__).resolve().parent
TEMPLATES_DIR = APP_DIR / "templates"
STATIC_DIR = APP_DIR / "static"

app = FastAPI(title="MW Worker Dashboard")

app.add_middleware(
    SessionMiddleware,
    secret_key=config.WEB_SECRET_KEY,
    same_site="lax",
    https_only=config.WEB_COOKIE_HTTPS_ONLY,
)

app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

app.include_router(auth_router)
app.include_router(site_router)
app.include_router(topups_router)
app.include_router(admin_staff_profiles.router)
app.include_router(admin_router)
app.include_router(admin_staff_router)
app.include_router(admin_audit_router)
app.include_router(admin_payouts_router)
app.include_router(admin_payout_summary_router)
app.include_router(admin_payout_exports_router)
app.include_router(dispatch_router)
app.include_router(payouts_router)
app.include_router(order_history_router)
app.include_router(admin_payouts_grouped.router)


@app.on_event("startup")
async def startup_event():
    create_all_tables()
    ensure_topup_tables()


def get_current_user(request: Request) -> dict | None:
    return request.session.get("user")


@app.get("/no-access")
async def no_access(request: Request):
    return templates.TemplateResponse(
        request=request,
        name="no_access.html",
        context={
            "title": "沒有權限",
            "message": "你的 Discord 身分組目前沒有網站使用權限。",
            "user": get_current_user(request),
        },
        status_code=403,
    )


@app.get("/health")
async def health():
    return {
        "ok": True,
        "service": "mw-worker-dashboard",
    }

from web.app.routers import dispatch_state
from web.app.routers import admin_wallets
app.include_router(dispatch_state.router)
app.include_router(admin_wallets.router)

# AUTO DISCORD AVATAR ROUTER
try:
    from web.app.routers.discord_avatars import router as discord_avatars_router
    app.include_router(discord_avatars_router)
except Exception as exc:
    print(f"[discord_avatars] router load failed: {exc}")



# AUTO ORDER REVIEWS ROUTER
try:
    from web.app.routers.admin_reviews import router as admin_reviews_router
    app.include_router(admin_reviews_router)
except Exception as exc:
    print(f"[admin_reviews] router load failed: {exc}")
