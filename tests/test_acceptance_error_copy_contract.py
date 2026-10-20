from services.acceptance.error_presentation import format_acceptance_claim_error


def test_full_order_message_does_not_invite_retry_spam():
    text = format_acceptance_claim_error("這張單已經滿人，無法接單。")
    assert "等待付款" in text
    assert "接單人數已滿" in text
    assert "若有人取消接單" in text
