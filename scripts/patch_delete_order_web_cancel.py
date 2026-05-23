from pathlib import Path

path = Path("bot.py")
text = path.read_text(encoding="utf-8")

helper = r'''

def sync_web_order_cancelled_from_bot(ticket_channel_id, dispatch_message_id=None, note: str | None = None) -> None:
    """DC bot 刪除/取消訂單後，把網站訂單狀態同步成 cancelled。"""
    try:
        from shared.web_order_sync import update_web_order_status_by_ticket_channel

        ok = update_web_order_status_by_ticket_channel(
            ticket_channel_id=ticket_channel_id,
            status="cancelled",
            dispatch_message_id=dispatch_message_id,
            note=note or "由 DC bot 刪除/取消訂單同步。",
        )
        print(
            f"[web-sync] cancel order "
            f"ticket_channel_id={ticket_channel_id} "
            f"dispatch_message_id={dispatch_message_id} ok={ok}"
        )
    except Exception as exc:
        print(
            f"[web-sync] 刪除/取消訂單同步網站失敗 "
            f"ticket_channel_id={ticket_channel_id}: {exc}"
        )
'''

if "def sync_web_order_cancelled_from_bot(" not in text:
    marker = "@bot.tree.command(\n    name=\"delete_order\""
    if marker not in text:
        raise RuntimeError("找不到 delete_order command")
    text = text.replace(marker, helper + "\n\n" + marker, 1)
    print("inserted sync_web_order_cancelled_from_bot helper")
else:
    print("helper already exists")

target = """        SELF_SERVICE_ORDER_SELECTIONS.pop(channel_id, None)
        delete_order_row_from_db(channel_id)
        save_bot_data()
"""

insert = """        sync_web_order_cancelled_from_bot(
            ticket_channel_id=channel_id,
            dispatch_message_id=dispatch_message_id,
            note="由 /delete_order 刪除訂單同步。",
        )

        SELF_SERVICE_ORDER_SELECTIONS.pop(channel_id, None)
        delete_order_row_from_db(channel_id)
        save_bot_data()
"""

if insert not in text:
    if target not in text:
        raise RuntimeError("找不到 delete_order 刪除資料區塊")
    text = text.replace(target, insert, 1)
    print("patched delete_order web cancelled sync")
else:
    print("delete_order already patched")

path.write_text(text, encoding="utf-8")
print("done")
