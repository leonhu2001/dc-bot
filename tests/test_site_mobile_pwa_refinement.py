from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_site_pwa_mobile_shell_stays_viewport_safe():
    source = (ROOT / "web" / "app" / "static" / "css" / "site_pwa.css").read_text(
        encoding="utf-8"
    )
    assert "100dvh" in source
    assert ".mw-support-panel" in source
    assert "safe-area-inset-bottom" in source
    assert "overflow-x:auto" in source
    assert ".site-mobile-nav" in source


def test_employee_mobile_workspace_handles_narrow_tables_and_actions():
    source = (
        ROOT
        / "web"
        / "app"
        / "static"
        / "css"
        / "pages"
        / "employee_mobile_pwa.css"
    ).read_text(encoding="utf-8")
    assert "scroll-snap-type:x proximity" in source
    assert "width:max-content" in source
    assert "@media(max-width:380px)" in source
    assert "overflow-x:auto" in source
