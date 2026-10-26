from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CSS = ROOT / "web/app/static/css/pages/mobile_app_component_sizing_v7.css"
SITE_LAYOUT = ROOT / "web/app/templates/site_layout.html"
ADMIN_LAYOUT = ROOT / "web/app/templates/admin_layout.html"
SHELLS = [
    ROOT / "web/app/templates/_customer_mobile_app_shell.html",
    ROOT / "web/app/templates/_employee_mobile_app_shell.html",
    ROOT / "web/app/templates/_admin_mobile_app_shell.html",
]


def test_v7_file_remains_available_as_retired_reference() -> None:
    css = CSS.read_text(encoding="utf-8")
    assert "Mobile component sizing v7" in css


def test_mobile_shell_partials_are_markup_only() -> None:
    for shell in SHELLS:
        text = shell.read_text(encoding="utf-8")
        assert "<link rel=\"stylesheet\"" not in text, shell.name
        assert "mobile_app_rebuild_v6.css" not in text, shell.name
        assert "mobile_app_component_sizing_v7.css" not in text, shell.name


def test_v7_is_not_loaded_by_active_layouts() -> None:
    for layout in (SITE_LAYOUT, ADMIN_LAYOUT):
        text = layout.read_text(encoding="utf-8")
        assert "mobile_app_component_sizing_v7.css" not in text, layout.name
