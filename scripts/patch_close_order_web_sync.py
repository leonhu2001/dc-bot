from pathlib import Path

path = Path("bot.py")
text = path.read_text(encoding="utf-8")

helper = r'''

def sync_web_order_closed_from_bot(ticket_channel_id, dispatch_message_id=None) -> None:
    """DC bot 結單後，把網站訂單狀態同步成 closed。"""
    try:
        from shared.web_order_sync import update_web_order_status_by_ticket_channel

        ok = update_web_order_status_by_ticket_channel(
            ticket_channel_id=ticket_channel_id,
            status="closed",
            dispatch_message_id=dispatch_message_id,
            note="由 DC bot 結單同步。",
        )
        print(f"[web-sync] close order ticket_channel_id={ticket_channel_id} dispatch_message_id={dispatch_message_id} ok={ok}")
    except Exception as exc:
        print(f"[web-sync] 結單同步網站失敗 ticket_channel_id={ticket_channel_id}: {exc}")
'''

if "def sync_web_order_closed_from_bot(" not in text:
    marker = "# ========= 收據 Modal ========="
    if marker not in text:
        raise RuntimeError("找不到收據 Modal 區塊")
    text = text.replace(marker, helper + "\n\n" + marker, 1)
    print("inserted sync_web_order_closed_from_bot helper")
else:
    print("helper already exists")

target = """        remember_order_data(order_channel.id, order_data)
"""

insert = """        remember_order_data(order_channel.id, order_data)
        sync_web_order_closed_from_bot(
            ticket_channel_id=order_channel.id,
            dispatch_message_id=order_data.get("dispatch_message_id"),
        )
"""

if insert not in text:
    if target not in text:
        raise RuntimeError("找不到 remember_order_data(order_channel.id, order_data)")
    text = text.replace(target, insert, 1)
    print("patched receipt close sync")
else:
    print("receipt close sync already patched")

path.write_text(text, encoding="utf-8")
print("done")
