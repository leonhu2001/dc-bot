"""Independent affection websites: paid-only, role-scoped, persisted and current photo scores."""
from __future__ import annotations

import sqlite3

import pytest

from web.app.services import affection_game_service as games
from services.order_rules import calculate_price, get_rule


def make_db(path, key="fun_our_love_start_75", status="active"):
    with sqlite3.connect(path) as db:
        db.executescript("""
            CREATE TABLE web_orders (
                id INTEGER PRIMARY KEY, customer_discord_id TEXT,
                customer_display_name TEXT, order_rule_key TEXT,
                item TEXT, category TEXT, status TEXT, bot_order_no TEXT
            );
            CREATE TABLE order_assignments (
                id INTEGER PRIMARY KEY, order_id INTEGER,
                worker_discord_id TEXT, worker_display_name TEXT,
                role_type TEXT, is_active INTEGER
            );
        """)
        db.execute(
            "INSERT INTO web_orders VALUES (1,'boss','老闆',?,'趣味單','三角洲趣味單',?,'M1')",
            (key, status),
        )
        db.execute("INSERT INTO order_assignments VALUES (1,1,'escort','護航','protector',1)")
        db.commit()


@pytest.mark.parametrize("key,game,initial,price,guarantee", [
    ("fun_our_love_start_75", "our_love", 75, 2488, 2088),
    ("fun_our_love_start_50", "our_love", 50, 3688, 3088),
    ("fun_our_love_start_0", "our_love", 0, 4888, 3688),
    ("fun_mawan_galagame_basic", "romance", 30, 2200, None),
    ("fun_mawan_galagame_standard", "romance", 0, 3288, None),
    ("fun_mawan_galagame_hard", "romance", -30, 4888, None),
    ("fun_mawan_galagame_hell", "romance", -80, 5688, None),
])
def test_plan_checkout_and_private_web_agree(tmp_path, key, game, initial, price, guarantee):
    db = tmp_path / "game.db"
    make_db(db, key=key)
    rule = get_rule(key)
    assert calculate_price(rule, quantity=1).base_amount == price
    data = games.get_context("boss", 1, game=game, db_file=db)
    assert data["plan"]["price"] == price
    assert data["plan"]["initial_affection"] == initial
    assert data["plan"]["guarantee_w"] == guarantee
    assert data["viewer"]["role"] == "boss"
    assert data["state"]["affection"] == initial
    assert games.get_context("escort", 1, db_file=db)["viewer"]["role"] == "companion"
    with pytest.raises(PermissionError):
        games.get_context("stranger", 1, db_file=db)
    with pytest.raises(ValueError):
        games.get_context("boss", 1, game=("romance" if game == "our_love" else "our_love"), db_file=db)


def test_paid_only_and_closed_readonly(tmp_path):
    db = tmp_path / "private.db"
    make_db(db, status="waiting_payment")
    entry = games.get_entry_info("boss", 1, game="our_love", db_file=db)
    assert not entry["available"]
    with pytest.raises(PermissionError, match="付款"):
        games.get_context("boss", 1, db_file=db)
    with pytest.raises(PermissionError):
        games.get_entry_info("stranger", 1, db_file=db)

    with sqlite3.connect(db) as conn:
        conn.execute("UPDATE web_orders SET status='active' WHERE id=1")
    ctx = games.mutate("boss", 1, "start", db_file=db)
    assert ctx["state"]["started"] is True
    assert games.get_entry_info("boss", 1, db_file=db)["available"] is True

    with sqlite3.connect(db) as conn:
        conn.execute("UPDATE web_orders SET status='closed' WHERE id=1")
    ctx = games.get_context("boss", 1, db_file=db)
    assert ctx["read_only"] is True
    assert games.get_entry_info("boss", 1, db_file=db)["view_only"] is True
    with pytest.raises(PermissionError):
        games.mutate("boss", 1, "event", event_key="escort_kill", db_file=db)


def test_our_love_photo_events_and_settlement_guarantee(tmp_path):
    db = tmp_path / "our.db"
    make_db(db, key="fun_our_love_start_0")
    games.mutate("boss", 1, "start", db_file=db)
    events = {
        "escort_kill": 1, "small_red": 2, "big_red": 5,
        "huge_red": 10, "heart_tear_breath": 35, "boss_kill": -1,
    }
    assert {k: v[1] for k, v in games.EVENTS["our_love"].items()} == events
    for key, points in events.items():
        old = games.get_context("boss", 1, db_file=db)["state"]["affection"]
        cur = games.mutate("boss", 1, "event", event_key=key, expected_round=1, db_file=db)
        assert cur["state"]["affection"] == old + points
    after = games.mutate("boss", 1, "settle", result="success", extra=True,
                         expected_round=1, db_file=db)
    assert after["state"]["affection"] == 60  # 52 + 5 + 3
    assert after["state"]["round_no"] == 2
    with pytest.raises(ValueError, match="重新整理"):
        games.mutate("boss", 1, "settle", result="success", extra=True,
                     expected_round=1, db_file=db)
    with pytest.raises(ValueError, match="千萬撤離"):
        games.mutate("boss", 1, "settle", result="fail", extra=True,
                     expected_round=2, db_file=db)
    after = games.mutate("boss", 1, "settle", result="fail", extra=False,
                         expected_round=2, db_file=db)
    assert after["state"]["affection"] == 50


def test_romance_photo_events_and_single_500w_bonus(tmp_path):
    db = tmp_path / "romance.db"
    make_db(db, key="fun_mawan_galagame_standard")
    games.mutate("boss", 1, "start", db_file=db)
    assert dict((k, v[1]) for k, v in games.EVENTS["romance"].items()) == {
        "small_gold": 2, "small_red": 5, "big_red": 10,
        "heart_tear": 30, "purple_card": 5, "gold_card": 10,
        "red_card": 15, "escort_kill": 3, "boss_revived": 2,
        "boss_kill": -5,
    }
    with pytest.raises(PermissionError):
        games.mutate("escort", 1, "event", event_key="escort_kill", db_file=db)
    games.mutate("boss", 1, "event", event_key="heart_tear", db_file=db)
    ctx = games.mutate("boss", 1, "settle", result="success",
                       extra=True, expected_round=1, db_file=db)
    assert ctx["state"]["affection"] == 33
    with pytest.raises(ValueError):
        games.mutate("boss", 1, "event", event_key="old_guess", db_file=db)
    with pytest.raises(ValueError, match="500W"):
        games.mutate("boss", 1, "settle", result="fail", extra=True,
                     expected_round=2, db_file=db)


def test_undo_preserves_previous_round_and_is_order_scoped(tmp_path):
    db = tmp_path / "undo.db"
    make_db(db)
    games.mutate("boss", 1, "start", db_file=db)
    games.mutate("boss", 1, "event", event_key="escort_kill", db_file=db)
    data = games.mutate("boss", 1, "undo", db_file=db)
    assert data["state"]["affection"] == 75
    assert any(event["undone"] for event in data["events"])
    games.mutate("boss", 1, "settle", result="fail", expected_round=1, db_file=db)
    with pytest.raises(ValueError, match="沒有可撤銷"):
        games.mutate("boss", 1, "undo", db_file=db)
    assert games.get_context("boss", 1, db_file=db)["state"]["round_no"] == 2


def test_legacy_romance_records_remain_separate(tmp_path):
    db = tmp_path / "legacy.db"
    make_db(db, key="fun_mawan_galagame_standard")
    with sqlite3.connect(db) as conn:
        conn.execute("CREATE TABLE love_delta_sessions(order_id INTEGER PRIMARY KEY)")
        conn.execute("INSERT INTO love_delta_sessions VALUES (1)")
    assert games.legacy_romance_session_exists(1, db_file=db)
    with pytest.raises(ValueError, match="舊版"):
        games.get_context("boss", 1, db_file=db)


def test_auth_routes_and_public_artifacts_are_wired():
    from web.app.main import app
    routes = {getattr(route, "path", "") for route in app.routes}
    for path in (
        "/me/orders/{order_id}/our-love",
        "/me/orders/{order_id}/our-love/entry",
        "/me/orders/{order_id}/romance-delta",
        "/me/orders/{order_id}/love-delta",
        "/me/orders/{order_id}/affection-game/start",
        "/me/orders/{order_id}/affection-game/event",
        "/me/orders/{order_id}/affection-game/settle",
        "/me/orders/{order_id}/affection-game/undo",
    ):
        assert path in routes
