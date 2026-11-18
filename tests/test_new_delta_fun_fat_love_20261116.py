from __future__ import annotations

from pathlib import Path

import pytest

from services import orders
from services import order_rules
from services import quick_order_v2_price_lists as price_lists
from services.order_rules import (
    ALL_RECEIVER_ROLES,
    PROTECTOR_ROLES,
    DELTA_DESKTOP_GAME_ROLE,
    FULL_SOURCE_AUTHORITY_RULE_KEYS,
    calculate_price,
    get_allowed_role_ids,
    get_base_rule,
    get_required_staff_count,
)
from web.app.services import order_catalog_cards as cards


ROOT = Path(__file__).resolve().parents[1]

FAT = (
    ("fun_eat_to_fat_10kg", 2888, 1888, 10),
    ("fun_eat_to_fat_20kg", 3988, 2688, 20),
    ("fun_eat_to_fat_35kg", 6888, 3688, 35),
    ("fun_eat_to_fat_50kg", 12888, 6288, 50),
    ("fun_eat_to_fat_100kg", 26888, 16888, 100),
)

LOVE = (
    ("fun_our_love_start_75", 2488, 75, 2088),
    ("fun_our_love_start_50", 3688, 50, 3088),
    ("fun_our_love_start_0", 4888, 0, 3688),
)


@pytest.mark.parametrize("key,price,guarantee,weight", FAT)
def test_eat_to_fat_exact_picture_prices_and_two_companions(
    key, price, guarantee, weight,
):
    rule = get_base_rule(key)
    assert rule.category == "delta_desktop_fun"
    assert rule.label == f"吃到發胖｜{weight}KG紅"
    assert rule.price == price
    assert rule.pricing_type == "fixed"
    assert rule.allowed_roles == ALL_RECEIVER_ROLES
    assert rule.required_game_roles == DELTA_DESKTOP_GAME_ROLE
    assert get_required_staff_count(rule) == 2
    assert rule.min_quantity == rule.max_quantity == 1
    assert calculate_price(rule, quantity=1).total_amount == price
    assert f"保底{guarantee}W" in rule.note
    assert f"{weight}KG" in rule.note
    assert "25公斤" in rule.note
    assert "紅卡8公斤" in rule.note
    assert "不聽指揮" in rule.note
    assert key in FULL_SOURCE_AUTHORITY_RULE_KEYS


@pytest.mark.parametrize("key,price,start,guarantee", LOVE)
def test_our_love_exact_picture_prices_two_any_protectors_and_score(
    key, price, start, guarantee,
):
    rule = get_base_rule(key)
    assert rule.category == "delta_desktop_fun"
    assert rule.label == f"我們的愛｜初始好感度{start}"
    assert rule.price == price
    assert rule.pricing_type == "fixed"
    assert rule.allowed_roles == PROTECTOR_ROLES
    assert rule.min_protector_count == 2
    assert rule.required_game_roles == DELTA_DESKTOP_GAME_ROLE
    assert get_required_staff_count(rule) == 2
    assert get_allowed_role_ids(rule) == [
        order_rules.ROLE_IDS[key] for key in PROTECTOR_ROLES
    ]
    assert rule.min_quantity == rule.max_quantity == 1
    assert calculate_price(rule, quantity=1).total_amount == price
    assert f"初始好感度{start}" in rule.note
    assert f"保底{guarantee}W" in rule.note
    for term in ("達100", "撤離失敗-10", "老闆擊殺1名幹員-1", "復甦呼吸機+35", "紅修不算"):
        assert term in rule.note
    assert key in FULL_SOURCE_AUTHORITY_RULE_KEYS


def test_discord_and_web_have_one_group_per_challenge_with_exact_variants():
    discord = {
        group["label"]: group
        for group in orders.SELF_SERVICE_ORDER_CATALOG["delta_desktop_fun"]
    }
    assert "吃到發胖" in discord
    assert "我們的愛" in discord
    assert [v["rule_key"] for v in discord["吃到發胖"]["details"]] == [
        rule_key for rule_key, *_ in FAT
    ]
    assert [v["rule_key"] for v in discord["我們的愛"]["details"]] == [
        rule_key for rule_key, *_ in LOVE
    ]

    web = {item["label"]: item for item in cards._build_cards("delta_desktop_fun")}
    assert web["吃到發胖"]["starting_price"] == 2888
    assert web["吃到發胖"]["variant_count"] == 5
    assert web["吃到發胖"]["image_url"] == (
        "/static/price_lists/delta_fun_eat_to_fat.webp"
    )
    assert web["我們的愛"]["starting_price"] == 2488
    assert web["我們的愛"]["variant_count"] == 3
    assert web["我們的愛"]["image_url"] == (
        "/static/price_lists/delta_fun_our_love.webp"
    )
    assert len([g for g in cards._build_cards("delta_desktop_fun") if g["label"] == "吃到發胖"]) == 1
    assert len([g for g in cards._build_cards("delta_desktop_fun") if g["label"] == "我們的愛"]) == 1

    for group_key, expected in (("eat_to_fat", FAT), ("our_love", LOVE)):
        detail = cards._build_group_detail(group_key)
        assert detail is not None
        assert [v["rule_key"] for v in detail["variants"]] == [
            rule_key for rule_key, *_ in expected
        ]
        assert [v["price"] for v in detail["variants"]] == [
            amount for _rule_key, amount, *_ in expected
        ]


def test_discord_fun_price_lists_use_canonical_amounts_and_original_artwork():
    fat_list = price_lists.DELTA_FUN_PRICE_LISTS["eat_to_fat"]
    love_list = price_lists.DELTA_FUN_PRICE_LISTS["our_love"]
    assert fat_list["image"] == "price_lists/delta_fun_eat_to_fat.webp"
    assert love_list["image"] == "price_lists/delta_fun_our_love.webp"
    for key, amount, _guarantee, _weight in FAT:
        assert f"{amount:,}T" in fat_list["text"]
        assert price_lists._approved_fun_price(key) == f"{amount:,}T"
    for key, amount, _start, _guarantee in LOVE:
        assert f"{amount:,}T" in love_list["text"]
        assert price_lists._approved_fun_price(key) == f"{amount:,}T"

    for plan in (fat_list, love_list):
        asset = ROOT / "web" / "app" / "static" / plan["image"]
        assert asset.is_file()
        assert asset.read_bytes()[:4] == b"RIFF"
        assert asset.stat().st_size > 100_000

    for key in ("eat_to_fat", "our_love"):
        embed = price_lists._delta_fun_embed(key)
        assert embed.image.url.startswith("https://mowanentertainment.com/static/price_lists/")
        assert "?v=missing" not in embed.image.url


def test_existing_approved_fun_products_and_prices_are_not_overwritten():
    assert get_base_rule("fun_eat_yourself").price == 13888
    assert get_base_rule("fun_read_no_reply").price == 2500
    assert get_base_rule("fun_lovebirds").price == 2000
    assert get_base_rule("fun_rich_enough").price == 2000


def test_new_fun_products_ignore_stale_admin_rule_overrides(monkeypatch):
    monkeypatch.setattr(order_rules.ORDER_RULES, "_refresh_external", lambda: None)
    overrides = {
        rule_key: {
            "payload": {
                "price": 1,
                "label": "舊版商品",
                "allowed_roles": ["female_companion"],
                "required_staff_count": 1,
                "catalog_group_label": "舊分類",
            },
        }
        for rule_key, *_ in (*FAT, *LOVE)
    }
    monkeypatch.setattr(order_rules.ORDER_RULES, "_override_cache", overrides)
    for rule_key in overrides:
        assert order_rules.ORDER_RULES[rule_key] == get_base_rule(rule_key)


def test_public_artwork_is_shown_in_cards_and_modal_without_untrusted_sources():
    html = (ROOT / "web/app/templates/order_catalog.html").read_text(encoding="utf-8")
    js = (ROOT / "web/app/static/js/mw_order.js").read_text(encoding="utf-8")
    css = (ROOT / "web/app/static/css/mw_site.css").read_text(encoding="utf-8")

    assert '{% if group.image_url %}' in html
    assert 'href="{{ group.image_url }}"' in html
    assert "renderGroupMedia(group)" in js
    assert 'url.startsWith(' in js
    assert '"/static/price_lists/"' in js
    assert ".order3-media-poster" in css
