from services import order_rule_store
from services.order_rule_store import (
    create_custom_order_rule,
    ensure_order_rule_store,
    list_rule_versions,
    publish_rule_override,
    reset_rule_override,
    rollback_rule_override,
)
from services.order_rules import (
    ORDER_RULES,
    OrderRule,
    build_custom_rule,
    get_base_rule,
    get_rules_by_category,
    invalidate_rule_override_cache,
    preview_rule_override,
    rule_to_override_payload,
)


def test_rule_override_publish_rollback_and_reset(tmp_path, monkeypatch):
    db_file = tmp_path / "web_dashboard.db"
    ensure_order_rule_store(db_file)

    monkeypatch.setattr(
        order_rule_store,
        "default_db_path",
        lambda: db_file,
    )

    key = "basic_tech_secret_single"
    base = get_base_rule(key)
    payload_v1 = rule_to_override_payload(base)
    payload_v1["price"] = int(base.price) + 11
    payload_v1["label"] = base.label + " 測試"

    preview_rule_override(key, payload_v1)
    first = publish_rule_override(
        rule_key=key,
        payload=payload_v1,
        actor_discord_id="1",
        actor_display_name="Tester",
        expected_active_version=0,
        db_file=db_file,
    )

    invalidate_rule_override_cache()
    assert ORDER_RULES[key].price == int(base.price) + 11
    assert ORDER_RULES[key].label.endswith("測試")

    payload_v2 = dict(payload_v1)
    payload_v2["price"] = int(base.price) + 22
    second = publish_rule_override(
        rule_key=key,
        payload=payload_v2,
        actor_discord_id="1",
        actor_display_name="Tester",
        expected_active_version=int(first["version"]),
        db_file=db_file,
    )

    invalidate_rule_override_cache()
    assert ORDER_RULES[key].price == int(base.price) + 22

    rolled = rollback_rule_override(
        rule_key=key,
        target_version=int(first["version"]),
        actor_discord_id="1",
        actor_display_name="Tester",
        expected_active_version=int(second["version"]),
        db_file=db_file,
    )
    invalidate_rule_override_cache()
    assert ORDER_RULES[key].price == int(base.price) + 11
    assert int(rolled["source_version"]) == int(first["version"])

    versions = list_rule_versions(key, db_file=db_file)
    assert [row["action"] for row in versions[:3]] == [
        "rollback",
        "publish",
        "publish",
    ]

    reset_rule_override(
        rule_key=key,
        actor_discord_id="1",
        actor_display_name="Tester",
        expected_active_version=int(rolled["version"]),
        db_file=db_file,
    )
    invalidate_rule_override_cache()
    assert ORDER_RULES[key].price == base.price
    assert ORDER_RULES[key].label == base.label


def test_invalid_rule_override_is_blocked():
    key = "basic_tech_secret_single"
    payload = rule_to_override_payload(get_base_rule(key))
    payload["allowed_roles"] = []
    payload["allowed_game_roles"] = []

    try:
        preview_rule_override(key, payload)
    except RuntimeError as exc:
        assert "no allowed roles" in str(exc)
    else:
        raise AssertionError("invalid rule override should be blocked")

def test_manager_created_rule_becomes_effective_without_code_definition(
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

    key = "admin_apex_test_product"
    seed = OrderRule(
        category="apex",
        key=key,
        label="APEX｜測試新商品",
        pricing_type="hourly",
        price=420,
        unit_label="H",
        allowed_roles=("male_companion",),
        required_game_roles=("apex_game",),
        required_staff_count=1,
        min_quantity=1,
        max_quantity=4,
    )
    payload = rule_to_override_payload(seed)

    preview = build_custom_rule(key, "apex", payload)
    assert preview.category == "apex"
    assert preview.price == 420

    created = create_custom_order_rule(
        rule_key=key,
        category="apex",
        payload=payload,
        actor_discord_id="1",
        actor_display_name="Tester",
        db_file=db_file,
    )
    assert created["action"] == "create"

    invalidate_rule_override_cache()

    assert key in ORDER_RULES
    assert ORDER_RULES[key].label == "APEX｜測試新商品"
    assert ORDER_RULES[key].required_game_roles == ("apex_game",)
    assert key in {rule.key for rule in get_rules_by_category("apex")}
    assert get_base_rule(key).price == 420

    edited = dict(payload)
    edited["price"] = 450
    result = publish_rule_override(
        rule_key=key,
        payload=edited,
        actor_discord_id="1",
        actor_display_name="Tester",
        expected_active_version=0,
        db_file=db_file,
    )

    invalidate_rule_override_cache()
    assert ORDER_RULES[key].price == 450

    reset_rule_override(
        rule_key=key,
        actor_discord_id="1",
        actor_display_name="Tester",
        expected_active_version=int(result["version"]),
        db_file=db_file,
    )
    invalidate_rule_override_cache()

    assert ORDER_RULES[key].price == 420
    assert [row["action"] for row in list_rule_versions(key, db_file=db_file)[:3]] == [
        "reset",
        "publish",
        "create",
    ]


def test_manager_created_rule_appears_in_dynamic_self_service_group(
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

    key = "admin_valorant_test_product"
    payload = rule_to_override_payload(
        OrderRule(
            category="valorant",
            key=key,
            label="特戰英豪｜測試商品",
            pricing_type="game",
            price=300,
            unit_label="局",
            allowed_game_roles=("valorant_ascendant",),
            required_game_roles=("valorant_game",),
            required_staff_count=1,
            min_quantity=1,
            max_quantity=5,
        )
    )

    create_custom_order_rule(
        rule_key=key,
        category="valorant",
        payload=payload,
        actor_discord_id="1",
        actor_display_name="Tester",
        db_file=db_file,
    )
    invalidate_rule_override_cache()

    from services.orders import (
        DYNAMIC_ADMIN_GROUP_LABEL,
        ORDER_ITEM_GROUPS_BY_CATEGORY,
        get_order_item_details_for_group,
        get_order_item_group_label,
    )

    groups = ORDER_ITEM_GROUPS_BY_CATEGORY.get("valorant", [])
    assert DYNAMIC_ADMIN_GROUP_LABEL in groups

    details = get_order_item_details_for_group(
        "valorant",
        DYNAMIC_ADMIN_GROUP_LABEL,
    )
    assert any(
        item["rule_key"] == key
        and item["label"] == "特戰英豪｜測試商品"
        and item["quantity_unit"] == "局"
        and item["max_quantity"] == 5
        for item in details
    )
    assert get_order_item_group_label("特戰英豪｜測試商品") == (
        DYNAMIC_ADMIN_GROUP_LABEL
    )

