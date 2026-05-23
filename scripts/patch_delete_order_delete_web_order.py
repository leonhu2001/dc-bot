from pathlib import Path
import re

BOT_PATH = Path("bot.py")
SYNC_PATH = Path("shared/web_order_sync.py")

bot_text = BOT_PATH.read_text(encoding="utf-8")
sync_text = SYNC_PATH.read_text(encoding="utf-8")

delete_func = r'''

def delete_web_order_by_ticket_channel(*, ticket_channel_id=None, dispatch_message_id=None) -> bool:
    """從網站資料庫刪除對應 web_order 與相關分潤/接單資料。

    用於 DC bot /delete_order：
    - 網站不保留 cancelled/deleted 訂單
    - 只保留 active / stored / closed
    """
    from sqlalchemy import text

    from shared.db import SessionLocal

    ticket_channel_id_text = _to_text_id(ticket_channel_id)
    dispatch_message_id_text = _to_text_id(dispatch_message_id)

    if not ticket_channel_id_text and not dispatch_message_id_text:
        return False

    db = SessionLocal()

    try:
        conditions = []
        params = {}

        if ticket_channel_id_text:
            conditions.append("ticket_channel_id = :ticket_channel_id")
            params["ticket_channel_id"] = ticket_channel_id_text

        if dispatch_message_id_text:
            conditions.append("dispatch_message_id = :dispatch_message_id")
            params["dispatch_message_id"] = dispatch_message_id_text

        sql = "SELECT id FROM web_orders WHERE " + " OR ".join(conditions) + " LIMIT 1"
        row = db.execute(text(sql), params).first()

        if row is None:
            db.commit()
            return False

        order_id = int(row[0])

        for table_name in (
            "worker_payouts",
            "customer_service_payouts",
            "order_assignments",
            "sync_events",
        ):
            db.execute(
                text(f"DELETE FROM {table_name} WHERE order_id = :order_id"),
                {"order_id": order_id},
            )

        db.execute(
            text("DELETE FROM web_orders WHERE id = :order_id"),
            {"order_id": order_id},
        )

        db.commit()
        return True

    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
'''

if "def delete_web_order_by_ticket_channel(" not in sync_text:
    sync_text = sync_text.rstrip() + delete_func + "\n"
    print("patched shared/web_order_sync.py delete_web_order_by_ticket_channel")
else:
    print("delete_web_order_by_ticket_channel already exists")

helper = r'''

def sync_web_order_deleted_from_bot(ticket_channel_id, dispatch_message_id=None, note: str | None = None) -> None:
    """DC bot 刪除訂單後，從網站資料庫直接刪除對應 web_order。"""
    try:
        from shared.web_order_sync import delete_web_order_by_ticket_channel

        ok = delete_web_order_by_ticket_channel(
            ticket_channel_id=ticket_channel_id,
            dispatch_message_id=dispatch_message_id,
        )

        print(
            f"[web-sync] delete web order "
            f"ticket_channel_id={ticket_channel_id} "
            f"dispatch_message_id={dispatch_message_id} ok={ok}"
        )
    except Exception as exc:
        print(
            f"[web-sync] 刪除網站訂單失敗 "
            f"ticket_channel_id={ticket_channel_id} "
            f"dispatch_message_id={dispatch_message_id}: {exc}"
        )
'''

if "def sync_web_order_deleted_from_bot(" not in bot_text:
    marker = "@bot.tree.command(\n    name=\"delete_order\""
    if marker not in bot_text:
        raise RuntimeError("找不到 delete_order command")

    bot_text = bot_text.replace(marker, helper + "\n\n" + marker, 1)
    print("inserted sync_web_order_deleted_from_bot helper")
else:
    print("sync_web_order_deleted_from_bot already exists")

# 把原本 cancelled 同步改成直接刪除網站訂單
bot_text = re.sub(
    r"""        sync_web_order_cancelled_from_bot\(
            ticket_channel_id=channel_id,
            dispatch_message_id=dispatch_message_id,
            note="由 /delete_order 刪除訂單同步。",
        \)

""",
    """        sync_web_order_deleted_from_bot(
            ticket_channel_id=channel_id,
            dispatch_message_id=dispatch_message_id,
            note="由 /delete_order 刪除網站訂單。",
        )

""",
    bot_text,
)

# 如果尚未插入過 delete sync，但有 delete_order 原始區塊，補在刪 bot.db 前
target = """        SELF_SERVICE_ORDER_SELECTIONS.pop(channel_id, None)
        delete_order_row_from_db(channel_id)
        save_bot_data()
"""

insert = """        sync_web_order_deleted_from_bot(
            ticket_channel_id=channel_id,
            dispatch_message_id=dispatch_message_id,
            note="由 /delete_order 刪除網站訂單。",
        )

        SELF_SERVICE_ORDER_SELECTIONS.pop(channel_id, None)
        delete_order_row_from_db(channel_id)
        save_bot_data()
"""

if "sync_web_order_deleted_from_bot(\n            ticket_channel_id=channel_id" not in bot_text:
    if target not in bot_text:
        raise RuntimeError("找不到 delete_order 刪除資料區塊")
    bot_text = bot_text.replace(target, insert, 1)
    print("patched delete_order to delete web order")
else:
    print("delete_order delete web sync already patched")

BOT_PATH.write_text(bot_text, encoding="utf-8")
SYNC_PATH.write_text(sync_text, encoding="utf-8")

print("done")
