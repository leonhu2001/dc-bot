from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_employee_workspace_reserves_scrollbar_gutter():
    header = _read("web/app/templates/_site_header.html")
    css = _read("web/app/static/css/pages/employee_workspace_viewport.css")

    assert "employee_workspace_viewport.css?v=20261020-1" in header
    assert "current_path.startswith('/employee')" in header
    assert "current_path.startswith('/dispatch')" in header
    assert "scrollbar-gutter: stable" in css
    assert "overflow-y: scroll" in css


def test_employee_center_and_workspace_keep_same_1180px_rail():
    center_css = _read("web/app/static/css/pages/employee_center.css")
    workspace_css = _read("web/app/static/css/pages/employee_workspace_site_shell.css")

    rail = "width:min(1180px,calc(100% - 28px))"
    assert rail in center_css
    assert "width: min(1180px, calc(100% - 28px)) !important;" in workspace_css
