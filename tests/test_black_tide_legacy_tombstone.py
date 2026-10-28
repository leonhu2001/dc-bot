from __future__ import annotations

import services  # noqa: F401 - installs production policies
from services import order_rule_store, order_rules, orders


def _stale_custom_definition(rule_key: str, label: str, group_label: str) -> dict:
    return {
        "rule_key": rule_key,
        "category": "delta_desktop_basic",
        "payload": {
            "label": label,
            "pricing_type": "hourly",
            "price": 320,
            "unit_label": "H",
            "catalog_group_label": group_label,
        },
        "created_by_discord_id": "legacy",
        "created_by_display_name": "legacy migration",
        "created_at": "2026-10-28T00:00:00+00:00",
    }


def test_retired_black_tide_database_rows_never_reenter_live_catalog(monkeypatch) -> None:
    stale = {
        "basic_black_tide_entertain_1": _stale_custom_definition(
            "basic_black_tide_entertain_1",
            "黑潮爆破｜娛樂單陪",
            "娛樂單陪",
        ),
        # Cover unknown historical suffixes too: only the two canonical keys may live.
        "basic_black_tide_tech_legacy_group": _stale_custom_definition(
            "basic_black_tide_tech_legacy_group",
            "黑潮爆破｜技術雙/三/四陪",
            "技術雙/三/四陪",
        ),
    }

    monkeypatch.setattr(order_rule_store, "load_custom_rule_definitions", lambda *args, **kwargs: stale)
    monkeypatch.setattr(order_rule_store, "load_active_overrides", lambda *args, **kwargs: {})

    order_rules.ORDER_RULES.invalidate()
    try:
        assert "basic_black_tide_entertain_1" not in order_rules.ORDER_RULES
        assert "basic_black_tide_tech_legacy_group" not in order_rules.ORDER_RULES

        group_labels = orders.ORDER_ITEM_GROUPS_BY_CATEGORY.get("delta_desktop_basic", [])
        assert "娛樂單陪" not in group_labels
        assert "娛樂雙/三/四陪" not in group_labels
        assert "技術單陪" not in group_labels
        assert "技術雙/三/四陪" not in group_labels

        details = orders.get_order_item_details_for_group(
            "delta_desktop_basic",
            "黑潮爆破",
        )
        assert [item["label"] for item in details] == ["娛樂陪", "技術陪"]
        assert [item["rule_key"] for item in details] == [
            "basic_black_tide_entertain",
            "basic_black_tide_tech",
        ]
    finally:
        order_rules.ORDER_RULES.invalidate()
