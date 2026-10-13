from pathlib import Path
import sqlite3

from core.vip_levels import (
    VIP_TOPUP_REBATE_POLICY_CURRENT,
    VIP_TOPUP_REBATE_POLICY_LEGACY,
)
from services.topups import (
    approve_topup_order,
    calculate_topup_preview,
    create_topup_order,
    ensure_topup_tables,
    get_topup_order,
    submit_topup_payment,
)


def test_platinum_topup_gets_same_transaction_rebate():
    preview = calculate_topup_preview(0, 12000)
    assert preview["vip_total_after"] == 12000
    assert preview["vip_level_after"] == "白金魔丸"
    assert preview["rebate_percent"] == 1
    assert preview["rebate_amount"] == 120
    assert preview["credited_amount"] == 12120


def test_rebate_uses_level_after_current_topup():
    cases = [
        (11999, 1, "白金魔丸", 1),
        (24999, 1, "鑽石魔丸", 2),
        (49999, 1, "白鑽魔丸", 3),
        (88887, 1, "黑鑽魔丸", 3),
    ]

    for before, amount, level_name, percent in cases:
        preview = calculate_topup_preview(before, amount)
        assert preview["vip_level_after"] == level_name
        assert preview["rebate_percent"] == percent


def test_legacy_topup_policy_keeps_old_rebate_rates():
    cases = [
        (11999, 1, "白金魔丸", 2),
        (24999, 1, "鑽石魔丸", 3),
        (49999, 1, "白鑽魔丸", 4),
        (88887, 1, "黑鑽魔丸", 5),
    ]

    for before, amount, level_name, percent in cases:
        preview = calculate_topup_preview(
            before,
            amount,
            policy_version=VIP_TOPUP_REBATE_POLICY_LEGACY,
        )
        assert preview["vip_level_after"] == level_name
        assert preview["rebate_percent"] == percent


def test_new_topup_order_is_stamped_with_current_policy(tmp_path: Path):
    db_file = tmp_path / "policy.db"
    order = create_topup_order(
        customer_discord_id="123",
        customer_display_name="Boss",
        amount=1000,
        source="web",
        db_file=db_file,
    )
    assert order["policy_version"] == VIP_TOPUP_REBATE_POLICY_CURRENT


def test_existing_topup_rows_migrate_as_legacy(tmp_path: Path):
    db_file = tmp_path / "legacy.db"
    with sqlite3.connect(db_file) as conn:
        conn.execute(
            """
            CREATE TABLE topup_orders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                topup_no TEXT UNIQUE,
                customer_discord_id TEXT NOT NULL,
                customer_display_name TEXT,
                amount INTEGER NOT NULL,
                payment_method TEXT NOT NULL DEFAULT 'bank_transfer',
                bank_last5 TEXT,
                payment_reference TEXT,
                payment_note TEXT,
                source TEXT NOT NULL DEFAULT 'web',
                status TEXT NOT NULL DEFAULT 'pending_payment',
                vip_total_before INTEGER,
                vip_total_after INTEGER,
                vip_level_before TEXT,
                vip_level_after TEXT,
                rebate_percent INTEGER NOT NULL DEFAULT 0,
                rebate_amount INTEGER NOT NULL DEFAULT 0,
                credited_amount INTEGER NOT NULL DEFAULT 0,
                wallet_transaction_id INTEGER,
                bonus_transaction_id INTEGER,
                submitted_at TEXT,
                approved_at TEXT,
                approved_by_discord_id TEXT,
                approved_by_display_name TEXT,
                completed_at TEXT,
                rejected_at TEXT,
                rejected_by_discord_id TEXT,
                rejected_reason TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            INSERT INTO topup_orders(
                topup_no, customer_discord_id, amount, created_at, updated_at
            ) VALUES('OLD-1', '123', 1000, '2026-10-13', '2026-10-13')
            """
        )
        conn.commit()

    ensure_topup_tables(db_file)
    with sqlite3.connect(db_file) as conn:
        row = conn.execute(
            "SELECT policy_version FROM topup_orders WHERE topup_no='OLD-1'"
        ).fetchone()
    assert row[0] == VIP_TOPUP_REBATE_POLICY_LEGACY


def test_topup_order_review_flow(tmp_path: Path):
    db_file = tmp_path / "topups.db"

    order = create_topup_order(
        customer_discord_id="123456789",
        customer_display_name="Test Boss",
        amount=12000,
        source="web",
        db_file=db_file,
    )
    assert order["status"] == "pending_payment"
    assert str(order["topup_no"]).startswith("TOPUP-")

    order = submit_topup_payment(
        int(order["id"]),
        customer_discord_id="123456789",
        bank_last5="12345",
        db_file=db_file,
    )
    assert order["status"] == "pending_review"
    assert order["bank_last5"] == "12345"

    order = approve_topup_order(
        int(order["id"]),
        operator_discord_id="987654321",
        operator_display_name="Staff",
        db_file=db_file,
    )
    assert order["status"] == "approved_pending_credit"

    stored = get_topup_order(int(order["id"]), db_file=db_file)
    assert stored is not None
    assert stored["status"] == "approved_pending_credit"


def test_jkopay_uses_account_last_five_digits(tmp_path: Path):
    db_file = tmp_path / "payment_methods.db"

    jko = create_topup_order(
        customer_discord_id="111",
        customer_display_name="JKO Boss",
        amount=3000,
        source="web",
        payment_method="jkopay",
        db_file=db_file,
    )
    jko = submit_topup_payment(
        int(jko["id"]),
        customer_discord_id="111",
        payment_reference="88422",
        db_file=db_file,
    )
    assert jko["status"] == "pending_review"
    assert jko["payment_method"] == "jkopay"
    assert jko["payment_reference"] == "88422"
    assert jko["bank_last5"] == "88422"
