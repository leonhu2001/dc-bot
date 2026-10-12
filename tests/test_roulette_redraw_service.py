import sqlite3

import pytest

from web.app.services.roulette_redraw_service import (
    ensure_redraw_tables,
    get_redraw_state,
    grant_redraw,
    prepare_redraw_if_credited,
)
from web.app.services.roulette_service import (
    ROULETTE_RULE_KEY,
    draw_roulette,
)


def _seed_order(db):
    with sqlite3.connect(db) as conn:
        conn.execute(
            """
            CREATE TABLE web_orders (
                id INTEGER PRIMARY KEY,
                customer_discord_id TEXT,
                customer_display_name TEXT,
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
                id,
                customer_discord_id,
                customer_display_name,
                order_rule_key,
                item,
                status,
                bot_order_no,
                ticket_channel_id
            )
            VALUES (1, '123', '老闆A', ?, '俄羅斯輪盤', 'active', 'MO1', '456')
            """,
            (ROULETTE_RULE_KEY,),
        )
        conn.commit()


def test_grant_redraw_archives_previous_result(tmp_path):
    db = tmp_path / "roulette-redraw.db"
    _seed_order(db)
    ensure_redraw_tables(db)

    first = draw_roulette(
        "123",
        1,
        mode="single",
        selection=7,
        db_file=db,
        notify=False,
    )

    granted = grant_redraw(
        1,
        count=1,
        reason="客服核准重抽",
        admin_user={"id": "999", "username": "客服"},
        db_file=db,
        notify=False,
    )
    assert granted["remaining"] == 1

    prepared = prepare_redraw_if_credited(
        "123",
        1,
        db_file=db,
    )
    assert prepared == {"prepared": True, "remaining": 0}

    with sqlite3.connect(db) as conn:
        current_count = conn.execute(
            "SELECT COUNT(*) FROM roulette_draws WHERE order_id = 1"
        ).fetchone()[0]
        history = conn.execute(
            """
            SELECT source_draw_id, guarantee_million
            FROM roulette_draw_history
            WHERE order_id = 1
            """
        ).fetchone()

    assert current_count == 0
    assert history == (first["id"], first["prize"])

    second = draw_roulette(
        "123",
        1,
        mode="safe",
        selection="red",
        db_file=db,
        notify=False,
    )
    assert second["already_drawn"] is False

    state = get_redraw_state(1, db_file=db)
    assert state["remaining"] == 0
    assert state["attempt_count"] == 2
    assert len(state["history"]) == 1
    assert state["final_draw"]["id"] == second["id"]


def test_multiple_redraw_credits_are_consumed_one_at_a_time(tmp_path):
    db = tmp_path / "roulette-redraw-multi.db"
    _seed_order(db)
    ensure_redraw_tables(db)

    draw_roulette(
        "123",
        1,
        mode="single",
        selection=9,
        db_file=db,
        notify=False,
    )
    grant_redraw(
        1,
        count=2,
        reason="補發兩次",
        admin_user={"id": "999", "username": "客服"},
        db_file=db,
        notify=False,
    )

    first_prepare = prepare_redraw_if_credited("123", 1, db_file=db)
    assert first_prepare["prepared"] is True
    assert first_prepare["remaining"] == 1

    draw_roulette(
        "123",
        1,
        mode="safe",
        selection="black",
        db_file=db,
        notify=False,
    )

    second_prepare = prepare_redraw_if_credited("123", 1, db_file=db)
    assert second_prepare["prepared"] is True
    assert second_prepare["remaining"] == 0


def test_wrong_customer_cannot_consume_redraw(tmp_path):
    db = tmp_path / "roulette-redraw-owner.db"
    _seed_order(db)
    ensure_redraw_tables(db)

    draw_roulette(
        "123",
        1,
        mode="single",
        selection=3,
        db_file=db,
        notify=False,
    )
    grant_redraw(
        1,
        count=1,
        reason="測試",
        admin_user={"id": "999", "username": "客服"},
        db_file=db,
        notify=False,
    )

    with pytest.raises(LookupError):
        prepare_redraw_if_credited("456", 1, db_file=db)

    state = get_redraw_state(1, db_file=db)
    assert state["remaining"] == 1
    assert state["final_draw"] is not None


def test_closed_order_cannot_receive_redraw(tmp_path):
    db = tmp_path / "roulette-redraw-closed.db"
    _seed_order(db)
    ensure_redraw_tables(db)

    with sqlite3.connect(db) as conn:
        conn.execute("UPDATE web_orders SET status = 'closed' WHERE id = 1")
        conn.commit()

    with pytest.raises(ValueError):
        grant_redraw(
            1,
            count=1,
            reason="不應允許",
            admin_user={"id": "999", "username": "客服"},
            db_file=db,
            notify=False,
        )
