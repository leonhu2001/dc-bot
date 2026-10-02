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


def _catalog_context() -> str:
    try:
        from services.orders import (
            ORDER_CATEGORY_LABELS,
            SELF_SERVICE_ORDER_CATALOG,
        )
    except Exception:
        return ""

    lines: list[str] = []

    for category_key, products in SELF_SERVICE_ORDER_CATALOG.items():
        category_label = str(
            ORDER_CATEGORY_LABELS.get(category_key)
            or category_key
        ).strip()

        product_lines: list[str] = []

        for product in products:
            product_label = str(product.get("label") or "").strip()
            if not product_label:
                continue

            detail_labels = [
                str(item.get("label") or "").strip()
                for item in (product.get("details") or [])
                if str(item.get("label") or "").strip()
            ]

            if detail_labels:
                product_lines.append(
                    f"{product_label}（{'、'.join(detail_labels[:12])}）"
                )
            else:
                product_lines.append(product_label)

        if product_lines:
            lines.append(
                f"- {category_label}："
                + "、".join(product_lines[:24])
            )

    return "\n".join(lines)[:6000]


def _official_knowledge() -> str:
    catalog = _catalog_context()

    rules = (
        "官方客服知識：\n"
        "- 所有訂單應透過官方網站或官方客服建立，禁止私單、跳單與私下交易。\n"
        "- 最新價格、活動價格、實際可下單規格一律以網站「立即下單」頁當下顯示為準。\n"
        "- 客服時間為 AM 10:00－AM 02:00。\n"
        "- 陪玩單以陪伴、互動及娛樂體驗為主，不包卡；技術表現不是一般陪玩單的客訴依據。\n"
        "- 護航單、趣味單與其他服務的細節規則，以網站「下單須知」及實際訂單內容為準。\n"
        "- 對訂單有疑慮，應於服務完成後 72 小時內聯絡客服。\n"
        "- 退款、付款異常、客訴、帳密、隱私、人工改金額、錢包調帳都必須轉真人處理。\n"
        "- 不可要求客人把帳號密碼、付款證明敏感內容直接提供給 AI。"
    )

    if catalog:
        rules += (
            "\n\n目前網站可選服務分類與品項名稱（不代表即時價格或庫存）：\n"
            + catalog
        )

    return rules


def _system_prompt() -> str:
    return (
        "你是魔丸娛樂網站客服助理。請使用繁體中文，回答簡潔、自然、友善。"
        "只根據下方官方客服知識與對話內容回答；不知道就直接說不確定，不要自行捏造價格、規則、"
        "折扣、可接人力、完成時間或退款結果。"
        "若客人詢問最新價格，請引導至網站「立即下單」查看即時價格。"
        "你可以回答一般服務內容、下單方式、VIP/點數、付款方式、接單流程、網站操作。"
        "如果問題涉及退款、付款異常、客訴、帳密、隱私、人工改金額、錢包調帳或需要人工判斷，"
        "請只告知需要轉真人客服，不要做財務承諾，也不要要求對方提供敏感資料。"
        "\n\n"
        + _official_knowledge()
    )


def _history_input(
    message: str,
    history: list[dict[str, Any]] | None,
) -> list[dict[str, str]]:
    items: list[dict[str, str]] = []

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

        items.append(
            {
                "role": role,
                "content": body[:2000],
            }
        )

    current = str(message or "").strip()[:2000]
    if not items or items[-1].get("content") != current:
        items.append(
            {
                "role": "user",
                "content": current,
            }
        )

    return items


def _extract_responses_text(data: Any) -> str:
    if not isinstance(data, dict):
        return ""

    direct = str(data.get("output_text") or "").strip()
    if direct:
        return direct

    chunks: list[str] = []

    for item in data.get("output") or []:
        if not isinstance(item, dict):
            continue
        if str(item.get("type") or "") != "message":
            continue

        for content in item.get("content") or []:
            if not isinstance(content, dict):
                continue
            if str(content.get("type") or "") != "output_text":
                continue

            text = str(content.get("text") or "").strip()
            if text:
                chunks.append(text)

    return "\n".join(chunks).strip()


def _extract_chat_completions_text(data: Any) -> str:
    if not isinstance(data, dict):
        return ""

    choices = data.get("choices")
    if not isinstance(choices, list) or not choices:
        return ""

    first = choices[0]
    if not isinstance(first, dict):
        return ""

    return str(
        first.get("message", {}).get("content")
        or ""
    ).strip()


async def generate_ai_response(
    message: str,
    *,
    history: list[dict[str, Any]] | None = None,
) -> tuple[str, bool]:
    """
    Returns (reply, used_external_ai).

    The default integration uses OpenAI's Responses API. A custom
    OpenAI-compatible Chat Completions endpoint can still be supplied through
    AI_SUPPORT_API_URL. If the provider is unavailable or unconfigured, the
    conservative local FAQ responder remains available.
    """
    api_url = str(config.AI_SUPPORT_API_URL or "").strip()
    api_key = str(config.AI_SUPPORT_API_KEY or "").strip()
    model = str(config.AI_SUPPORT_MODEL or "").strip()

    if not api_url or not api_key or not model:
        return local_faq_response(message), False

    input_items = _history_input(message, history)

    is_responses_api = api_url.rstrip("/").endswith("/responses")

    if is_responses_api:
        payload = {
            "model": model,
            "instructions": _system_prompt(),
            "input": input_items,
            "max_output_tokens": 500,
            "store": False,
        }
    else:
        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": _system_prompt()},
                *input_items,
            ],
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

        reply = (
            _extract_responses_text(data)
            if is_responses_api
            else _extract_chat_completions_text(data)
        )

        if not reply:
            return local_faq_response(message), False

        return reply[:3000], True

    except Exception:
        return local_faq_response(message), False

