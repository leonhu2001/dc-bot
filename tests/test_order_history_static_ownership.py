from __future__ import annotations

from pathlib import Path


ROOT = Path(".")


def test_order_history_owns_stable_page_assets_and_preserves_dossier_behaviour() -> None:
    template = (ROOT / "web/app/templates/order_history.html").read_text(encoding="utf-8")

    stable_css = ROOT / "web/app/static/css/pages/order_history.css"
    stable_toggle_js = ROOT / "web/app/static/js/pages/order_history_dossier_toggle.js"
    stable_auto_open_js = ROOT / "web/app/static/js/pages/order_history_auto_open.js"

    legacy_css = ROOT / "web/app/static/css/pages/order_history_inline_1.css"
    legacy_toggle_js = ROOT / "web/app/static/js/pages/order_history_inline_1.js"
    legacy_auto_open_js = ROOT / "web/app/static/js/pages/order_history_inline_2.js"

    assert '/static/css/pages/order_history.css?v=20261013' in template
    assert '/static/js/pages/order_history_dossier_toggle.js?v=20261013' in template
    assert '/static/js/pages/order_history_auto_open.js?v=20261013' in template

    assert "order_history_inline_1.css" not in template
    assert "order_history_inline_1.js" not in template
    assert "order_history_inline_2.js" not in template

    assert stable_css.is_file()
    assert stable_toggle_js.is_file()
    assert stable_auto_open_js.is_file()
    assert not legacy_css.exists()
    assert not legacy_toggle_js.exists()
    assert not legacy_auto_open_js.exists()

    css = stable_css.read_text(encoding="utf-8")
    toggle_js = stable_toggle_js.read_text(encoding="utf-8")
    auto_open_js = stable_auto_open_js.read_text(encoding="utf-8")

    assert ".history-ledger-page" in css
    assert ".history-dossier-detail-row[hidden]" in css

    assert 'button.history-dossier-toggle[data-dossier-target]' in toggle_js
    assert 'document.querySelectorAll(".history-dossier-detail-row")' in toggle_js
    assert 'row.removeAttribute("hidden")' in toggle_js
    assert 'row.setAttribute("hidden", "")' in toggle_js

    assert "new URLSearchParams" in auto_open_js
    assert 'params.get("open")' in auto_open_js
    assert "button.click()" in auto_open_js
    assert "button.scrollIntoView" in auto_open_js
