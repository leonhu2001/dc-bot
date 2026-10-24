from __future__ import annotations

import inspect
from types import SimpleNamespace

from services import vip_timer_selector_order_v4 as v4


def _detail(rule_key: str, spec: str, service: str, value: str) -> dict:
    return {
        "rule_key": rule_key,
        "vip_timer_spec_label": spec,
        "vip_timer_service_type": service,
        "label": spec,
        "item": f"{spec}｜{service}",
        "value": value,
        "player_count": {"單陪": 1, "雙陪": 2}.get(service, 1),
    }


def test_timer_checkout_groups_category_before_gameplay(monkeypatch):
    rules = {
        "fun-ng": SimpleNamespace(catalog_group_label="娛樂陪"),
        "tech-secret-1": SimpleNamespace(catalog_group_label="技術陪"),
        "tech-secret-2": SimpleNamespace(catalog_group_label="技術陪"),
        "tech-classified": SimpleNamespace(catalog_group_label="技術陪"),
    }
    monkeypatch.setattr(v4, "_rule_for_detail", lambda detail: rules[detail["rule_key"]])
    monkeypatch.setattr(v4, "_effective_rate", lambda detail: 300)

    details = [
        _detail("fun-ng", "娛樂｜NG", "單陪", "fun-ng"),
        _detail("tech-secret-1", "技術｜機密", "單陪", "secret-1"),
        _detail("tech-secret-2", "技術｜機密", "雙陪", "secret-2"),
        _detail("tech-classified", "技術｜絕密", "單陪", "classified"),
    ]

    categories = v4._category_groups(details)
    assert [row["label"] for row in categories] == ["娛樂陪", "技術陪"]
    assert all("機密" not in row["label"] and "絕密" not in row["label"] for row in categories)

    technical = next(row for row in categories if row["label"] == "技術陪")
    gameplay = v4._gameplay_groups(technical["details"], technical["label"])
    assert [row["label"] for row in gameplay] == ["機密", "絕密"]

    secret = next(row for row in gameplay if row["label"] == "機密")
    assert [v4._headcount_label(row) for row in v4._headcount_details(secret)] == ["單陪", "雙陪"]


def test_timer_view_exposes_game_category_gameplay_headcount_in_that_order():
    game_source = inspect.getsource(v4.VipTimerGameSelect.__init__)
    category_source = inspect.getsource(v4.VipTimerCategorySelect.__init__)
    gameplay_source = inspect.getsource(v4.VipTimerGameplaySelect.__init__)
    headcount_source = inspect.getsource(v4.VipTimerHeadcountSelect.__init__)
    view_source = inspect.getsource(v4._install_view_patch)

    assert 'placeholder="選擇遊戲"' in game_source
    assert 'row=0' in game_source
    assert 'placeholder = "選擇分類"' in category_source
    assert 'row=1' in category_source
    assert 'placeholder = "選擇玩法／規格"' in gameplay_source
    assert 'row=2' in gameplay_source
    assert 'placeholder = "選擇陪玩人數"' in headcount_source
    assert 'row=3' in headcount_source

    assert "VipTimerGameSelect(customer_id, channel_id)" in view_source
    assert "VipTimerCategorySelect(customer_id, channel_id)" in view_source
    assert "VipTimerGameplaySelect(customer_id, channel_id)" in view_source
    assert "VipTimerHeadcountSelect(customer_id, channel_id)" in view_source


def test_timer_checkout_hides_irrelevant_disabled_finance_buttons():
    source = inspect.getsource(v4._install_view_patch)
    for custom_id in (
        "self_service_order_specified_staff_button",
        "self_service_order_point_benefit_button",
        "self_service_order_staff_price_button",
        "self_service_order_staff_discount_coupon_button",
    ):
        assert custom_id in source
