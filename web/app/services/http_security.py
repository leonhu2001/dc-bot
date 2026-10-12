from __future__ import annotations

import base64
import csv
import io
import secrets
from collections.abc import Iterable
from urllib.parse import urlsplit

from fastapi import Request
from fastapi.responses import Response

from web.app.services.discord_service import get_dashboard_access


MANAGER_ONLY_ADMIN_PREFIXES = (
    "/admin/wallets",
    "/admin/audit",
    "/admin/system",
    "/admin/anomalies",
    "/admin/accounting-reconciliation",
    "/admin/marketing",
    "/admin/ai-support-knowledge",
    "/admin/ai-operations",
    "/admin/order-rules",
    # Customer service may read payout/export data; only status-changing
    # endpoints below require manager privileges.
    "/admin/payouts/summary/mark-paid",
    "/admin/payouts/summary/mark-unpaid",
    "/admin/payouts/summary/person-status",
)

def new_csp_nonce() -> str:
    return base64.b64encode(secrets.token_bytes(18)).decode("ascii")


def build_content_security_policy(nonce: str) -> str:
    safe_nonce = str(nonce or "").strip()
    if not safe_nonce:
        raise ValueError("CSP nonce is required")

    # Inline JavaScript is nonce-bound and template style attributes are eliminated.
    # Both executable code and styles therefore load only from trusted self-hosted assets.
    return "; ".join(
        (
            "default-src 'self'",
            "base-uri 'self'",
            "object-src 'none'",
            "frame-ancestors 'none'",
            "form-action 'self'",
            f"script-src 'self' 'nonce-{safe_nonce}'",
            "style-src 'self'",
            "img-src 'self' data: https:",
            "font-src 'self' data:",
            "connect-src 'self'",
            "upgrade-insecure-requests",
        )
    )


def is_admin_path(path: str) -> bool:
    return path == "/admin" or path.startswith("/admin/")


def is_manager_only_admin_path(path: str) -> bool:
    return any(
        path == prefix or path.startswith(prefix + "/")
        for prefix in MANAGER_ONLY_ADMIN_PREFIXES
    )


def origin_from_referer(value: str) -> str:
    try:
        parsed = urlsplit(str(value or ""))
    except Exception:
        return ""

    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return ""
    return f"{parsed.scheme}://{parsed.netloc}".rstrip("/")


def csrf_source_allowed(
    request: Request,
    *,
    allowed_origins: Iterable[str],
) -> bool:
    if request.method.upper() not in {"POST", "PUT", "PATCH", "DELETE"}:
        return True

    fetch_site = str(request.headers.get("sec-fetch-site") or "").lower().strip()
    if fetch_site == "cross-site":
        return False

    normalized_origins = {
        str(origin or "").rstrip("/")
        for origin in allowed_origins
        if str(origin or "").strip()
    }

    origin = str(request.headers.get("origin") or "").strip().rstrip("/")
    if origin:
        return origin in normalized_origins

    referer_origin = origin_from_referer(request.headers.get("referer") or "")
    if referer_origin:
        return referer_origin in normalized_origins

    # Browser state-changing requests must identify a same-site source. This
    # also blocks blind form POST CSRF when a client omits Origin.
    return False


def apply_live_access(user: dict, role_ids: list[str]) -> dict:
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
            # Legacy routes use is_admin for manager-or-CS backoffice access.
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


def revoke_staff_access(user: dict) -> dict:
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


def safe_csv_cell(value: str) -> str:
    text = str(value or "")
    check = text.lstrip()
    if (
        check.startswith(("=", "+", "-", "@"))
        or text.startswith(("\t", "\r", "\n"))
    ):
        return "'" + text
    return text


async def sanitize_csv_response(response):
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
        writer.writerow([safe_csv_cell(cell) for cell in row])

    payload = b"\xef\xbb\xbf" + output.getvalue().encode("utf-8")
    headers = dict(response.headers)
    headers.pop("content-length", None)

    return Response(
        content=payload,
        status_code=response.status_code,
        headers=headers,
    )
