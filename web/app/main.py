from collections import deque
import csv
import io
import time
from pathlib import Path
from urllib.parse import urlsplit

from fastapi import FastAPI, Request
from fastapi.responses import PlainTextResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.concurrency import run_in_threadpool
from starlette.middleware.sessions import SessionMiddleware

from shared.db import create_all_tables
from services.topups import ensure_topup_tables
from services.payment_reviews import ensure_payment_review_tables
from services.wallet_service import ensure_wallet_tables
from services.ticket_archives import ensure_ticket_archive_tables
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
from web.app.routers.payment_reviews import router as payment_reviews_router
from web.app.routers.ticket_archives import router as ticket_archives_router
from web.app.routers import admin_staff_profiles
from web.app.routers import admin_staff_profiles_ui
from web.app.routers import admin_payouts_grouped
from web.app.services.discord_service import get_dashboard_access, get_member_role_ids

APP_DIR = Path(__file__).resolve().parent
TEMPLATES_DIR = APP_DIR / "templates"
STATIC_DIR = APP_DIR / "static"

app = FastAPI(title="MW Worker Dashboard")

# ---------------------------------------------------------------------------
# Security policy helpers
# ---------------------------------------------------------------------------

_UNSAFE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}
_MANAGER_ONLY_ADMIN_PREFIXES = (
    "/admin/wallets",
    "/admin/audit",
    # 客服可以查看分潤與匯出資料；只有下列會改發放狀態的端點限總管。
    "/admin/payouts/summary/mark-paid",
    "/admin/payouts/summary/mark-unpaid",
    "/admin/payouts/summary/person-status",
)
_RATE_BUCKETS: dict[tuple[str, str], deque[float]] = {}
_RATE_REQUEST_COUNTER = 0

# 目前模板仍有不少 inline style/script，因此 CSP 保留 unsafe-inline，
# 但把 object/frame/base/form/connect 等高風險來源收緊，不破壞現有 UI。
_CONTENT_SECURITY_POLICY = "; ".join(
    (
        "default-src 'self'",
        "base-uri 'self'",
        "object-src 'none'",
        "frame-ancestors 'none'",
        "form-action 'self'",
        "script-src 'self' 'unsafe-inline'",
        "style-src 'self' 'unsafe-inline'",
        "img-src 'self' data: https:",
        "font-src 'self' data:",
        "connect-src 'self'",
        "upgrade-insecure-requests",
    )
)


def _is_admin_path(path: str) -> bool:
    return path == "/admin" or path.startswith("/admin/")


def _is_manager_only_admin_path(path: str) -> bool:
    return any(
        path == prefix or path.startswith(prefix + "/")
        for prefix in _MANAGER_ONLY_ADMIN_PREFIXES
    )


def _client_ip(request: Request) -> str:
    # Uvicorn 只綁 127.0.0.1，公開流量必須經 Nginx/Cloudflare；因此可優先
    # 使用 Cloudflare 正規化後的來源 IP。沒有該 header 時才 fallback socket IP。
    cloudflare_ip = str(request.headers.get("cf-connecting-ip") or "").strip()
    if cloudflare_ip:
        return cloudflare_ip[:80]

    forwarded = str(request.headers.get("x-forwarded-for") or "").split(",", 1)[0].strip()
    if forwarded:
        return forwarded[:80]

    if request.client is not None:
        return str(request.client.host or "unknown")[:80]
    return "unknown"


def _rate_limit_spec(request: Request) -> tuple[str, int, int] | None:
    path = request.url.path

    if path == "/health" or path.startswith("/static/"):
        return None

    if path.startswith("/auth/"):
        return ("auth", 30, 60)

    if path.startswith("/discord-avatar/"):
        return ("avatar", 120, 60)

    if request.method.upper() in _UNSAFE_METHODS and _is_admin_path(path):
        return ("admin-write", 60, 60)

    if request.method.upper() in _UNSAFE_METHODS:
        return ("write", 90, 60)

    # Broad per-IP ceiling so scanners cannot issue unbounded dynamic requests.
    return ("general", 600, 60)


def _rate_limit_allowed(request: Request) -> tuple[bool, int]:
    global _RATE_REQUEST_COUNTER

    spec = _rate_limit_spec(request)
    if spec is None:
        return True, 0

    bucket_name, limit, window_seconds = spec
    now = time.monotonic()
    cutoff = now - window_seconds
    key = (_client_ip(request), bucket_name)
    bucket = _RATE_BUCKETS.setdefault(key, deque())

    while bucket and bucket[0] <= cutoff:
        bucket.popleft()

    if len(bucket) >= limit:
        retry_after = max(1, int(window_seconds - (now - bucket[0])))
        return False, retry_after

    bucket.append(now)
    _RATE_REQUEST_COUNTER += 1

    # Keep attacker-created IP buckets bounded in memory.
    if _RATE_REQUEST_COUNTER % 500 == 0 and len(_RATE_BUCKETS) > 2000:
        for old_key, old_bucket in list(_RATE_BUCKETS.items()):
            while old_bucket and old_bucket[0] <= cutoff:
                old_bucket.popleft()
            if not old_bucket:
                _RATE_BUCKETS.pop(old_key, None)

    return True, 0


def _origin_from_referer(value: str) -> str:
    try:
        parsed = urlsplit(str(value or ""))
    except Exception:
        return ""

    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return ""
    return f"{parsed.scheme}://{parsed.netloc}".rstrip("/")


def _csrf_source_allowed(request: Request) -> bool:
    if request.method.upper() not in _UNSAFE_METHODS:
        return True

    fetch_site = str(request.headers.get("sec-fetch-site") or "").lower().strip()
    if fetch_site == "cross-site":
        return False

    allowed_origins = {origin.rstrip("/") for origin in config.WEB_ALLOWED_ORIGINS}

    origin = str(request.headers.get("origin") or "").strip().rstrip("/")
    if origin:
        return origin in allowed_origins

    referer_origin = _origin_from_referer(request.headers.get("referer") or "")
    if referer_origin:
        return referer_origin in allowed_origins

    # Browser state-changing requests must identify a same-site source. This also
    # blocks blind form POST CSRF even when a client omits Origin.
    return False


def _apply_live_access(user: dict, role_ids: list[str]) -> dict:
    access = get_dashboard_access(role_ids)
    is_manager = bool(
        access.get("is_manager", False)
        or access.get("is_admin", False)
    )
    is_customer_service = bool(access.get("is_customer_service", False))
    is_admin = bool(is_manager or is_customer_service)
    is_worker = bool(access.get("is_worker", False))
    is_companion = bool(access.get("is_companion", False))

    user.update(
        {
            "role_ids": list(role_ids),
            "is_manager": is_manager,
            # 舊 route 相容：營運後台仍接受總管或客服。
            "is_admin": is_admin,
            "is_customer_service": is_customer_service,
            "is_worker": is_worker,
            "is_companion": is_companion,
            "is_employee": bool(
                is_manager
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
            "is_manager": False,
            "is_admin": False,
            "is_customer_service": False,
            "is_worker": False,
            "is_companion": False,
            "is_employee": False,
        }
    )
    return user


def _safe_csv_cell(value: str) -> str:
    text = str(value or "")
    check = text.lstrip()
    if (
        check.startswith(("=", "+", "-", "@"))
        or text.startswith(("\t", "\r", "\n"))
    ):
        return "'" + text
    return text


async def _sanitize_csv_response(response):
    content_type = str(response.headers.get("content-type") or "").lower()
    if "text/csv" not in content_type or not hasattr(response, "body_iterator"):
        return response

    chunks: list[bytes] = []
    async for chunk in response.body_iterator:
        if isinstance(chunk, str):
            chunks.append(chunk.encode("utf-8"))
        else:
            chunks.append(bytes(chunk))

    raw = b"".join(chunks)
    text = raw.decode("utf-8-sig", errors="replace").lstrip("\ufeff")

    source = io.StringIO(text)
    output = io.StringIO(newline="")
    writer = csv.writer(output)
    for row in csv.reader(source):
        writer.writerow([_safe_csv_cell(cell) for cell in row])

    payload = b"\xef\xbb\xbf" + output.getvalue().encode("utf-8")
    headers = dict(response.headers)
    headers.pop("content-length", None)

    return Response(
        content=payload,
        status_code=response.status_code,
        headers=headers,
    )


@app.middleware("http")
async def security_and_refresh_access(request: Request, call_next):
    allowed, retry_after = _rate_limit_allowed(request)
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

    if not _csrf_source_allowed(request):
        return PlainTextResponse("CSRF validation failed", status_code=403)

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
                    # Security-sensitive paths fail closed. Do not preserve stale
                    # manager/customer-service privileges when Discord is unavailable.
                    refreshed_user = _revoke_staff_access(refreshed_user)
                    print(
                        "[admin_access_refresh_failed]",
                        type(exc).__name__,
                    )

            request.session["user"] = refreshed_user

            if (
                _is_manager_only_admin_path(request.url.path)
                and not refreshed_user.get("is_manager")
            ):
                return PlainTextResponse(
                    "此功能僅限總管使用。",
                    status_code=403,
                )

    response = await call_next(request)
    response = await _sanitize_csv_response(response)

    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    response.headers.setdefault(
        "Strict-Transport-Security",
        "max-age=31536000",
    )
    response.headers.setdefault("Content-Security-Policy", _CONTENT_SECURITY_POLICY)
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
app.include_router(topups_router)
app.include_router(payment_reviews_router)
app.include_router(ticket_archives_router)
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
    ensure_payment_review_tables()
    ensure_wallet_tables()
    ensure_ticket_archive_tables()


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
