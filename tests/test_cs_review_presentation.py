from services.web_sync.cs_presentation import (
    admin_order_workspace_url,
    build_cs_review_alert_text,
)


def test_admin_order_workspace_url_uses_canonical_site():
    assert admin_order_workspace_url(321) == (
        "https://mowanentertainment.com/admin/order-workspace/321"
    )


def test_cs_alert_mentions_role_when_configured():
    assert build_cs_review_alert_text(321, 987) == (
        "<@&987>｜WEB-321 有新訂單需要客服確認。"
    )


def test_cs_alert_still_works_without_role():
    assert build_cs_review_alert_text(321, None) == (
        "WEB-321 有新訂單需要客服確認。"
    )
