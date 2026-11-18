"""Latest owner-posters are the source of truth for Discord/Web and both live sites."""
from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from services import orders
from services.order_rules import (
    FULL_SOURCE_AUTHORITY_RULE_KEYS, PROTECTOR_ROLES,
    get_base_rule, get_required_staff_count, calculate_price,
)
from services.quick_order_v2_price_lists import DELTA_FUN_PRICE_LISTS
from web.app.services import love_delta_service as live
from web.app.services.order_groups import GROUP_SPECS
from web.app.routers.love_delta import router as romance_router


LOVE = (
    ("fun_our_love_start_75", 2488, 75, 2088),
    ("fun_our_love_start_50", 3688, 50, 3088),
    ("fun_our_love_start_0", 4888, 0, 3688),
)
DELTA = (
    ("fun_mawan_galagame_basic", "基礎", 2288, 30),
    ("fun_mawan_galagame_standard", "標準", 3288, 0),
    ("fun_mawan_galagame_hard", "困難", 4888, -30),
    ("fun_mawan_galagame_hell", "地獄", 5688, -80),
)


def _test_db(path: Path, key: str, status: str = "active"):
    with sqlite3.connect(path) as conn:
        conn.executescript("""
            CREATE TABLE web_orders (
                id INTEGER PRIMARY KEY, customer_discord_id TEXT,
                customer_display_name TEXT, order_rule_key TEXT,
                item TEXT, category TEXT, status TEXT,
                bot_order_no TEXT, ticket_channel_id TEXT
            );
            CREATE TABLE order_assignments (
                id INTEGER PRIMARY KEY, order_id INTEGER,
                worker_discord_id TEXT, worker_display_name TEXT,
                role_type TEXT, is_active INTEGER
            );
        """)
        conn.execute(
            "INSERT INTO web_orders VALUES (1, 'boss', '老闆', ?, '', '三角洲趣味單', ?, 'MO-LOVE', '500')",
            (key, status),
        )
        conn.execute(
            "INSERT INTO order_assignments VALUES (1,1,'guard','護航','protector',1)"
        )


def _start(db):
    live.get_love_delta_context("boss", 1, db_file=db)
    return live.start_love_delta("boss", 1, db_file=db)


@pytest.mark.parametrize("key,price,initial,guarantee", LOVE)
def test_our_love_sku_exact_price_discord_web_and_site(key, price, initial, guarantee):
    rule = get_base_rule(key)
    assert rule.price == price
    assert rule.allowed_roles == PROTECTOR_ROLES
    assert get_required_staff_count(rule) == 2
    assert calculate_price(rule, quantity=1).total_amount == price
    assert f"保底{guarantee}W" in rule.note
    assert key in FULL_SOURCE_AUTHORITY_RULE_KEYS
    plan = live.OUR_LOVE_RULE_KEYS[key]
    assert (plan["price"], plan["initial_affection"], plan["guarantee"]) == (price, initial, guarantee)
    discord = next(g for g in orders.SELF_SERVICE_ORDER_CATALOG["delta_desktop_fun"] if g["label"] == "我們的愛")
    detail = next(v for v in discord["details"] if v["rule_key"] == key)
    assert f"{price:,}T" in detail["label"]
    assert f"保{guarantee}W" in detail["label"]
    group = next(g for g in GROUP_SPECS if g["key"] == "our_love")
    assert (key, f"初始{initial}｜保底{guarantee}W") in group["variants"]


@pytest.mark.parametrize("key,label,price,initial", DELTA)
def test_love_delta_sku_exact_price_discord_web_and_site(key, label, price, initial):
    rule = get_base_rule(key)
    assert (rule.label, rule.price) == (f"戀與三角洲｜{label}", price)
    assert get_required_staff_count(rule) == 2
    assert calculate_price(rule, quantity=1).total_amount == price
    assert key in FULL_SOURCE_AUTHORITY_RULE_KEYS
    plan = live.LOVE_DELTA_RULE_KEYS[key]
    assert (plan["price"], plan["initial_affection"]) == (price, initial)
    discord = next(g for g in orders.SELF_SERVICE_ORDER_CATALOG["delta_desktop_fun"] if g["label"] == "戀與三角洲")
    assert key in {v["rule_key"] for v in discord["details"]}
    group = next(g for g in GROUP_SPECS if g["key"] == "galagame")
    assert (key, label) in group["variants"]


def test_legacy_galagame_group_routes_old_tickets_to_renamed_current_skus():
    old = orders.get_order_item_details_for_group("delta_desktop_fun", "魔丸娛樂嘎拉給木")
    new = orders.get_order_item_details_for_group("delta_desktop_fun", "戀與三角洲")
    assert old and old == new
    assert "魔丸娛樂嘎拉給木" not in orders.get_live_order_item_groups("delta_desktop_fun")


@pytest.mark.parametrize("key,price,initial,guarantee", LOVE)
def test_our_love_live_initial_affection_and_guarantee(tmp_path, key, price, initial, guarantee):
    db = tmp_path / "live.db"
    _test_db(db, key)
    context = live.get_love_delta_context("boss", 1, db_file=db)
    assert (context["game_key"], context["game_title"]) == ("our_love", "我們的愛")
    assert context["state"]["affection"] == initial
    assert context["plan"]["guarantee"] == guarantee
    info = live.get_love_delta_entry_info("boss", 1, db_file=db)
    assert info["href"] == "/me/orders/1/our-love"
    assert info["game_title"] == "我們的愛"
    assert live.get_love_delta_context("guard", 1, db_file=db)["viewer"]["role"] == "companion"
    with pytest.raises(PermissionError):
        live.get_love_delta_context("nonparticipant", 1, db_file=db)


def test_our_love_points_1000w_extra_and_fail_are_separate(tmp_path):
    db = tmp_path / "live.db"
    _test_db(db, "fun_our_love_start_0")
    _start(db)
    for kind, value in (
        ("guard_kill", 1), ("our_small_red", 2),
        ("our_big_red", 5), ("our_huge_red", 10),
        ("boss_kill", -1),
    ):
        ctx = live.apply_love_delta_event("boss", 1, kind, db_file=db)
    assert ctx["state"]["affection"] == 17
    ctx = live.settle_love_delta_round("boss", 1, expected_round=1, result="success", extraction_tier=1000, db_file=db)
    assert ctx["state"]["affection"] == 25  # +5 successful and +3 million+ extraction
    assert ctx["state"]["round_no"] == 2
    ctx = live.apply_love_delta_event("boss", 1, "our_big_red", db_file=db)
    assert ctx["state"]["affection"] == 30
    ctx = live.settle_love_delta_round("boss", 1, expected_round=2, result="fail", extraction_tier=1000, db_file=db)
    assert ctx["state"]["affection"] == 20  # -10, no +3 on a failed extraction
    assert ctx["state"]["theme_affection"] == 25
    with pytest.raises(ValueError, match="撤離價值"):
        live.settle_love_delta_round("boss", 1, expected_round=3, result="fail", extraction_tier=600, db_file=db)


def test_our_love_max_heart_and_safe_red_on_failed_extract(tmp_path):
    db = tmp_path / "live.db"
    _test_db(db, "fun_our_love_start_0")
    _start(db)
    context = live.apply_love_delta_event("guard", 1, "our_heart_tear", db_file=db)
    assert context["state"]["affection"] == 35
    context = live.settle_love_delta_round("boss", 1, expected_round=1, result="fail", extraction_tier=0, db_file=db)
    assert context["state"]["affection"] == 25  # Box red was counted as +35, then fail -10


def test_cross_game_events_and_speech_rules_are_rejected(tmp_path):
    db = tmp_path / "live.db"
    _test_db(db, "fun_our_love_start_75")
    _start(db)
    for event in ("item_small_gold", "miss_callout", "ban_1", "four_same", "first_rescue"):
        with pytest.raises(ValueError, match="未知"):
            live.apply_love_delta_event("boss", 1, event, db_file=db)
    with pytest.raises(ValueError, match="不使用"):
        live.save_bans("boss", 1, ["甲", "乙", "丙"], db_file=db)
    with pytest.raises(ValueError, match="不使用"):
        live.save_boss_guess("boss", 1, answer="紅卡", db_file=db)
    with pytest.raises(ValueError, match="不使用"):
        live.save_next_loadout("boss", 1, agent="紅狼", weapon="M4", db_file=db)


def test_love_delta_latest_distinct_scores(tmp_path):
    db = tmp_path / "live.db"
    _test_db(db, "fun_mawan_galagame_standard")
    _start(db)
    for kind, expected in (
        ("item_small_gold", 2), ("item_small_red", 5), ("item_big_red", 15),
        ("item_heart_tear", 30), ("item_purple_card", 5),
        ("item_gold_card", 10), ("item_red_card", 15), ("miss_callout", -2),
    ):
        ctx = live.apply_love_delta_event("boss", 1, kind, db_file=db)
    assert ctx["state"]["affection"] == 80
    ctx = live.settle_love_delta_round("boss", 1, expected_round=1, result="fail", extraction_tier=600, db_file=db)
    assert ctx["state"]["affection"] == 82  # Safe-box value on failed extraction
    for obsolete in ("squad_wipe", "item_gold", "first_rescue", "guard_kill"):
        with pytest.raises(ValueError, match="未知"):
            live.apply_love_delta_event("boss", 1, obsolete, db_file=db)


def test_two_live_website_routes_are_registered_and_priced_posters_are_current():
    from web.app.main import app
    routes = {(route.path, ",".join(sorted(getattr(route, "methods", ())))) for route in app.routes}
    for path in (
        "/me/orders/{order_id}/love-delta",
        "/me/orders/{order_id}/our-love",
        "/me/orders/{order_id}/love-delta/state",
        "/me/orders/{order_id}/our-love/state",
        "/me/orders/{order_id}/love-delta/settle",
        "/me/orders/{order_id}/our-love/settle",
    ):
        assert any(r[0] == path for r in routes)
    assert len(romance_router.routes) >= 25

    root = Path(__file__).resolve().parents[1] / "web/app/static/price_lists"
    love = (root / "delta_fun_our_love_20261119.svg").read_text(encoding="utf-8")
    delta = (root / "delta_fun_love_delta_20261119.svg").read_text(encoding="utf-8")
    for money in ("2,488T", "3,688T", "4,888T", "2088W", "3088W", "3688W"):
        assert money in love
    for money in ("2,288T", "3,288T", "4,888T", "5,688T"):
        assert money in delta
    assert "<script" not in love and "<script" not in delta
    assert "2,488T" in DELTA_FUN_PRICE_LISTS["our_love"]["text"]
    assert "5,688T" in DELTA_FUN_PRICE_LISTS["love_delta"]["text"]
