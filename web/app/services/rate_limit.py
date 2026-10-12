from __future__ import annotations

from collections import deque
from dataclasses import dataclass
import ipaddress
import time
from typing import Protocol

from fastapi import Request

from web.app.services.web_security import is_sensitive_path


UNSAFE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}

CLOUDFLARE_PROXY_NETWORKS = tuple(
    ipaddress.ip_network(value)
    for value in (
        "103.21.244.0/22",
        "103.22.200.0/22",
        "103.31.4.0/22",
        "104.16.0.0/13",
        "104.24.0.0/14",
        "108.162.192.0/18",
        "131.0.72.0/22",
        "141.101.64.0/18",
        "162.158.0.0/15",
        "172.64.0.0/13",
        "173.245.48.0/20",
        "188.114.96.0/20",
        "190.93.240.0/20",
        "197.234.240.0/22",
        "198.41.128.0/17",
        "2400:cb00::/32",
        "2606:4700::/32",
        "2803:f800::/32",
        "2405:b500::/32",
        "2405:8100::/32",
        "2a06:98c0::/29",
        "2c0f:f248::/32",
    )
)


@dataclass(frozen=True)
class RateLimitSpec:
    bucket: str
    limit: int
    window_seconds: int


class RateLimiterBackend(Protocol):
    def allow(
        self,
        client_key: str,
        spec: RateLimitSpec,
        *,
        now: float | None = None,
    ) -> tuple[bool, int]: ...


class InMemorySlidingWindowRateLimiter:
    """Single-process backend used by the current one-worker deployment.

    The HTTP policy is kept separate from storage so a shared Redis-backed
    implementation can replace this class when Web scales to multiple workers.
    """

    def __init__(self) -> None:
        self._buckets: dict[tuple[str, str], deque[float]] = {}
        self._request_counter = 0

    def allow(
        self,
        client_key: str,
        spec: RateLimitSpec,
        *,
        now: float | None = None,
    ) -> tuple[bool, int]:
        current = time.monotonic() if now is None else float(now)
        cutoff = current - spec.window_seconds
        key = (client_key, spec.bucket)
        bucket = self._buckets.setdefault(key, deque())

        while bucket and bucket[0] <= cutoff:
            bucket.popleft()

        if len(bucket) >= spec.limit:
            retry_after = max(
                1,
                int(spec.window_seconds - (current - bucket[0])),
            )
            return False, retry_after

        bucket.append(current)
        self._request_counter += 1

        if self._request_counter % 500 == 0 and len(self._buckets) > 2000:
            self._prune(cutoff)

        return True, 0

    def _prune(self, cutoff: float) -> None:
        for old_key, old_bucket in list(self._buckets.items()):
            while old_bucket and old_bucket[0] <= cutoff:
                old_bucket.popleft()
            if not old_bucket:
                self._buckets.pop(old_key, None)

    def clear(self) -> None:
        self._buckets.clear()
        self._request_counter = 0


DEFAULT_BACKEND: RateLimiterBackend = InMemorySlidingWindowRateLimiter()


def normalized_ip(value: str | None) -> str:
    try:
        return str(ipaddress.ip_address(str(value or "").strip()))
    except ValueError:
        return ""


def is_cloudflare_proxy_ip(value: str | None) -> bool:
    normalized = normalized_ip(value)
    if not normalized:
        return False
    address = ipaddress.ip_address(normalized)
    return any(
        address.version == network.version and address in network
        for network in CLOUDFLARE_PROXY_NETWORKS
    )


def client_ip(request: Request) -> str:
    # Nginx always overwrites X-Real-IP. During rollout it may still contain a
    # Cloudflare edge IP; only then is CF-Connecting-IP trusted.
    real_ip = normalized_ip(request.headers.get("x-real-ip"))
    if real_ip and is_cloudflare_proxy_ip(real_ip):
        visitor_ip = normalized_ip(request.headers.get("cf-connecting-ip"))
        if visitor_ip:
            return visitor_ip
    if real_ip:
        return real_ip
    if request.client is not None:
        socket_ip = normalized_ip(request.client.host)
        if socket_ip:
            return socket_ip
    return "unknown"


def rate_limit_spec(request: Request) -> RateLimitSpec | None:
    path = request.url.path
    method = request.method.upper()

    if path == "/health" or path.startswith("/static/"):
        return None
    if path.startswith("/auth/"):
        return RateLimitSpec("auth", 30, 60)
    if path.startswith("/api/support-chat"):
        if method in UNSAFE_METHODS:
            return RateLimitSpec("support-chat-write", 30, 60)
        return RateLimitSpec("support-chat-read", 120, 60)
    if path.startswith("/admin/ai-operations") and method in UNSAFE_METHODS:
        return RateLimitSpec("ai-operations-write", 12, 60)
    if path.startswith("/discord-avatar/"):
        return RateLimitSpec("avatar", 120, 60)
    if method in UNSAFE_METHODS and is_sensitive_path(path):
        return RateLimitSpec("sensitive-write", 20, 60)
    if method in UNSAFE_METHODS and (path == "/admin" or path.startswith("/admin/")):
        return RateLimitSpec("admin-write", 60, 60)
    if method in UNSAFE_METHODS:
        return RateLimitSpec("write", 90, 60)
    return RateLimitSpec("general", 600, 60)


def rate_limit_allowed(
    request: Request,
    *,
    backend: RateLimiterBackend = DEFAULT_BACKEND,
) -> tuple[bool, int]:
    spec = rate_limit_spec(request)
    if spec is None:
        return True, 0
    return backend.allow(client_ip(request), spec)
