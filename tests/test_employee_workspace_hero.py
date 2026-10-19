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
    assert "_employee_path == '/dispatch'" in hero
    assert "_employee_path.startswith('/employee/store-bindings')" in hero


def test_workspace_uses_employee_center_hero_css_and_same_content_rail():
    sidebar = _read("web/app/templates/_employee_sidebar.html")
    css = _read("web/app/static/css/pages/employee_workspace_site_shell.css")

    assert "employee_center_inline_1.css?v=20261020-2" in sidebar
    assert "employee-workspace-top" in sidebar
    assert "width: min(1180px, calc(100% - 28px))" in css
    assert ".employee-workspace-hero .ec-btn.active" in css
