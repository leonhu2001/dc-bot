from pathlib import Path
import secrets
from urllib.parse import quote, urlsplit

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import PlainTextResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.concurrency import run_in_threadpool
from starlette.middleware.sessions import SessionMiddleware

from shared.db import create_all_tables
from services.topups import ensure_topup_tables
from services.payment_reviews import ensure_payment_review_tables
from services.wallet_service import ensure_wallet_tables
from services.ticket_archives import ensure_ticket_archive_tables
from services.support_calls import ensure_support_call_tables
from services.smart_dispatch import ensure_smart_dispatch_tables
from services.web_support_chat import ensure_web_support_tables
from services.ai_support_knowledge import ensure_ai_support_knowledge_tables
from services.order_rule_store import ensure_order_rule_store
from services.promotion_benefits import ensure_promotion_benefit_tables
from services.vip_timer_policy_v5 import install_vip_timer_policy_v5
from web.app.config import config
from web.app.routers.admin import router as admin_router
from web.app.routers.admin_staff import router as admin_staff_router
from web.app.routers.admin_audit import router as admin_audit_router
from web.app.routers.admin_system import router as admin_system_router
from web.app.routers.admin_global_search import router as admin_global_search_router
from web.app.routers.marketing import router as marketing_router
from web.app.routers.admin_support_calls import router as admin_support_calls_router
from web.app.routers.admin_ai_support_knowledge import router as admin_ai_support_knowledge_router
from web.app.routers.admin_ai_operations import router as admin_ai_operations_router
from web.app.routers.admin_anomalies import router as admin_anomalies_router
from web.app.routers.admin_accounting_reconciliation import router as admin_accounting_reconciliation_router
from web.app.routers.admin_order_rules import router as admin_order_rules_router
from web.app.routers.admin_centers import router as admin_centers_router
from web.app.routers.admin_benefits import router as admin_benefits_router
from web.app.routers.admin_payouts import router as admin_payouts_router
from web.app.routers.admin_payout_summary import router as admin_payout_summary_router
from web.app.routers.admin_operations_report import router as admin_operations_report_router
from web.app.routers.admin_payout_exports import router as admin_payout_exports_router
from web.app.routers.auth import router as auth_router
from web.app.routers.site import router as site_router
from web.app.routers.game_tools import router as game_tools_router
from web.app.routers.web_support import router as web_support_router
from web.app.routers.dispatch import router as dispatch_router
from web.app.routers.payouts import router as payouts_router
from web.app.routers.order_history import router as order_history_router
from web.app.routers.store_bindings import router as store_bindings_router
from web.app.routers.topups import router as topups_router
from web.app.routers.payment_reviews import router as payment_reviews_router
from web.app.routers.ticket_archives import router as ticket_archives_router
from web.app.routers.dispatch_state import router as dispatch_state_router
from web.app.routers.admin_wallets import router as admin_wallets_router
from web.app.routers.discord_avatars import router as discord_avatars_router
from web.app.routers import admin_staff_profiles
from web.app.routers import admin_staff_profiles_ui
from web.app.routers import admin_payouts_grouped
from web.app.services.admin_role_cache import get_admin_member_role_ids
from web.app.services.health_check import check_runtime_dependencies
from web.app.services.http_security import (
    build_content_security_policy,
    apply_live_access,
    csrf_source_allowed,
    is_admin_path,
    is_manager_only_admin_path,
    revoke_staff_access,
    sanitize_csv_response,
)
from web.app.services.marketing_funnel import ensure_marketing_tables
from web.app.services.rate_limit import rate_limit_allowed
from web.app.services.web_security import (
    csrf_token_from_request_parts,
    csrf_tokens_match,
    ensure_csrf_token,
    has_recent_auth,
    is_sensitive_path,
    requires_csrf,
    should_no_store,
)

APP_DIR = Path(__file__).resolve().parent
TEMPLATES_DIR = APP_DIR / "templates"
STATIC_DIR = APP_DIR / "static"

app = FastAPI(title="MW Worker Dashboard")


@app.middleware("http")
async def security_and_refresh_access(request: Request, call_next):
    csp_nonce = secrets.token_urlsafe(24)
    request.state.csp_nonce = csp_nonce

    allowed, retry_after = rate_limit_allowed(request)
    if not allowed:
        return PlainTextResponse(
            "Too Many Requests",
            status_code=429,
            headers={"Retry-After": str(retry_after)},
        )

    # 舊版 GET /admin/staff/sync 會改資料。保留 route 以免舊連結 404，
    # 但 middleware 一律拒絕 GET，只允許受 CSRF 保護的 POST。
    if request.method.upper() == "GET" and request.url.path == "/admin/staff/sync":
        return PlainTextResponse(
            "Method Not Allowed",
            status_code=405,
            headers={"Allow": "POST"},
        )

    if not csrf_source_allowed(
        request,
        allowed_origins=config.WEB_ALLOWED_ORIGINS,
    ):
        return PlainTextResponse("CSRF source validation failed", status_code=403)

    expected_csrf = ensure_csrf_token(request.session)

    if requires_csrf(request.method):
        body = await request.body()
        supplied_csrf = csrf_token_from_request_parts(
            header_token=request.headers.get("x-csrf-token"),
            body=body,
            content_type=request.headers.get("content-type"),
        )

        if not csrf_tokens_match(expected_csrf, supplied_csrf):
            return PlainTextResponse(
                "CSRF token validation failed",
                status_code=403,
            )

    if is_admin_path(request.url.path):
        user = request.session.get("user")

        if not user and request.method.upper() in {"GET", "HEAD"}:
            next_path = request.url.path
            if request.url.query:
                next_path += "?" + request.url.query
            return RedirectResponse(
                url="/auth/discord/login?next=" + quote(next_path, safe=""),
                status_code=303,
            )

        if user:
            refreshed_user = dict(user)
            discord_id = str(refreshed_user.get("id") or "").strip()

            if not discord_id:
                refreshed_user = revoke_staff_access(refreshed_user)
            else:
                try:
                    role_ids = await get_admin_member_role_ids(
                        discord_id,
                        force_refresh=(
                            is_sensitive_path(request.url.path)
                            or requires_csrf(request.method)
                        ),
                    )
                    refreshed_user = apply_live_access(
                        refreshed_user,
                        role_ids,
                    )
                except Exception as exc:
                    # Security-sensitive paths fail closed. Do not preserve stale
                    # manager/customer-service privileges when Discord is unavailable.
                    refreshed_user = revoke_staff_access(refreshed_user)
                    print(
                        "[admin_access_refresh_failed]",
                        type(exc).__name__,
                    )

            request.session["user"] = refreshed_user

            if (
                is_manager_only_admin_path(request.url.path)
                and not refreshed_user.get("is_manager")
            ):
                return PlainTextResponse(
                    "此功能僅限總管使用。",
                    status_code=403,
                )

            if (
                refreshed_user.get("is_admin")
                and is_sensitive_path(request.url.path)
                and not has_recent_auth(
                    request.session,
                    max_age_seconds=config.WEB_RECENT_AUTH_SECONDS,
                )
            ):
                if request.method.upper() == "GET":
                    next_path = request.url.path
                    if request.url.query:
                        next_path += "?" + request.url.query
                else:
                    next_path = "/admin"
                    referer = str(request.headers.get("referer") or "").strip()
                    if referer:
                        try:
                            parsed_referer = urlsplit(referer)
                            if parsed_referer.path.startswith("/admin"):
                                next_path = parsed_referer.path
                                if parsed_referer.query:
                                    next_path += "?" + parsed_referer.query
                        except Exception:
                            pass

                return RedirectResponse(
                    url=(
                        "/auth/discord/login?reauth=1&next="
                        + quote(next_path, safe="")
                    ),
                    status_code=303,
                )

    response = await call_next(request)
    response = await sanitize_csv_response(response)

    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    response.headers.setdefault(
        "Strict-Transport-Security",
        "max-age=31536000",
    )
    response.headers.setdefault("Content-Security-Policy", build_content_security_policy(csp_nonce))
    response.headers.setdefault(
        "Permissions-Policy",
        "camera=(), microphone=(), geolocation=(), payment=()",
    )
    response.headers.setdefault("Cross-Origin-Opener-Policy", "same-origin")
    response.headers.setdefault("Cross-Origin-Resource-Policy", "same-site")

    if should_no_store(
        request.url.path,
        authenticated=bool(request.session.get("user")),
    ):
        response.headers["Cache-Control"] = "no-store, private, max-age=0"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"

    return response


# SessionMiddleware must wrap the security middleware so request.session exists
# before live authorization runs. Keep this registration after the decorator.
app.add_middleware(
    SessionMiddleware,
    secret_key=config.WEB_SECRET_KEY,
    same_site="lax",
    https_only=config.WEB_COOKIE_HTTPS_ONLY,
    # Signed-cookie sessions are integrity protected, not encrypted. Keep the
    # lifetime bounded and never place OAuth tokens/secrets in the session.
    max_age=60 * 60 * 12,
)

app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

app.include_router(auth_router)
app.include_router(site_router)
app.include_router(game_tools_router)
app.include_router(web_support_router)
app.include_router(topups_router)
app.include_router(payment_reviews_router)
app.include_router(ticket_archives_router)
app.include_router(admin_staff_profiles_ui.router)
app.include_router(admin_staff_profiles.router)
app.include_router(admin_router)
app.include_router(admin_staff_router)
app.include_router(admin_audit_router)
app.include_router(admin_system_router)
app.include_router(admin_global_search_router)
app.include_router(marketing_router)
app.include_router(admin_support_calls_router)
app.include_router(admin_ai_support_knowledge_router)
app.include_router(admin_ai_operations_router)
app.include_router(admin_anomalies_router)
app.include_router(admin_accounting_reconciliation_router)
app.include_router(admin_order_rules_router)
app.include_router(admin_centers_router)
app.include_router(admin_benefits_router)
app.include_router(admin_payouts_router)
app.include_router(admin_operations_report_router)
app.include_router(admin_payout_summary_router)
app.include_router(admin_payout_exports_router)
app.include_router(dispatch_router)
app.include_router(payouts_router)
app.include_router(order_history_router)
app.include_router(store_bindings_router)
app.include_router(admin_payouts_grouped.router)


@app.get("/discord/login", include_in_schema=False)
async def legacy_discord_login_redirect():
    # 舊版員工中心仍可能導向這個網址；統一送進目前的 Discord OAuth，
    # 並在登入完成後回到員工中心，避免使用者落到 FastAPI 404 JSON。
    return RedirectResponse(
        url="/auth/discord/login?next=/employee",
        status_code=303,
    )


@app.on_event("startup")
async def startup_event():
    create_all_tables()
    ensure_topup_tables()
    ensure_payment_review_tables()
    ensure_wallet_tables()
    ensure_ticket_archive_tables()
    ensure_support_call_tables()
    ensure_smart_dispatch_tables()
    ensure_web_support_tables()
    ensure_ai_support_knowledge_tables()
    ensure_marketing_tables()
    ensure_order_rule_store()
    ensure_promotion_benefit_tables()
    # Keep VIP timer catalog/discount/loyalty exclusions identical in the web
    # process, especially when admin reconciliation rebuilds loyalty progress.
    install_vip_timer_policy_v5()

    if config.AI_SUPPORT_API_KEY:
        print(
            "[support-ai] external AI enabled "
            f"model={config.AI_SUPPORT_MODEL}",
            flush=True,
        )
    else:
        print(
            "[support-ai] external AI not configured; "
            "using safe FAQ fallback",
            flush=True,
        )


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
    try:
        checks = await run_in_threadpool(
            check_runtime_dependencies,
            STATIC_DIR,
        )
    except Exception as exc:
        print("[health_check_failed]", type(exc).__name__)
        raise HTTPException(
            status_code=503,
            detail="service not ready",
        ) from exc

    return {
        "ok": True,
        "service": "mw-worker-dashboard",
        **checks,
    }


app.include_router(dispatch_state_router)
app.include_router(admin_wallets_router)
app.include_router(discord_avatars_router)