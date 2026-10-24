from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PRODUCTION_SOURCE = ROOT / "services" / "quick_order_v2_production.py"


def test_production_layer_does_not_wrap_new_ticket_creation() -> None:
    source = PRODUCTION_SOURCE.read_text(encoding="utf-8")

    assert "_ORIGINAL_CREATE_TICKET" not in source
    assert "_install_create_ticket_cleanup" not in source
    assert "quick._create_ticket =" not in source


def test_production_layer_does_not_override_core_entry_callbacks() -> None:
    source = PRODUCTION_SOURCE.read_text(encoding="utf-8")

    assert "async def _clean_confirmation" not in source
    assert "async def _clean_delta_callback" not in source
    assert "quick._send_confirmation =" not in source
    assert "quick.QuickDeltaCategoryButton.callback =" not in source


def test_legacy_copy_cleanup_remains_startup_repair_only() -> None:
    source = PRODUCTION_SOURCE.read_text(encoding="utf-8")

    assert "async def _clean_ticket_messages" in source
    assert "async def repair_existing_quick_order_v2_copy" in source
    assert "await _clean_ticket_messages(channel)" in source
