from __future__ import annotations

from io import BytesIO
from types import SimpleNamespace

import tools.probe_public_market_source as probe


def test_extract_candidates_finds_public_api_json_and_fetch_paths():
    text = """
    const a = fetch('/api/prices?region=tw');
    const b = axios.get('/history/ammo.json');
    const c = 'https://demo.supabase.co/rest/v1/market_prices';
    const ignored = 'https://example.com/about';
    """

    values = probe.extract_candidates(text, base_url="https://app.852941.xyz/")

    assert "https://app.852941.xyz/api/prices?region=tw" in values
    assert "https://app.852941.xyz/history/ammo.json" in values
    assert "https://demo.supabase.co/rest/v1/market_prices" in values
    assert "https://example.com/about" not in values


def test_same_origin_requires_scheme_host_and_port_match():
    assert probe._same_origin("https://app.852941.xyz/", "https://app.852941.xyz/app.js")
    assert not probe._same_origin("https://app.852941.xyz/", "http://app.852941.xyz/app.js")
    assert not probe._same_origin("https://app.852941.xyz/", "https://cdn.example/app.js")


def test_fetch_public_text_uses_get_and_no_auth_or_cookie(monkeypatch):
    captured = {}

    class Response:
        status = 200
        headers = SimpleNamespace(
            get=lambda key, default=None: "text/plain; charset=utf-8" if key == "content-type" else default,
            get_content_charset=lambda: "utf-8",
        )

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self, size=-1):
            return b"ok"

        def geturl(self):
            return "https://app.852941.xyz/"

    def fake_urlopen(request, **kwargs):
        captured["method"] = request.get_method()
        captured["headers"] = {key.lower(): value for key, value in request.header_items()}
        return Response()

    monkeypatch.setattr(probe, "urlopen", fake_urlopen)

    record, text = probe.fetch_public_text("https://app.852941.xyz/")

    assert record.status == 200
    assert text == "ok"
    assert captured["method"] == "GET"
    assert "authorization" not in captured["headers"]
    assert "cookie" not in captured["headers"]


def test_run_probe_never_requests_discovered_candidate(monkeypatch):
    requested = []

    monkeypatch.setattr(probe, "resolve_host", lambda host: ["203.0.113.10"])

    def fake_fetch(url, **kwargs):
        requested.append(url)
        if url == "https://app.852941.xyz/":
            html = "<script src='/app.js'></script>"
        elif url == "https://app.852941.xyz/app.js":
            html = "fetch('/api/prices')"
        else:
            html = ""
        return probe.FetchRecord(url=url, status=200, final_url=url), html

    monkeypatch.setattr(probe, "fetch_public_text", fake_fetch)

    report = probe.run_probe("https://app.852941.xyz/")

    assert "https://app.852941.xyz/api/prices" in report.candidate_urls
    assert "https://app.852941.xyz/api/prices" not in requested
