from pathlib import Path

from services.topups import (
    approve_topup_order,
    calculate_topup_preview,
    create_topup_order,
    get_topup_order,
    submit_topup_payment,
)


def test_platinum_topup_gets_same_transaction_rebate():
    preview = calculate_topup_preview(0, 12000)
    assert preview["vip_total_after"] == 12000
    assert preview["vip_level_after"] == "白金魔丸"
    assert preview["rebate_percent"] == 2
    assert preview["rebate_amount"] == 240
    assert preview["credited_amount"] == 12240


def test_rebate_uses_level_after_current_topup():
    cases = [
        (11999, 1, "白金魔丸", 2),
        (24999, 1, "鑽石魔丸", 3),
        (49999, 1, "白鑽魔丸", 4),
        (88887, 1, "黑鑽魔丸", 5),
    ]

    for before, amount, level_name, percent in cases:
        preview = calculate_topup_preview(before, amount)
        assert preview["vip_level_after"] == level_name
        assert preview["rebate_percent"] == percent


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
