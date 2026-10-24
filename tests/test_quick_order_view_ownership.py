from pathlib import Path
from types import SimpleNamespace

import discord

from services.quick_order_v2_select_display import (
    LEGACY_RESELECT_FLAG,
    apply_quick_order_select_display,
)


def test_order_ticket_policy_no_longer_owns_quick_order_view_patch():
    source = Path("services/order_ticket_ui_policy.py").read_text(encoding="utf-8")

    assert "_install_ticket_patch" not in source
    assert "SelfServiceOrderView.__init__" not in source
    assert "classic_aware_view_init" not in source


def test_production_is_the_single_quick_order_view_owner():
    source = Path("services/quick_order_v2_production.py").read_text(encoding="utf-8")

    assert source.count("ui.SelfServiceOrderView.__init__ = ticket_view_init") == 1
    assert "selected_category is None" in source
    assert "data[LEGACY_RESELECT_FLAG] = True" in source
    assert "apply_quick_order_select_display(self, data)" in source


def _select(custom_id: str, options: list[tuple[str, str]]) -> discord.ui.Select:
    return discord.ui.Select(
        custom_id=custom_id,
        options=[
            discord.SelectOption(label=label, value=value)
            for label, value in options
        ],
    )


def test_classic_reselect_display_restores_all_four_saved_selections():
    category = _select(
        "self_service_order_category_select",
        [("三角洲行動", "delta"), ("英雄聯盟", "lol")],
    )
    item = _select(
        "self_service_order_item_select",
        [("娛樂陪", "娛樂陪"), ("大師陪", "大師陪")],
    )
    detail = _select(
        "self_service_order_detail_select",
        [("雙陪", "duo"), ("單陪", "solo")],
    )
    quantity = _select(
        "self_service_order_quantity_select",
        [("1 小時", "1"), ("2 小時", "2")],
    )

    view = SimpleNamespace(children=[category, item, detail, quantity])
    data = {
        "quick_order_v2": True,
        LEGACY_RESELECT_FLAG: True,
        "category": "delta",
        "item_group": "娛樂陪",
        "item_detail_value": "duo",
        "item": "雙陪",
        "quantity": 2,
    }

    apply_quick_order_select_display(view, data)

    assert category.placeholder == "已選：三角洲行動"
    assert item.placeholder == "已選：娛樂陪"
    assert detail.placeholder == "已選：雙陪"
    assert quantity.placeholder == "已選：2 小時"

    assert next(option for option in category.options if option.value == "delta").default
    assert next(option for option in item.options if option.value == "娛樂陪").default
    assert next(option for option in detail.options if option.value == "duo").default
    assert next(option for option in quantity.options if option.value == "2").default
