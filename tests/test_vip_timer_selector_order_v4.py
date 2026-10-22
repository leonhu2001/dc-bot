from __future__ import annotations

from services import vip_timer_catalog_guard as guard
from services import vip_timer_policy_v5 as v5
from services import vip_timer_select_flow as flow
from services import vip_timer_selector_order_v2 as v2
from services import vip_timer_selector_order_v3 as v3
from services import vip_timer_selector_order_v4 as v4


def _install_checkout_stack() -> None:
    guard.install_vip_timer_catalog_guard()
    flow.install_vip_timer_select_flow()
    v2.install_vip_timer_selector_order_v2()
    v3.install_vip_timer_selector_order_v3()
    v4.install_vip_timer_selector_order_v4()
    v5.install_vip_timer_policy_v5()


def test_second_layer_is_game_only_and_third_layer_is_gameplay():
    _install_checkout_stack()

    game_labels = [str(group.get("label") or "") for group in v4._game_rows()]
    assert game_labels
    assert {"三角洲端遊", "三角洲手遊", "特戰英豪", "英雄聯盟", "APEX", "STEAM"}.issubset(
        set(game_labels)
    )
    assert set(game_labels).isdisjoint(
        {"娛樂陪", "技術陪", "黑潮爆破", "一陪一護", "絕巴技術陪"}
    )

    desktop_details = v4._direct_details_for_game("三角洲端遊")
    gameplay_groups = v3._spec_groups(desktop_details)
    gameplay_labels = {str(group.get("label") or "") for group in gameplay_groups}

    assert "娛樂陪" in gameplay_labels
    assert any(label.startswith("技術陪") for label in gameplay_labels)
    assert "黑潮爆破" in gameplay_labels
    assert "絕巴技術陪" in gameplay_labels
    assert any(label.startswith("一陪一護") for label in gameplay_labels)


def test_fourth_layer_contains_only_supported_headcount_options():
    _install_checkout_stack()

    allowed = {"單陪", "雙陪", "三陪", "四陪"}
    for game in v4._game_rows():
        details = v4._direct_details_for_game(str(game.get("label") or ""))
        for group in v3._spec_groups(details):
            headcounts = [
                str(detail.get("vip_timer_service_type") or "")
                for detail in list(group.get("details") or ())
            ]
            assert headcounts
            assert set(headcounts).issubset(allowed)
            assert len(headcounts) == len(set(headcounts))
