from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from services.web_support_chat import (
    STATUS_AI,
    STATUS_CLOSED,
    STATUS_HUMAN,
    STATUS_WAITING_HUMAN,
    SENDER_AI,
    SENDER_CUSTOMER,
    SENDER_SYSTEM,
    add_message,
    bind_session_identity,
    create_session,
    get_session_by_token,
    list_messages,
    recent_customer_text,
    request_human,
)
from web.app.services.ai_support import (
    detect_handoff_reason,
    generate_ai_response,
)

router = APIRouter(prefix="/api/support-chat", tags=["web-support"])


class ChatMessagePayload(BaseModel):
    message: str = Field(min_length=1, max_length=2000)


def _identity(request: Request) -> tuple[str | None, str | None]:
    user = request.session.get("user") or {}
    discord_id = str(user.get("id") or "").strip() or None
    display_name = str(
        user.get("display_name")
        or user.get("global_name")
        or user.get("username")
        or ""
    ).strip() or None
    return discord_id, display_name


def _public_message(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": int(item.get("id") or 0),
        "sender_type": str(item.get("sender_type") or ""),
        "sender_display_name": str(item.get("sender_display_name") or ""),
        "body": str(item.get("body") or ""),
        "created_at": str(item.get("created_at") or ""),
    }


def _public_session(session: dict[str, Any]) -> dict[str, Any]:
    status = str(session.get("status") or STATUS_AI)
    return {
        "id": int(session.get("id") or 0),
        "status": status,
        "human_active": status in {STATUS_WAITING_HUMAN, STATUS_HUMAN},
        "waiting_human": status == STATUS_WAITING_HUMAN,
        "claimed_by": str(session.get("claimed_by_display_name") or ""),
    }


def _session_matches_identity(
    request: Request,
    session: dict[str, Any],
) -> bool:
    current_id, _ = _identity(request)
    stored_id = str(session.get("customer_discord_id") or "").strip() or None

    if stored_id is None:
        return True

    return current_id is not None and str(current_id) == stored_id


def _get_existing_session(request: Request) -> dict[str, Any]:
    token = str(request.session.get("web_support_token") or "").strip()
    session = get_session_by_token(token) if token else None
    if session is None or not _session_matches_identity(request, session):
        raise HTTPException(status_code=404, detail="客服對話尚未建立")
    return session


def _get_or_create_session(request: Request) -> dict[str, Any]:
    discord_id, display_name = _identity(request)
    token = str(request.session.get("web_support_token") or "").strip()
    session = get_session_by_token(token) if token else None

    if (
        session is None
        or str(session.get("status") or "") == STATUS_CLOSED
        or not _session_matches_identity(request, session)
    ):
        session = create_session(
            customer_discord_id=discord_id,
            customer_display_name=display_name,
        )
        request.session["web_support_token"] = session["public_token"]
    elif discord_id:
        bind_session_identity(
            int(session["id"]),
            customer_discord_id=discord_id,
            customer_display_name=display_name,
        )
        session = get_session_by_token(token) or session

    return session


@router.post("/bootstrap")
async def bootstrap_chat(request: Request):
    session = _get_or_create_session(request)
    messages = list_messages(int(session["id"]), limit=200)

    if not messages:
        greeting = add_message(
            int(session["id"]),
            sender_type=SENDER_AI,
            body=(
                "嗨，我是魔丸網站客服 👋\n"
                "我可以先協助下單、付款方式、VIP、服務內容與一般規則。"
                "如果你想找真人，直接輸入「轉接真人客服」即可。"
            ),
            sender_display_name="魔丸客服助理",
            metadata={"kind": "greeting"},
        )
        messages = [greeting]

    return {
        "ok": True,
        "session": _public_session(session),
        "messages": [_public_message(item) for item in messages],
    }


@router.get("/messages")
async def poll_messages(
    request: Request,
    after_id: int = 0,
):
    session = _get_existing_session(request)
    messages = list_messages(
        int(session["id"]),
        after_id=max(0, int(after_id or 0)),
        limit=200,
    )
    latest_session = get_session_by_token(
        str(request.session.get("web_support_token") or "")
    ) or session

    return {
        "ok": True,
        "session": _public_session(latest_session),
        "messages": [_public_message(item) for item in messages],
    }


@router.post("/messages")
async def send_message(
    request: Request,
    payload: ChatMessagePayload,
):
    session = _get_or_create_session(request)
    session_id = int(session["id"])
    status = str(session.get("status") or STATUS_AI)
    discord_id, display_name = _identity(request)

    message_text = str(payload.message or "").strip()
    if not message_text:
        raise HTTPException(status_code=400, detail="訊息不可為空白")

    customer_message = add_message(
        session_id,
        sender_type=SENDER_CUSTOMER,
        body=message_text,
        sender_discord_id=discord_id,
        sender_display_name=display_name or "網站訪客",
    )

    if status in {STATUS_WAITING_HUMAN, STATUS_HUMAN}:
        return {
            "ok": True,
            "session": _public_session(
                get_session_by_token(
                    str(request.session.get("web_support_token") or "")
                ) or session
            ),
            "messages": [_public_message(customer_message)],
        }

    handoff_reason = detect_handoff_reason(message_text)
    if handoff_reason:
        request_human(session_id, reason=handoff_reason)
        system_message = add_message(
            session_id,
            sender_type=SENDER_SYSTEM,
            body=(
                "已幫你通知真人客服。客服接手後會直接在這個視窗回覆，"
                "你不用另外重複送出。"
            ),
            sender_display_name="系統",
            metadata={"handoff_reason": handoff_reason},
        )
        updated = get_session_by_token(
            str(request.session.get("web_support_token") or "")
        ) or session
        return {
            "ok": True,
            "session": _public_session(updated),
            "messages": [
                _public_message(customer_message),
                _public_message(system_message),
            ],
        }

    history = recent_customer_text(session_id, limit=8)
    reply, used_external_ai = await generate_ai_response(
        message_text,
        history=history,
    )

    ai_message = add_message(
        session_id,
        sender_type=SENDER_AI,
        body=reply,
        sender_display_name="魔丸客服助理",
        metadata={"external_ai": bool(used_external_ai)},
    )

    return {
        "ok": True,
        "session": _public_session(session),
        "messages": [
            _public_message(customer_message),
            _public_message(ai_message),
        ],
    }


@router.post("/human")
async def request_human_support(request: Request):
    session = _get_or_create_session(request)
    session_id = int(session["id"])
    status = str(session.get("status") or STATUS_AI)

    if status == STATUS_CLOSED:
        raise HTTPException(status_code=409, detail="這段對話已結束")

    if status not in {STATUS_WAITING_HUMAN, STATUS_HUMAN}:
        request_human(session_id, reason="customer_clicked_human")
        add_message(
            session_id,
            sender_type=SENDER_SYSTEM,
            body=(
                "已幫你通知真人客服。客服接手後會直接在這個視窗回覆。"
            ),
            sender_display_name="系統",
            metadata={"handoff_reason": "customer_clicked_human"},
        )

    updated = get_session_by_token(
        str(request.session.get("web_support_token") or "")
    ) or session

    return {
        "ok": True,
        "session": _public_session(updated),
    }
