from pathlib import Path


def test_mobile_styles_are_isolated_from_desktop_layout():
    site_layout = Path("web/app/templates/site_layout.html").read_text(encoding="utf-8")
    customer_shell = Path("web/app/templates/_customer_mobile_app_shell.html").read_text(encoding="utf-8")
    employee_shell = Path("web/app/templates/_employee_mobile_app_shell.html").read_text(encoding="utf-8")

    media = 'media="(max-width: 767px) and (hover: none) and (pointer: coarse)"'

    assert "/static/css/pages/customer_mobile_app.css?v=20261026-2" in site_layout
    assert "/static/css/pages/mobile_app_rebuild_v6.css?v=20261026-2" in site_layout
    assert "/static/css/pages/mobile_app_component_sizing_v7.css?v=20261026-2" in site_layout
    assert site_layout.count(media) >= 12

    assert "mobile_app_rebuild_v6.css" not in customer_shell
    assert "mobile_app_component_sizing_v7.css" not in customer_shell
    assert "mobile_app_rebuild_v6.css" not in employee_shell
    assert "mobile_app_component_sizing_v7.css" not in employee_shell
