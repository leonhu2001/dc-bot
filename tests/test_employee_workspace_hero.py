from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_employee_center_and_legacy_employee_pages_share_site_layout_shell():
    employee = _read("web/app/templates/employee_center.html")
    bridge = _read("web/app/templates/layout.html")
    site_layout = _read("web/app/templates/site_layout.html")
    admin_layout = _read("web/app/templates/admin_layout.html")

    assert '{% extends "site_layout.html" %}' in employee
    assert '"admin_layout.html" if request.url.path.startswith(\'/admin\') else "site_layout.html"' in bridge
    assert "employee_workspace_shell = not request.url.path.startswith('/admin')" in bridge

    assert '{% include "_site_header.html" %}' in site_layout
    assert 'class="site-body mw-public-r5' in site_layout
    assert 'class="mw-r5-layout' in admin_layout
    assert '{% include "_admin_sidebar.html" %}' in admin_layout


def test_employee_center_and_workspace_render_the_same_hero_on_the_same_ec_rail():
    employee = _read("web/app/templates/employee_center.html")
    site_layout = _read("web/app/templates/site_layout.html")
    center_css = _read("web/app/static/css/pages/employee_center.css")

    include = '{% include "_employee_workspace_hero.html" %}'
    assert include in employee
    assert include in site_layout
    assert 'class="ec employee-workspace-frame"' in site_layout
    assert 'class="employee-workspace-page-content"' in site_layout
    assert ".ec{width:min(1180px,calc(100% - 28px));margin:52px auto 90px" in center_css


def test_employee_hero_keeps_fixed_navigation_and_marks_current_page_active():
    hero = _read("web/app/templates/_employee_workspace_hero.html")

    for label in (
        "員工後台",
        "接單大廳",
        "報單系統",
        "報單審核",
        "綁店管理",
        "內部轉帳",
        "公開個人牆",
        "個人中心",
    ):
        assert label in hero

    assert "員工中心" not in hero
    assert "完整薪資" not in hero
    assert "active{% endif %}" in hero
    assert "_employee_path == '/employee'" in hero
    assert "_employee_path == '/dispatch'" in hero
    assert "_employee_path.startswith('/employee/store-bindings')" in hero

    store_line = next(line for line in hero.splitlines() if "_employee_store_name =" in line)
    name_line = next(line for line in hero.splitlines() if "_employee_name =" in line)
    assert "_employee_member.get('name')" in store_line
    assert "_employee_member.get('display_name')" in store_line
    assert "user.staff_display_name" in store_line
    assert name_line.index("_employee_store_name") < name_line.index("user.display_name")


def test_workspace_reuses_employee_center_shared_css_and_isolates_page_content_css():
    employee = _read("web/app/templates/employee_center.html")
    site_layout = _read("web/app/templates/site_layout.html")
    page_css = _read("web/app/static/css/pages/employee_workspace_page_content.css")

    assert "employee_workspace_site_shell.css?v=" in employee
    assert "employee_workspace_site_shell.css?v=" in site_layout
    assert "employee_workspace_page_content.css?v=" in site_layout

    # Page-only CSS is forbidden from changing the site header or shared hero.
    assert ".employee-workspace-page-content" in page_css
    assert ".mw-shared-site-header" not in page_css
    assert ".employee-workspace-hero" not in page_css
    assert "body.mw-r5-employee" not in page_css


def test_workspace_identity_cache_uses_store_name():
    site_layout = _read("web/app/templates/site_layout.html")
    script = _read("web/app/static/js/pages/employee_workspace_identity.js")

    assert "employee_workspace_identity.js?v=20261020-1" in site_layout
    assert "mw_employee_store_name:" in script
    assert "data-employee-workspace-name" in _read("web/app/templates/_employee_workspace_hero.html")
