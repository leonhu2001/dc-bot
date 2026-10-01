from web.app.routers.admin_audit import _preferred_operator_name


def test_preferred_operator_name_uses_server_display_name_first():
    assert _preferred_operator_name(
        display_name="客服小丸",
        global_name="Global",
        username="user",
        discord_id="123",
    ) == "客服小丸"


def test_preferred_operator_name_falls_back_to_global_then_username_then_id():
    assert _preferred_operator_name(
        global_name="Global Name",
        username="user",
        discord_id="123",
    ) == "Global Name"

    assert _preferred_operator_name(
        username="user",
        discord_id="123",
    ) == "user"

    assert _preferred_operator_name(
        discord_id="123",
    ) == "123"
