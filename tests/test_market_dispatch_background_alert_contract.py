from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def _function_string_literals(source: str, function_name: str) -> set[str]:
    tree = ast.parse(source)
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == function_name:
            return {
                value.value
                for value in ast.walk(node)
                if isinstance(value, ast.Constant) and isinstance(value.value, str)
            }
    raise AssertionError(f"function {function_name} not found")


def test_market_page_has_live_freshness_history_and_category_controls():
    template = _read("web/app/templates/game_market.html")
    script = _read("web/app/static/js/pages/game_market_live.js")
    stylesheet = _read("web/app/static/css/pages/game_market.css")

    assert "game_market_live.js" in template
    assert "data-market-updated-at" in template
    assert "data-market-age" in template
    assert "data-market-live-state" in template
    assert "data-market-category-filters" in template
    assert "data-market-category=" in template
    assert "coverage_hours" in template
    assert "24H 統計" in template
    assert "7D 統計" in template

    assert "Asia/Taipei" in script
    assert "/api/items" in script
    assert "window.location.reload()" in script
    assert "data-market-category" in script
    assert "document.hidden" in script

    assert ".game-market-livebar" in stylesheet
    assert ".game-market-category-filters" in stylesheet
    assert "[data-market-row][hidden]" in stylesheet


def test_background_dispatch_stream_is_presence_free_and_minimal():
    source = _read("web/app/routers/dispatch_background_alerts.py")
    literals = _function_string_literals(source, "_background_payload")

    assert 'router.get("/dispatch/alerts/config")' in source
    assert 'router.get("/dispatch/alerts/events")' in source
    assert "_shared_dispatch_event_snapshot" in source
    assert "_public_dispatch_snapshot" in source
    assert "touch_dispatch_user_presence" not in source

    assert "alert_keys" in literals
    assert "customer" not in literals
    assert "amount" not in literals
    assert "orders" not in literals
    assert "claim_access" not in literals


def test_dispatch_routes_are_mounted_through_shared_site_router():
    bootstrap = _read("web/app/routers/__init__.py")

    assert "_site.router.include_router(_dispatch_state_router)" in bootstrap
    assert "_site.router.include_router(_dispatch_background_alerts_router)" in bootstrap


def test_site_runtime_only_starts_background_notifications_when_already_enabled():
    script = _read("web/app/static/js/site_pwa.js")

    assert "window.location.pathname === '/dispatch'" in script
    assert "mw_dispatch_desktop_notification_enabled" in script
    assert "Notification.permission !== 'granted'" in script
    assert "Notification.requestPermission" not in script
    assert "'/dispatch/alerts/config'" in script
    assert "'/dispatch/alerts/events'" in script
    assert "new EventSource(BACKGROUND_EVENTS_URL)" in script
    assert "window.location.href = '/dispatch'" in script
    assert "mowan-dispatch-new-order-background" in script
