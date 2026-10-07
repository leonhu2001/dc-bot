from services import order_rule_store
from services.order_rule_store import (
    create_custom_order_rule,
    ensure_order_rule_store,
)
from services.order_rules import (
    OrderRule,
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
