from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
GUARD = ROOT / "web" / "app" / "static" / "js" / "mw_order_guard.js"
CATALOG = ROOT / "web" / "app" / "templates" / "order_catalog.html"


def test_order_cards_expose_canonical_group_metadata() -> None:
    source = CATALOG.read_text(encoding="utf-8")
    assert 'data-order-group-card="{{ group.key }}"' in source
    assert 'data-order-group="{{ group.key }}"' in source
    assert '"specified_staff_id"' in source


def test_guard_consumes_page_data_instead_of_inferring_from_copy() -> None:
    source = GUARD.read_text(encoding="utf-8")
    assert 'byId("mw-order-groups-data")' in source
    assert 'byId("mw-order-context-data")' in source
    assert 'card.dataset.orderGroupCard' in source
    assert 'context.specified_staff_id' in source
    assert 'variant.rule_key' in source

    assert "開始設定" not in source
    assert "查看個人牆" not in source
    assert "已從個人牆選擇" not in source
    assert "已從陪玩陣容" not in source
    assert "location.search" not in source
    assert "parentElement" not in source


def test_guard_does_not_own_quote_checkout_dom_reset() -> None:
    source = GUARD.read_text(encoding="utf-8")
    assert 'new CustomEvent("mawan:order-reset")' in source
    assert 'byId("mw-server-result")' not in source
    assert 'byId("mw-checkout-panel")' not in source
    assert 'byId("mw-checkout-summary")' not in source
    assert 'mw-checkout-use-wallet' not in source
    assert 'mw-checkout-payment' not in source


def test_guard_is_event_driven_without_runtime_patch_layers() -> None:
    source = GUARD.read_text(encoding="utf-8")
    assert "MutationObserver" not in source
    assert "MWGuardNoopObserver" not in source
    assert 'document.createElement("style")' not in source
    assert source.count("requestAnimationFrame(filterVariants)") == 2
    assert "/order/staff-filter?staff_id=" in source
