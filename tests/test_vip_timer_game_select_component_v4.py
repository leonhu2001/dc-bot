from services import vip_timer_catalog_guard as guard
from services import vip_timer_policy_v5 as v5
from services import vip_timer_select_flow as flow
from services import vip_timer_selector_order_v2 as v2
from services import vip_timer_selector_order_v3 as v3
from services import vip_timer_selector_order_v4 as v4


def test_game_select_options_are_games_not_gameplay_groups():
    guard.install_vip_timer_catalog_guard()
    flow.install_vip_timer_select_flow()
    v2.install_vip_timer_selector_order_v2()
    v3.install_vip_timer_selector_order_v3()
    v4.install_vip_timer_selector_order_v4()
    v5.install_vip_timer_policy_v5()

    select = v4.VipTimerGameSelect(customer_id=1, channel_id=999999)
    labels = {option.label for option in select.options}

    assert {"三角洲端遊", "三角洲手遊", "特戰英豪", "英雄聯盟", "APEX", "STEAM"}.issubset(labels)
    assert labels.isdisjoint({"娛樂陪", "技術陪", "黑潮爆破", "一陪一護", "絕巴技術陪"})
    assert select.row == 1
