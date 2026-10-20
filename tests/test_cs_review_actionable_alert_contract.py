from services.web_sync.cs_presentation import build_cs_review_alert_text


def test_actionable_alert_identifies_exact_order():
    text = build_cs_review_alert_text(456, 123)
    assert "WEB-456" in text
    assert "需要客服確認" in text
    assert "<@&123>" in text
