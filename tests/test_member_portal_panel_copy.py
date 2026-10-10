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
    assert 'label="我的錢包"' in source
    assert "discord.ButtonStyle.link" in source


def test_member_portal_detail_embeds_are_result_first_and_use_link_buttons():
    source = (ROOT / "views/member_portal.py").read_text(encoding="utf-8")

    assert 'name="訂單摘要"' in source
    assert 'name="最近 5 筆"' in source
    assert '_link_view("查看完整訂單"' in source
    assert '_link_view("查看錢包紀錄"' in source
    assert '_link_view("查看 VIP 專區"' in source
    assert '_link_view("查看我的福利"' in source
    assert 'value="請使用 Discord 的儲值中心。"' in source
    assert 'value="尚未開始累積。\\n完成符合活動的付費服務後才會顯示。"' in source

    # The detail responses should use buttons instead of exposing raw URL fields.
    assert 'name="完整紀錄"' not in source
    assert 'name="完整專區"' not in source
    assert 'name="官網"' not in source
