from pathlib import Path

required = {
    "services/vip_monthly_benefits.py": [
        "MONTHLY_CASH_AMOUNTS",
        "def list_available_cash_benefits(",
        "def reserve_cash_benefit_for_channel(",
        "def release_cash_benefits_for_channel(",
        "def redeem_cash_benefits_for_channel(",
    ],
    "services/self_service_selection_runtime.py": [
        "available_vip_monthly_benefits",
        'value=f"vip_monthly:{benefit[\'id\']}"',
        "selected_vip_monthly_benefit_id",
    ],
    "services/self_service_financials.py": [
        "selected_vip_monthly_benefit_id",
        "additional_store_discount_amount=point_cash + vip_monthly_cash",
        "vip_monthly_cash_amount",
    ],
    "services/self_service_runtime.py": [
        "reserve_cash_benefit_for_channel",
        'data["customer_id"] = int(customer_id)',
    ],
    "shared/web_order_sync.py": [
        "_sync_vip_monthly_cash_benefit_lifecycle",
        "redeem_cash_benefits_for_channel",
        "release_cash_benefits_for_channel",
    ],
    "web/app/services/payout_notifications.py": [
        'if "unpaid_count" in totals:',
    ],
}

for filename, markers in required.items():
    source = Path(filename).read_text(encoding="utf-8")
    missing = [marker for marker in markers if marker not in source]
    if missing:
        raise SystemExit(f"{filename}: first-stage repair incomplete: {missing}")

path = Path("tests/test_payout_notifications.py")
source = path.read_text(encoding="utf-8")
marker = "def test_individual_paid_notification_accepts_canonical_payout_summary_snapshot():"
if marker not in source:
    source += '''\n\n\ndef test_individual_paid_notification_accepts_canonical_payout_summary_snapshot():\n    before = {\n        "month": "2026-10",\n        "role": "worker",\n        "person_id": "123",\n        "totals": {\n            "person_count": 1,\n            "unpaid_total": 800,\n            "unpaid_count": 2,\n            "paid_total": 0,\n            "paid_count": 0,\n        },\n        "people": [],\n    }\n    after = {"target_status": "paid", "person_role": "worker"}\n    assert payout_notifications.should_send_payout_paid_notification(before=before, after=after) is True\n\n    before["totals"]["unpaid_count"] = 0\n    assert payout_notifications.should_send_payout_paid_notification(before=before, after=after) is False\n'''
    path.write_text(source, encoding="utf-8")
