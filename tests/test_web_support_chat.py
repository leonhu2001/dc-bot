import sqlite3

from services import web_support_chat
from web.app.services.ai_support import (
    _extract_chat_completions_text,
    _extract_responses_text,
    _history_input,
    _provider_error_summary,
    _response_usage,
    detect_handoff_reason,
    local_faq_response,
)


def test_web_support_session_lifecycle(tmp_path):
    db_path = tmp_path / "web_dashboard.db"

    session = web_support_chat.create_session(
        customer_discord_id="123",
        customer_display_name="測試客人",
        db_file=db_path,
    )

    assert session["status"] == web_support_chat.STATUS_AI
    assert session["customer_discord_id"] == "123"

    customer = web_support_chat.add_message(
        int(session["id"]),
        sender_type=web_support_chat.SENDER_CUSTOMER,
        sender_display_name="測試客人",
        body="我要真人客服",
        db_file=db_path,
    )

    assert customer["body"] == "我要真人客服"

    assert web_support_chat.request_human(
        int(session["id"]),
        reason="customer_requested_human",
        db_file=db_path,
    )

    pending = web_support_chat.list_pending_handoffs(
        db_file=db_path,
    )
    assert [item["id"] for item in pending] == [session["id"]]

    web_support_chat.set_discord_bridge(
        int(session["id"]),
        channel_id="10",
        thread_id="20",
        notification_message_id="30",
        db_file=db_path,
    )

    assert web_support_chat.claim_session(
        int(session["id"]),
        staff_discord_id="999",
        staff_display_name="客服小丸",
        db_file=db_path,
    )

    claimed = web_support_chat.get_session(
        int(session["id"]),
        db_file=db_path,
    )
    assert claimed["status"] == web_support_chat.STATUS_HUMAN
    assert claimed["claimed_by_display_name"] == "客服小丸"

    assert web_support_chat.close_session(
        int(session["id"]),
        db_file=db_path,
    )

    closed = web_support_chat.get_session(
        int(session["id"]),
        db_file=db_path,
    )
    assert closed["status"] == web_support_chat.STATUS_CLOSED


def test_customer_message_delivery_tracking(tmp_path):
    db_path = tmp_path / "web_dashboard.db"
    session = web_support_chat.create_session(db_file=db_path)

    message = web_support_chat.add_message(
        int(session["id"]),
        sender_type=web_support_chat.SENDER_CUSTOMER,
        body="網站訊息",
        db_file=db_path,
    )

    pending = web_support_chat.list_undelivered_customer_messages(
        int(session["id"]),
        db_file=db_path,
    )
    assert [item["id"] for item in pending] == [message["id"]]

    web_support_chat.mark_message_delivered_to_discord(
        int(message["id"]),
        discord_message_id="456",
        db_file=db_path,
    )

    assert web_support_chat.list_undelivered_customer_messages(
        int(session["id"]),
        db_file=db_path,
    ) == []

    with sqlite3.connect(db_path) as conn:
        row = conn.execute(
            """
            SELECT delivered_to_discord, discord_message_id
            FROM web_support_messages
            WHERE id = ?
            """,
            (int(message["id"]),),
        ).fetchone()

    assert row == (1, "456")


def test_handoff_detector_handles_human_and_sensitive_topics():
    assert detect_handoff_reason("我要轉接真人客服") == "customer_requested_human"
    assert detect_handoff_reason("付款異常可以幫我看嗎") == "sensitive_support_topic"
    assert detect_handoff_reason("VIP 有什麼功能") is None


def test_local_faq_does_not_invent_prices():
    reply = local_faq_response("這個多少錢")
    assert "立即下單" in reply
    assert "為準" in reply


def test_responses_api_output_parser():
    payload = {
        "output": [
            {
                "type": "message",
                "content": [
                    {
                        "type": "output_text",
                        "text": "您好，這是 AI 回覆。",
                    }
                ],
            }
        ]
    }

    assert _extract_responses_text(payload) == "您好，這是 AI 回覆。"


def test_chat_completions_output_parser_kept_for_custom_provider():
    payload = {
        "choices": [
            {
                "message": {
                    "content": "相容模式回覆",
                }
            }
        ]
    }

    assert _extract_chat_completions_text(payload) == "相容模式回覆"


def test_ai_history_only_keeps_customer_and_reply_context():
    history = [
        {"sender_type": "system", "body": "不要送進 AI"},
        {"sender_type": "customer", "body": "有 VIP 嗎"},
        {"sender_type": "ai", "body": "有會員制度"},
        {"sender_type": "staff", "body": "客服補充"},
    ]

    items = _history_input("怎麼下單", history)

    assert items == [
        {"role": "user", "content": "有 VIP 嗎"},
        {"role": "assistant", "content": "有會員制度"},
        {"role": "assistant", "content": "客服補充"},
        {"role": "user", "content": "怎麼下單"},
    ]


def test_provider_error_summary_does_not_need_raw_response_text():
    payload = {
        "error": {
            "code": "model_not_found",
            "message": "The requested model does not exist.",
        }
    }

    assert _provider_error_summary(payload) == (
        "model_not_found: The requested model does not exist."
    )


def test_response_usage_supports_responses_api_shape():
    payload = {
        "usage": {
            "input_tokens": 123,
            "output_tokens": 45,
            "total_tokens": 168,
        }
    }

    assert _response_usage(payload) == (123, 45, 168)
