from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_public_layout_server_selects_one_surface_and_one_mobile_stack():
    layout = _read("web/app/templates/site_layout.html")

    assert "mobile_surface =" in layout
    assert 'data-ui-surface="{{ \'mobile\' if mobile_surface else \'desktop\' }}"' in layout
    assert "{% if not mobile_surface %}" in layout
    assert '{% include "_site_header.html" %}' in layout
    assert '{% include "_customer_mobile_app_shell.html" %}' in layout

    # Active mobile stack is intentionally small: base + structural + sizing.
    assert "customer_mobile_app.css?v=20261026-2" in layout
    assert "employee_mobile_app.css?v=20261026-2" in layout
    assert "mobile_app_rebuild_v6.css?v=20261026-2" in layout
    assert "mobile_surface_sizing.css?v=20261026-1" in layout

    retired = (
        "mobile_app_polish.css",
        "mobile_app_repair.css",
        "mobile_app_page_audit.css",
        "mobile_app_redesign_v3.css",
        "mobile_app_redesign_v3_pages.css",
        "mobile_app_ux_v2.css",
        "mobile_app_visual_system_v4.css",
        "mobile_app_public_pages_v4.css",
        "mobile_app_geometry_v5.css",
        "mobile_app_component_sizing_v7.css",
    )
    for filename in retired:
        assert filename not in layout


def test_admin_layout_server_selects_mobile_shell_or_desktop_sidebar_not_both():
    layout = _read("web/app/templates/admin_layout.html")
    sidebar = _read("web/app/templates/_admin_sidebar.html")

    assert "mobile_surface =" in layout
    assert '{% include "_admin_mobile_app_shell.html" %}' in layout
    assert '{% include "_admin_sidebar.html" %}' in layout
    assert "mobile_surface_sizing.css?v=20261026-1" in layout
    assert "mobile_app_component_sizing_v7.css" not in layout
    assert "mobile_app_visual_system_v4.css" not in layout
    assert "mobile_app_geometry_v5.css" not in layout

    # Desktop sidebar is desktop-only markup and cannot pull mobile assets back in.
    assert "mobile_app_rebuild_v6.css" not in sidebar
    assert "mobile_surface_sizing.css" not in sidebar
    assert "_admin_mobile_app_shell.html" not in sidebar


def test_mobile_shell_partials_do_not_own_stylesheet_loading():
    customer_shell = _read("web/app/templates/_customer_mobile_app_shell.html")
    employee_shell = _read("web/app/templates/_employee_mobile_app_shell.html")

    assert '<link rel="stylesheet"' not in customer_shell
    assert '<link rel="stylesheet"' not in employee_shell


def test_experience_and_crew_layout_have_separate_source_owners():
    css = _read("web/app/static/css/pages/customer_mobile_app.css")
    sizing = _read("web/app/static/css/pages/mobile_surface_sizing.css")

    assert "body.customer-mobile-app-site .experience-grid{" in css
    assert "grid-template-columns:repeat(2,minmax(0,1fr))!important" in css
    assert "grid-auto-flow:row" in css

    assert "body.customer-mobile-app-site .crew-grid{" in css
    assert "grid-auto-flow:column" in css
    assert "grid-auto-columns:min(82vw,330px)" in css

    # The sizing layer may size cards, but must never own layout composition.
    forbidden_layout_tokens = (
        "grid-template-columns",
        "grid-auto-flow",
        "grid-auto-columns",
        "flex-direction",
        "position:fixed",
        "position: sticky",
    )
    for token in forbidden_layout_tokens:
        assert token not in sizing
