import sqlite3

import pytest

from web.app.services import roulette_service
from web.app.services.roulette_service import (
    ROULETTE_RULE_KEY,
    corner_numbers,
    draw_roulette,
    ensure_roulette_draw_tables,
    normalize_bet,
    notify_ready_roulette_orders,
    resolve_roulette_result,
    six_line_numbers,
)


def test_safe_red_hit_and_miss():
    assert resolve_roulette_result("safe", "red", 3)["prize"] == 1500
    result = resolve_roulette_result("safe", "red", 2)
    assert result["hit"] is False
    assert result["prize"] == 1200


def test_zero_is_not_outside_bet_hit():
    result = resolve_roulette_result("safe", "red", 0)
    assert result["hit"] is False
    assert result["prize"] == 1200


def test_single_and_zero_jackpot():
    normal = resolve_roulette_result("single", 7, 7)
    assert normal["hit"] is True
    assert normal["prize"] == 6000
    assert normal["is_jackpot"] is False

    jackpot = resolve_roulette_result("single", 0, 0)
    assert jackpot["hit"] is True
    assert jackpot["prize"] == 7000
    assert jackpot["is_jackpot"] is True


def test_six_and_corner_coverage_match_frontend_rules():
    assert six_line_numbers(17) == [16, 17, 18, 19, 20, 21]
    assert corner_numbers(17) == [16, 19, 17, 20]

    six = resolve_roulette_result("six", 17, 20)
    assert six["hit"] is True
    assert six["prize"] == 2000

    corner = resolve_roulette_result("corner", 17, 19)
    assert corner["hit"] is True
    assert corner["prize"] == 2500


def test_invalid_bet_is_rejected():
    with pytest.raises(ValueError):
        normalize_bet("safe", "green")
    with pytest.raises(ValueError):
        normalize_bet("six", 0)
    with pytest.raises(ValueError):
        normalize_bet("single", 37)


def test_order_can_only_draw_once(tmp_path):
    db = tmp_path / "roulette.db"
    with sqlite3.connect(db) as conn:
        conn.execute(
            """
            CREATE TABLE web_orders (
                id INTEGER PRIMARY KEY,
                customer_discord_id TEXT,
                order_rule_key TEXT,
                item TEXT,
                status TEXT,
                bot_order_no TEXT,
                ticket_channel_id TEXT
            )
            """
        )
        conn.execute(
            """
            INSERT INTO web_orders (
                id, customer_discord_id, order_rule_key,
                item, status, bot_order_no, ticket_channel_id
            ) VALUES (1, '123', ?, '俄羅斯輪盤', 'active', 'MO1', '456')
            """,
            (ROULETTE_RULE_KEY,),
        )
        conn.commit()

    ensure_roulette_draw_tables(db)
    first = draw_roulette(
        "123",
        1,
        mode="single",
        selection=7,
        db_file=db,
        notify=False,
    )
    second = draw_roulette(
        "123",
        1,
        mode="safe",
        selection="red",
        db_file=db,
        notify=False,
    )

    assert first["already_drawn"] is False
    assert second["already_drawn"] is True
    assert second["id"] == first["id"]
    assert second["number"] == first["number"]
    assert second["prize"] == first["prize"]

    with sqlite3.connect(db) as conn:
        count = conn.execute("SELECT COUNT(*) FROM roulette_draws").fetchone()[0]
    assert count == 1


def test_ready_prompt_is_sent_once_for_paid_order(tmp_path, monkeypatch):
    db = tmp_path / "roulette-ready.db"
    with sqlite3.connect(db) as conn:
        conn.execute(
            """
            CREATE TABLE web_orders (
                id INTEGER PRIMARY KEY,
                customer_discord_id TEXT,
                order_rule_key TEXT,
                item TEXT,
                status TEXT,
                bot_order_no TEXT,
                ticket_channel_id TEXT
            )
            """
        )
        conn.execute(
            """
            INSERT INTO web_orders (
                id, customer_discord_id, order_rule_key,
                item, status, bot_order_no, ticket_channel_id
            ) VALUES (9, '123', ?, '俄羅斯輪盤', 'active', 'MO9', '456')
            """,
            (ROULETTE_RULE_KEY,),
        )
        conn.commit()

    calls = []

    class Response:
        status_code = 200
        text = ""

        @staticmethod
        def json():
            return {"id": "999"}

    def fake_post(url, *, headers, json, timeout):
        calls.append((url, headers, json, timeout))
        return Response()

    monkeypatch.setattr(roulette_service.config, "DISCORD_BOT_TOKEN", "test-token")
    monkeypatch.setattr(roulette_service.requests, "post", fake_post)

    assert notify_ready_roulette_orders(db_file=db) == 1
    assert notify_ready_roulette_orders(db_file=db) == 0
    assert len(calls) == 1

    payload = calls[0][2]
    button = payload["components"][0]["components"][0]
    assert button["label"] == "前往輪盤抽取保底"
    assert button["url"].endswith("/me/orders/9/roulette")

    with sqlite3.connect(db) as conn:
        row = conn.execute(
            "SELECT status, message_id FROM roulette_ready_notifications WHERE order_id = 9"
        ).fetchone()
    assert row == ("sent", "999")
