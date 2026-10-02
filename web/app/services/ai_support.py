from __future__ import annotations

import json
import re
from typing import Any

import aiohttp

from web.app.config import config

HUMAN_REQUEST_PATTERNS = (
    "真人客服",
    "轉接真人",
    "转接真人",
    "找真人",
    "人工客服",
    "真人",
    "轉客服",
    "转客服",
    "找客服",
)

SENSITIVE_HANDOFF_PATTERNS = (
    "退款",
    "退費",
    "退费",
    "客訴",
    "客诉",
    "付款異常",
    "付款异常",
    "付款沒到",
    "付款没到",
    "重複扣款",
    "重复扣款",
    "扣款異常",
    "扣款异常",
    "帳密",
    "账号密码",
    "帳號密碼",
    "帐号密码",
    "密碼",
    "密码",
    "被盜",
    "被盗",
)


def detect_handoff_reason(message: str) -> str | None:
    text = re.sub(r"\s+", "", str(message or "")).lower()
    if not text:
        return None

    if any(pattern.lower() in text for pattern in HUMAN_REQUEST_PATTERNS):
        return "customer_requested_human"

    if any(pattern.lower() in text for pattern in SENSITIVE_HANDOFF_PATTERNS):
        return "sensitive_support_topic"

    return None


def local_faq_response(message: str) -> str:
    text = str(message or "").strip()
    compact = re.sub(r"\s+", "", text).lower()

    if any(word in compact for word in ("vip", "會員", "会员", "點數", "点数")):
        return (
            "VIP、會員等級與點數可以在「我的專區」查看。"
            "若你想確認目前自己的等級或點數，請先用 Discord 登入網站後前往「我的專區」。"
        )

    if any(word in compact for word in ("付款方式", "怎麼付款", "怎么付款", "付款")):
        return (
            "付款方式會依你下單時可選的選項為準；建立訂單後，票口與網站訂單頁會顯示目前付款狀態。"
            "如果是付款後沒有更新、重複扣款或其他付款異常，我可以直接幫你轉真人客服。"
        )

    if any(word in compact for word in ("價格", "价钱", "價目", "多少錢", "多少钱", "費用", "费用")):
        return (
            "最新價格請以網站「立即下單」頁顯示為準，避免舊價格或活動價格造成誤差。"
            "你也可以告訴我遊戲和想要的服務，我可以先協助你找方向。"
        )

    if any(word in compact for word in ("下單", "下单", "怎麼買", "怎么买", "訂單", "订单")):
        return (
            "你可以直接從網站上方「立即下單」建立訂單；登入 Discord 後，"
            "也能在「我的專區 → 我的訂單」查看進度、付款與客服紀錄。"
        )

    if any(word in compact for word in ("接單", "接单", "多久", "等待", "没人", "沒人")):
        return (
            "派單會依服務資格與目前人力通知適合的人員；如果等待時間較久，系統會自動擴大通知。"
            "若你已經有訂單而且需要人工協助，可以直接跟我說「轉接真人客服」。"
        )

    if any(word in compact for word in ("客服", "幫忙", "帮忙")):
        return (
            "我可以先協助一般規則、付款方式、VIP、下單與服務問題。"
            "如果你要真人處理，直接輸入「轉接真人客服」即可。"
        )

    return (
        "我可以協助你查詢下單方式、服務內容、付款、VIP 與一般規則。"
        "如果問題涉及退款、付款異常、客訴、帳號密碼，或你想直接找真人，"
        "請輸入「轉接真人客服」。"
    )


def _system_prompt() -> str:
    return (
        "你是魔丸娛樂網站客服助理。請使用繁體中文，回答簡潔、友善、不要自行捏造價格或規則。"
        "價格一律以網站即時下單頁為準。"
        "你可以回答：一般服務內容、下單方式、VIP/點數、付款方式、接單流程、網站操作。"
        "你不可以處理或要求使用者提供：退款核准、人工改金額、錢包調帳、付款證明內容、"
        "訂單帳號密碼、其他顧客資料、後台資料。"
        "如果問題涉及退款、付款異常、客訴、帳密、隱私或需要人工判斷，"
        "請明確告知需要轉真人客服，且不要做任何財務承諾。"
    )


async def generate_ai_response(
    message: str,
    *,
    history: list[dict[str, Any]] | None = None,
) -> tuple[str, bool]:
    """
    Returns (reply, used_external_ai).

    Provider contract is intentionally OpenAI-compatible but fully configurable
    through AI_SUPPORT_API_URL / API_KEY / MODEL. If unavailable or malformed,
    fall back to the conservative local FAQ responder.
    """
    api_url = str(config.AI_SUPPORT_API_URL or "").strip()
    api_key = str(config.AI_SUPPORT_API_KEY or "").strip()
    model = str(config.AI_SUPPORT_MODEL or "").strip()

    if not api_url or not api_key or not model:
        return local_faq_response(message), False

    messages: list[dict[str, str]] = [
        {"role": "system", "content": _system_prompt()},
    ]

    for item in (history or [])[-8:]:
        sender = str(item.get("sender_type") or "")
        body = str(item.get("body") or "").strip()
        if not body:
            continue
        if sender == "customer":
            role = "user"
        elif sender in {"ai", "staff"}:
            role = "assistant"
        else:
            continue
        messages.append({"role": role, "content": body[:2000]})

    if not messages or messages[-1].get("content") != str(message).strip():
        messages.append({"role": "user", "content": str(message).strip()[:2000]})

    payload = {
        "model": model,
        "messages": messages,
        "temperature": 0.2,
        "max_tokens": 500,
    }

    timeout = aiohttp.ClientTimeout(
        total=int(config.AI_SUPPORT_TIMEOUT_SECONDS or 12)
    )

    try:
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(
                api_url,
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                data=json.dumps(payload, ensure_ascii=False),
            ) as response:
                if response.status < 200 or response.status >= 300:
                    return local_faq_response(message), False

                data = await response.json(content_type=None)

        choices = data.get("choices") if isinstance(data, dict) else None
        if not isinstance(choices, list) or not choices:
            return local_faq_response(message), False

        content = (
            choices[0].get("message", {}).get("content")
            if isinstance(choices[0], dict)
            else None
        )
        reply = str(content or "").strip()

        if not reply:
            return local_faq_response(message), False

        return reply[:3000], True

    except Exception:
        return local_faq_response(message), False
