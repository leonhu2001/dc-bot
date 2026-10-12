from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
LEGACY = ROOT / "web" / "app" / "static" / "js" / "mw_order_form_fix.js"
CONTROLLER = ROOT / "web" / "app" / "static" / "js" / "mw_order_ui.js"
STYLES = ROOT / "web" / "app" / "static" / "css" / "order_ui.css"
SITE_LAYOUT = ROOT / "web" / "app" / "templates" / "site_layout.html"
EXTRA_PATCH = ROOT / "web" / "app" / "static" / "js" / "mw_order_extra_fix.js"


def test_legacy_order_form_fix_is_only_a_compatibility_sentinel() -> None:
    source = LEGACY.read_text(encoding="utf-8")
    assert LEGACY.stat().st_size < 1_000
    assert "__MAWAN_ORDER_UI_COMPAT_LOADER__" in source
    assert "document.createElement" not in source
    assert "appendChild" not in source
    assert "mw_order_ui.js" not in source
    assert "order_ui.css" not in source


def test_canonical_order_assets_are_loaded_by_public_layout() -> None:
    source = SITE_LAYOUT.read_text(encoding="utf-8")
    assert '/static/js/mw_order_ui.js?v=20261013' in source
    assert '/static/css/order_ui.css?v=20261013' in source


def test_obsolete_extra_patch_asset_is_removed() -> None:
    assert not EXTRA_PATCH.exists()


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
