from pathlib import Path

from services.custom_order_quick_entry import (
    CUSTOM_ORDER_QUICK_CHANNEL_ID,
    CustomOrderQuickEntryView,
    build_custom_order_entry_embed,
    is_custom_order_level_eligible,
)


def test_custom_order_quick_entry_uses_owner_channel():
    assert CUSTOM_ORDER_QUICK_CHANNEL_ID == 1563459313635168256


def test_custom_order_is_gold_or_above_but_not_silver():
    assert not is_custom_order_level_eligible("普通魔丸")
    assert not is_custom_order_level_eligible("銀級魔丸")
    assert is_custom_order_level_eligible("金級魔丸")
    assert is_custom_order_level_eligible("白金魔丸")
    assert is_custom_order_level_eligible("鑽石魔丸")
    assert is_custom_order_level_eligible("白鑽魔丸")
    assert is_custom_order_level_eligible("黑鑽魔丸")


def test_custom_order_panel_does_not_pretend_request_is_a_paid_order():
    embed = build_custom_order_entry_embed()
    text = f"{embed.title}\n{embed.description}"
    assert "金級會員以上" in text
    assert "客服確認內容與價格後" in text
    assert "不會扣款或派單" in text


def test_custom_order_persistent_view_has_stable_open_button():
    view = CustomOrderQuickEntryView()
    buttons = [item for item in view.children if getattr(item, "custom_id", None)]
    assert [item.custom_id for item in buttons] == ["custom_order_quick_entry:open"]
    assert view.timeout is None


def test_setup_installs_custom_order_quick_entry():
    source = (
        Path(__file__).resolve().parents[1] / "cogs" / "setup_commands.py"
    ).read_text(encoding="utf-8")
    assert "from services.custom_order_quick_entry import install_custom_order_quick_entry" in source
    assert "install_custom_order_quick_entry(bot)" in source


def test_vip_timer_quick_order_copy_stays_platinum_or_above():
    from services import quick_order_v2 as quick
    from services import quick_order_v2_production as production

    embed = production._clean_entry_embed(
        quick.QUICK_ORDER_V2_CHANNELS["vip_timer"]
    )
    first_line = str(embed.description or "").splitlines()[0]
    assert first_line == "白金級會員以上限定。"
