from pathlib import Path


def test_close_path_finalizes_claim_before_discord_fetch():
    root = Path(__file__).resolve().parents[1]
    source = (root / "services" / "order_runtime.py").read_text(
        encoding="utf-8"
    )

    start = source.index("async def lock_dispatch_claim_panel")
    end = source.index(
        "def sync_web_order_status_from_bot",
        start,
    )
    block = source[start:end]

    finalize_index = block.index(
        "remember_claim_data(dispatch_message_id, claim_data)"
    )
    fetch_index = block.index(
        "message = await dispatch_channel.fetch_message(dispatch_message_id)"
    )

    assert finalize_index < fetch_index
    assert "if not isinstance(dispatch_channel, discord.TextChannel):" in block
