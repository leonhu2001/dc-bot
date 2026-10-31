from __future__ import annotations

import inspect

from core.discord_settings import VIP_MONTHLY_ANNOUNCEMENT_CHANNEL_ID
from services import vip_review_runtime
from services.vip_monthly_announcement_policy import (
    NOVEMBER_2026_ANNOUNCEMENT_MESSAGE_ID,
    _reconcile_november_2026_message,
    build_vip_monthly_announcement_embed,
)


def _embed_text(month_key: str = "2026-11") -> str:
    embed = build_vip_monthly_announcement_embed(month_key)
    payload = embed.to_dict()
    fields = payload.get("fields") or []
    return "\n".join(
        [
            str(payload.get("title") or ""),
            str(payload.get("description") or ""),
            *[str(field.get("name") or "") for field in fields],
            *[str(field.get("value") or "") for field in fields],
            str((payload.get("footer") or {}).get("text") or ""),
        ]
    )


def test_current_monthly_announcement_matches_cash_entitlements() -> None:
    text = _embed_text()

    assert "白金魔丸：200T 折現券 ×1" in text
    assert "鑽石魔丸：200T 折現券 ×1" in text
    assert "白鑽魔丸：200T 折現券 ×1 + 500T 折現券 ×1" in text
    assert "黑鑽魔丸：200T 折現券 ×1 + 500T 折現券 ×1" in text
    assert "200T 折現券：原始服務金額滿 1,500T" in text
    assert "500T 折現券：原始服務金額滿 4,000T" in text


def test_announcement_does_not_expose_obsolete_monthly_rules() -> None:
    text = _embed_text()

    for obsolete in (
        "黑鑽尊享",
        "機密航天",
        "娛樂陪 2H",
        "二選一兌換",
        "最近 30 日",
        "近 30 日",
        "取消",
        "退役",
        "福利變少",
    ):
        assert obsolete not in text


def test_november_message_is_fixed_in_place_in_the_target_channel() -> None:
    assert VIP_MONTHLY_ANNOUNCEMENT_CHANNEL_ID == 1482083972031840257
    assert NOVEMBER_2026_ANNOUNCEMENT_MESSAGE_ID == 1566120120735236107

    source = inspect.getsource(_reconcile_november_2026_message)
    assert "fetch_message(NOVEMBER_2026_ANNOUNCEMENT_MESSAGE_ID)" in source
    assert "message.edit(embed=target_embed)" in source
    assert "channel.send" not in source


def test_future_monthly_announcements_use_current_policy_builder() -> None:
    source = inspect.getsource(vip_review_runtime._sync_monthly_benefits_and_announce)

    assert "build_vip_monthly_announcement_embed(month)" in source
    assert "AllowedMentions.none()" in source
