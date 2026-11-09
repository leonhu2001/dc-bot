"""Full admin rule-editor contract: every editable rule, pricing and rollback.

SQLite writes are isolated to tmp_path. No production DB or Discord operations.
"""
from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

import pytest
from starlette.datastructures import FormData

from services import order_rule_store
from services.order_rule_store import (
    ensure_order_rule_store,
    get_active_override,
    publish_rule_override,
    reset_rule_override,
    rollback_rule_override,
)
from services.order_rules import (
    ORDER_RULES,
    OWNER_APPROVED_20261110_GAME_PRICE_KEYS,
    OWNER_APPROVED_GAME_PRICE_REVISION,
    ADMIN_MANAGED_PLAYER_COUNT_PRICE_REVISION,
    calculate_price,
    get_base_rule,
    invalidate_rule_override_cache,
    preview_rule_override,
    rule_to_override_payload,
)
from services.orders import get_order_item_details_for_group
from web.app.routers import admin_order_rules as admin
from web.app.services.order_groups import get_grouped_order_catalog


def _form_from_rule(rule):
    payload = rule_to_override_payload(rule)
    scalar_fields = (
        "label", "catalog_group_label", "pricing_type", "unit_label",
        "note", "intro", "price", "min_quantity", "max_quantity",
        "specify_fee_default", "max_specified_count",
        "specify_free_min_units", "min_player_count", "max_player_count",
        "min_protector_count", "required_staff_count",
    )
    values = [
        (field, "" if payload.get(field) is None else str(payload[field]))
        for field in scalar_fields if field in payload
    ]
    for field in admin.BOOL_FIELDS:
        if payload.get(field):
            values.append((field, "on"))
    supported = {
        "allowed_roles": set(), "allowed_game_roles": set(),
        "required_game_roles": set(),
    }
    for group in admin.QUALIFICATION_GROUPS:
        for option in group["options"]:
            supported[option["field"]].add(option["key"])
    for group in admin.GAME_IDENTITY_GROUPS:
        for option in group["options"]:
            supported["required_game_roles"].add(option["key"])
    for field, keys in supported.items():
        for role in payload.get(field) or []:
            if role in keys:
                values.append((field, role))
    return FormData(values)


def test_every_visible_admin_rule_can_roundtrip_through_its_actual_form():
    covered = set()
    for key, rule in admin.ORDER_RULES.items():
        if not admin._is_admin_editable_rule(key):
            continue
        form = _form_from_rule(rule)
        result = admin._payload_from_form(key, form)
        candidate = preview_rule_override(key, result)
        assert candidate.key == rule.key, key
        assert candidate.category == rule.category, key
        assert candidate.price == rule.price, key
        assert candidate.allowed_roles == rule.allowed_roles, key
        assert candidate.allowed_game_roles == rule.allowed_game_roles, key
        assert candidate.required_game_roles == rule.required_game_roles, key
        covered.add(rule.category)
    assert {"valorant", "lol", "apex", "steam", "custom", "farm"}.issubset(covered)


def test_hidden_qualifications_survive_ordinary_admin_form_edits():
    # Some system-order eligibility keys have no checkbox in the dashboard.
    visible = {
        option["key"]
        for group in admin.QUALIFICATION_GROUPS
        for option in group["options"]
    }
    examples = [
        (key, rule)
        for key, rule in admin.ORDER_RULES.items()
        if admin._is_admin_editable_rule(key)
        and any(r not in visible for r in rule.allowed_roles)
    ]
    assert examples, "expected production rules with hidden staff roles"
    for key, rule in examples:
        result = admin._payload_from_form(key, _form_from_rule(rule))
        assert set(rule.allowed_roles).issubset(result["allowed_roles"]), key


def test_locked_structural_changes_are_rejected_not_silently_ignored():
    key = "apex_entertain_ranked_tier_master"
    form = _form_from_rule(ORDER_RULES[key])
    values = [
        (k, ("3" if k == "max_player_count" else v))
        for k, v in form.multi_items()
    ]
    with pytest.raises(ValueError, match="系統規則控管"):
        admin._payload_from_form(key, FormData(values))


def test_poster_price_old_override_is_ignored_but_new_manager_publish_works(
    tmp_path, monkeypatch
):
    db = tmp_path / "web_dashboard.db"
    ensure_order_rule_store(db)
    monkeypatch.setattr(order_rule_store, "default_db_path", lambda: db)
    monkeypatch.setattr(admin, "write_sqlite_audit_log", lambda **kwargs: None)
    key = "lol_elite_ranked"
    assert key in OWNER_APPROVED_20261110_GAME_PRICE_KEYS
    default = get_base_rule(key).price
    assert default == 430
    old = rule_to_override_payload(get_base_rule(key))
    old["price"] = 999
    v1 = publish_rule_override(
        rule_key=key, payload=old,
        actor_discord_id="test", actor_display_name="old",
        db_file=db,
    )
    invalidate_rule_override_cache()
    assert ORDER_RULES[key].price == default

    edited = rule_to_override_payload(ORDER_RULES[key])
    edited["price"] = 470
    edited["intro"] = "管理員調價測試"
    response = asyncio.run(admin.admin_order_rule_publish(
        SimpleNamespace(session={"user": {
            "id": "123", "display_name": "總管", "is_manager": True,
        }}),
        rule_key=key,
        payload_json=json.dumps(edited),
        expected_active_version=v1["version"],
    ))
    assert response.status_code == 303
    invalidate_rule_override_cache()
    assert ORDER_RULES[key].price == 470
    active = get_active_override(key, db_file=db)
    assert active["payload"]["_owner_price_revision"] == OWNER_APPROVED_GAME_PRICE_REVISION
    assert active["payload"]["price"] == 470

    # A manager's verified publish must be seen by Web pricing and Bot rules.
    web_variant = next(
        v for g in get_grouped_order_catalog("lol")
        if g["key"] == "lol_elite"
        for v in g["variants"]
        if v["rule_key"] == key
    )
    assert web_variant["price"] == 470
    assert any(
        row["rule_key"] == key
        for row in get_order_item_details_for_group("lol", "菁英陪")
    )
    v2 = active["version"]

    v3 = rollback_rule_override(
        rule_key=key, target_version=v1["version"],
        actor_discord_id="123", actor_display_name="總管",
        expected_active_version=v2, db_file=db,
    )
    invalidate_rule_override_cache()
    # Restoring an old version must not resurrect a pre-poster price.
    assert ORDER_RULES[key].price == default
    assert v3["version"] > v2

    reset_rule_override(
        rule_key=key, actor_discord_id="123", actor_display_name="總管",
        expected_active_version=v3["version"], db_file=db,
    )
    invalidate_rule_override_cache()
    assert ORDER_RULES[key].price == default



def test_black_tide_per_seat_checkout_price_edit_is_real_and_rollback_safe(
    tmp_path, monkeypatch
):
    db = tmp_path / "web_dashboard.db"
    ensure_order_rule_store(db)
    monkeypatch.setattr(order_rule_store, "default_db_path", lambda: db)
    monkeypatch.setattr(admin, "write_sqlite_audit_log", lambda **kwargs: None)
    key = "basic_black_tide_entertain"
    base = get_base_rule(key)
    assert base.player_count_prices == {1: 320, 2: 600, 3: 900, 4: 1200}

    legacy_payload = rule_to_override_payload(base)
    legacy_payload["player_count_prices"] = {1: 1, 2: 1, 3: 1, 4: 1}
    old = publish_rule_override(
        rule_key=key, payload=legacy_payload,
        actor_discord_id="1", actor_display_name="preposter", db_file=db,
    )
    invalidate_rule_override_cache()
    assert ORDER_RULES[key].player_count_prices == base.player_count_prices

    form_values = list(_form_from_rule(ORDER_RULES[key]).multi_items())
    assert all(not key_name.startswith("player_count_price_") for key_name, _ in form_values)
    # Browser submits separate per-seat inputs on this editor.
    form_values.extend([
        ("player_count_price_1", "320"),
        ("player_count_price_2", "660"),
        ("player_count_price_3", "900"),
        ("player_count_price_4", "1200"),
    ])
    payload = admin._payload_from_form(key, FormData(form_values))
    assert payload["player_count_prices"][2] == 660
    assert preview_rule_override(key, payload).player_count_prices[2] == 660

    response = asyncio.run(admin.admin_order_rule_publish(
        SimpleNamespace(session={"user": {
            "id": "123", "display_name": "總管", "is_manager": True,
        }}),
        rule_key=key, payload_json=json.dumps(payload),
        expected_active_version=old["version"],
    ))
    assert response.status_code == 303
    invalidate_rule_override_cache()
    assert ORDER_RULES[key].player_count_prices[2] == 660
    assert calculate_price(ORDER_RULES[key], quantity=1, player_count=2).base_amount == 660
    applied = get_active_override(key, db_file=db)
    assert applied["payload"]["_admin_seat_price_revision"] == (
        ADMIN_MANAGED_PLAYER_COUNT_PRICE_REVISION
    )

    # Old versions still cannot revive stale per-seat pricing.
    rollback_rule_override(
        rule_key=key, target_version=old["version"],
        actor_discord_id="123", actor_display_name="總管",
        expected_active_version=applied["version"], db_file=db,
    )
    invalidate_rule_override_cache()
    assert ORDER_RULES[key].player_count_prices == base.player_count_prices


def test_admin_seat_price_template_discloses_real_unit_prices():
    from pathlib import Path
    template = (
        Path(__file__).resolve().parents[1]
        / "web/app/templates/admin_order_rules.html"
    ).read_text(encoding="utf-8")
    assert "player_count_price_{{ count }}" in template
    assert "依陪玩人數定價" in template
    assert "非上面的參考售價" in template


@pytest.mark.parametrize("key,new_price", [
    ("valorant_entertain_ranked", 305),
    ("apex_diamond_ranked_tier_master", 555),
    ("steam_play", 390),
    ("lol_entertain_ranked_tier_challenger", 555),
])
def test_new_poster_revision_is_effective_for_all_four_games(
    tmp_path, monkeypatch, key, new_price
):
    db = tmp_path / "web_dashboard.db"
    ensure_order_rule_store(db)
    monkeypatch.setattr(order_rule_store, "default_db_path", lambda: db)
    base = get_base_rule(key)
    old_payload = rule_to_override_payload(base)
    old_payload["price"] = 1
    publish_rule_override(
        rule_key=key, payload=old_payload,
        actor_discord_id="1", actor_display_name="legacy", db_file=db,
    )
    invalidate_rule_override_cache()
    assert ORDER_RULES[key].price == base.price

    current = rule_to_override_payload(ORDER_RULES[key])
    current["price"] = new_price
    current["_owner_price_revision"] = OWNER_APPROVED_GAME_PRICE_REVISION
    publish_rule_override(
        rule_key=key, payload=current,
        actor_discord_id="1", actor_display_name="manager", db_file=db,
    )
    invalidate_rule_override_cache()
    assert ORDER_RULES[key].price == new_price

    # Keep each tier's unit and player multiplier correct after the edit.
    rule = ORDER_RULES[key]
    assert rule.pricing_type == base.pricing_type
    assert rule.price_multiply_player_count == base.price_multiply_player_count
