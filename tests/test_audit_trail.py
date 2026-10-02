import json
import sqlite3

from services.wallet_service import adjust_wallet_balance
from web.app.services.audit_trail import (
    REDACTED,
    audit_changes,
    sanitize_audit_payload,
    write_sqlite_audit_log,
)


def test_audit_payload_redacts_sensitive_fields_recursively():
    payload = {
        "amount": 500,
        "password": "super-secret",
        "nested": {
            "access_token": "abc",
            "payment_reference": "bank-proof-123",
            "safe_note": "manual correction",
        },
        "credentials": {
            "username": "boss",
            "password": "pw",
        },
    }

    cleaned = sanitize_audit_payload(payload)

    assert cleaned["amount"] == 500
    assert cleaned["password"] == REDACTED
    assert cleaned["nested"]["access_token"] == REDACTED
    assert cleaned["nested"]["payment_reference"] == REDACTED
    assert cleaned["nested"]["safe_note"] == "manual correction"
    assert cleaned["credentials"] == REDACTED


def test_audit_changes_only_returns_changed_fields_and_redacts():
    changes = audit_changes(
        {
            "amount": 1000,
            "status": "active",
            "password": "old",
        },
        {
            "amount": 850,
            "status": "active",
            "password": "new",
        },
    )

    assert changes == {
        "amount": {
            "before": 1000,
            "after": 850,
        }
    }


def test_sqlite_audit_writer_persists_before_after_reason_and_masks(tmp_path):
    db_path = tmp_path / "web_dashboard.db"

    audit_id = write_sqlite_audit_log(
        admin_discord_id="999",
        action="test_sensitive_change",
        target_type="test",
        target_id="123",
        before={
            "amount": 100,
            "password": "before-secret",
        },
        after={
            "amount": 200,
            "password": "after-secret",
        },
        reason="測試原因",
        metadata={
            "payment_reference": "should-hide",
            "source": "pytest",
        },
        db_file=db_path,
    )

    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT * FROM admin_audit_logs WHERE id=?",
            (audit_id,),
        ).fetchone()

    assert row is not None
    assert row["admin_discord_id"] == "999"
    assert row["action"] == "test_sensitive_change"
    assert row["target_type"] == "test"
    assert row["target_id"] == "123"

    before = json.loads(row["before_json"])
    after = json.loads(row["after_json"])

    assert before["amount"] == 100
    assert before["password"] == REDACTED
    assert after["amount"] == 200
    assert after["password"] == REDACTED
    assert after["reason"] == "測試原因"
    assert after["_audit_meta"]["payment_reference"] == REDACTED
    assert after["_audit_meta"]["source"] == "pytest"


def test_operator_wallet_change_writes_audit_to_matching_environment(tmp_path):
    bot_db = tmp_path / "bot.db"
    web_db = tmp_path / "web_dashboard.db"

    transaction = adjust_wallet_balance(
        customer_id="123",
        amount=500,
        tx_type="adjustment",
        operator_discord_id="999",
        operator_display_name="總管A",
        note="人工補款",
        db_file=bot_db,
    )

    assert transaction["balance_before"] == 0
    assert transaction["balance_after"] == 500

    with sqlite3.connect(web_db) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            """
            SELECT *
            FROM admin_audit_logs
            WHERE action='wallet_adjustment'
            ORDER BY id DESC
            LIMIT 1
            """
        ).fetchone()

    assert row is not None
    assert row["admin_discord_id"] == "999"
    assert row["target_type"] == "customer_wallet"
    assert row["target_id"] == "123"

    before = json.loads(row["before_json"])
    after = json.loads(row["after_json"])

    assert before["balance"] == 0
    assert after["balance"] == 500
    assert after["amount"] == 500
    assert after["transaction_id"] == transaction["id"]
    assert after["operator_display_name"] == "總管A"
    assert after["reason"] == "人工補款"
