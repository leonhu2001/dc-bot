from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_member_wallet_explains_bonus_first_spending():
    template = (ROOT / "web/app/templates/member_wallet.html").read_text(encoding="utf-8")

    assert "一般點單會先使用贈額，再扣實付本金" in template
    assert "雞腿／打賞只能使用實付本金" in template
    assert "wallet.refundable_balance" in template


def test_discord_wallet_shows_principal_bonus_and_refundable_cash():
    source = (ROOT / "views/member_portal.py").read_text(encoding="utf-8")

    assert "💳 實付本金" in source
    assert "🎁 VIP／活動贈額" in source
    assert "可退款金額" in source
    assert "一般點單會先使用贈額，再扣實付本金" in source


def test_admin_refund_form_uses_refundable_balance_not_raw_principal():
    template = (ROOT / "web/app/templates/admin_wallet_detail.html").read_text(encoding="utf-8")

    assert 'max="{{ wallet.refundable_balance or 0 }}"' in template
    assert "目前可實退" in template
    assert "已用贈額待抵扣" in template
