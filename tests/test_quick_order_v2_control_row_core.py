from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
QUICK_SOURCE = ROOT / "services" / "quick_order_v2.py"
FIX_SOURCE = ROOT / "services" / "quick_order_v2_fixes.py"


def test_core_builds_control_row_on_initial_ticket_message() -> None:
    source = QUICK_SOURCE.read_text(encoding="utf-8")

    assert "def _build_order_control_view()" in source
    assert "view=_build_order_control_view()," in source
    assert "state.order_control_view_type" in source


def test_fixes_layer_no_longer_wraps_ticket_creation() -> None:
    source = FIX_SOURCE.read_text(encoding="utf-8")

    assert "_ORIGINAL_CREATE_TICKET" not in source
    assert "_install_create_ticket_wrapper" not in source
    assert "quick._create_ticket =" not in source


def test_existing_ticket_control_repair_is_preserved() -> None:
    source = FIX_SOURCE.read_text(encoding="utf-8")

    assert "async def _attach_order_control_view" in source
    assert "await _attach_order_control_view(channel)" in source
