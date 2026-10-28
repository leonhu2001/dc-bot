from __future__ import annotations

import services  # noqa: F401 - installs production policies
from services import (
    black_tide_legacy_tombstone,
    order_rule_store,
    order_rules,
    orders,
)
from web.app.services import order_groups as web_order_groups


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


def _store_payload(label: str, group_label: str) -> dict:
    return {
        "label": label,
        "pricing_type": "hourly",
        "price": 320,
        "unit_label": "H",
        "catalog_group_label": group_label,
    }


def test_retired_black_tide_database_rows_never_reenter_live_catalog(monkeypatch) -> None:
    stale = {
        # Old runtime/source-style key: should be blocked regardless of group name.
        "basic_black_tide_entertain_1": _stale_custom_definition(
            "basic_black_tide_entertain_1",
            "黑潮爆破｜娛樂單陪",
            "娛樂單陪",
        ),
        # Web manager creates generated admin_* keys. If it lives under 黑潮爆破,
        # it must not be merged into Discord/Web as a third Black Tide variant.
        "admin_delta_desktop_basic_legacy_bt_1": _stale_custom_definition(
            "admin_delta_desktop_basic_legacy_bt_1",
            "娛樂雙/三/四陪",
            "黑潮爆破",
        ),
        # Also cover a custom rule that was later moved into 黑潮爆破 by an override.
        "admin_delta_desktop_basic_legacy_bt_2": _stale_custom_definition(
            "admin_delta_desktop_basic_legacy_bt_2",
            "技術單陪",
            "舊測試分組",
        ),
        # A normal custom product elsewhere must remain available.
        "admin_delta_desktop_basic_keep_me": _stale_custom_definition(
            "admin_delta_desktop_basic_keep_me",
            "測試保留商品",
            "其他測試分組",
        ),
    }
    overrides = {
        "admin_delta_desktop_basic_legacy_bt_2": {
            "version": 7,
            "payload": {"catalog_group_label": "黑潮爆破"},
            "updated_by_discord_id": "legacy",
            "updated_by_display_name": "legacy migration",
            "updated_at": "2026-10-28T00:00:00+00:00",
        }
    }

    monkeypatch.setattr(order_rule_store, "load_custom_rule_definitions", lambda *args, **kwargs: stale)
    monkeypatch.setattr(order_rule_store, "load_active_overrides", lambda *args, **kwargs: overrides)

    order_rules.ORDER_RULES.invalidate()
    try:
        assert "basic_black_tide_entertain_1" not in order_rules.ORDER_RULES
        assert "admin_delta_desktop_basic_legacy_bt_1" not in order_rules.ORDER_RULES
        assert "admin_delta_desktop_basic_legacy_bt_2" not in order_rules.ORDER_RULES
        assert "admin_delta_desktop_basic_keep_me" in order_rules.ORDER_RULES

        group_labels = orders.ORDER_ITEM_GROUPS_BY_CATEGORY.get("delta_desktop_basic", [])
        assert "娛樂單陪" not in group_labels
        assert "娛樂雙/三/四陪" not in group_labels
        assert "技術單陪" not in group_labels
        assert "技術雙/三/四陪" not in group_labels
        assert "其他測試分組" in group_labels

        details = orders.get_order_item_details_for_group(
            "delta_desktop_basic",
            "黑潮爆破",
        )
        assert [item["label"] for item in details] == ["娛樂陪", "技術陪"]
        assert [item["rule_key"] for item in details] == [
            "basic_black_tide_entertain",
            "basic_black_tide_tech",
        ]

        web_black_tide = next(
            group
            for group in web_order_groups.get_grouped_order_catalog("delta_desktop_basic")
            if group["key"] == "black_tide"
        )
        assert [item["label"] for item in web_black_tide["variants"]] == ["娛樂陪", "技術陪"]
        assert [item["rule_key"] for item in web_black_tide["variants"]] == [
            "basic_black_tide_entertain",
            "basic_black_tide_tech",
        ]
    finally:
        order_rules.ORDER_RULES.invalidate()


def test_stale_black_tide_manager_rows_are_persistently_deactivated(tmp_path) -> None:
    db_file = tmp_path / "manager-rules.db"
    order_rule_store.ensure_order_rule_store(db_file)

    rows = {
        "basic_black_tide_tech_4": _store_payload(
            "黑潮爆破｜技術四陪",
            "舊歷史分組",
        ),
        "admin_delta_desktop_basic_bt_group": _store_payload(
            "娛樂雙/三/四陪",
            "黑潮爆破",
        ),
        "admin_delta_desktop_basic_bt_override": _store_payload(
            "技術單陪",
            "舊測試分組",
        ),
        "admin_delta_desktop_basic_keep": _store_payload(
            "其他正常商品",
            "其他正常分組",
        ),
    }

    for key, payload in rows.items():
        order_rule_store.create_custom_order_rule(
            rule_key=key,
            category="delta_desktop_basic",
            payload=payload,
            actor_discord_id="test",
            actor_display_name="test",
            db_file=db_file,
        )

    order_rule_store.publish_rule_override(
        rule_key="admin_delta_desktop_basic_bt_override",
        payload={"catalog_group_label": "黑潮爆破"},
        actor_discord_id="test",
        actor_display_name="test",
        db_file=db_file,
    )

    retired = black_tide_legacy_tombstone.retire_stale_black_tide_custom_rows(db_file)
    assert retired == 3

    active = order_rule_store.load_custom_rule_definitions(db_file)
    assert set(active) == {"admin_delta_desktop_basic_keep"}

    # The cleanup is idempotent and does not touch normal manager products.
    assert black_tide_legacy_tombstone.retire_stale_black_tide_custom_rows(db_file) == 0
    active_again = order_rule_store.load_custom_rule_definitions(db_file)
    assert set(active_again) == {"admin_delta_desktop_basic_keep"}
