import sqlite3
from pathlib import Path

from web.app.routers import admin_centers
from web.app.services.admin_customer_loyalty import (
    enrich_customer_rows,
    load_customer_loyalty,
    load_customer_loyalty_detail,
)


def _make_db(path: Path) -> None:
    with sqlite3.connect(path) as conn:
        conn.executescript(
            """
            CREATE TABLE web_orders (
                id INTEGER PRIMARY KEY,
                customer_discord_id TEXT,
                customer_display_name TEXT,
                status TEXT,
                amount INTEGER,
                customer_pay_amount INTEGER,
                created_at TEXT,
                updated_at TEXT
            );

            CREATE TABLE customer_loyalty_progress (
                customer_discord_id TEXT NOT NULL,
                scope_key TEXT NOT NULL,
                rule_key TEXT NOT NULL,
                rule_label TEXT NOT NULL,
                pricing_type TEXT NOT NULL,
                player_count INTEGER NOT NULL DEFAULT 1,
                progress_units REAL NOT NULL DEFAULT 0,
                threshold_units REAL NOT NULL,
                benefit_kind TEXT NOT NULL,
                benefit_units REAL NOT NULL,
                updated_at TEXT NOT NULL,
                PRIMARY KEY (customer_discord_id, scope_key)
            );

            CREATE TABLE customer_benefit_coupons (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                customer_discord_id TEXT NOT NULL,
                scope_key TEXT NOT NULL,
                rule_key TEXT NOT NULL,
                rule_label TEXT NOT NULL,
                pricing_type TEXT NOT NULL,
                player_count INTEGER NOT NULL DEFAULT 1,
                benefit_kind TEXT NOT NULL,
                benefit_units REAL NOT NULL,
                status TEXT NOT NULL DEFAULT 'active',
                source TEXT NOT NULL DEFAULT 'loyalty',
                issued_at TEXT NOT NULL,
                expires_at TEXT,
                reserved_order_id INTEGER,
                redeemed_order_id INTEGER,
                redeemed_at TEXT
            );
            """
        )
        conn.execute(
            """
            INSERT INTO web_orders
            VALUES (1,'100','老闆A','closed',500,450,'2026-10-11','2026-10-11')
            """
        )
        conn.execute(
            """
            INSERT INTO customer_loyalty_progress
            VALUES ('100','delta_desktop_fun|basic_entertain','basic_entertain_single',
                    '娛樂陪〈端遊〉｜單陪','hourly',1,6,10,'extra_hours',0.5,'2026-10-11T01:00:00+08:00')
            """
        )
        conn.execute(
            """
            INSERT INTO customer_loyalty_progress
            VALUES ('100','valorant|valorant_entertain_ranked','valorant_entertain_ranked',
                    '特戰英豪｜娛樂陪｜積分','game',2,14,20,'extra_games',1,'2026-10-11T02:00:00+08:00')
            """
        )
        for status in ("active", "reserved", "redeemed", "expired"):
            conn.execute(
                """
                INSERT INTO customer_benefit_coupons (
                    customer_discord_id, scope_key, rule_key, rule_label,
                    pricing_type, player_count, benefit_kind, benefit_units,
                    status, source, issued_at, expires_at,
                    reserved_order_id, redeemed_order_id, redeemed_at
                ) VALUES ('100','delta_desktop_fun|basic_entertain','basic_entertain_single',
                          '娛樂陪〈端遊〉｜雙陪','hourly',2,'extra_hours',0.5,?,'loyalty',
                          '2026-10-11T03:00:00+08:00','2027-01-09T03:00:00+08:00',
                          CASE WHEN ? = 'reserved' THEN 77 ELSE NULL END,
                          CASE WHEN ? = 'redeemed' THEN 88 ELSE NULL END,
                          CASE WHEN ? = 'redeemed' THEN '2026-10-11T04:00:00+08:00' ELSE NULL END)
                """,
                (status, status, status, status),
            )
        conn.commit()


def test_load_customer_loyalty_formats_progress_coupon_counts_and_new_benefit_language(tmp_path: Path):
    db = tmp_path / "web_dashboard.db"
    _make_db(db)

    snapshot = load_customer_loyalty(db, ["100"])["100"]

    assert snapshot["progress"][0]["title"] == "娛樂陪〈端遊〉"
    assert snapshot["progress"][0]["progress_text"] == "6 / 10H"
    assert snapshot["progress"][0]["benefit_text"] == "折抵 30 分鐘額度"
    assert snapshot["progress"][1]["title"] == "特戰英豪｜娛樂陪｜積分"
    assert snapshot["progress"][1]["progress_text"] == "14 / 20局"
    assert snapshot["progress"][1]["benefit_text"] == "折抵 1 局額度"
    assert snapshot["coupon_counts"] == {
        "active": 1,
        "reserved": 1,
        "redeemed": 1,
        "expired": 1,
        "revoked": 0,
        "other": 0,
    }
    assert len(snapshot["active_coupons"]) == 1
    assert snapshot["active_coupons"][0]["title"] == "娛樂陪〈端遊〉｜折抵 30 分鐘額度"
    assert "雙陪" not in snapshot["active_coupons"][0]["title"]


def test_enrich_customer_rows_keeps_customer_center_fields_and_coupon_preview(tmp_path: Path):
    db = tmp_path / "web_dashboard.db"
    _make_db(db)

    rows = enrich_customer_rows(
        db,
        [
            {"customer_discord_id": "100", "customer_display_name": "老闆A"},
            {"customer_discord_id": "200", "customer_display_name": "老闆B"},
        ],
    )

    assert rows[0]["customer_display_name"] == "老闆A"
    assert len(rows[0]["loyalty_progress"]) == 2
    assert len(rows[0]["loyalty_active_coupons"]) == 1
    assert rows[0]["loyalty_coupon_counts"]["active"] == 1
    assert rows[0]["loyalty_has_anything"] is True
    assert rows[1]["loyalty_progress"] == []
    assert rows[1]["loyalty_active_coupons"] == []
    assert rows[1]["loyalty_coupon_counts"]["active"] == 0
    assert rows[1]["loyalty_has_anything"] is False


def test_customer_center_snapshot_includes_loyalty_progress(tmp_path: Path, monkeypatch):
    web_db = tmp_path / "web_dashboard.db"
    _make_db(web_db)

    monkeypatch.setattr(admin_centers, "WEB_DB", web_db)
    monkeypatch.setattr(admin_centers, "BOT_DB", tmp_path / "missing_bot.db")

    snapshot = admin_centers._customer_snapshot(include_wallets=False)
    row = snapshot["rows"][0]

    assert row["customer_discord_id"] == "100"
    assert row["completed_spend"] == 450
    assert [item["progress_text"] for item in row["loyalty_progress"]] == [
        "6 / 10H",
        "14 / 20局",
    ]
    assert row["loyalty_coupon_counts"]["active"] == 1
    assert row["loyalty_active_coupons"][0]["status_label"] == "可使用"


def test_admin_loyalty_detail_keeps_games_separate_and_exposes_order_references(tmp_path: Path):
    db = tmp_path / "web_dashboard.db"
    _make_db(db)

    detail = load_customer_loyalty_detail(db, "100")

    assert len(detail["groups"]) == 2
    assert {group["scope_key"] for group in detail["groups"]} == {
        "delta_desktop_fun|basic_entertain",
        "valorant|valorant_entertain_ranked",
    }
    reserved = next(coupon for coupon in detail["coupons"] if coupon["status"] == "reserved")
    redeemed = next(coupon for coupon in detail["coupons"] if coupon["status"] == "redeemed")
    assert reserved["status_label"] == "使用中"
    assert reserved["reserved_order_id"] == 77
    assert redeemed["status_label"] == "已使用"
    assert redeemed["redeemed_order_id"] == 88
    assert redeemed["redeemed_at_text"].startswith("2026-10-11 04:00")
