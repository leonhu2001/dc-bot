from pathlib import Path
import inspect

from services.custom_order_quick_entry import (
    CUSTOM_ORDER_QUICK_CHANNEL_ID,
    CustomOrderQuickEntryView,
    _create_custom_order_request_ticket,
    build_custom_order_entry_embed,
    is_custom_order_level_eligible,
)


def test_custom_order_quick_entry_uses_owner_channel():
    assert CUSTOM_ORDER_QUICK_CHANNEL_ID == 1563459313635168256


def test_custom_order_policy_still_describes_gold_entitlement():
    assert not is_custom_order_level_eligible("普通魔丸")
    assert not is_custom_order_level_eligible("銀級魔丸")
    assert is_custom_order_level_eligible("金級魔丸")
    assert is_custom_order_level_eligible("白金魔丸")
    assert is_custom_order_level_eligible("鑽石魔丸")
    assert is_custom_order_level_eligible("白鑽魔丸")
    assert is_custom_order_level_eligible("黑鑽魔丸")


def test_custom_order_discord_panel_relies_on_channel_access():
    embed = build_custom_order_entry_embed()
    text = f"{embed.title}\n{embed.description}"
    assert "金級會員以上" not in text
    assert "此專屬頻道可直接提出" in text
    assert "客服確認內容與價格後" in text
    assert "不會扣款或派單" in text


def test_custom_order_discord_runtime_does_not_recheck_vip_level():
    button_source = inspect.getsource(CustomOrderQuickEntryView.open_request)
    ticket_source = inspect.getsource(_create_custom_order_request_ticket)
    assert "assert_custom_order_eligible" not in button_source
    assert "assert_custom_order_eligible" not in ticket_source


def test_custom_order_ticket_uses_normal_order_identity_and_staff_controls():
    source = inspect.getsource(_create_custom_order_request_ticket)
    assert "order_customer_id={member.id}" in source
    assert "view=_order_control_view(interaction.client)" in source


def test_custom_order_persistent_view_has_stable_open_button():
    view = CustomOrderQuickEntryView()
    buttons = [item for item in view.children if getattr(item, "custom_id", None)]
    assert [item.custom_id for item in buttons] == ["custom_order_quick_entry:open"]
    assert view.timeout is None


def test_setup_installs_custom_order_and_discord_vip_access():
    source = (
        Path(__file__).resolve().parents[1] / "cogs" / "setup_commands.py"
    ).read_text(encoding="utf-8")
    assert "from services.custom_order_quick_entry import install_custom_order_quick_entry" in source
    assert "install_custom_order_quick_entry(bot)" in source
    assert "from services.discord_vip_channel_access import install_discord_vip_channel_access" in source
    assert "install_discord_vip_channel_access()" in source


def test_vip_timer_discord_access_policy_keeps_duplicate_guard_but_not_level_gate():
    source = (
        Path(__file__).resolve().parents[1]
        / "services"
        / "discord_vip_channel_access.py"
    ).read_text(encoding="utf-8")
    assert "has_open_vip_timer" in source
    assert "_customer_vip_name" not in source
    assert "quick.assert_vip_timer_self_service_eligible = discord_timer_access" in source
    assert ".replace(\"白金級會員以上限定。\", \"\")" in source
    assert ".replace(\"金級會員以上限定。\", \"\")" in source
