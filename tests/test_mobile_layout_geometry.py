from pathlib import Path


GEOMETRY_CSS = Path("web/app/static/css/pages/mobile_app_geometry_v5.css")
SITE_LAYOUT = Path("web/app/templates/site_layout.html")
ADMIN_LAYOUT = Path("web/app/templates/admin_layout.html")
REPORT_TEMPLATE = Path("web/app/templates/order_reports.html")


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_public_phone_heroes_cannot_inherit_desktop_billboard_heights() -> None:
    source = _read(GEOMETRY_CSS)

    assert 'body.customer-mobile-app-site .site-main [class*="-hero"]' in source
    assert "min-height: 0 !important" in source
    assert "body.customer-mobile-app-site .order3-hero" in source
    assert "body.customer-mobile-app-site .crew-page-hero" in source
    assert "body.customer-mobile-app-site .vip-page-hero" in source
    assert "body.customer-mobile-app-site .hero-grid" in source


def test_mobile_dock_has_single_safe_area_geometry_owner() -> None:
    source = _read(GEOMETRY_CSS)

    assert "--m5-dock-base: 66px" in source
    assert "height: calc(var(--m5-dock-base) + env(safe-area-inset-bottom)) !important" in source
    assert "padding: 6px max(6px, env(safe-area-inset-right)) env(safe-area-inset-bottom)" in source
    assert "padding-bottom: calc(var(--m5-dock-base) + env(safe-area-inset-bottom) + 10px) !important" in source


def test_final_geometry_layer_is_loaded_after_v4_on_phone_shells() -> None:
    site = _read(SITE_LAYOUT)
    admin = _read(ADMIN_LAYOUT)

    marker = "/static/css/pages/mobile_app_geometry_v5.css?v=20261026-1"
    assert marker in site
    assert marker in admin
    assert site.index("mobile_app_public_pages_v4.css") < site.index(marker)
    assert admin.index("mobile_app_visual_system_v4.css") < admin.index(marker)


def test_report_phone_copy_is_compact_and_task_focused() -> None:
    source = _read(REPORT_TEMPLATE)

    assert "已結單待補" in source
    assert "被退回待補" in source
    assert "查看歷史" in source
    assert "目前沒有報單" in source
    assert "未報單與被退回的訂單優先，完成後再看歷史。" not in source
