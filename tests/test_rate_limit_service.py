from types import SimpleNamespace

from web.app.services.rate_limit import (
    InMemorySlidingWindowRateLimiter,
    RateLimitSpec,
    client_ip,
    rate_limit_spec,
)


def request(path: str, method: str = "GET", headers: dict | None = None):
    return SimpleNamespace(
        url=SimpleNamespace(path=path),
        method=method,
        headers=headers or {},
        client=SimpleNamespace(host="127.0.0.1"),
    )


def test_sliding_window_blocks_after_limit() -> None:
    limiter = InMemorySlidingWindowRateLimiter()
    spec = RateLimitSpec("test", 2, 60)

    assert limiter.allow("client", spec, now=100.0) == (True, 0)
    assert limiter.allow("client", spec, now=101.0) == (True, 0)
    allowed, retry_after = limiter.allow("client", spec, now=102.0)
    assert allowed is False
    assert retry_after > 0

    assert limiter.allow("client", spec, now=161.0) == (True, 0)


def test_rate_limit_policy_preserves_existing_buckets() -> None:
    assert rate_limit_spec(request("/health")) is None
    assert rate_limit_spec(request("/static/x.js")) is None
    assert rate_limit_spec(request("/auth/discord/login")).bucket == "auth"
    assert rate_limit_spec(request("/api/support-chat", "POST")).bucket == "support-chat-write"
    assert rate_limit_spec(request("/api/support-chat")).bucket == "support-chat-read"
    assert rate_limit_spec(request("/admin/ai-operations/run", "POST")).bucket == "ai-operations-write"
    assert rate_limit_spec(request("/discord-avatar/123")).bucket == "avatar"
    assert rate_limit_spec(request("/admin/example", "POST")).bucket == "admin-write"
    assert rate_limit_spec(request("/ordinary", "POST")).bucket == "write"
    assert rate_limit_spec(request("/ordinary")).bucket == "general"


def test_client_ip_only_trusts_cloudflare_header_from_cloudflare_peer() -> None:
    direct = request(
        "/",
        headers={
            "x-real-ip": "203.0.113.5",
            "cf-connecting-ip": "198.51.100.9",
        },
    )
    assert client_ip(direct) == "203.0.113.5"

    cloudflare = request(
        "/",
        headers={
            "x-real-ip": "104.16.1.1",
            "cf-connecting-ip": "198.51.100.9",
        },
    )
    assert client_ip(cloudflare) == "198.51.100.9"
