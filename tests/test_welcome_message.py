from views.welcome import (
    PROFILE_CHANNEL_IDS,
    SUPPORT_CHANNEL_ID,
    build_welcome_description,
    build_welcome_embed,
    extract_welcome_member_mention,
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



def test_welcome_sections_are_visually_separated():
    description = build_welcome_description("<@123>")

    assert "歡迎加入我們 ฅ՞•ﻌ•՞ฅ\n\n👤 **挑選陪玩／打手**" in description
    assert "先看看大家的個人牆\n\n🎟️ **下單／客服**" in description
    assert "直接下單、詢問服務或尋求協助\n\n**祝你在魔丸玩得開心 🖤**" in description



def test_extract_welcome_member_mention_matches_old_and_new_copy():
    assert (
        extract_welcome_member_mention(
            "**歡迎 <@123> 來到魔丸娛樂!**\n\n歡迎闆闆光臨!"
        )
        == "<@123>"
    )
    assert (
        extract_welcome_member_mention(
            "🎉 **歡迎 <@!456> 來到魔丸娛樂！**\n\n歡迎加入我們"
        )
        == "<@!456>"
    )


def test_extract_welcome_member_mention_ignores_unrelated_messages():
    assert extract_welcome_member_mention("一般公告 <@123>") is None
    assert extract_welcome_member_mention(None) is None
