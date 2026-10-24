from __future__ import annotations

import inspect

from services import orders
from services import quick_order_v2 as quick
from services.vip_timer import VIP_TIMER_CATEGORY


def test_vip_timer_public_entry_uses_game_catalog_not_legacy_gameplay_groups(monkeypatch):
    monkeypatch.setattr(quick, "refresh_vip_timer_self_service_catalog", lambda: None)
    monkeypatch.setitem(
        orders.ORDER_ITEM_GROUPS_BY_CATEGORY,
        VIP_TIMER_CATEGORY,
        ["娛樂陪", "技術陪"],
    )
    monkeypatch.setitem(
        orders.SELF_SERVICE_ORDER_CATALOG,
        VIP_TIMER_CATEGORY,
        [
            {"label": "三角洲行動｜端遊", "details": [{"rule_key": "delta_desktop"}]},
            {"label": "三角洲行動｜手遊", "details": [{"rule_key": "delta_mobile"}]},
            {"label": "特戰英豪", "details": [{"rule_key": "valorant"}]},
            {"label": "英雄聯盟", "details": [{"rule_key": "lol"}]},
            {"label": "APEX", "details": [{"rule_key": "apex"}]},
            {"label": "STEAM 遊戲", "details": [{"rule_key": "steam"}]},
            {"label": "其他／自訂", "details": [{"rule_key": "legacy_custom"}]},
        ],
    )

    select = quick.QuickVipGameSelect()
    labels = [option.label for option in select.options]
    values = [option.value for option in select.options]

    assert labels == [
        "三角洲｜端遊",
        "三角洲｜手遊",
        "特戰英豪",
        "英雄聯盟",
        "APEX",
        "STEAM",
        "自訂單",
    ]
    assert "娛樂陪" not in labels
    assert "技術陪" not in labels
    assert "三角洲行動｜端遊" in values
    assert "三角洲行動｜手遊" in values
    assert "STEAM 遊戲" in values
    assert quick.VIP_TIMER_CUSTOM_ORDER_VALUE in values
    assert select.placeholder == "請選擇遊戲類型"


def test_vip_timer_custom_entry_routes_to_existing_custom_order_flow_before_timer_checks():
    source = inspect.getsource(quick.QuickVipGameSelect.callback)
    assert "VIP_TIMER_CUSTOM_ORDER_VALUE" in source
    assert "CustomOrderCompanionCountView" in source
    assert source.index("VIP_TIMER_CUSTOM_ORDER_VALUE") < source.index(
        "assert_vip_timer_self_service_eligible"
    )


def test_vip_timer_entry_copy_explains_game_type_and_custom_order():
    embed = quick.build_entry_embed(quick.QUICK_ORDER_V2_CHANNELS["vip_timer"])
    description = str(embed.description or "")
    assert "遊戲類型" in description
    assert "自訂單" in description
    assert "客服報價" in description
