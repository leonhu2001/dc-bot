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


def test_public_site_and_employee_workspace_share_same_header_partial():
    site_layout = _read("web/app/templates/site_layout.html")
    workspace = _read("web/app/templates/_employee_sidebar.html")
    header = _read("web/app/templates/_site_header.html")

    include = '{% include "_site_header.html" %}'
    assert include in site_layout
    assert include in workspace
    assert 'class="site-header mw-shared-site-header"' in header
    assert 'class="site-nav-shell"' in header
    assert 'class="site-desktop-nav"' in header
    assert 'class="account-menu"' in header
    assert 'class="site-mobile-nav"' in header


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

    # The same logged-in user name must be shown on every workspace page even
    # when /employee also has a WebStaffMember object in its template context.
    name_line = next(line for line in hero.splitlines() if "_employee_name =" in line)
    assert name_line.index("user.display_name") < name_line.index("_employee_member.get('name')")


def test_workspace_uses_employee_center_hero_css_and_same_content_rail():
    employee = _read("web/app/templates/employee_center.html")
    sidebar = _read("web/app/templates/_employee_sidebar.html")
    css = _read("web/app/static/css/pages/employee_workspace_site_shell.css")

    assert "employee_center_inline_1.css?v=20261020-2" in sidebar
    assert "employee_workspace_site_shell.css?v=20261020-7" in sidebar
    assert "employee_workspace_site_shell.css?v=20261020-7" in employee
    assert "employee-workspace-top" in sidebar
    assert "width: min(1180px, calc(100% - 28px))" in css

    # /employee uses site_layout while inner employee pages use layout.html.
    # The active state and hero typography must therefore not depend on the
    # backoffice body class.
    assert ".employee-workspace-hero .ec-btn.active" in css
    assert "body.mw-r5-employee .employee-workspace-hero .ec-btn.active" not in css
    assert "font-size: 15px !important;" in css
    assert "font-weight: 500 !important;" in css
    assert "font-size: clamp(34px,5vw,54px) !important;" in css
    assert ".employee-workspace-hero .ec-btn" in css
    assert "font-size: 12px !important;" in css
    assert "font-weight: 800 !important;" in css


def test_workspace_header_matches_public_r5_typography_and_breakpoints():
    sidebar = _read("web/app/templates/_employee_sidebar.html")
    css = _read("web/app/static/css/pages/employee_workspace_site_shell.css")
    public_css = _read("web/app/static/css/mw_public_r5.css")

    assert "/static/css/mw_site.css?v=16" in sidebar
    assert "/static/js/mw_site.js?v=3-order-rule-intro" in sidebar
    assert "ewu-site-header" not in sidebar

    # Public pages use Inter first, 15px/500 body text, 14px/700 nav links and
    # 12.5px small text. The employee copy must lock to the same values instead
    # of the previous Noto Sans TC / 400 approximation.
    assert "Inter," in public_css
    assert 'font-family: Inter, "Noto Sans TC", "Microsoft JhengHei", system-ui, sans-serif !important;' in css
    assert ".mw-shared-site-header .site-brand-copy small" in css
    assert "font-size: 12.5px !important;" in css
    assert ".mw-shared-site-header .site-desktop-nav a" in css
    assert "font-size: 14px !important;" in css
    assert "font-weight: 700 !important;" in css

    # Desktop and mobile controls are mutually exclusive; this prevents the
    # empty outlined mobile-menu button from appearing beside the desktop nav.
    assert ".mw-shared-site-header .mobile-nav-button" in css
    assert "display: none !important;" in css
    assert "@media (max-width: 1050px)" in css
    assert ".mw-shared-site-header .site-desktop-nav { display: none !important; }" in css
    assert ".mw-shared-site-header .mobile-nav-button { display: block !important; }" in css
