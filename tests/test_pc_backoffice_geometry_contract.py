from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TEMPLATES = ROOT / "web" / "app" / "templates"
CSS = ROOT / "web" / "app" / "static" / "css" / "pages"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_dispatch_has_one_hero_css_owner() -> None:
    site_layout = _read(TEMPLATES / "site_layout.html")
    canonical = _read(CSS / "dispatch_status_capsules.css")

    assert "dispatch_hero_controls.css" not in site_layout
    assert not (CSS / "dispatch_hero_controls.css").exists()
    assert "grid-template-columns: minmax(0, 1fr) auto" in canonical
    assert "@media (min-width: 768px) and (max-width: 1180px)" in canonical
    assert "min-width: 0 !important" in canonical


def test_admin_dashboard_owns_desktop_grid_geometry() -> None:
    template = _read(TEMPLATES / "admin.html")
    css = _read(CSS / "admin_dashboard_pc.css")
    responsive = _read(CSS / "admin_dashboard_responsive.css")

    assert "admin_dashboard_pc.css?v=" in template
    assert "admin_dashboard_responsive.css?v=" in template
    assert "body.mw-desktop-ui .admin-dashboard-stats" in css
    assert "grid-template-columns: repeat(5, minmax(0, 1fr))" in css
    assert "body.mw-desktop-ui .admin-dashboard-orders .order-head" in css
    assert "body.mw-desktop-ui .admin-dashboard-orders .order-row" in css
    assert "max-width: 1500px" in responsive


def test_report_queue_owns_desktop_workbar_geometry() -> None:
    template = _read(TEMPLATES / "order_reports.html")
    css = _read(CSS / "order_reports_desktop.css")

    assert "order_reports_desktop.css?v=" in template
    assert "body.desktop-ui .report-workbar" in css
    assert "grid-template-columns: auto minmax(0, 1fr) auto" in css
    assert "body.desktop-ui .report-worktabs" in css
    assert "body.desktop-ui .report-worktool" in css
    assert "@media (min-width: 768px) and (max-width: 1080px)" in css
