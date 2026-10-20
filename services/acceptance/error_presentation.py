from __future__ import annotations


def format_acceptance_claim_error(message: str) -> str:
    """Turn canonical acceptance rejections into clearer Discord guidance.

    This module is presentation-only. It never decides whether a claim is
    allowed and deliberately falls back to the backend's original message for
    any rejection it does not recognize.
    """
    text = str(message or "").strip()
    if not text:
        return "接單失敗，請稍後再試或通知客服。"

    if "1 分鐘接單保護期" in text:
        return (
            "🔒 目前狀態：等待接單｜接單保護中。\n"
            "指定人員可立即接單；其他人請等派單面板顯示的公開開放時間後再按。"
        )

    if "遊戲身分組或職位／階級不符合" in text:
        return (
            "⛔ 你目前的遊戲身分組或職位／階級不符合這張單的接單資格。\n"
            "如果你認為資格應該正確，請通知客服檢查身分組。"
        )

    if "你已經接了這張單" in text:
        return "✅ 你已經在這張單的接單名單裡，不需要重複接單。"

    if "已經滿人" in text:
        return "👥 這張單目前為「等待付款」；接單人數已滿。若有人取消接單，面板會重新開放。"

    if "剩餘名額不可由你接單" in text:
        return "🔐 這張單的剩餘名額已保留給指定人員，目前沒有可由你接的公開名額。"

    if "固定 1 護 + 1 陪；已有護級接單" in text:
        return "🛡️ 這張單固定 1 護 + 1 陪，目前護級名額已有人接；下一位必須由陪級接單。"

    if "固定 1 護 + 1 陪；剩餘名額必須由護級接單" in text:
        return "🛡️ 這張單固定 1 護 + 1 陪，目前剩餘名額必須由護級接單。"

    if "至少需要護級接單，剩餘名額不能再由陪級接" in text:
        return "🛡️ 這張單仍需要護級名額，剩餘位置不能再由陪級接單。"

    if "目前不是等待接單狀態" in text:
        return "ℹ️ 這張單目前已不是「等待接單」狀態，請以最新派單面板為準。"

    return text
