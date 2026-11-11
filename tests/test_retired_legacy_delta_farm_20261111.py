"""Public retirement of expired Delta farm products (2026-11-11).

Old rules remain usable for historical order and salary lookups, but are never
listed, selectable, reactivated, or accepted as a NEW Bot/Web checkout.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from services import order_product_status, order_rule_store, orders
from services.order_product_status import (
    RETIRED_LEGACY_FARM_RULE_KEYS,
    get_order_product_status,
    install_discord_catalog_guards,
    install_web_catalog_guards,
    is_order_product_active,
    is_retired_legacy_farm_product,
    set_order_product_active,
)
from services.order_rules import ORDER_RULES
from web.app.services.order_groups import get_grouped_order_catalog
from web.app.services.public_checkout import build_public_quote


@pytest.mark.parametrize("key", sorted(RETIRED_LEGACY_FARM_RULE_KEYS))
def test_old_halfcoin_archived_but_rule_and_historical_price_remain(key):
    assert key in ORDER_RULES
    assert ORDER_RULES[key].category == "farm"
    assert is_retired_legacy_farm_product(key)
    assert not is_order_product_active(key)
    assert get_order_product_status(key)["is_active"] is False
    with pytest.raises(ValueError, match="停止提供"):
        build_public_quote(rule_key=key, quantity=1, player_count=1)


def test_old_halfcoin_and_mouth_organ_absent_from_web_bot_new_order_menus():
    install_web_catalog_guards()
    install_discord_catalog_guards()

    farm_groups = orders.ORDER_ITEM_GROUPS_BY_CATEGORY.get("farm")
    assert "哈夫幣代洗" not in farm_groups
    assert "哈夫幣代肝" not in farm_groups
    assert "守夜人口風琴" not in farm_groups
    assert orders.get_order_item_details_for_group("farm", "哈夫幣代洗") == []
    assert orders.get_order_item_details_for_group("farm", "守夜人口風琴") == []

    visible = get_grouped_order_catalog("farm")
    web_keys = {
        row["rule_key"] for group in visible for row in group["variants"]
    }
    assert not RETIRED_LEGACY_FARM_RULE_KEYS.intersection(web_keys)
    assert "halfcoin" not in {group["key"] for group in visible}
    assert all("口風琴" not in group["label"] for group in visible)

    # New replacements remain available, with prices and cuts untouched.
    groups = {group["key"]: group for group in visible}
    for kind, count in (("ammo_dump", 6), ("car_crash", 4)):
        assert len(groups[kind]["variants"]) == count


@pytest.mark.parametrize("key", sorted(RETIRED_LEGACY_FARM_RULE_KEYS))
def test_bot_direct_stale_selection_rejected_even_if_rule_still_exists(key):
    install_discord_catalog_guards()
    with pytest.raises(ValueError, match="已下架"):
        order_product_status._guarded_self_service_rule({
            "order_rule_key": key, "item": ORDER_RULES[key].label,
        })


def test_custom_old_event_cannot_resurface_when_admin_has_left_it_active(monkeypatch):
    old_get = ORDER_RULES.get
    old = {
        "custom_farm_old_event": SimpleNamespace(
            key="custom_farm_old_event", category="farm",
            label="守夜人口風琴｜三日活動", catalog_group_label="活動商品",
        ),
        "custom_farm_old_halfcoin": SimpleNamespace(
            key="custom_farm_old_halfcoin", category="farm",
            label="測試規格", catalog_group_label="哈夫幣代洗",
        ),
        "custom_other_event": SimpleNamespace(
            key="custom_other_event", category="apex",
            label="守夜人口風琴", catalog_group_label="娛樂",
        ),
    }

    monkeypatch.setattr(
        ORDER_RULES, "get", lambda key, default=None: old.get(key, old_get(key, default))
    )
    assert is_retired_legacy_farm_product("custom_farm_old_event")
    assert is_retired_legacy_farm_product("custom_farm_old_halfcoin")
    assert not is_order_product_active("custom_farm_old_event")
    assert not is_retired_legacy_farm_product("custom_other_event")

    with pytest.raises(ValueError, match="已退役"):
        set_order_product_active(
            rule_key="custom_farm_old_event", is_active=True,
            actor_discord_id="manager", actor_display_name="Manager",
        )


@pytest.mark.parametrize("key", sorted(RETIRED_LEGACY_FARM_RULE_KEYS))
def test_manager_cannot_reenable_retired_builtins_even_if_old_database_says_active(
    tmp_path, key,
):
    db = tmp_path / "test_status.db"
    order_product_status.ensure_order_product_status_store(db)
    with pytest.raises(ValueError, match="已退役"):
        set_order_product_active(
            rule_key=key, is_active=True, actor_discord_id="manager",
            actor_display_name="Manager", db_file=db,
        )
    assert not is_order_product_active(key, db)


def test_legacy_retirement_does_not_disable_special_internal_or_new_fixed_cut():
    for key in (
        "staff_internal_ammo_dump_500m",
        "staff_internal_car_500m",
        "farm_ammo_dump_100m",
        "farm_ammo_dump_500m",
        "farm_car_crash_100m",
        "farm_car_crash_1000m",
        "farm_aw_collision_1_100",
        "farm_season_3x3_normal",
    ):
        assert not is_retired_legacy_farm_product(key), key


def test_admin_product_editor_keeps_retired_halfcoin_out_of_active_rule_list():
    from web.app.routers.admin_order_rules import _is_admin_editable_rule
    assert not any(
        _is_admin_editable_rule(key) for key in RETIRED_LEGACY_FARM_RULE_KEYS
    )
    assert _is_admin_editable_rule("farm_ammo_dump_100m")
    assert _is_admin_editable_rule("farm_car_crash_1000m")
