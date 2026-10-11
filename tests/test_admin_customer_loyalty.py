import sqlite3
from pathlib import Path

from web.app.services.admin_customer_loyalty import (
    enrich_customer_rows,
    load_customer_loyalty_detail,
)


def _db(tmp_path: Path) -> Path:
    path = tmp_path / "loyalty-admin.db"
    with sqlite3.connect(path) as conn:
        conn.execute("""
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
            )
        """)
        conn.execute("""
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
            )
        """)
        conn.execute("""
            INSERT INTO customer_loyalty_progress VALUES
            ('123', 'valorant|valorant_entertain_ng', 'valorant_entertain_ng', 'VALORANT｜娛樂陪｜雙陪', 'hourly', 2, 6, 10, 'extra_hours', 0.5, '2026-10-11T10:00:00+08:00'),
            ('123', 'lol|lol_entertain_ng', 'lol_entertain_ng', 'LOL｜娛樂陪', 'hourly', 1, 4, 10, 'extra_hours', 0.5, '2026-10-11T11:00:00+08:00')
        """)
        conn.execute("""
            INSERT INTO customer_benefit_coupons (
                customer_discord_id, scope_key, rule_key, rule_label, pricing_type,
                player_count, benefit_kind, benefit_units, status, source,
                issued_at, expires_at, reserved_order_id, redeemed_order_id, redeemed_at
            ) VALUES
            ('123', 'valorant|valorant_entertain_ng', 'valorant_entertain_ng', 'VALORANT｜娛樂陪｜雙陪', 'hourly', 2, 'extra_hours', 0.5, 'active', 'loyalty', '2026-10-11T10:00:00+08:00', '2027-01-09T10:00:00+08:00', NULL, NULL, NULL),
            ('123', 'lol|lol_entertain_ng', 'lol_entertain_ng', 'LOL｜娛樂陪', 'hourly', 1, 'extra_hours', 0.5, 'redeemed', 'loyalty', '2026-10-11T09:00:00+08:00', '2027-01-09T09:00:00+08:00', NULL, 88, '2026-10-11T12:00:00+08:00')
        """)
    return path


def test_admin_loyalty_detail_shows_real_coupon_status_and_keeps_games_separate(tmp_path: Path):
    data = load_customer_loyalty_detail(_db(tmp_path), "123")

    assert len(data["groups"]) == 2
    assert {group["scope_key"] for group in data["groups"]} == {
        "valorant|valorant_entertain_ng",
        "lol|lol_entertain_ng",
    }
    assert data["coupon_counts"]["active"] == 1
    assert data["coupon_counts"]["redeemed"] == 1
    assert data["active_coupons"][0]["status_label"] == "可使用"
    assert "折抵 30 分鐘額度" in data["active_coupons"][0]["title"]
    assert "雙陪" not in data["active_coupons"][0]["title"]
    assert all("位" not in row["title"] for row in data["progress"])


def test_customer_list_enrichment_contains_coupon_preview_and_progress(tmp_path: Path):
    rows = enrich_customer_rows(
        _db(tmp_path),
        [{"customer_discord_id": "123", "customer_display_name": "老闆A"}],
    )

    assert rows[0]["loyalty_has_anything"] is True
    assert len(rows[0]["loyalty_progress"]) == 2
    assert len(rows[0]["loyalty_active_coupons"]) == 1
    assert rows[0]["loyalty_coupon_counts"]["redeemed"] == 1
