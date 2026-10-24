from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
FIX_SOURCE = ROOT / "services" / "quick_order_v2_fixes.py"
PRODUCTION_SOURCE = ROOT / "services" / "quick_order_v2_production.py"
SELECT_SOURCE = ROOT / "services" / "quick_order_v2_select_display.py"
PRICE_SOURCE = ROOT / "services" / "quick_order_v2_price_lists.py"


def test_legacy_core_ticket_wrapper_is_disabled_before_quick_install() -> None:
    source = FIX_SOURCE.read_text(encoding="utf-8")

    assert "def _disable_legacy_ticket_patch" in source
    assert "quick._PATCH_INSTALLED = True" in source
    assert "_disable_legacy_ticket_patch()" in source


def test_select_display_is_a_pure_view_mutator_not_another_view_wrapper() -> None:
    source = SELECT_SOURCE.read_text(encoding="utf-8")

    assert "def apply_quick_order_select_display" in source
    assert "def _install_quick_order_view_patch" not in source
    assert "ui.SelfServiceOrderView.__init__ =" not in source


def test_price_list_layer_no_longer_owns_entry_copy_or_vip_gate() -> None:
    source = PRICE_SOURCE.read_text(encoding="utf-8")

    assert "_ORIGINAL_ENTRY_EMBED" not in source
    assert "def _install_entry_copy" not in source
    assert "def _live_vip_timer_eligibility" not in source
    assert "quick.assert_vip_timer_self_service_eligible =" not in source
    assert "quick_order_v2_production as production" not in source


def test_production_is_single_ticket_view_owner() -> None:
    source = PRODUCTION_SOURCE.read_text(encoding="utf-8")

    assert source.count("ui.SelfServiceOrderView.__init__ =") == 1
    assert "apply_quick_order_select_display(self, data)" in source
