from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_member_portal_panel_is_compact_and_uses_icons():
    source = (ROOT / "views/member_portal.py").read_text(encoding="utf-8")

    assert 'title="👤 我的專區"' in source
    assert '"查詢訂單、錢包、點數 / VIP 與會員福利。\\n"' in source
    assert '"查詢結果僅自己可見。"' in source
    assert 'name="會員功能"' not in source
    assert 'name="官網完整專區"' not in source
    assert 'MEMBER_PORTAL_MARKER = "\\u200b"' in source

    for emoji in ("📋", "💰", "👑", "🎁", "🌐"):
        assert f'emoji="{emoji}"' in source

    assert 'label="網站專區"' in source
    assert "discord.ButtonStyle.link" in source
