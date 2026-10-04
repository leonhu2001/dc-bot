from services import order_rule_store
from services.order_rule_store import (
    create_custom_rule_definition,
    ensure_order_rule_store,
    list_custom_rule_definitions,
    list_rule_versions,
    publish_rule_override,
    reset_rule_override,
    rollback_rule_override,
)
from services.order_rules import (
    ORDER_RULES,
    build_custom_rule_definition,
    get_base_rule,
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

def test_custom_product_is_live_in_effective_rules_and_can_be_overridden(
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
    invalidate_rule_override_cache()

    key = "admin_steam_test_product"
    payload = rule_to_override_payload(get_base_rule("steam_play"))
    payload["label"] = "Steam｜後台新增測試"
    payload["price"] = 777
    payload["min_quantity"] = 1
    payload["max_quantity"] = 6

    rule = build_custom_rule_definition(key, "steam", payload)
    create_custom_rule_definition(
        rule_key=key,
        category="steam",
        payload=rule_to_override_payload(rule),
        actor_discord_id="1",
        actor_display_name="Tester",
        db_file=db_file,
    )

    invalidate_rule_override_cache()
    try:
        assert key in ORDER_RULES
        assert ORDER_RULES[key].category == "steam"
        assert ORDER_RULES[key].label == "Steam｜後台新增測試"
        assert ORDER_RULES[key].price == 777
        assert get_base_rule(key).price == 777

        rows = list_custom_rule_definitions(
            category="steam",
            db_file=db_file,
        )
        assert [row["rule_key"] for row in rows] == [key]

        override = rule_to_override_payload(ORDER_RULES[key])
        override["price"] = 888
        result = publish_rule_override(
            rule_key=key,
            payload=override,
            actor_discord_id="1",
            actor_display_name="Tester",
            expected_active_version=0,
            db_file=db_file,
        )
        assert int(result["version"]) == 1

        invalidate_rule_override_cache()
        assert ORDER_RULES[key].price == 888

        reset_rule_override(
            rule_key=key,
            actor_discord_id="1",
            actor_display_name="Tester",
            expected_active_version=1,
            db_file=db_file,
        )
        invalidate_rule_override_cache()
        assert ORDER_RULES[key].price == 777
    finally:
        invalidate_rule_override_cache()


def test_custom_product_is_discoverable_by_web_and_discord_catalogs(
    tmp_path,
    monkeypatch,
):
    from services.orders import (
        get_order_item_details_for_group,
        get_order_item_groups_for_category,
    )
    from web.app.services.order_groups import get_grouped_order_catalog

    db_file = tmp_path / "web_dashboard.db"
    ensure_order_rule_store(db_file)
    monkeypatch.setattr(
        order_rule_store,
        "default_db_path",
        lambda: db_file,
    )
    invalidate_rule_override_cache()

    key = "admin_lol_test_product"
    payload = rule_to_override_payload(get_base_rule("lol_entertain_ng"))
    payload["label"] = "英雄聯盟｜後台新品"
    payload["price"] = 666
    payload["min_quantity"] = 1
    payload["max_quantity"] = 3

    rule = build_custom_rule_definition(key, "lol", payload)
    create_custom_rule_definition(
        rule_key=key,
        category="lol",
        payload=rule_to_override_payload(rule),
        actor_discord_id="1",
        actor_display_name="Tester",
        db_file=db_file,
    )

    invalidate_rule_override_cache()
    try:
        group_labels = get_order_item_groups_for_category("lol")
        assert "英雄聯盟｜後台新品" in group_labels

        details = get_order_item_details_for_group(
            "lol",
            "英雄聯盟｜後台新品",
        )
        assert len(details) == 1
        assert details[0]["rule_key"] == key
        assert details[0]["value"] == key
        assert details[0]["min_quantity"] == 1
        assert details[0]["max_quantity"] == 3

        web_groups = get_grouped_order_catalog("lol")
        custom_group = next(
            group
            for group in web_groups
            if group["key"] == f"custom_{key}"
        )
        assert custom_group["label"] == "英雄聯盟｜後台新品"
        assert custom_group["variants"][0]["rule_key"] == key
        assert custom_group["variants"][0]["price"] == 666
    finally:
        invalidate_rule_override_cache()

