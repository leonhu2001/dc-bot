from __future__ import annotations

from pathlib import Path

from services import quick_order_v2 as quick
from services import quick_order_v2_fixes as fixes


ROOT = Path(__file__).resolve().parents[1]


def test_live_quick_order_groups_are_native_and_preserve_fixed_3x3(monkeypatch):
    seen = []
    monkeypatch.setattr(fixes, "_ORIGINAL_DETAILS_RESOLVER", lambda category, label: [])
    monkeypatch.setattr(
        fixes,
        "_live_groups",
        lambda category: seen.append(category) or ["賽季3x3", "命運契約"],
    )

    assert quick._groups.__module__ == "services.quick_order_v2"
    assert quick._groups("farm") == ["賽季3x3", "命運契約"]
    assert seen == ["farm"]

    options = quick._options("farm")
    assert [item.label for item in options] == ["賽季3x3", "命運契約"]


def test_quick_order_raw_catalog_fallback_before_setup(monkeypatch):
    monkeypatch.setattr(fixes, "_ORIGINAL_DETAILS_RESOLVER", None)
    monkeypatch.setattr(
        quick,
        "ORDER_ITEM_GROUPS_BY_CATEGORY",
        {"farm": ["賽季3x3", "賽季3x3", "其他服務", "  ", "其他服務"]},
    )
    assert quick._groups("farm") == ["賽季3x3", "其他服務"]


def test_quick_group_resolver_no_longer_monkey_patches_quick_module():
    quick_source = (ROOT / "services/quick_order_v2.py").read_text(encoding="utf-8")
    fixes_source = (ROOT / "services/quick_order_v2_fixes.py").read_text(encoding="utf-8")

    assert "quick._groups = _live_groups" not in fixes_source
    assert "return fixes._live_groups(category)" in quick_source
    assert "quick._groups =" not in fixes_source
    # Keep the separate catalog resolver startup patch in place for now; its
    # cross-module consumers will be migrated in a future dedicated change.
    assert "_install_canonical_group_resolver()" in fixes_source
