from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BOT_PATH = ROOT / "bot.py"

HELPER = r'''

def sync_cancelled_order_to_web_dashboard_by_channel_id(
    *,
    order_channel_id: int | str | None,
    dispatch_message_id: int | str | None = None,
    note: str | None = None,
) -> None:
    """把取消 / 刪除票口同步到網站，避免 /admin 留下 active 殭屍訂單。"""
    if order_channel_id is None:
        return

    try:
        update_web_order_status_by_ticket_channel(
            ticket_channel_id=order_channel_id,
            status="cancelled",
            dispatch_message_id=dispatch_message_id,
            note=note or "由 DC bot 取消訂單同步。",
        )
    except Exception as e:
        print(f"同步取消訂單到網站資料庫失敗：{e}")
'''

DELETE_SYNC_SNIPPET = r'''    sync_cancelled_order_to_web_dashboard_by_channel_id(
        order_channel_id=order_channel_id,
        dispatch_message_id=dispatch_message_id,
        note="由 DC bot 取消訂單同步。",
    )

'''

CHANNEL_DELETE_SNIPPET = r'''    if isinstance(channel, discord.TextChannel):
        dispatch_message_id = None
        data = SELF_SERVICE_ORDER_SELECTIONS.get(channel.id, {})

        if isinstance(data, dict):
            dispatch_message_id = data.get("dispatch_message_id")

        sync_cancelled_order_to_web_dashboard_by_channel_id(
            order_channel_id=channel.id,
            dispatch_message_id=dispatch_message_id,
            note="票口頻道被刪除，自動同步取消。",
        )

'''


def patch_bot() -> None:
    text = BOT_PATH.read_text(encoding="utf-8")
    changed = False

    if "def sync_cancelled_order_to_web_dashboard_by_channel_id" not in text:
        marker = "def cleanup_old_closed_orders() -> None:"
        if marker not in text:
            raise RuntimeError("找不到 cleanup_old_closed_orders，無法插入取消同步 helper。")
        text = text.replace(marker, HELPER + "\n" + marker, 1)
        changed = True

    if "note=\"由 DC bot 取消訂單同步。\"" not in text:
        marker = "    if dispatch_message_id is not None:\n"
        func_marker = "async def delete_dispatch_claim_panel_for_order"
        func_pos = text.find(func_marker)
        if func_pos == -1:
            raise RuntimeError("找不到 delete_dispatch_claim_panel_for_order。")
        marker_pos = text.find(marker, func_pos)
        if marker_pos == -1:
            raise RuntimeError("找不到 delete_dispatch_claim_panel_for_order 裡的 dispatch_message_id 判斷。")
        text = text[:marker_pos] + DELETE_SYNC_SNIPPET + text[marker_pos:]
        changed = True

    if "票口頻道被刪除，自動同步取消。" not in text:
        old = '''@bot.event
async def on_guild_channel_delete(channel: discord.abc.GuildChannel):
    # 如果入職票口被手動刪除，也嘗試收回申請人暫時身分組。
    await remove_recruit_applicant_role(channel.guild, channel)
'''
        new = '''@bot.event
async def on_guild_channel_delete(channel: discord.abc.GuildChannel):
    # 如果入職票口被手動刪除，也嘗試收回申請人暫時身分組。
    await remove_recruit_applicant_role(channel.guild, channel)

''' + CHANNEL_DELETE_SNIPPET.rstrip() + "\n"
        if old not in text:
            raise RuntimeError("找不到 on_guild_channel_delete 的原始區塊，無法套用手動刪頻道同步。")
        text = text.replace(old, new, 1)
        changed = True

    if changed:
        BOT_PATH.write_text(text, encoding="utf-8")
        print("patched bot.py cancel sync")
    else:
        print("bot.py already patched")


if __name__ == "__main__":
    patch_bot()
