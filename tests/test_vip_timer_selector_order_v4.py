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


def test_game_layer_is_game_only_and_next_layer_is_category():
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
    category_groups = v4._category_groups(desktop_details)
    category_labels = {str(group.get("label") or "") for group in category_groups}

    assert "娛樂陪" in category_labels
    assert "技術陪" in category_labels
    assert "絕巴技術陪" in category_labels
    assert all("機密" not in label and "絕密" not in label for label in category_labels)

    # Concrete gameplay now lives one level below the category.
    technical = next(group for group in category_groups if group["label"] == "技術陪")
    gameplay_labels = {
        str(group.get("label") or "")
        for group in v4._gameplay_groups(technical["details"], technical["label"])
    }
    assert "機密" in gameplay_labels
    assert "絕密" in gameplay_labels

    # The hierarchy is derived only from currently eligible hourly products.
    detail_rule_keys = {str(detail.get("rule_key") or "") for detail in desktop_details}
    assert all(detail_rule_keys)


def test_headcount_layer_contains_only_supported_options():
    _install_checkout_stack()

    allowed = {"單陪", "雙陪", "三陪", "四陪"}
    for game in v4._game_rows():
        details = v4._direct_details_for_game(str(game.get("label") or ""))
        for category in v4._category_groups(details):
            gameplay_groups = v4._gameplay_groups(
                category["details"],
                str(category.get("label") or ""),
            )
            for gameplay in gameplay_groups:
                headcounts = [v4._headcount_label(detail) for detail in v4._headcount_details(gameplay)]
                assert headcounts
                assert set(headcounts).issubset(allowed)
                assert len(headcounts) == len(set(headcounts))
