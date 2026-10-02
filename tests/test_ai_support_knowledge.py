from services import ai_support_knowledge, web_support_chat


def _message(
    db_path,
    session_id,
    sender_type,
    body,
    *,
    sender_discord_id=None,
    sender_display_name=None,
):
    return web_support_chat.add_message(
        session_id,
        sender_type=sender_type,
        body=body,
        sender_discord_id=sender_discord_id,
        sender_display_name=sender_display_name,
        db_file=db_path,
    )


def test_human_reply_becomes_pending_candidate_until_manager_approves(tmp_path):
    db_path = tmp_path / "web_dashboard.db"
    session = web_support_chat.create_session(db_file=db_path)

    question = _message(
        db_path,
        int(session["id"]),
        web_support_chat.SENDER_CUSTOMER,
        "第一次來三角洲，陪玩跟護航有什麼差別？",
    )
    answer = _message(
        db_path,
        int(session["id"]),
        web_support_chat.SENDER_STAFF,
        "陪玩偏互動娛樂；護航則依訂單內容提供對應服務。",
        sender_discord_id="999",
        sender_display_name="雞腿",
    )

    candidate = ai_support_knowledge.capture_learning_candidate(
        session_id=int(session["id"]),
        answer_message_id=int(answer["id"]),
        db_file=db_path,
    )

    assert candidate is not None
    assert candidate["question_message_id"] == question["id"]
    assert candidate["status"] == "pending"
    assert ai_support_knowledge.list_knowledge(db_file=db_path) == []

    knowledge = ai_support_knowledge.approve_candidate(
        int(candidate["id"]),
        question=candidate["question"],
        answer=candidate["answer"],
        reviewed_by_discord_id="1",
        reviewed_by_display_name="總管",
        db_file=db_path,
    )

    assert knowledge is not None
    assert knowledge["status"] == "active"

    matches = ai_support_knowledge.find_relevant_knowledge(
        "我想知道陪玩和護航差在哪",
        db_file=db_path,
    )

    assert [item["id"] for item in matches] == [knowledge["id"]]


def test_multiple_staff_messages_extend_same_pending_candidate(tmp_path):
    db_path = tmp_path / "web_dashboard.db"
    session = web_support_chat.create_session(db_file=db_path)

    _message(
        db_path,
        int(session["id"]),
        web_support_chat.SENDER_CUSTOMER,
        "你們客服時間是幾點？",
    )

    first = _message(
        db_path,
        int(session["id"]),
        web_support_chat.SENDER_STAFF,
        "客服時間是 AM 10:00 到 AM 02:00。",
        sender_discord_id="9",
        sender_display_name="客服A",
    )
    candidate = ai_support_knowledge.capture_learning_candidate(
        session_id=int(session["id"]),
        answer_message_id=int(first["id"]),
        db_file=db_path,
    )

    second = _message(
        db_path,
        int(session["id"]),
        web_support_chat.SENDER_STAFF,
        "如果有訂單問題也可以直接從網站轉真人。",
        sender_discord_id="9",
        sender_display_name="客服A",
    )
    updated = ai_support_knowledge.capture_learning_candidate(
        session_id=int(session["id"]),
        answer_message_id=int(second["id"]),
        db_file=db_path,
    )

    assert candidate is not None
    assert updated is not None
    assert updated["id"] == candidate["id"]
    assert "客服時間" in updated["answer"]
    assert "網站轉真人" in updated["answer"]


def test_attachments_are_not_copied_into_learning_candidate(tmp_path):
    db_path = tmp_path / "web_dashboard.db"
    session = web_support_chat.create_session(db_file=db_path)

    _message(
        db_path,
        int(session["id"]),
        web_support_chat.SENDER_CUSTOMER,
        "怎麼看訂單？",
    )
    staff = _message(
        db_path,
        int(session["id"]),
        web_support_chat.SENDER_STAFF,
        "到我的專區查看。\n[附件] https://example.com/private.png",
        sender_discord_id="9",
        sender_display_name="客服A",
    )

    candidate = ai_support_knowledge.capture_learning_candidate(
        session_id=int(session["id"]),
        answer_message_id=int(staff["id"]),
        db_file=db_path,
    )

    assert candidate is not None
    assert "我的專區" in candidate["answer"]
    assert "example.com" not in candidate["answer"]


def test_reject_does_not_create_knowledge(tmp_path):
    db_path = tmp_path / "web_dashboard.db"
    session = web_support_chat.create_session(db_file=db_path)

    _message(
        db_path,
        int(session["id"]),
        web_support_chat.SENDER_CUSTOMER,
        "這是單一客人的特殊處理嗎？",
    )
    staff = _message(
        db_path,
        int(session["id"]),
        web_support_chat.SENDER_STAFF,
        "這次個案另外處理。",
        sender_discord_id="9",
        sender_display_name="客服A",
    )

    candidate = ai_support_knowledge.capture_learning_candidate(
        session_id=int(session["id"]),
        answer_message_id=int(staff["id"]),
        db_file=db_path,
    )
    assert candidate is not None

    assert ai_support_knowledge.reject_candidate(
        int(candidate["id"]),
        reviewed_by_discord_id="1",
        reviewed_by_display_name="總管",
        db_file=db_path,
    )

    assert ai_support_knowledge.list_knowledge(db_file=db_path) == []


def test_archive_removes_knowledge_from_retrieval(tmp_path):
    db_path = tmp_path / "web_dashboard.db"

    knowledge = ai_support_knowledge.create_manual_knowledge(
        question="VIP 點數在哪裡看？",
        answer="登入 Discord 後到我的專區查看。",
        created_by_discord_id="1",
        created_by_display_name="總管",
        db_file=db_path,
    )

    assert ai_support_knowledge.find_relevant_knowledge(
        "VIP 點數",
        db_file=db_path,
    )

    assert ai_support_knowledge.archive_knowledge(
        int(knowledge["id"]),
        db_file=db_path,
    )

    assert ai_support_knowledge.find_relevant_knowledge(
        "VIP 點數",
        db_file=db_path,
    ) == []
