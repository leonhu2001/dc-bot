from __future__ import annotations

from types import SimpleNamespace

from services import vip_timer_selector_order_v2 as flow_v2


def test_service_type_splits_three_and_four_companions():
    rule = SimpleNamespace(label="技術陪", required_staff_count="player_count", min_player_count=1)

    assert flow_v2._service_type("技術陪", {"label": "機密", "player_count": 1}, rule) == "單陪"
    assert flow_v2._service_type("技術陪", {"label": "機密", "player_count": 2}, rule) == "雙陪"
    assert flow_v2._service_type("技術陪", {"label": "機密", "player_count": 3}, rule) == "三陪"
    assert flow_v2._service_type("技術陪", {"label": "機密", "player_count": 4}, rule) == "四陪"


def test_unsupported_special_services_stay_out_of_vip_timer():
    rule = SimpleNamespace(label="甜蜜單", required_staff_count=2)
    assert flow_v2._service_type("甜蜜單", {"label": "甜蜜雙人"}, rule) == "不支援"

    rule = SimpleNamespace(label="教學單", required_staff_count=1)
    assert flow_v2._service_type("教學單", {"label": "導師教學"}, rule) == "不支援"


def test_gameplay_group_collects_service_variants_for_dynamic_fourth_layer():
    groups = flow_v2._spec_groups(
        [
            {
                "vip_timer_spec_label": "技術｜機密",
                "vip_timer_service_type": "單陪",
                "value": "vt:single:1",
            },
            {
                "vip_timer_spec_label": "技術｜機密",
                "vip_timer_service_type": "雙陪",
                "value": "vt:double:2",
            },
            {
                "vip_timer_spec_label": "技術｜絕密",
                "vip_timer_service_type": "單陪",
                "value": "vt:secret:1",
            },
        ]
    )

    assert [group["label"] for group in groups] == ["技術｜機密", "技術｜絕密"]
    assert [row["vip_timer_service_type"] for row in groups[0]["details"]] == ["雙陪", "單陪"] or [
        row["vip_timer_service_type"] for row in groups[0]["details"]
    ] == ["單陪", "雙陪"]


def test_spec_label_removes_headcount_words_from_gameplay_layer():
    assert flow_v2._spec_label(
        source_group="技術陪",
        detail_label="機密三陪｜陪玩3名",
        variant="基礎",
        service_type="三陪",
    ) == "技術｜機密"
