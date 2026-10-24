from __future__ import annotations

from pathlib import Path

from services import quick_order_v2 as quick
from services import quick_order_v2_panel_images as panel_images
from services import quick_order_v2_production as production


ROOT = Path(__file__).resolve().parents[1]
PRODUCTION_SOURCE = ROOT / "services" / "quick_order_v2_production.py"


def _custom_ids(view) -> list[str]:
    return [str(getattr(child, "custom_id", "") or "") for child in view.children]


def test_delta_public_view_is_final_on_first_build() -> None:
    channel_id = quick.QUICK_ORDER_V2_CHANNELS["delta"]
    view = production._public_view_for_channel(channel_id)
    custom_ids = _custom_ids(view)

    delta_ids = [
        custom_id
        for custom_id in custom_ids
        if custom_id.startswith("quick_order_v2_delta_")
    ]
    assert len(delta_ids) == 4
    assert f"quick_order_v2_price_list_{channel_id}" in custom_ids

    delta_buttons = [
        child
        for child in view.children
        if str(getattr(child, "custom_id", "") or "").startswith("quick_order_v2_delta_")
    ]
    assert {getattr(child, "row", None) for child in delta_buttons} == {0}


def test_game_public_view_contains_service_and_price_list_without_factory_patch() -> None:
    channel_id = quick.QUICK_ORDER_V2_CHANNELS["apex"]
    view = production._public_view_for_channel(channel_id)
    custom_ids = _custom_ids(view)

    assert "quick_order_v2_service_apex" in custom_ids
    assert f"quick_order_v2_price_list_{channel_id}" in custom_ids


def test_static_panel_artwork_mapping_stays_in_helper_module() -> None:
    assert panel_images.panel_image_filename(
        quick.QUICK_ORDER_V2_CHANNELS["apex"]
    ) == "apex_panel.png"
    assert panel_images.panel_image_filename(
        quick.QUICK_ORDER_V2_CHANNELS["lol"]
    ) == "lol_panel.png"
    assert panel_images.panel_image_filename(
        quick.QUICK_ORDER_V2_CHANNELS["steam"]
    ) == "steam_panel.png"
    assert panel_images.panel_image_filename(
        quick.QUICK_ORDER_V2_CHANNELS["valorant"]
    ) == "valorant_panel.png"
    assert panel_images.panel_image_filename(
        quick.QUICK_ORDER_V2_CHANNELS["vip_timer"]
    ) is None


def test_delta_cover_is_owned_by_public_policy_not_callback_patch() -> None:
    source = PRODUCTION_SOURCE.read_text(encoding="utf-8")

    assert '"delta_desktop_fun": "delta_fun_panel.png"' in source
    assert "public_order_panel_image_url(filename)" in source
    assert "quick.QuickDeltaCategoryButton.callback =" not in source
