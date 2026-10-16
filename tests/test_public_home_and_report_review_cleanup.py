from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
HOME = ROOT / "web" / "app" / "templates" / "home.html"
REVIEW = ROOT / "web" / "app" / "templates" / "order_report_review_detail.html"
REPORT_CSS = ROOT / "web" / "app" / "static" / "css" / "order_reports.css"


def test_home_popular_cards_skip_generic_filler_copy() -> None:
    source = HOME.read_text(encoding="utf-8")
    assert "service_description not in" in source
    assert "選擇適合你的方案。" in source
    assert "{{ service_description }}" in source


def test_report_review_radios_are_not_styled_as_text_inputs() -> None:
    css = REPORT_CSS.read_text(encoding="utf-8")
    assert ".report-field input:not([type=radio]):not([type=checkbox])" in css
    assert ".report-choice-grid input[type=radio]{width:13px!important" in css
    assert "min-height:13px!important" in css


def test_report_review_uses_refreshed_styles_and_clean_copy() -> None:
    source = REVIEW.read_text(encoding="utf-8")
    assert 'order_reports.css?v=5' in source
    assert 'placeholder="例如：玉米"' not in source
    assert "掛名審核後寫回薪資；直播狀態按人保存" not in source
