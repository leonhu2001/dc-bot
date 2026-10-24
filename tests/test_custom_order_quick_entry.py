from pathlib import Path
import inspect

from services.custom_order_quick_entry import (
    CUSTOM_ORDER_QUICK_CHANNEL_ID,
    CUSTOM_ORDER_RULE_KEY,
    CustomOrderCompanionCountSelect,
    CustomOrderQuickEntryView,
    _create_custom_order_request_ticket,
    _custom_order_detail,
    _send_custom_order_self_service_panel,
    build_custom_order_entry_embed,
    install_custom_order_quick_entry,
    is_custom_order_level_eligible,
    repair_existing_custom_order_ticket_controls,
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
    assert "1～4 位陪玩" in text
    assert "自助下單" in text
    assert "不會扣款或派單" in text


def test_custom_order_discord_runtime_does_not_recheck_vip_level():
    button_source = inspect.getsource(CustomOrderQuickEntryView.open_request)
    ticket_source = inspect.getsource(_create_custom_order_request_ticket)
    assert "assert_custom_order_eligible" not in button_source
    assert "assert_custom_order_eligible" not in ticket_source


def test_custom_order_headcount_select_exposes_one_to_four_people():
    select = CustomOrderCompanionCountSelect(123)
    assert [option.value for option in select.options] == ["1", "2", "3", "4"]
    assert [option.label for option in select.options] == [
        "1 位陪玩",
        "2 位陪玩",
        "3 位陪玩",
        "4 位陪玩",
    ]

    for count in range(1, 5):
        detail = _custom_order_detail(count)
        assert detail["rule_key"] == CUSTOM_ORDER_RULE_KEY
        assert detail["player_count"] == count


def test_custom_order_ticket_uses_normal_order_identity_staff_controls_and_self_service():
    source = inspect.getsource(_create_custom_order_request_ticket)
    assert "order_customer_id={member.id}" in source
    assert "custom_order_companion_count={count}" in source
    assert "view=_order_control_view(interaction.client)" in source
    assert "_send_custom_order_self_service_panel(" in source

    panel_source = inspect.getsource(_send_custom_order_self_service_panel)
    assert "SelfServiceOrderView" in panel_source
    assert "selected_category=CUSTOM_ORDER_CATEGORY" in panel_source


def test_existing_custom_order_tickets_are_repaired_idempotently_on_startup():
    repair_source = inspect.getsource(repair_existing_custom_order_ticket_controls)
    install_source = inspect.getsource(install_custom_order_quick_entry)
    assert '"custom_order_request=1"' in repair_source
    assert '"order_customer_id=" not in topic' in repair_source
    assert '"custom_order_companion_count=" not in topic' in repair_source
    assert "_message_has_order_controls(message)" in repair_source
    assert "_message_has_self_service_panel(message)" in repair_source
    assert "_send_custom_order_self_service_panel(" in repair_source
    assert "repair_existing_custom_order_ticket_controls(bot)" in install_source


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
