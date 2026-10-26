from pathlib import Path


CUSTOMER_SHELL = Path("web/app/templates/_customer_mobile_app_shell.html")
EMPLOYEE_SHELL = Path("web/app/templates/_employee_mobile_app_shell.html")
ADMIN_SIDEBAR = Path("web/app/templates/_admin_sidebar.html")
CSS = Path("web/app/static/css/pages/mobile_app_rebuild_v6.css")


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_v6_is_loaded_from_all_mobile_shell_surfaces() -> None:
    marker = "/static/css/pages/mobile_app_rebuild_v6.css?v=20261026-1"
    assert marker in _read(CUSTOMER_SHELL)
    assert marker in _read(EMPLOYEE_SHELL)
    assert marker in _read(ADMIN_SIDEBAR)


def test_customer_home_and_order_have_dedicated_mobile_dom() -> None:
    source = _read(CUSTOMER_SHELL)
    assert "mobile-v6-home" in source
    assert "今晚想玩什麼？" in source
    assert "mobile-v6-order" in source
    assert "mobile-v6-category-strip" in source
    assert "選擇服務" in source


def test_report_has_dedicated_task_first_mobile_dom() -> None:
    source = _read(EMPLOYEE_SHELL)
    assert "mobile-v6-report" in source
    assert "待辦報單" in source
    assert "mobile-v6-report-actions" in source
    assert "客服審核" in source


def test_v6_hides_duplicate_desktop_heroes_on_mobile() -> None:
    source = _read(CSS)
    assert "body:has(.mobile-v6-home) .site-main > .hero" in source
    assert "body:has(.mobile-v6-order) .order3-hero" in source
    assert "body:has(.mobile-v6-staff) .crew-page-hero" in source
    assert "body:has(.mobile-v6-vip) .vip-page-hero" in source
    assert "body:has(.mobile-v6-report) .report-hero" in source


def test_v6_dock_is_hard_pinned_to_viewport_edge() -> None:
    source = _read(CSS)
    assert "bottom: 0 !important" in source
    assert "height: calc(var(--v6-dock) + env(safe-area-inset-bottom)) !important" in source
    assert "background: #0d0d0f !important" in source
