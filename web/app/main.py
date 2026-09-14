from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.concurrency import run_in_threadpool
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
from web.app.routers import admin_staff_profiles_ui
from web.app.routers import admin_payouts_grouped
from web.app.services.discord_service import get_dashboard_access, get_member_role_ids

APP_DIR = Path(__file__).resolve().parent
TEMPLATES_DIR = APP_DIR / "templates"
STATIC_DIR = APP_DIR / "static"

app = FastAPI(title="MW Worker Dashboard")


def _is_admin_path(path: str) -> bool:
    return path == "/admin" or path.startswith("/admin/")


def _apply_live_access(user: dict, role_ids: list[str]) -> dict:
    access = get_dashboard_access(role_ids)
    is_customer_service = bool(access.get("is_customer_service", False))
    is_admin = bool(access.get("is_admin", False) or is_customer_service)
    is_worker = bool(access.get("is_worker", False))
    is_companion = bool(access.get("is_companion", False))

    user.update(
        {
            "role_ids": list(role_ids),
            "is_admin": is_admin,
            "is_customer_service": is_customer_service,
            "is_worker": is_worker,
            "is_companion": is_companion,
            "is_employee": bool(
                is_admin
                or is_customer_service
                or is_worker
                or is_companion
            ),
        }
    )
    return user


def _revoke_staff_access(user: dict) -> dict:
    user.update(
        {
            "role_ids": [],
            "is_admin": False,
            "is_customer_service": False,
            "is_worker": False,
            "is_companion": False,
            "is_employee": False,
        }
    )
    return user


@app.middleware("http")
async def refresh_admin_access(request: Request, call_next):
    """Never trust the staff/admin flags stored at OAuth login time.

    Every request entering /admin re-checks the member's current Discord roles.
    If Discord cannot be checked, fail closed for staff privileges instead of
    continuing to trust a stale privileged session.
    """
    if _is_admin_path(request.url.path):
        user = request.session.get("user")

        if user:
            refreshed_user = dict(user)
            discord_id = str(refreshed_user.get("id") or "").strip()

            if not discord_id:
                refreshed_user = _revoke_staff_access(refreshed_user)
            else:
                try:
                    role_ids = await run_in_threadpool(
                        get_member_role_ids,
                        discord_id,
                    )
                    refreshed_user = _apply_live_access(
                        refreshed_user,
                        role_ids,
                    )
                except Exception as exc:
                    # Security-sensitive paths fail closed. Do not preserve a
                    # previous is_admin=True snapshot when Discord is unavailable.
                    refreshed_user = _revoke_staff_access(refreshed_user)
                    print(
                        "[admin_access_refresh_failed]",
                        type(exc).__name__,
                    )

            request.session["user"] = refreshed_user

    return await call_next(request)


# SessionMiddleware must wrap refresh_admin_access so request.session exists
# before the authorization middleware runs. Keep this registration after the
# @app.middleware declaration above.
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
app.include_router(admin_staff_profiles_ui.router)
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
