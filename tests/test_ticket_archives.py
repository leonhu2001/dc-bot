from pathlib import Path

from services.ticket_archives import (
    get_ticket_archive,
    list_ticket_archives,
    save_ticket_archive,
)


def test_ticket_archive_round_trip_and_search(tmp_path: Path):
    db_file = tmp_path / "archive.db"

    archive_id = save_ticket_archive(
        ticket_channel_id="12345",
        ticket_channel_name="已結單-測試老闆-0926",
        order_id=88,
        order_no="MW-88",
        customer_discord_id="100",
        customer_display_name="測試老闆",
        customer_service_discord_id="200",
        customer_service_display_name="客服A",
        closed_by_discord_id="200",
        closed_by_display_name="客服A",
        closed_at="2026-09-26T21:00:00+08:00",
        archived_at="2026-09-26T21:00:01+08:00",
        messages=[
            {
                "discord_message_id": "1",
                "author_discord_id": "100",
                "author_display_name": "測試老闆",
                "author_is_bot": False,
                "content": "我想查一下這張單",
                "attachments": [],
                "embeds": [],
                "reply_to_message_id": "",
                "created_at": "2026-09-26T20:55:00+08:00",
                "edited_at": "",
            },
            {
                "discord_message_id": "2",
                "author_discord_id": "200",
                "author_display_name": "客服A",
                "author_is_bot": False,
                "content": "好的，我幫你確認",
                "attachments": [
                    {
                        "filename": "proof.png",
                        "url": "https://cdn.discordapp.com/attachments/proof.png",
                    }
                ],
                "embeds": [],
                "reply_to_message_id": "1",
                "created_at": "2026-09-26T20:56:00+08:00",
                "edited_at": "",
            },
        ],
        db_file=db_file,
    )

    bundle = get_ticket_archive(archive_id, db_file=db_file)
    assert bundle is not None
    assert bundle["archive"]["customer_display_name"] == "測試老闆"
    assert bundle["archive"]["customer_discord_id"] == "100"
    assert bundle["archive"]["customer_service_display_name"] == "客服A"
    assert bundle["archive"]["customer_service_discord_id"] == "200"
    assert bundle["archive"]["message_count"] == 2
    assert bundle["messages"][0]["content"] == "我想查一下這張單"
    assert bundle["messages"][1]["attachments"][0]["filename"] == "proof.png"

    by_customer = list_ticket_archives(
        search="測試老闆",
        db_file=db_file,
    )
    assert [row["id"] for row in by_customer] == [archive_id]

    by_message = list_ticket_archives(
        search="幫你確認",
        db_file=db_file,
    )
    assert [row["id"] for row in by_message] == [archive_id]
