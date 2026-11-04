from __future__ import annotations

import inspect

from services import orders
from services import quick_order_v2 as quick
from services.vip_timer import VIP_TIMER_CATEGORY
from services.vip_timer_game_compat import resolve_vip_timer_game_label


def test_historical_panel_values_use_current_game_labels(monkeypatch):
    monkeypatch.setitem(
        orders.SELF_SERVICE_ORDER_CATALOG,
        VIP_TIMER_CATEGORY,
        [
            {"label": "三角洲端遊", "details": [{"rule_key": "delta"}]},
            {"label": "三角洲手遊", "details": [{"rule_key": "mobile"}]},
            {"label": "特戰英豪", "details": [{"rule_key": "valorant"}]},
            {"label": "STEAM", "details": [{"rule_key": "steam"}]},
            {"label": "APEX", "details": []},  # no eligible timer items
        ],
    )

    for value in ("三角洲端遊", "三角洲｜端遊", "三角洲行動｜端遊", "三角洲 | 端遊"):
        assert resolve_vip_timer_game_label(value) == "三角洲端遊"
    for value in ("三角洲｜手遊", "三角洲行動｜手遊"):
        assert resolve_vip_timer_game_label(value) == "三角洲手遊"
    assert resolve_vip_timer_game_label("STEAM 遊戲") == "STEAM"
    assert resolve_vip_timer_game_label("特戰英豪") == "特戰英豪"

    for value in ("", "舊版已下架遊戲", "APEX", "__vip_timer_custom_order__"):
        assert resolve_vip_timer_game_label(value) is None


def test_quick_entry_normalizes_legacy_selection_at_both_interaction_stages():
    selection_source = inspect.getsource(quick.QuickVipGameSelect.callback)
    ticket_source = inspect.getsource(quick._create_ticket)
    assert "resolve_vip_timer_game_label(selected)" in selection_source
    assert "resolve_vip_timer_game_label(item_group)" in ticket_source
    assert "traceback.print_exc()" in ticket_source
    assert "stage=\{stage\}" not in ticket_source
    assert "stage={stage}" in ticket_source
