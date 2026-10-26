from pathlib import Path


V6_CSS = Path("web/app/static/css/pages/mobile_app_rebuild_v6.css")
SITE_LAYOUT = Path("web/app/templates/site_layout.html")
ADMIN_LAYOUT = Path("web/app/templates/admin_layout.html")
REPORT_TEMPLATE = Path("web/app/templates/order_reports.html")


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_public_phone_heroes_cannot_inherit_desktop_billboard_heights() -> None:
    source = _read(V6_CSS)

    assert 'body.customer-mobile-app-site .site-main [class*="-hero"]' in source
    assert "min-height: 0 !important" in source
    assert "body:has(.mobile-v6-order) .order3-hero" in source
    assert "body:has(.mobile-v6-staff) .crew-page-hero" in source
    assert "body:has(.mobile-v6-vip) .vip-page-hero" in source


def test_mobile_dock_has_one_active_geometry_owner() -> None:
    source = _read(V6_CSS)

    assert "--v6-dock: 62px" in source
    assert "bottom: 0 !important" in source
    assert "height: calc(var(--v6-dock) + env(safe-area-inset-bottom)) !important" in source
    assert "padding-bottom: calc(var(--v6-dock) + env(safe-area-inset-bottom) + 10px) !important" in source


def test_legacy_geometry_and_visual_layers_are_retired_from_active_surfaces() -> None:
    site = _read(SITE_LAYOUT)
    admin = _read(ADMIN_LAYOUT)

    for layout in (site, admin):
        assert "mobile_app_geometry_v5.css" not in layout
        assert "mobile_app_visual_system_v4.css" not in layout
        assert "mobile_app_component_sizing_v7.css" not in layout
        assert "mobile_app_rebuild_v6.css?v=20261026-2" in layout
        assert "mobile_surface_sizing.css?v=20261026-1" in layout


def test_report_phone_copy_is_compact_and_task_focused() -> None:
    source = _read(REPORT_TEMPLATE)

    assert "已結單待補" in source
    assert "被退回待補" in source
    assert "查看歷史" in source
    assert "目前沒有報單" in source
    assert "未報單與被退回的訂單優先，完成後再看歷史。" not in source
