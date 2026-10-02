from __future__ import annotations

import json
import re
import secrets
import time
from typing import Any
from urllib.parse import parse_qs


CSRF_SESSION_KEY = "csrf_token"
AUTH_TIME_SESSION_KEY = "auth_time"
DEFAULT_RECENT_AUTH_SECONDS = 30 * 60

_UNSAFE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}

_SENSITIVE_PATH_PREFIXES = (
    "/admin/wallets",
    "/admin/payment-reviews",
    "/admin/topups",
    "/admin/accounting-reconciliation",
    "/admin/payouts/summary",
    "/admin/audit",
    "/admin/system",
)

_SENSITIVE_PATH_EXACT = {
    "/admin/staff/sync",
}

_MULTIPART_CSRF_RE = re.compile(
    br'name="csrf_token"\r\n(?:[^\r\n]*\r\n)*\r\n([^\r\n]+)'
)


def ensure_csrf_token(session: dict[str, Any]) -> str:
    token = str(session.get(CSRF_SESSION_KEY) or "").strip()

    if len(token) < 32:
        token = secrets.token_urlsafe(32)
        session[CSRF_SESSION_KEY] = token

    return token


def rotate_csrf_token(session: dict[str, Any]) -> str:
    token = secrets.token_urlsafe(32)
    session[CSRF_SESSION_KEY] = token
    return token


def mark_authenticated_now(
    session: dict[str, Any],
    *,
    now: float | None = None,
) -> float:
    value = float(time.time() if now is None else now)
    session[AUTH_TIME_SESSION_KEY] = value
    return value


def auth_age_seconds(
    session: dict[str, Any],
    *,
    now: float | None = None,
) -> float | None:
    raw = session.get(AUTH_TIME_SESSION_KEY)

    try:
        authenticated_at = float(raw)
    except (TypeError, ValueError):
        return None

    current = float(time.time() if now is None else now)
    return max(0.0, current - authenticated_at)


def has_recent_auth(
    session: dict[str, Any],
    *,
    max_age_seconds: int = DEFAULT_RECENT_AUTH_SECONDS,
    now: float | None = None,
) -> bool:
    age = auth_age_seconds(session, now=now)
    if age is None:
        return False
    return age <= max(1, int(max_age_seconds))


def is_sensitive_path(path: str) -> bool:
    normalized = str(path or "").rstrip("/") or "/"

    if normalized in _SENSITIVE_PATH_EXACT:
        return True

    return any(
        normalized == prefix
        or normalized.startswith(prefix + "/")
        for prefix in _SENSITIVE_PATH_PREFIXES
    )


def requires_csrf(method: str) -> bool:
    return str(method or "").upper() in _UNSAFE_METHODS


def csrf_tokens_match(expected: str | None, supplied: str | None) -> bool:
    expected_text = str(expected or "").strip()
    supplied_text = str(supplied or "").strip()

    if not expected_text or not supplied_text:
        return False

    return secrets.compare_digest(expected_text, supplied_text)


def extract_csrf_token_from_body(
    body: bytes,
    content_type: str | None,
) -> str | None:
    content_type = str(content_type or "").lower()

    if not body:
        return None

    if "application/x-www-form-urlencoded" in content_type:
        try:
            parsed = parse_qs(
                body.decode("utf-8", errors="strict"),
                keep_blank_values=True,
            )
        except Exception:
            return None

        values = parsed.get("csrf_token") or []
        return str(values[0]).strip() if values else None

    if "multipart/form-data" in content_type:
        match = _MULTIPART_CSRF_RE.search(body)
        if match is None:
            return None

        try:
            return match.group(1).decode("utf-8", errors="strict").strip()
        except Exception:
            return None

    if "application/json" in content_type:
        try:
            payload = json.loads(body.decode("utf-8"))
        except Exception:
            return None

        if isinstance(payload, dict):
            value = payload.get("csrf_token")
            if value is not None:
                return str(value).strip()

    return None


def csrf_token_from_request_parts(
    *,
    header_token: str | None,
    body: bytes,
    content_type: str | None,
) -> str | None:
    header = str(header_token or "").strip()
    if header:
        return header

    return extract_csrf_token_from_body(
        body,
        content_type,
    )


def should_no_store(path: str, *, authenticated: bool) -> bool:
    if not authenticated:
        return False

    prefixes = (
        "/admin",
        "/me",
        "/employee",
        "/service",
        "/dispatch",
        "/my",
    )
    normalized = str(path or "")
    return any(
        normalized == prefix
        or normalized.startswith(prefix + "/")
        for prefix in prefixes
    )
