from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SIZING = ROOT / "web/app/static/css/pages/mobile_surface_sizing.css"
V6 = ROOT / "web/app/static/css/pages/mobile_app_rebuild_v6.css"
SITE_LAYOUT = ROOT / "web/app/templates/site_layout.html"
ADMIN_LAYOUT = ROOT / "web/app/templates/admin_layout.html"


def test_shared_mobile_sizing_is_layout_neutral() -> None:
    css = SIZING.read_text(encoding="utf-8")
    for token in (
        "--mobile-control-h: 44px",
        "--mobile-stat-h: 72px",
        "--mobile-card-pad: 12px",
        "--mobile-radius-control: 12px",
        "--mobile-radius-card: 16px",
    ):
        assert token in css

    for forbidden in (
        "grid-template-columns",
        "grid-auto-flow",
        "grid-auto-columns",
        "flex-direction",
        "position: fixed",
        "position: sticky",
    ):
        assert forbidden not in css


def test_v6_owns_mobile_shell_and_route_component_dimensions_at_source() -> None:
    css = V6.read_text(encoding="utf-8")
    for token in (
        "width: 40px !important",
        "min-height: 40px !important",
        "min-height: 50px !important",
        "min-height: 44px !important",
        "min-height: 70px !important",
        "min-height: 42px !important",
        "min-height: 66px !important",
    ):
        assert token in css


def test_mobile_assets_have_layout_owners_not_partial_owners() -> None:
    site = SITE_LAYOUT.read_text(encoding="utf-8")
    admin = ADMIN_LAYOUT.read_text(encoding="utf-8")

    for layout in (site, admin):
        assert "mobile_app_rebuild_v6.css?v=20261026-2" in layout
        assert "mobile_surface_sizing.css?v=20261026-1" in layout
        assert "mobile_app_component_sizing_v7.css" not in layout
