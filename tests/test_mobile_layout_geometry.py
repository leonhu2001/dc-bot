from pathlib import Path


SITE_LAYOUT = Path("web/app/templates/site_layout.html")
ADMIN_LAYOUT = Path("web/app/templates/admin_layout.html")
CUSTOMER_CSS = Path("web/app/static/css/pages/customer_mobile_app.css")
EMPLOYEE_CSS = Path("web/app/static/css/pages/employee_mobile_app.css")
ADMIN_CSS = Path("web/app/static/css/pages/admin_mobile_app.css")
REPORT_TEMPLATE = Path("web/app/templates/order_reports.html")


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_old_geometry_overlay_is_not_loaded_anymore() -> None:
    for layout in (SITE_LAYOUT, ADMIN_LAYOUT):
        source = _read(layout)
        assert "mobile_app_geometry_v5.css" not in source
        assert "mobile_app_visual_system_v4.css" not in source
        assert "mobile_app_public_pages_v4.css" not in source


def test_customer_mobile_geometry_is_owned_by_customer_stylesheet() -> None:
    source = _read(CUSTOMER_CSS)
    compact = "".join(source.split())
    assert "--cm-topbar:56px" in compact
    assert "--cm-dock:64px" in compact
    assert "bottom:0" in compact
    assert "grid-template-columns:repeat(2,minmax(0,1fr))" in compact
    assert "grid-auto-flow:row" in compact
    assert "grid-auto-flow:column" not in compact


def test_employee_and_admin_geometry_have_separate_owners() -> None:
    employee = _read(EMPLOYEE_CSS)
    admin = _read(ADMIN_CSS)
    assert ".employee-app-bottom-nav" in employee
    assert ".admin-app-bottom-nav" in admin
    assert ".admin-app-bottom-nav" not in employee
    assert ".employee-app-bottom-nav" not in admin


def test_report_phone_copy_is_compact_and_task_focused() -> None:
    source = _read(REPORT_TEMPLATE)
    assert "已結單待補" in source
    assert "退回待補" in source
    assert "全部紀錄" in source
    assert "完整歷史" in source
    assert "目前沒有報單" in source
    assert "未報單與被退回的訂單優先，完成後再看歷史。" not in source
