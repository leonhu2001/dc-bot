from services import order_rule_store
from services.order_rule_store import (
    create_custom_order_rule,
    ensure_order_rule_store,
    publish_rule_override,
)
from services.order_rules import (
    OrderRule,
    get_base_rule,
    invalidate_rule_override_cache,
    rule_to_override_payload,
)
from web.app.services.order_groups import get_grouped_order_catalog


def test_manager_created_product_appears_in_public_catalog(
    tmp_path,
    monkeypatch,
):
    db_file = tmp_path / "web_dashboard.db"
    ensure_order_rule_store(db_file)

    monkeypatch.setattr(
        order_rule_store,
        "default_db_path",
        lambda: db_file,
    )

    key = "admin_farm_brave_companion"
    payload = rule_to_override_payload(
        OrderRule(
            category="farm",
            key=key,
            label="陪解 勇敢者",
            catalog_group_label="陪解",
            pricing_type="fixed",
            price=3600,
            unit_label="單",
            allowed_roles=("male_companion",),
            required_staff_count=2,
            min_quantity=1,
            max_quantity=1,
        )
    )

    create_custom_order_rule(
        rule_key=key,
        category="farm",
        payload=payload,
        actor_discord_id="1",
        actor_display_name="Tester",
        db_file=db_file,
    )
    invalidate_rule_override_cache()

    groups = get_grouped_order_catalog("farm")
    group = next(
        item
        for item in groups
        if item["label"] == "陪解"
    )
    variant = next(
        item
        for item in group["variants"]
        if item["rule_key"] == key
    )

    assert variant["label"] == "陪解 勇敢者"
    assert variant["price"] == 3600
    assert group["starting_price_text"] == "3,600T"

    invalidate_rule_override_cache()


def test_manager_rename_updates_builtin_public_and_discord_catalogs(
    tmp_path,
    monkeypatch,
):
    db_file = tmp_path / "web_dashboard.db"
    ensure_order_rule_store(db_file)

    monkeypatch.setattr(
        order_rule_store,
        "default_db_path",
        lambda: db_file,
    )

    key = "fun_read_no_reply"
    payload = rule_to_override_payload(get_base_rule(key))
    payload["label"] = "一命通關"
    payload["catalog_group_label"] = "一命通關"

    publish_rule_override(
        rule_key=key,
        payload=payload,
        actor_discord_id="1",
        actor_display_name="Tester",
        expected_active_version=0,
        db_file=db_file,
    )
    invalidate_rule_override_cache()

    web_groups = get_grouped_order_catalog("delta_desktop_fun")
    renamed = next(
        item
        for item in web_groups
        if item["label"] == "一命通關"
    )
    variant = next(
        item
        for item in renamed["variants"]
        if item["rule_key"] == key
    )

    assert variant["label"] == "一命通關"
    assert not any(
        item["label"] == "已讀亂回"
        and any(
            option["rule_key"] == key
            for option in item["variants"]
        )
        for item in web_groups
    )

    from services.orders import (
        ORDER_ITEM_GROUPS_BY_CATEGORY,
        get_order_item_details_for_group,
    )

    discord_groups = ORDER_ITEM_GROUPS_BY_CATEGORY.get("delta_desktop_fun")
    assert "一命通關" in discord_groups
    assert "已讀亂回" not in discord_groups

    discord_details = get_order_item_details_for_group(
        "delta_desktop_fun",
        "一命通關",
    )
    discord_variant = next(
        item
        for item in discord_details
        if item["rule_key"] == key
    )
    assert discord_variant["label"] == "一命通關"
    assert discord_variant["item"] == "一命通關"

    invalidate_rule_override_cache()
