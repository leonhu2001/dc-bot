import sqlite3
from pathlib import Path

import pytest

from web.app.services import love_delta_service as service


def make_db(path: Path, rule_key="fun_mawan_galagame_hard", status="active"):
    with sqlite3.connect(path) as conn:
        conn.executescript(
            """
            CREATE TABLE web_orders (
                id INTEGER PRIMARY KEY,
                customer_discord_id TEXT,
                customer_display_name TEXT,
                order_rule_key TEXT,
                item TEXT,
                category TEXT,
                status TEXT,
                bot_order_no TEXT,
                ticket_channel_id TEXT
            );
            CREATE TABLE order_assignments (
                id INTEGER PRIMARY KEY,
                order_id INTEGER,
                worker_discord_id TEXT,
                worker_display_name TEXT,
                role_type TEXT,
                is_active INTEGER
            );
            """
        )
        conn.execute(
            "INSERT INTO web_orders VALUES (1,'boss','Boss',?,'困難','三角洲趣味單',?,'MO1','456')",
            (rule_key, status),
        )
        conn.execute(
            "INSERT INTO order_assignments VALUES (1,1,'girl1','麻糬','companion',1)"
        )
        conn.execute(
            "INSERT INTO order_assignments VALUES (2,1,'girl2','小玄','companion',1)"
        )
        conn.commit()


def start(db):
    service.get_love_delta_context("boss", 1, db_file=db)
    return service.start_love_delta("boss", 1, db_file=db)


def test_plan_and_roles(tmp_path):
    db = tmp_path / "ld.db"
    make_db(db)
    ctx = service.get_love_delta_context("boss", 1, db_file=db)
    assert ctx["plan"]["label"] == "困難"
    assert ctx["state"]["affection"] == -30
    assert ctx["viewer"]["role"] == "boss"
    girl = service.get_love_delta_context("girl1", 1, db_file=db)
    assert girl["viewer"]["role"] == "companion"
    with pytest.raises(PermissionError):
        service.get_love_delta_context("stranger", 1, db_file=db)


def test_boss_starts_and_companion_cannot(tmp_path):
    db = tmp_path / "ld.db"
    make_db(db)
    service.get_love_delta_context("girl1", 1, db_file=db)
    with pytest.raises(PermissionError):
        service.start_love_delta("girl1", 1, db_file=db)
    ctx = service.start_love_delta("boss", 1, db_file=db)
    assert ctx["state"]["started"] is True


def test_correct_guess_multiplies_positive_round_score(tmp_path):
    db = tmp_path / "ld.db"
    make_db(db, rule_key="fun_mawan_galagame_standard")
    start(db)
    service.save_boss_guess("boss", 1, answer="非洲之心", hint_category="收藏品", hint_quality="紅色", db_file=db)
    service.save_companion_guess("girl1", 1, guess=" 非洲之心 ", db_file=db)
    service.apply_love_delta_event("girl1", 1, "item_big_red", db_file=db)
    ctx = service.settle_love_delta_round(
        "boss", 1, expected_round=1, result="success", extraction_tier=300, db_file=db
    )
    assert ctx["state"]["affection"] == 28.8
    assert ctx["state"]["round_no"] == 2
    assert ctx["state"]["theme_affection"] == 28.8


def test_failed_extraction_counts_safe_value_but_does_not_change_theme(tmp_path):
    db = tmp_path / "ld.db"
    make_db(db, rule_key="fun_mawan_galagame_standard")
    start(db)
    service.apply_love_delta_event("girl1", 1, "item_gold", db_file=db)
    ctx = service.settle_love_delta_round(
        "girl1", 1, expected_round=1, result="fail", extraction_tier=600, db_file=db
    )
    assert ctx["state"]["affection"] == 11
    assert ctx["state"]["theme_affection"] == 0


def test_first_rescue_is_per_companion(tmp_path):
    db = tmp_path / "ld.db"
    make_db(db, rule_key="fun_mawan_galagame_standard")
    start(db)
    service.apply_love_delta_event("boss", 1, "first_rescue", target_companion_id="girl1", db_file=db)
    with pytest.raises(ValueError):
        service.apply_love_delta_event("boss", 1, "first_rescue", target_companion_id="girl1", db_file=db)
    ctx = service.apply_love_delta_event("boss", 1, "first_rescue", target_companion_id="girl2", db_file=db)
    assert ctx["state"]["affection"] == 10


def test_four_same_unlocks_next_round_loadout(tmp_path):
    db = tmp_path / "ld.db"
    make_db(db, rule_key="fun_mawan_galagame_standard")
    start(db)
    service.apply_love_delta_event("girl1", 1, "four_same", db_file=db)
    ctx = service.save_next_loadout("boss", 1, agent="紅狼", weapon="M4A1", db_file=db)
    assert ctx["state"]["next_designation"] == {"round_no": 2, "agent": "紅狼", "weapon": "M4A1"}
    ctx = service.settle_love_delta_round("boss", 1, expected_round=1, result="success", extraction_tier=0, db_file=db)
    assert ctx["state"]["current_designation"]["agent"] == "紅狼"


def test_closed_unstarted_order_has_no_fake_history(tmp_path):
    db = tmp_path / "ld.db"
    make_db(db, status="closed")
    info = service.get_love_delta_entry_info("boss", 1, db_file=db)
    assert info["view_only"] is False
    assert info["expired"] is True
