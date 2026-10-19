from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_employee_center_and_workspace_share_same_hero_partial():
    employee = _read("web/app/templates/employee_center.html")
    workspace = _read("web/app/templates/_employee_sidebar.html")

    include = '{% include "_employee_workspace_hero.html" %}'
    assert include in employee
    assert include in workspace


def test_employee_hero_keeps_fixed_navigation_and_marks_current_page_active():
    hero = _read("web/app/templates/_employee_workspace_hero.html")

    for label in (
        "員工中心",
        "接單大廳",
        "報單系統",
        "報單審核",
        "綁店管理",
        "內部轉帳",
        "公開個人牆",
        "個人中心",
    ):
        assert label in hero

    assert "完整薪資" not in hero
    assert "{% if _employee_path != '/dispatch' %}" not in hero
    assert "active{% endif %}" in hero
    assert "_employee_path == '/employee'" in hero
    assert "_employee_path == '/dispatch'" in hero
    assert "_employee_path.startswith('/employee/store-bindings')" in hero


def test_workspace_uses_employee_center_hero_css_and_same_content_rail():
    employee = _read("web/app/templates/employee_center.html")
    sidebar = _read("web/app/templates/_employee_sidebar.html")
    css = _read("web/app/static/css/pages/employee_workspace_site_shell.css")

    assert "employee_center_inline_1.css?v=20261020-2" in sidebar
    assert "employee_workspace_site_shell.css?v=20261020-6" in sidebar
    assert "employee_workspace_site_shell.css?v=20261020-6" in employee
    assert "employee-workspace-top" in sidebar
    assert "width: min(1180px, calc(100% - 28px))" in css

    # /employee uses site_layout while inner employee pages use layout.html.
    # The active state must therefore not depend on body.mw-r5-employee.
    assert ".employee-workspace-hero .ec-btn.active" in css
    assert "body.mw-r5-employee .employee-workspace-hero .ec-btn.active" not in css


def test_workspace_uses_public_site_header_markup_and_styles():
    sidebar = _read("web/app/templates/_employee_sidebar.html")
    css = _read("web/app/static/css/pages/employee_workspace_site_shell.css")

    assert "/static/css/mw_site.css?v=16" in sidebar
    assert 'class="site-header employee-site-header"' in sidebar
    assert 'class="site-nav-shell"' in sidebar
    assert 'class="site-desktop-nav"' in sidebar
    assert 'class="account-menu"' in sidebar
    assert 'class="site-mobile-nav"' in sidebar
    assert "/static/js/mw_site.js?v=3-order-rule-intro" in sidebar
    assert "ewu-site-header" not in sidebar

    # mw_portal_r5.css applies a backoffice-wide font/line-height/button reset
    # with !important. The employee copy of the public header must explicitly
    # restore the real public-site typography and mobile button dimensions.
    assert 'font-family: "Noto Sans TC", "Microsoft JhengHei", system-ui, -apple-system, sans-serif !important;' in css
    assert ".employee-site-header .site-brand-copy small" in css
    assert "font-size: 9px !important;" in css
    assert ".employee-site-header .site-desktop-nav a" in css
    assert "font-size: 14px !important;" in css
    assert ".employee-site-header .mobile-nav-button" in css
    assert "width: 42px !important;" in css
    assert "height: 42px !important;" in css
