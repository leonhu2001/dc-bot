"""Pin both romance catalogs and dedicated website behavior to owner price posters."""
from pathlib import Path

import pytest

from services.order_rules import get_rule
from services.quick_order_v2_price_lists import DELTA_FUN_PRICE_LISTS
from web.app.services import love_delta_service as service


OUR_LOVE_POSTER = (
    ("fun_our_love_start_75", 2488, 75, 2088),
    ("fun_our_love_start_50", 3688, 50, 3088),
    ("fun_our_love_start_0", 4888, 0, 3688),
)
LOVE_DELTA_POSTER = (
    ("fun_mawan_galagame_basic", 2288, 30),
    ("fun_mawan_galagame_standard", 3288, 0),
    ("fun_mawan_galagame_hard", 4888, -30),
    ("fun_mawan_galagame_hell", 5688, -80),
)


@pytest.mark.parametrize("key,price,initial,guarantee", OUR_LOVE_POSTER)
def test_our_love_poster_prices_are_consistent_in_checkout_discord_and_site(
    key, price, initial, guarantee,
):
    assert get_rule(key).price == price
    plan = service.OUR_LOVE_RULE_KEYS[key]
    assert plan["price"] == price
    assert plan["initial_affection"] == initial
    assert plan["guarantee"] == guarantee
    assert plan["game_key"] == "our_love"
    discord_text = DELTA_FUN_PRICE_LISTS["our_love"]["text"]
    assert f"{price:,}T" in discord_text
    assert f"保底 {guarantee}W" in discord_text


@pytest.mark.parametrize("key,price,initial", LOVE_DELTA_POSTER)
def test_love_delta_poster_prices_unchanged_and_consistent(key, price, initial):
    assert get_rule(key).price == price
    plan = service.LOVE_DELTA_RULE_KEYS[key]
    assert plan["price"] == price
    assert plan["initial_affection"] == initial
    assert plan["game_key"] == "love_delta"
    assert f"{price:,}T" in DELTA_FUN_PRICE_LISTS["love_delta"]["text"]


def make_db(path: Path, rule_key: str):
    import sqlite3

    with sqlite3.connect(path) as conn:
        conn.executescript(
            """
            CREATE TABLE web_orders (
                id INTEGER PRIMARY KEY,
                customer_discord_id TEXT, customer_display_name TEXT,
                order_rule_key TEXT, item TEXT, category TEXT, status TEXT,
                bot_order_no TEXT, ticket_channel_id TEXT
            );
            CREATE TABLE order_assignments (
                id INTEGER PRIMARY KEY, order_id INTEGER,
                worker_discord_id TEXT, worker_display_name TEXT,
                role_type TEXT, is_active INTEGER
            );
            """
        )
        conn.execute(
            "INSERT INTO web_orders VALUES (1,'boss','老闆',?,'我們的愛','三角洲趣味單',"
            "'active','MO001','456')",
            (rule_key,),
        )
        conn.execute("INSERT INTO order_assignments VALUES (1,1,'guard1','護航甲','protector',1)")
        conn.execute("INSERT INTO order_assignments VALUES (2,1,'guard2','護航乙','protector',1)")


def test_our_love_is_a_dedicated_website_with_shared_live_widgets():
    root = Path(__file__).resolve().parents[1]
    template = (root / "web/app/templates/member_our_love.html").read_text(encoding="utf-8")
    base = (root / "web/app/templates/member_love_delta.html").read_text(encoding="utf-8")
    router = (root / "web/app/routers/love_delta.py").read_text(encoding="utf-8")
    css = (root / "web/app/static/css/love_delta.css").read_text(encoding="utf-8")
    js = (root / "web/app/static/js/love_delta.js").read_text(encoding="utf-8")
    assert '{% extends "member_love_delta.html" %}' in template
    assert 'name="member_our_love.html" if context["game_key"] == "our_love"' in router
    assert '@router.get("/me/orders/{order_id}/our-love")' in router
    assert '.ld-page[data-game="our_love"]' in css
    assert 'isOurLove = boot.game_key === "our_love"' in js
    assert 'data-ld-event="guard_kill"' in base
    assert 'data-ld-event="our_heart_tear"' in base
    assert 'data-ld-event="boss_kill"' in base
    assert 'data-ld-event="item_small_gold"' in base
    assert "if is_our_love" in base
    assert "本單{{ '護航' if is_our_love else '女陪' }}" in base


def test_our_love_score_events_and_fail_safe_red_are_separate(tmp_path):
    db = tmp_path / "romance.db"
    make_db(db, "fun_our_love_start_50")
    entry = service.get_love_delta_entry_info("boss", 1, db_file=db)
    assert entry["href"] == "/me/orders/1/our-love"
    context = service.get_love_delta_context("guard1", 1, db_file=db)
    assert context["game_title"] == "我們的愛"
    assert context["plan"]["price"] == 3688
    assert context["plan"]["guarantee"] == 3088
    assert context["state"]["affection"] == 50
    with pytest.raises(PermissionError):
        service.start_love_delta("guard1", 1, db_file=db)
    service.start_love_delta("boss", 1, db_file=db)
    with pytest.raises(ValueError, match="未知"):
        service.apply_love_delta_event("boss", 1, "item_small_gold", db_file=db)
    for event in ("guard_kill", "our_small_red", "our_big_red", "our_huge_red", "boss_kill"):
        context = service.apply_love_delta_event("boss", 1, event, db_file=db)
    assert context["state"]["affection"] == 67
    context = service.settle_love_delta_round(
        "boss", 1, expected_round=1, result="fail", extraction_tier=1000, db_file=db
    )
    # +1 +2 +5 +10 -1, failed extraction -10; no +3 on failure.
    assert context["state"]["affection"] == 57
    assert context["state"]["round_no"] == 2
    assert context["state"]["round_positive"] == 0
    context = service.apply_love_delta_event("boss", 1, "our_heart_tear", db_file=db)
    assert context["state"]["affection"] == 92
    context = service.settle_love_delta_round(
        "boss", 1, expected_round=2, result="success", extraction_tier=1000, db_file=db
    )
    # +5 success, +3 for >= 1000W extraction, stops at 100.
    assert context["state"]["affection"] == 100
    assert context["state"]["completed"]
    with pytest.raises(PermissionError):
        service.apply_love_delta_event("boss", 1, "guard_kill", db_file=db)


def test_love_delta_has_independent_score_and_guess_rules():
    assert service.EVENT_SCORES["item_small_gold"][1] == 2
    assert service.EVENT_SCORES["item_small_red"][1] == 5
    assert service.EVENT_SCORES["item_big_red"][1] == 15
    assert service.EVENT_SCORES["item_heart_tear"][1] == 30
    assert service.EVENT_SCORES["item_purple_card"][1] == 5
    assert service.EVENT_SCORES["item_gold_card"][1] == 10
    assert service.EVENT_SCORES["item_red_card"][1] == 15
    assert service.EVENT_SCORES["miss_callout"][1] == -2
    assert service.EVENT_SCORES["miss_suffix"][1] == -2
    assert service.EXTRACTION_TIERS[600] == 2
    assert service.OUR_LOVE_EXTRACTION_TIERS[1000] == 3
    assert service.OUR_LOVE_EVENT_SCORES["our_heart_tear"][1] == 35
