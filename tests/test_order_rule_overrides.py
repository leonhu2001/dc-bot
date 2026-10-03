from services import order_rule_store
from services.order_rule_store import (
    ensure_order_rule_store,
    list_rule_versions,
    publish_rule_override,
    reset_rule_override,
    rollback_rule_override,
)
from services.order_rules import (
    ORDER_RULES,
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
