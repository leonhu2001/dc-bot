from types import SimpleNamespace

from services import orders


def test_customer_display_prefers_live_server_name():
    member = SimpleNamespace(
        display_name="阿Ru",
        global_name="aru-global",
        name="aru-user",
    )
    guild = SimpleNamespace(get_member=lambda user_id: member)
    channel = SimpleNamespace(id=9001, guild=guild)

    orders.configure_order_helpers({})

    assert (
        orders._resolve_guild_customer_display_name(
            channel,
            "<@123456789012345678>",
        )
        == "阿Ru"
    )


def test_customer_display_falls_back_to_saved_name_without_exposing_id():
    guild = SimpleNamespace(get_member=lambda user_id: None)
    channel = SimpleNamespace(id=9002, guild=guild)

    orders.configure_order_helpers(
        {
            9002: {
                "customer_display_name": "阿Ru",
            }
        }
    )

    assert (
        orders._resolve_guild_customer_display_name(
            channel,
            "<@123456789012345678>",
        )
        == "阿Ru"
    )


def test_customer_display_never_falls_back_to_raw_discord_id():
    guild = SimpleNamespace(get_member=lambda user_id: None)
    channel = SimpleNamespace(id=9003, guild=guild)

    orders.configure_order_helpers({})

    text = orders._resolve_guild_customer_display_name(
        channel,
        "<@123456789012345678>",
    )

    assert text == "未知顧客"
    assert "123456789012345678" not in text
