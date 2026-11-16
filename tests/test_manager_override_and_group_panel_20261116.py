from __future__ import annotations

import json
from pathlib import Path

import pytest

from services import order_rule_store, order_rules, orders
from services.order_rule_store import (
    ensure_order_rule_store,
    publish_rule_override,
    rollback_rule_override,
)
from services.order_rules import (
    ORDER_RULES,
    PROTECTOR_ROLES,
    get_allowed_role_ids,
    get_base_rule,
    invalidate_rule_override_cache,
    rule_to_override_payload,
)
from web.app.routers import admin_order_rules
from web.app.services import order_groups


ROOT = Path(__file__).resolve().parents[1]


def test_our_love_accepts_any_two_protectors_not_companions():
    for key in ("fun_our_love_start_50", "fun_our_love_start_0"):
        rule = get_base_rule(key)
        assert rule.allowed_roles == PROTECTOR_ROLES
        assert rule.required_staff_count == 2
        assert rule.min_protector_count == 2
        assert set(get_allowed_role_ids(rule)) == {
            order_rules.ROLE_IDS["top_protector"],
            order_rules.ROLE_IDS["male_protector"],
            order_rules.ROLE_IDS["female_protector"],
        }
        assert order_rules.ROLE_IDS["male_companion"] not in get_allowed_role_ids(rule)
        assert order_rules.ROLE_IDS["female_companion"] not in get_allowed_role_ids(rule)

    info = order_groups._current_group_specs()
    our_love = next(spec for spec in info if spec["key"] == "our_love")
    assert "男護／女護／頂護皆可" in our_love["description"]


@pytest.mark.parametrize("key,expected", (
    ("fun_our_love_start_50", "我們的愛"),
    ("fun_eat_to_fat_10kg", "吃到發胖"),
    ("fun_eat_yourself", "一命通關"),
    ("basic_tech_secret_single", "技術陪"),
    ("farm_coin_wash_car_100m", "哈夫幣代洗"),
    ("farm_season_3x3_normal", "賽季3x3"),
))
def test_second_column_uses_actual_source_group_not_empty(key, expected):
    assert orders.get_source_catalog_group_label(key) == expected
    base = get_base_rule(key)
    assert base.catalog_group_label == ""
    assert admin_order_rules._display_catalog_group_label(key, base) == expected
    assert admin_order_rules._payload_with_presentation(key, base)["catalog_group_label"] == expected


def test_all_manager_editable_products_have_visible_second_column():
    for key in ORDER_RULES:
        if not admin_order_rules._is_admin_editable_rule(key):
            continue
        row = admin_order_rules._rule_row(key)
        assert row["catalog_group_label"].strip(), key


def test_source_authority_protects_old_overrides_but_respects_new_manager_publication(
    tmp_path, monkeypatch,
):
    db_file = tmp_path / "web_dashboard.db"
    ensure_order_rule_store(db_file)
    monkeypatch.setattr(order_rule_store, "default_db_path", lambda: db_file)

    key = "fun_our_love_start_50"
    base = get_base_rule(key)
    old = rule_to_override_payload(base)
    old.update(price=111, label="舊版錯誤商品", allowed_roles=["male_companion"], required_staff_count=1)
    first = publish_rule_override(
        rule_key=key,
        payload=old,
        actor_discord_id="1",
        actor_display_name="Manager",
        expected_active_version=0,
        db_file=db_file,
    )
    invalidate_rule_override_cache()
    assert ORDER_RULES[key].price == base.price
    assert ORDER_RULES[key].allowed_roles == PROTECTOR_ROLES
    assert ORDER_RULES[key].required_staff_count == 2

    approved = rule_to_override_payload(base)
    approved.update(
        price=3399,
        label="我們的愛｜調整方案",
        catalog_group_label="我們的愛",
        allowed_roles=list(PROTECTOR_ROLES),
        __owner_confirmed_after_canonical=True,
    )
    second = publish_rule_override(
        rule_key=key,
        payload=approved,
        actor_discord_id="1",
        actor_display_name="Manager",
        expected_active_version=first["version"],
        db_file=db_file,
    )
    invalidate_rule_override_cache()
    assert ORDER_RULES[key].price == 3399
    assert ORDER_RULES[key].label == "我們的愛｜調整方案"
    specs = order_groups._current_group_specs()
    matches = [g for g in specs if g["key"] == "our_love"]
    assert len(matches) == 1  # Publishing the built-in group never duplicates it.
    assert ("fun_our_love_start_50", "我們的愛｜調整方案") in matches[0]["variants"]
    assert orders._effective_builtin_group_label(ORDER_RULES[key], "我們的愛") == "我們的愛"

    # Roll back to an unmarked pre-canonical version: only history changes,
    # none of the old price / role restrictions can leak onto the storefront.
    rollback_rule_override(
        rule_key=key,
        target_version=first["version"],
        actor_discord_id="1",
        actor_display_name="Manager",
        expected_active_version=second["version"],
        db_file=db_file,
    )
    invalidate_rule_override_cache()
    assert ORDER_RULES[key] == base


def test_explicit_manager_approval_works_for_every_old_protected_policy(monkeypatch):
    cases = {
        "fun_read_no_reply": 2650,                   # previous full-source lock
        "fun_eat_to_fat_10kg": 2999,                # new challenge
        "farm_coin_wash_car_100m": 777,             # approved wash tier
        "apex_entertain_ng": 333,                  # approved game prices
    }
    versions = {}
    for key, desired in cases.items():
        payload = rule_to_override_payload(get_base_rule(key))
        payload["price"] = desired
        payload["__owner_confirmed_after_canonical"] = True
        versions[key] = {"payload": payload}

    monkeypatch.setattr(ORDER_RULES, "_refresh_external", lambda: None)
    monkeypatch.setattr(ORDER_RULES, "_override_cache", versions)
    for key, desired in cases.items():
        assert ORDER_RULES[key].price == desired, key
        assert get_base_rule(key).price != desired, key


def test_admin_real_headcount_price_fields_update_checkout_totals(monkeypatch):
    from starlette.datastructures import FormData

    key = "basic_tech_secret_single"
    base = get_base_rule(key)
    assert base.player_count_prices
    current = rule_to_override_payload(base)
    original_tiers = dict(current["player_count_prices"])
    rows = [
        ("label", base.label),
        ("catalog_group_label", "技術陪"),
        ("pricing_type", base.pricing_type),
        ("unit_label", base.unit_label),
        ("note", base.note),
        ("intro", ""),
        ("required_staff_count", "player_count"),
        ("price", str(base.price)),
        ("min_quantity", str(base.min_quantity)),
        ("min_player_count", str(base.min_player_count)),
        ("min_protector_count", str(base.min_protector_count)),
        ("specify_fee_default", str(base.specify_fee_default)),
    ]
    for flag in admin_order_rules.BOOL_FIELDS:
        if bool(getattr(base, flag, False)):
            rows.append((flag, "on"))
    for field in admin_order_rules.OPTIONAL_INT_FIELDS:
        value = getattr(base, field, None)
        if value is not None:
            rows.append((field, str(value)))
    for role in base.allowed_roles:
        rows.append(("allowed_roles", role))
    for role in base.allowed_game_roles:
        rows.append(("allowed_game_roles", role))
    for role in base.required_game_roles:
        rows.append(("required_game_roles", role))
    for count, amount in original_tiers.items():
        rows.append((f"player_count_price_{count}", str(amount + 33)))
    form = FormData(rows)
    updated = admin_order_rules._payload_from_form(key, form)

    assert updated["player_count_prices"] == {
        int(k): v + 33 for k, v in original_tiers.items()
    }
    updated["__owner_confirmed_after_canonical"] = True
    updated[order_rules.DELTA_DESKTOP_APPROVAL_REVISION_MARKER] = True
    monkeypatch.setattr(ORDER_RULES, "_refresh_external", lambda: None)
    monkeypatch.setattr(ORDER_RULES, "_override_cache", {key: {"payload": updated}})
    actual = ORDER_RULES[key]
    for count, expected in updated["player_count_prices"].items():
        assert order_rules.calculate_price(actual, quantity=1, player_count=count).total_amount == expected


def test_manager_locked_aw_tariffs_are_not_silently_accepted():
    key = "farm_aw_collision_101_500"
    before = rule_to_override_payload(get_base_rule(key))
    admin_order_rules._validate_special_rate_rule_edit(key, before)
    after = dict(before, price=99)
    with pytest.raises(ValueError, match="每發級距"):
        admin_order_rules._validate_special_rate_rule_edit(key, after)


def test_website_and_discord_fun_list_use_live_post_publish_pricing(monkeypatch):
    key = "fun_eat_to_fat_10kg"
    from services import quick_order_v2_price_lists as price_lists
    source = get_base_rule(key)
    override = rule_to_override_payload(source)
    override["price"] = 3997
    override["__owner_confirmed_after_canonical"] = True
    monkeypatch.setattr(ORDER_RULES, "_refresh_external", lambda: None)
    monkeypatch.setattr(ORDER_RULES, "_override_cache", {key: {"payload": override}})

    assert ORDER_RULES[key].price == 3997
    embed = price_lists._delta_fun_embed("eat_to_fat")
    assert "3,997T" in embed.description
    import re
    assert re.search(r"10KG紅\s+3,997T", embed.description)
    assert re.search(r"10KG紅\s+2,888T", embed.description) is None
    assert "原始價目表圖片僅供玩法參考" in embed.description


def test_owner_confirmation_is_added_only_on_authenticated_publish():
    source = (ROOT / "web/app/routers/admin_order_rules.py").read_text(encoding="utf-8")
    assert 'published_payload["__owner_confirmed_after_canonical"] = True' in source
    assert 'if not user or not user.get("is_manager")' in source
    code = (ROOT / "services/order_rules.py").read_text(encoding="utf-8")
    assert 'payload.get("__owner_confirmed_after_canonical") is True' in code
