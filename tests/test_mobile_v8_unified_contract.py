"""Mobile V8 is a single late cascade and a genuine multi-route app shell."""
from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TEMPLATES = ROOT / "web/app/templates"
CSS = ROOT / "web/app/static/css/pages/mobile_app_unified_v8.css"
JS = ROOT / "web/app/static/js/pages/mobile_app_unified_v8.js"
ROUTE_BAR = TEMPLATES / "_mobile_v8_route_bar.html"


def text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_v8_single_mobile_cascade_is_last_in_both_layouts() -> None:
    for layout_name, old_mobile_sheet in (
        ("site_layout.html", "customer_mobile_app.css"),
        ("admin_layout.html", "admin_mobile_app.css"),
    ):
        source = text(TEMPLATES / layout_name)
        assert "mobile_app_unified_v8.css?v=20261117-1" in source
        assert "mobile_app_unified_v8.js?v=20261117-1" in source
        assert source.index(old_mobile_sheet) < source.index("mobile_app_unified_v8.css")
        assert source.index("mobile_app_unified_v8.css") < source.index("</head>")
        assert 'href="#m8-main"' in source
        assert 'id="m8-main"' in source
        assert "mobile_app_component_sizing_v7.css" not in source
        assert "mobile_app_rebuild_v6.css" not in source


def test_all_three_app_products_inherit_the_same_mobile_rail() -> None:
    css = text(CSS)
    for selector in (
        "body.customer-mobile-app-site",
        "body.employee-workspace-site",
        "body.mw-mobile-ui.mw-r5-admin",
        "body.mw-mobile-ui.mw-r5-employee",
        ".site-main",
        ".mw-mobile-main-host",
        ".customer-app-topbar",
        ".employee-app-topbar",
        ".admin-app-topbar",
        ".customer-app-bottom-nav",
        ".employee-app-bottom-nav",
        ".admin-app-bottom-nav",
    ):
        assert selector in css
    for token in (
        "--m8-rail: 560px", "--m8-card-radius: 18px",
        "--m8-control-height: 46px", "--m8-topbar-height: 62px",
        "--m8-bottom-height: 72px", "100dvh",
        "safe-area-inset-top", "safe-area-inset-bottom",
        "width: min(100%, var(--m8-rail))",
        "overflow-x: clip", "overscroll-behavior-x: contain",
    ):
        assert token in css
    assert "@media (max-width: 767px)" in css


def test_mobile_back_navigation_and_form_feedback_do_not_change_checkout_logic() -> None:
    for path in (
        "/admin/customer-center", "/admin/finance-center", "/dispatch/reports",
        "/me/orders", "/me/wallet", "/games/delta-force",
    ):
        assert path in text(ROUTE_BAR)
    for layout_name in ("site_layout.html", "admin_layout.html"):
        assert "_mobile_v8_route_bar.html" in text(TEMPLATES / layout_name)

    script = text(JS)
    for action in (
        "aria-current", "m8-editing", "focusin", "focusout", "pageshow",
        "scrollIntoView", "m8-table-scroll", "aria-invalid", "sessionStorage",
        "NAV_KEY", "prefers-reduced-motion",
    ):
        assert action in script
    assert "fetch(" not in script
    assert "XMLHttpRequest" not in script


def test_mobile_v8_is_distinct_from_desktop_without_touching_economics() -> None:
    source = text(CSS)
    assert "@media (max-width: 767px)" in source
    assert "body.customer-mobile-app-site" in source
    assert "body.mw-mobile-ui.mw-r5-admin" in source
    assert "m8-skip-link" in source
    assert "m8-route-bar" in source
    # Mobile shell code never invokes private finance/order endpoints.
    assert "api/order" not in text(JS)
    assert "payment" not in text(JS).lower()
