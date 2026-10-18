from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_no_access_login_returns_to_exact_requested_page() -> None:
    template = (ROOT / "web/app/templates/no_access.html").read_text(encoding="utf-8")

    assert "request.url.path" in template
    assert "request.url.query" in template
    assert "/auth/discord/login?next={{ return_target | urlencode }}" in template
    assert "{% if user %}" in template
    assert "/auth/logout" in template


def test_dispatch_reason_is_visible_on_shared_no_access_page() -> None:
    template = (ROOT / "web/app/templates/no_access.html").read_text(encoding="utf-8")

    assert "message if message is defined else reason" in template
