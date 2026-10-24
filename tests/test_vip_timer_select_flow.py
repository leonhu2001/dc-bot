from __future__ import annotations

from services.order_rules import ORDER_RULES
from services import vip_timer_select_flow as flow


def test_timer_catalog_is_grouped_by_game_and_service_type():
    groups = flow.build_vip_timer_self_service_catalog()

    assert groups
    assert len(groups) <= 25
    assert len({str(group.get("label") or "") for group in groups}) == len(groups)

    allowed_services = {"單陪", "雙陪", "三陪", "四陪", "多人陪", "甜蜜陪", "教學單", "其他"}
    seen_values: set[str] = set()

    for group in groups:
        details = list(group.get("details") or [])
        assert details
        for detail in details:
            rule_key = str(detail.get("rule_key") or "")
            rule = ORDER_RULES.get(rule_key)
            assert rule is not None
            assert str(getattr(rule, "pricing_type", "")) == "hourly"
            assert detail.get("vip_timer_service_type") in allowed_services
            assert str(detail.get("vip_timer_spec_label") or "").strip()
            assert int(detail.get("min_quantity") or 0) == 1
            assert int(detail.get("max_quantity") or 0) == 1
            value = str(detail.get("value") or "")
            assert value not in seen_values
            seen_values.add(value)


def test_second_layer_contains_games_not_play_styles():
    labels = {
        str(group.get("label") or "").strip()
        for group in flow.build_vip_timer_self_service_catalog()
    }

    assert labels
    assert labels.isdisjoint({
        "娛樂陪",
        "技術陪",
        "黑潮爆破",
        "絕巴技術陪",
        "一陪一護",
        "一陪一護〈端遊〉",
        "一陪一護〈手遊〉",
    })
    assert any(
        label in {"特戰英豪", "英雄聯盟", "APEX", "STEAM", "STEAM 遊戲"}
        or "三角洲" in label
        for label in labels
    )


def test_service_pages_never_exceed_discord_select_limit():
    for group in flow.build_vip_timer_self_service_catalog():
        pages = flow._service_pages(list(group.get("details") or []))
        assert pages
        assert len(pages) <= 25
        for page in pages:
            assert 1 <= len(page.get("details") or []) <= 25


def test_timer_game_grouping_keeps_delta_platforms_compact():
    labels = {str(group.get("label") or "") for group in flow.build_vip_timer_self_service_catalog()}

    assert {"三角洲端遊", "三角洲手遊"} & labels
    assert not any("基礎單" in label for label in labels)
    assert not any("趣味單" in label for label in labels)


def test_spec_label_removes_redundant_staff_count_words():
    assert flow._spec_label(
        source_group="技術陪",
        detail_label="機密單陪",
        variant="基礎",
        service_type="單陪",
    ) == "技術｜機密"

    assert flow._spec_label(
        source_group="娛樂陪",
        detail_label="NG｜陪玩2名",
        variant="",
        service_type="雙陪",
    ) == "娛樂"
