from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
FIX_SOURCE = ROOT / "services" / "quick_order_v2_fixes.py"
PRODUCTION_SOURCE = ROOT / "services" / "quick_order_v2_production.py"
SELECT_SOURCE = ROOT / "services" / "quick_order_v2_select_display.py"
PRICE_SOURCE = ROOT / "services" / "quick_order_v2_price_lists.py"
IMAGE_SOURCE = ROOT / "services" / "quick_order_v2_panel_images.py"
SETUP_SOURCE = ROOT / "cogs" / "setup_commands.py"


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
    assert "quick_order_v2_panel_images" not in source
    assert "install_quick_order_v2_panel_images" not in source


def test_price_list_layer_is_pure_presentation_not_runtime_patching() -> None:
    source = PRICE_SOURCE.read_text(encoding="utf-8")

    assert "def add_price_list_control" in source
    assert "def has_price_list" in source
    assert "_ORIGINAL_VIEW_FOR_CHANNEL" not in source
    assert "_ORIGINAL_DELTA_CALLBACK" not in source
    assert "def _install_view_factory" not in source
    assert "def _install_delta_cover_callback" not in source
    assert "quick._view_for_channel =" not in source
    assert "quick.QuickDeltaCategoryButton.callback =" not in source
    assert "quick_order_v2_production as production" not in source


def test_panel_image_layer_is_helper_repair_only() -> None:
    source = IMAGE_SOURCE.read_text(encoding="utf-8")

    assert "def panel_image_filename" in source
    assert "def cleanup_legacy_artwork_messages" in source
    assert "quick_order_v2_production" not in source
    assert "_ORIGINAL_ENSURE_PANEL" not in source
    assert "def _install_panel_sync" not in source
    assert "quick._ensure_panel =" not in source
    assert "production._clean_ensure_panel =" not in source


def test_production_owns_public_factory_and_panel_sync() -> None:
    source = PRODUCTION_SOURCE.read_text(encoding="utf-8")

    assert "def _public_view_for_channel" in source
    assert "class _PublicDeltaCategoryButton" in source
    assert "quick._view_for_channel = _public_view_for_channel" in source
    assert "quick._ensure_panel = _clean_ensure_panel" in source
    assert "quick.build_entry_embed =" not in source
    assert "add_price_list_control" in source
    assert "panel_image_url" in source


def test_production_is_single_ticket_view_owner() -> None:
    source = PRODUCTION_SOURCE.read_text(encoding="utf-8")

    assert source.count("ui.SelfServiceOrderView.__init__ =") == 1
    assert "apply_quick_order_select_display(self, data)" in source


def test_setup_installs_final_policy_before_core_persistent_views() -> None:
    source = SETUP_SOURCE.read_text(encoding="utf-8")

    fixes = source.index("install_quick_order_v2_fixes(bot)")
    production = source.index("install_quick_order_v2_production(bot)")
    core = source.index("install_quick_order_v2(bot)")
    select_display = source.index("install_quick_order_v2_select_display(bot)")

    assert fixes < production < core < select_display
