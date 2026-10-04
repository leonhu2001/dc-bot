from views.welcome import (
    PROFILE_CHANNEL_IDS,
    SUPPORT_CHANNEL_ID,
    build_welcome_description,
    build_welcome_embed,
)


def test_welcome_copy_routes_to_profiles_and_support():
    description = build_welcome_description("<@123>")

    assert "🎉 **歡迎 <@123> 來到魔丸娛樂！**" in description
    assert f"<#{PROFILE_CHANNEL_IDS[0]}>" in description
    assert f"<#{PROFILE_CHANNEL_IDS[1]}>" in description
    assert f"<#{SUPPORT_CHANNEL_ID}>" in description
    assert "祝你在魔丸玩得開心" in description


def test_welcome_embed_keeps_member_avatar():
    embed = build_welcome_embed(
        "<@123>",
        avatar_url="https://example.com/avatar.png",
    )

    assert embed.description == build_welcome_description("<@123>")
    assert embed.thumbnail.url == "https://example.com/avatar.png"
