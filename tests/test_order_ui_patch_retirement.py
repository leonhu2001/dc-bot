from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
LEGACY = ROOT / "web" / "app" / "static" / "js" / "mw_order_form_fix.js"
CONTROLLER = ROOT / "web" / "app" / "static" / "js" / "mw_order_ui.js"
GUARD = ROOT / "web" / "app" / "static" / "js" / "mw_order_guard.js"
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


def test_order_styles_are_canonical_and_guard_skips_runtime_injection() -> None:
    loader = LEGACY.read_text(encoding="utf-8")
    controller = CONTROLLER.read_text(encoding="utf-8")
    guard = GUARD.read_text(encoding="utf-8")
    css = STYLES.read_text(encoding="utf-8")

    assert "document.createElement(\"style\")" not in controller
    assert 'const cssId = "mw-role-filter-style"' in loader
    assert '"mw-role-filter-style"' in guard
    assert "#mw-extra-requirements" in css
    assert ".mw-role-filter-hidden" in css
    assert ".mw-role-filter-loading" in css
