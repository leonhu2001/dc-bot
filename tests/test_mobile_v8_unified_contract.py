"""V8 was retired from runtime; V9 is the sole visible mobile application."""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TPL = ROOT / "web/app/templates"
CSS = ROOT / "web/app/static/css/pages/mobile_app_v9.css"
JS = ROOT / "web/app/static/js/pages/mobile_app_v9.js"


def test_v8_is_no_longer_loaded_and_v9_is_the_late_mobile_stylesheet():
    for filename in ("site_layout.html", "admin_layout.html"):
        source = (TPL / filename).read_text(encoding="utf-8")
        assert "mobile_app_v9.css?v=20261117-1" in source
        assert "mobile_app_v9.js?v=20261117-1" in source
        assert "mobile_app_unified_v8.css" not in source
        assert "mobile_app_unified_v8.js" not in source
        assert 'include "_mobile_v9_shell.html"' in source
        assert 'include "_mobile_v9_page.html"' in source
        assert "m9-mobile" in source
        assert 'href="#m8-main"' in source and 'id="m8-main"' in source


def test_v9_unifies_customer_employee_and_admin_rails_and_dock():
    css = CSS.read_text(encoding="utf-8")
    for marker in (
        "body.m9-mobile", ".m9-topbar", ".m9-dock", ".m9-sheet",
        "body.m9-mobile .site-main", "body.m9-mobile .mw-mobile-main-host",
        "--m9-rail: 560px", "--m9-card-radius: 21px",
        "--m9-control-height: 48px", "--m9-top: 62px",
        "--m9-dock-height: 72px", "100dvh",
        "safe-area-inset-bottom", "transform: none !important;",
        "backdrop-filter: none !important;",
        "@media (max-width: 767px)",
    ):
        assert marker in css


def test_v9_navigation_and_form_feedback_do_not_touch_checkout():
    script = JS.read_text(encoding="utf-8")
    for marker in (
        "aria-current", "m9-input-active", "focusin", "focusout",
        "pageshow", "scrollIntoView", "m9-card-table",
        "aria-invalid", "sessionStorage", "prefers-reduced-motion",
    ):
        assert marker in script
    assert "fetch(" not in script
    assert "XMLHttpRequest" not in script
    assert "api/order" not in script
    assert "api/payment" not in script


def test_v9_keeps_usable_more_sheet_and_back_navigation():
    css = CSS.read_text(encoding="utf-8")
    assert "m9-sheet-backdrop" in css
    assert "m9-sheet-links" in css
    page = (TPL / "_mobile_v9_page.html").read_text(encoding="utf-8")
    assert "m9-breadcrumb" in page
    assert "m8-route-back" in page  # compatibility with navigation tests
