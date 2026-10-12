from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
LEGACY = ROOT / "web" / "app" / "static" / "js" / "mw_order_form_fix.js"
CONTROLLER = ROOT / "web" / "app" / "static" / "js" / "mw_order_ui.js"
STYLES = ROOT / "web" / "app" / "static" / "css" / "order_ui.css"
SITE_LAYOUT = ROOT / "web" / "app" / "templates" / "site_layout.html"
ORDER_CATALOG = ROOT / "web" / "app" / "templates" / "order_catalog.html"
EXTRA_PATCH = ROOT / "web" / "app" / "static" / "js" / "mw_order_extra_fix.js"


def test_legacy_order_patch_assets_are_fully_retired() -> None:
    assert not LEGACY.exists()
    assert not EXTRA_PATCH.exists()
    catalog = ORDER_CATALOG.read_text(encoding="utf-8")
    assert "mw_order_form_fix.js" not in catalog
    assert "mw_order_extra_fix.js" not in catalog


def test_canonical_order_assets_are_loaded_by_public_layout() -> None:
    source = SITE_LAYOUT.read_text(encoding="utf-8")
    assert '/static/js/mw_order_ui.js?v=20261013' in source
    assert '/static/css/order_ui.css?v=20261013' in source


def test_order_form_behavior_lives_in_canonical_controller() -> None:
    source = CONTROLLER.read_text(encoding="utf-8")
    assert "/order/rule-ui-meta" in source
    assert "mw-extra-requirements" in source
    assert "mw-fixed-player-count" in source


def test_extraction_preserves_legacy_rule_and_player_fallbacks() -> None:
    source = CONTROLLER.read_text(encoding="utf-8")
    assert "direct.dataset?.ruleKey" in source
    assert 'option?.getAttribute("data-rule-key")' in source
    assert 'byId("mw-player-value")' in source
    assert 'field.querySelector(".order3-stepper")' in source
    assert 'event.key === "Escape"' in source


def test_order_form_styles_are_not_runtime_style_text() -> None:
    source = CONTROLLER.read_text(encoding="utf-8")
    css = STYLES.read_text(encoding="utf-8")
    assert "document.createElement(\"style\")" not in source
    assert "#mw-extra-requirements" in css
