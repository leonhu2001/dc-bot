from __future__ import annotations

import inspect

from services.custom_order_quick_entry import (
    _create_custom_order_request_ticket,
    _custom_order_intro_text,
    repair_existing_custom_order_ticket_controls,
)


def test_custom_order_intro_matches_normal_ticket_plain_text_style():
    text = _custom_order_intro_text(
        support_mention="<@&100>",
        member_mention="<@200>",
        level_name="白金魔丸",
        companion_count=3,
        game_or_service="三角洲端遊",
        gameplay_rules="自訂規則",
        goal_plan="測試目標",
        extra_request="晚上玩",
        customer_notes="VIP 客戶資訊",
    )

    assert text.startswith("<@&100> <@200> 自訂單票口已建立。")
    assert "陪玩人數：**3 位**" in text
    assert "遊戲／服務內容：三角洲端遊" in text
    assert "玩法／規則／機制：自訂規則" in text
    assert "方案／目標：測試目標" in text
    assert "其他需求：晚上玩" in text
    assert "需求確認階段" in text


def test_new_custom_order_ticket_does_not_send_intro_embed():
    source = inspect.getsource(_create_custom_order_request_ticket)
    assert "intro_text = _custom_order_intro_text(" in source
    assert "content=intro_text" in source
    assert "title=\"✨ 自訂單需求\"" not in source
    assert "embed=embed" not in source


def test_existing_custom_order_intro_embed_is_migrated_without_reping():
    source = inspect.getsource(repair_existing_custom_order_ticket_controls)
    assert "_message_has_custom_order_intro_embed(message)" in source
    assert "embed=None" in source
    assert "users=False" in source
    assert "roles=False" in source
