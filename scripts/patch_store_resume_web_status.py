from pathlib import Path

path = Path("bot.py")
text = path.read_text(encoding="utf-8")

helper = r'''

def sync_web_order_status_from_bot(ticket_channel_id, status: str, dispatch_message_id=None, note: str | None = None) -> None:
    """DC bot 訂單狀態變更後，同步網站 web_orders.status。"""
    try:
        from shared.web_order_sync import update_web_order_status_by_ticket_channel

        ok = update_web_order_status_by_ticket_channel(
            ticket_channel_id=ticket_channel_id,
            status=status,
            dispatch_message_id=dispatch_message_id,
            note=note,
        )
        print(
            f"[web-sync] order status sync "
            f"ticket_channel_id={ticket_channel_id} "
            f"dispatch_message_id={dispatch_message_id} "
            f"status={status} ok={ok}"
        )
    except Exception as exc:
        print(
            f"[web-sync] 訂單狀態同步網站失敗 "
            f"ticket_channel_id={ticket_channel_id} "
            f"status={status}: {exc}"
        )
'''

if "def sync_web_order_status_from_bot(" not in text:
    marker = "async def store_dispatch_claim_panel"
    if marker not in text:
        raise RuntimeError("找不到 store_dispatch_claim_panel")
    text = text.replace(marker, helper + "\n\n" + marker, 1)
    print("inserted sync_web_order_status_from_bot helper")
else:
    print("helper already exists")


def patch_function(text: str, function_name: str, insert: str) -> str:
    start_marker = f"async def {function_name}"
    start = text.find(start_marker)

    if start == -1:
        raise RuntimeError(f"找不到 {function_name}")

    next_func = text.find("\nasync def ", start + len(start_marker))
    next_class = text.find("\nclass ", start + len(start_marker))

    candidates = [pos for pos in [next_func, next_class] if pos != -1]
    end = min(candidates) if candidates else len(text)

    block = text[start:end]

    if insert in block:
        print(f"{function_name} already patched")
        return text

    target = "    remember_order_data(order_channel.id, data)\n"

    idx = block.find(target)
    if idx == -1:
        raise RuntimeError(f"{function_name} 找不到 remember_order_data(order_channel.id, data)")

    insert_at = start + idx + len(target)
    print(f"patched {function_name}")
    return text[:insert_at] + insert + text[insert_at:]


store_insert = '''    sync_web_order_status_from_bot(
        ticket_channel_id=order_channel.id,
        status="stored",
        dispatch_message_id=dispatch_message_id,
        note="由 DC bot 存單同步。",
    )
'''

resume_insert = '''    sync_web_order_status_from_bot(
        ticket_channel_id=order_channel.id,
        status="active",
        dispatch_message_id=data.get("dispatch_message_id"),
        note="由 DC bot 恢復存單同步。",
    )
'''

text = patch_function(text, "store_dispatch_claim_panel", store_insert)
text = patch_function(text, "resume_stored_order", resume_insert)

path.write_text(text, encoding="utf-8")
print("done")
