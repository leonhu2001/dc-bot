from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
LEGACY = ROOT / "web" / "app" / "static" / "js" / "mw_order_form_fix.js"
CONTROLLER = ROOT / "web" / "app" / "static" / "js" / "mw_order_ui.js"
STYLES = ROOT / "web" / "app" / "static" / "css" / "order_ui.css"


def test_legacy_order_form_fix_is_only_a_loader() -> None:
    source = LEGACY.read_text(encoding="utf-8")
    assert LEGACY.stat().st_size < 2_000
    assert "mw_order_ui.js" in source
    assert "order_ui.css" in source
    assert "rule-ui-meta" not in source


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
