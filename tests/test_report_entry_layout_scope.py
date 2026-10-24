from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
LAYOUT = ROOT / "web" / "app" / "templates" / "admin_layout.html"
SHARED_STYLES = ROOT / "web" / "app" / "static" / "css" / "pages" / "layout.css"
REPORT_TEMPLATE = ROOT / "web" / "app" / "templates" / "order_report_detail.html"
REPORT_ENTRY_STYLES = ROOT / "web" / "app" / "static" / "css" / "order_report_entry.css"


def test_backoffice_density_is_not_global() -> None:
    shared = SHARED_STYLES.read_text(encoding="utf-8")
    assert ".mw-r5-main-host input" not in shared
    assert ".mw-r5-page-header > p" not in shared


def test_report_entry_page_owns_its_compact_layout() -> None:
    template = REPORT_TEMPLATE.read_text(encoding="utf-8")
    css = REPORT_ENTRY_STYLES.read_text(encoding="utf-8")
    assert '/static/css/order_report_entry.css?v=1' in template
    assert ".report-detail-shell .report-worker-service-row" in css
    assert '.report-detail-shell input[type="radio"]' in css
    assert "placeholder=\"例如：玉米\"" not in template


def test_reverted_shared_styles_use_fresh_cache_key() -> None:
    layout = LAYOUT.read_text(encoding="utf-8")
    assert "layout.css?v=20261016-backoffice-revert-1" in layout
