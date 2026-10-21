from __future__ import annotations

import json
from pathlib import Path

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from services import vip_timer
from services import vip_timer_billing_guard as billing
from services import vip_timer_policy_v5 as policy


def test_game_order_matches_storefront_request():
    assert policy._GAME_ORDER == (
        "三角洲端遊",
        "三角洲手遊",
        "特戰英豪",
        "英雄聯盟",
        "APEX",
        "STEAM",
    )


def test_delta_special_gameplay_labels_are_third_layer_names():
    assert policy._special_gameplay_label(
        source_group="絕巴技術陪",
        detail_label="絕巴技術陪",
        variant="",
        service_type="雙陪",
    ) == "絕巴技術陪"
    assert policy._special_gameplay_label(
        source_group="黑潮爆破",
        detail_label="雙陪",
        variant="",
        service_type="雙陪",
    ) == "黑潮爆破"


def test_delta_special_gameplays_are_desktop_only_policy():
    source = Path("services/vip_timer_policy_v5.py").read_text(encoding="utf-8")
    assert "basic_mobile_exbar_tech" not in source
    assert 'category == "delta_mobile_basic" and (' in source
    assert '"黑潮爆破" in text_value or "絕巴技術陪" in text_value' in source
    assert "第三層" in source


def test_vip_timer_snapshot_is_excluded_from_entertainment_loyalty():
    assert policy._is_vip_timer_snapshot(
        {"price_snapshot_json": json.dumps({"vip_timer": True})}
    ) is True
    assert policy._is_vip_timer_snapshot(
        {"price_snapshot_json": json.dumps({"vip_timer": False})}
    ) is False


def test_vip_percent_rounding_uses_customer_pay_rate():
    assert billing._discount_amount(1000, 98) == 980
    assert billing._discount_amount(1000, 96) == 960
    assert billing._discount_amount(1000, 94) == 940
    assert billing._discount_amount(101, 98) == 99


def test_discount_settlement_reduces_customer_and_payout_base_together(tmp_path, monkeypatch):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'vip-policy.db'}",
        connect_args={"check_same_thread": False},
    )
    local = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    monkeypatch.setattr(vip_timer, "SessionLocal", local)
    monkeypatch.setattr(billing, "_vip_level_and_rate", lambda order_id: ("金級魔丸", 98))

    with engine.begin() as conn:
        conn.execute(text("""
            CREATE TABLE vip_timer_sessions (
                order_id INTEGER PRIMARY KEY,
                final_amount INTEGER,
                updated_at TEXT
            )
        """))
        conn.execute(text("""
            CREATE TABLE vip_timer_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                order_id INTEGER NOT NULL,
                action TEXT NOT NULL,
                actor_discord_id TEXT,
                payload_json TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL
            )
        """))
        conn.execute(text("""
            CREATE TABLE web_orders (
                id INTEGER PRIMARY KEY,
                amount INTEGER,
                original_amount INTEGER,
                payout_base_amount INTEGER,
                customer_pay_amount INTEGER,
                price_snapshot_json TEXT,
                updated_at TEXT
            )
        """))
        conn.execute(text("""
            CREATE TABLE order_acceptance_meta (
                order_id INTEGER PRIMARY KEY,
                price_snapshot_json TEXT,
                updated_at TEXT
            )
        """))
        conn.execute(text("INSERT INTO vip_timer_sessions(order_id, final_amount) VALUES (1, 1000)"))
        conn.execute(text("INSERT INTO web_orders(id, price_snapshot_json) VALUES (1, '{}')"))
        conn.execute(text("INSERT INTO order_acceptance_meta(order_id) VALUES (1)"))

    result = billing._apply_vip_discount_to_result(
        1,
        {"order_id": 1, "final_amount": 1000, "total_seconds": 3600, "segments": []},
    )
    assert result["original_amount"] == 1000
    assert result["final_amount"] == 980
    assert result["payout_base_amount"] == 980

    with engine.begin() as conn:
        row = conn.execute(text(
            "SELECT amount, original_amount, payout_base_amount, customer_pay_amount, price_snapshot_json "
            "FROM web_orders WHERE id=1"
        )).mappings().one()
    assert int(row["amount"]) == 980
    assert int(row["original_amount"]) == 1000
    assert int(row["payout_base_amount"]) == 980
    assert int(row["customer_pay_amount"]) == 980
    snapshot = json.loads(str(row["price_snapshot_json"]))
    assert snapshot["vip_discount_pay_rate"] == 98
    assert "entertainment_loyalty_progress" in snapshot["excluded_benefits"]


def test_public_vip_page_documents_timer_policy():
    text_value = Path("web/app/templates/vip.html").read_text(encoding="utf-8")
    assert "可使用「VIP 自由計時」" in text_value
    assert "整張單最低計費 15 分鐘" in text_value
    assert "娛樂陪累積送時數" in text_value
    assert "VIP 自由計時僅可使用 VIP 百分比折扣" in text_value


def test_web_runtime_installs_timer_policy_for_admin_loyalty_reconciliation():
    source = Path("web/app/main.py").read_text(encoding="utf-8")
    assert "from services.vip_timer_policy_v5 import install_vip_timer_policy_v5" in source
    assert "install_vip_timer_policy_v5()" in source


def test_policy_source_excludes_sweet_teaching_and_mobile_delta_special_modes():
    source = Path("services/vip_timer_policy_v5.py").read_text(encoding="utf-8")
    assert '"甜蜜" in text_value' in source
    assert '"教學" in text_value' in source
    assert '"黑潮爆破" in text_value or "絕巴技術陪" in text_value' in source
    assert '"note": "vip_timer_excluded"' in source
