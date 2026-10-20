from services.acceptance.error_presentation import format_acceptance_claim_error


def test_lock_error_points_to_panel_open_time():
    result = format_acceptance_claim_error(
        "🔒 此訂單目前為 1 分鐘接單保護期；指定人員可立即接單，其他人請於派單 1 分鐘後再接。"
    )
    assert "1 分鐘接單保護期" in result
    assert "公開開放時間" in result


def test_role_error_gives_actionable_guidance():
    result = format_acceptance_claim_error(
        "你的遊戲身分組或職位／階級不符合這張單的可接條件。"
    )
    assert "不符合這張單的接單資格" in result
    assert "通知客服檢查身分組" in result


def test_unknown_error_is_not_hidden():
    assert format_acceptance_claim_error("自訂拒絕原因") == "自訂拒絕原因"
