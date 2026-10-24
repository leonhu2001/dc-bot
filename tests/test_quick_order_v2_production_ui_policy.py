from __future__ import annotations

from pathlib import Path

from services import quick_order_v2 as quick
from services import quick_order_v2_production as production


ROOT = Path(__file__).resolve().parents[1]
PRODUCTION_SOURCE = ROOT / "services" / "quick_order_v2_production.py"


def test_production_uses_one_ticket_ui_policy_instead_of_nested_wrappers() -> None:
    source = PRODUCTION_SOURCE.read_text(encoding="utf-8")

    assert "def _install_ticket_ui_policy" in source
    assert "def _install_panel_builder_cleanup" not in source
    assert "def _install_farm_ticket_ui" not in source
    assert "quick._ORIGINAL_PANEL_BUILDER" in source
    assert "quick._ORIGINAL_VIEW_INIT" in source
    assert source.count("ui.SelfServiceOrderView.__init__ =") == 1
    assert source.count("ui.build_self_service_panel_embed =") == 1


def test_consolidated_policy_keeps_farm_ui_rules() -> None:
    source = PRODUCTION_SOURCE.read_text(encoding="utf-8")

    assert '"season_3x3": 0' in source
    assert 'child.placeholder = "請選擇方案"' not in source  # nested ternary owns this copy
    assert '"請選擇方案"' in source
    assert 'child.placeholder = "請選擇數量"' in source
    assert '"self_service_order_specified_staff_button"' in source
    assert '"self_service_order_staff_price_button"' in source
    assert '"self_service_order_go_payment_button"' in source


def test_production_vip_entry_copy_derives_from_core_and_keeps_custom_order() -> None:
    embed = production._clean_entry_embed(
        quick.QUICK_ORDER_V2_CHANNELS["vip_timer"]
    )
    description = str(embed.description or "")

    assert "遊戲類型" in description
    assert "自訂單" in description
    assert "客服報價" in description
    assert str(getattr(embed.footer, "text", "") or "") == ""


def test_production_entry_copy_has_no_duplicate_vip_business_copy() -> None:
    source = PRODUCTION_SOURCE.read_text(encoding="utf-8")

    assert "白金級會員以上限定" not in source
    assert "請選擇起始遊戲；進入客服中心後" not in source
    assert "_CORE_ENTRY_EMBED" in source
