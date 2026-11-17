"""One customer-service review card across all producers and statuses."""
from __future__ import annotations

import pytest

from services.cs_review_presentation import (
    COLOR_NEUTRAL,
    COLOR_PENDING,
    COLOR_REJECTED,
    COLOR_SUCCESS,
    COLOR_WARNING,
    REVIEW_ACTION_LABEL,
    REVIEW_FOOTER,
    review_color,
    review_embed_payload,
    review_link_components,
    review_notification_text,
)
from services.customer_service_pending_notifications import _payment_embed, _transfer_embed
from services.topup_runtime import _topup_review_embed


@pytest.mark.parametrize("status,color", [
    ("pending", COLOR_PENDING),
    ("pending_review", COLOR_PENDING),
    ("approved", COLOR_SUCCESS),
    ("approved_pending_apply", COLOR_SUCCESS),
    ("completed", COLOR_SUCCESS),
    ("rejected", COLOR_REJECTED),
    ("cancelled", COLOR_NEUTRAL),
    ("apply_error", COLOR_WARNING),
])
def test_status_colors_are_consistent_for_all_review_types(status, color):
    assert review_color(status) == color


def test_common_review_embed_fields_are_ordered_and_bounded():
    payload = review_embed_payload(
        category="付款審核", status="pending_review", status_label="待客服審核",
        description="請確認款項", reference="PAY-101", applicant="老闆甲",
        amount=1260, fields=[
            ("付款方式", "銀行轉帳", True),
            ("客服備註", "測試" * 600, False),
        ],
    )
    assert payload["title"] == "📋 客服審核｜付款審核｜待客服審核"
    assert [item["name"] for item in payload["fields"][:3]] == [
        "案件編號", "申請人／老闆", "金額",
    ]
    assert [item["value"] for item in payload["fields"][:3]] == [
        "PAY-101", "老闆甲", "1,260T",
    ]
    assert len(payload["fields"][-1]["value"]) <= 1024
    assert payload["footer"]["text"] == REVIEW_FOOTER
    assert payload["color"] == COLOR_PENDING


def test_review_link_is_an_existing_page_not_a_new_approval_button():
    url = "https://mowanentertainment.com/admin/payment-reviews?status=pending"
    components = review_link_components(url)
    assert components == [{
        "type": 1,
        "components": [{
            "type": 2, "style": 5, "label": REVIEW_ACTION_LABEL,
            "url": url,
        }],
    }]
    assert "報單待審核" in review_notification_text("報單", reference="MO-42")
    with pytest.raises(ValueError, match="HTTPS"):
        review_link_components("javascript:alert(1)")


def test_payment_and_internal_transfer_share_review_layout():
    payment = _payment_embed({
        "id": 2, "status": "pending_review", "review_no": "PAY-2",
        "amount": 1500, "payment_method": "bank_transfer",
        "customer_display_name": "老闆乙", "source_type": "worker_tip",
        "ticket_channel_id": "1567812345678901234",
    })
    transfer = _transfer_embed({
        "id": 8, "status": "pending", "amount": 2800,
        "from_employee_display_name": "員工甲", "to_employee_display_name": "員工乙",
        "created_by_display_name": "店長",
    })
    assert payment.title.startswith("📋 客服審核｜付款審核｜")
    assert transfer.title.startswith("📋 客服審核｜內部轉帳｜")
    assert payment.footer.text.startswith(REVIEW_FOOTER)
    assert transfer.footer.text.startswith(REVIEW_FOOTER)
    assert payment.fields[0].name == transfer.fields[0].name == "案件編號"
    assert any(f.name == "來源" and f.value == "雞腿" for f in payment.fields)
    assert any(f.name == "轉入" and f.value == "員工乙" for f in transfer.fields)


@pytest.mark.parametrize("status,expected_status", [
    ("pending_review", "待客服審核"),
    ("completed", "已完成"),
    ("rejected", "已駁回"),
    ("cancelled", "已取消"),
])
def test_topup_pending_and_resolved_keep_same_embed_schema(status, expected_status):
    card = _topup_review_embed({
        "id": 11, "status": status, "topup_no": "TOPUP-11",
        "customer_display_name": "老闆丙", "customer_discord_id": "111",
        "amount": 1000, "payment_method": "bank_transfer",
        "payment_reference": "12345", "source": "web",
        "approved_by_display_name": "客服丁",
        "rejected_by_discord_id": "333",
        "rejected_reason": "款項未核對",
    })
    assert card.title == f"📋 客服審核｜儲值｜{expected_status}"
    assert card.fields[0].name == "案件編號"
    assert card.fields[0].value == "TOPUP-11"
    assert card.fields[2].name == "金額"
    assert card.fields[2].value == "1,000T"
    assert card.footer.text.startswith(REVIEW_FOOTER)
    assert any(f.name == "來源" and f.value == "網站" for f in card.fields)
    assert card.color.value == review_color(status)


def test_vip_and_report_notification_producers_share_presentation_contract():
    from pathlib import Path
    root = Path(__file__).resolve().parents[1]
    vip = (root / "services/vip_review_runtime.py").read_text(encoding="utf-8")
    report = (root / "web/app/services/order_reporting.py").read_text(encoding="utf-8")
    assert "review_embed_payload(" in vip
    assert 'category="VIP 保級"' in vip
    assert "review_embed_payload(" in report
    assert 'category="報單"' in report
    assert "review_link_components(report_url)" in report
    assert 'allowed_mentions": {"parse": []}' in report
    assert '"enforce_nonce": True' in report
