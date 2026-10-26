from pathlib import Path


CUSTOMER_SHELL = Path("web/app/templates/_customer_mobile_app_shell.html")
EMPLOYEE_SHELL = Path("web/app/templates/_employee_mobile_app_shell.html")
ADMIN_SHELL = Path("web/app/templates/_admin_mobile_app_shell.html")
SITE_LAYOUT = Path("web/app/templates/site_layout.html")
ADMIN_LAYOUT = Path("web/app/templates/admin_layout.html")
CUSTOMER_CSS = Path("web/app/static/css/pages/customer_mobile_app.css")
EMPLOYEE_ROUTES = Path("web/app/static/css/pages/employee_mobile_routes.css")


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_v6_is_not_loaded_by_active_layouts_or_shells() -> None:
    for path in (CUSTOMER_SHELL, EMPLOYEE_SHELL, ADMIN_SHELL, SITE_LAYOUT, ADMIN_LAYOUT):
        assert "mobile_app_rebuild_v6.css" not in _read(path), path.name


def test_customer_home_and_order_keep_dedicated_mobile_dom() -> None:
    source = _read(CUSTOMER_SHELL)
    assert "mobile-v6-home" in source
    assert "今晚想玩什麼？" in source
    assert "mobile-v6-order" in source
    assert "mobile-v6-category-strip" in source
    assert "選擇服務" in source


def test_customer_mobile_stylesheet_owns_duplicate_desktop_block_hiding() -> None:
    source = _read(CUSTOMER_CSS)
    assert "body.customer-mobile-app-site:has(.mobile-v6-home) .site-main > .hero" in source
    assert "body.customer-mobile-app-site:has(.mobile-v6-order) .order3-hero" in source
    assert "body.customer-mobile-app-site:has(.mobile-v6-staff) .crew-page-hero" in source
    assert "body.customer-mobile-app-site:has(.mobile-v6-vip) .vip-page-hero" in source


def test_report_has_dedicated_task_first_mobile_dom_and_owner() -> None:
    shell = _read(EMPLOYEE_SHELL)
    css = _read(EMPLOYEE_ROUTES)
    assert "mobile-v6-report" in shell
    assert "待辦報單" in shell
    assert "mobile-v6-report-actions" in shell
    assert "客服審核" in shell
    assert ".mobile-v6-report-actions" in css
    assert ".report-filter-bar" in css
