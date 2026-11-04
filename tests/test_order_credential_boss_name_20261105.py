from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from services.order_credential_runtime import (
    _build_credential_delivery_embed,
    _credential_display_name,
    _order_requires_credentials,
)


def test_private_credential_dm_shows_boss_name_not_order_number():
    embed = _build_credential_delivery_embed(
        customer_display_name="大魔丸、zY（碎心又出小版）",
        account_value="example_account",
        password_value="example_password",
        note_value="Garena 登入",
    )
    fields = {field.name: field.value for field in embed.fields}
    assert fields["老闆"] == "大魔丸、zY（碎心又出小版）"
    assert "訂單" not in fields
    assert fields["登入帳號"] == "example_account"
    assert fields["登入密碼"] == "example_password"
    assert fields["登入方式／備註"] == "Garena 登入"
    assert embed.title == "🔐 魔丸娛樂｜臨時帳號授權"


def test_credential_boss_name_prefers_discord_server_nickname():
    member = SimpleNamespace(display_name="店內暱稱")
    guild = SimpleNamespace(get_member=lambda uid: member if uid == 456 else None)
    user = SimpleNamespace(display_name="Discord 顯示名稱")
    assert _credential_display_name(guild, user, 456) == "店內暱稱"
    assert _credential_display_name(None, user, 456) == "Discord 顯示名稱"
    assert _credential_display_name(None, None, 456) == "456"


def test_private_dm_has_searchable_boss_name_without_mention_spam():
    source = (
        Path(__file__).resolve().parents[1]
        / "services"
        / "order_credential_runtime.py"
    ).read_text(encoding="utf-8")
    assert 'content=f"老闆：{customer_display_name}"' in source
    assert "allowed_mentions=discord.AllowedMentions.none()" in source
    assert 'f"老闆：**{customer_display_name}**' in source
    assert 'credential_embed.add_field(name="訂單"' not in source


def test_private_dm_change_preserves_farm_and_internal_credential_flow():
    assert _order_requires_credentials({"category": "farm", "order_rule_key": "farm_halfcoin_120m"})
    for key in (
        "staff_internal_ammo_dump_500m",
        "staff_internal_car_500m",
        "staff_internal_aw_collision",
    ):
        assert _order_requires_credentials({"category": "staff_internal", "order_rule_key": key})
