from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TEMPLATES = ROOT / "web" / "app" / "templates"
CSS = ROOT / "web" / "app" / "static" / "css" / "pages"


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_admin_sidebar_is_desktop_only_markup():
    sidebar = read(TEMPLATES / "_admin_sidebar.html")
    assert "mobile_app_rebuild" not in sidebar
    assert "mobile_app_component_sizing" not in sidebar
    assert "_admin_mobile_app_shell" not in sidebar
    assert '<aside class="mw-r5-sidebar">' in sidebar


def test_admin_layout_server_splits_mobile_and_desktop_shells():
    layout = read(TEMPLATES / "admin_layout.html")
    assert "{% if mobile_ui %}" in layout
    assert '{% include "_admin_mobile_app_shell.html" %}' in layout
    assert '{% include "_admin_sidebar.html" %}' in layout
    assert "mw-mobile-ui" in layout
    assert "mw-desktop-ui" in layout
    # Mobile assets belong to the mobile branch and desktop shell stylesheet to desktop.
    mobile_branch = layout.index("{% if mobile_ui %}")
    mobile_css = layout.index("admin_mobile_app.css")
    desktop_css = layout.index("admin_shell_layout.css")
    assert mobile_css > mobile_branch
    assert desktop_css > mobile_css


def test_public_layout_server_splits_mobile_and_desktop_dom():
    layout = read(TEMPLATES / "site_layout.html")
    assert "{% if mobile_ui %}" in layout
    assert '{% include "_customer_mobile_app_shell.html" %}' in layout
    assert '{% include "_employee_mobile_app_shell.html" %}' in layout
    assert '{% include "_site_header.html" %}' in layout
    assert "customer_mobile_app.css?v=20261026-3" in layout
    # Customer mobile no longer loads the generic v6/v7 cascade.
    customer_pos = layout.index("customer_mobile_app.css?v=20261026-3")
    employee_v6_pos = layout.index("mobile_app_rebuild_v6.css?v=20261026-2")
    assert employee_v6_pos < customer_pos


def test_employee_desktop_hero_does_not_render_mobile_shell():
    hero = read(TEMPLATES / "_employee_workspace_hero.html")
    assert "_employee_mobile_app_shell" not in hero


def test_customer_mobile_grid_has_single_owner_and_no_legacy_carousel_columns():
    css = read(CSS / "customer_mobile_app.css")
    compact = css.replace(" ", "").replace("\n", "")
    assert "grid-auto-flow:column" not in compact
    assert "grid-auto-columns:min(82vw,330px)" not in compact
    assert "grid-template-columns:repeat(2,minmax(0,1fr))" in compact
    assert "scroll-snap-type:none" in compact


def test_desktop_admin_grid_keeps_sidebar_first():
    portal = read(ROOT / "web" / "app" / "static" / "css" / "mw_portal_r5.css")
    compact = "".join(portal.split())
    assert ".mw-r5-shell{" in compact
    assert "grid-template-columns:var(--r5-side)minmax(0,1fr)!important" in compact
