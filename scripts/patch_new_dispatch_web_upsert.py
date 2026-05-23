from pathlib import Path

path = Path("bot.py")
text = path.read_text(encoding="utf-8")

helper = r'''

def sync_web_order_active_from_dispatch_from_bot(
    *,
    ticket_channel_id,
    dispatch_channel_id,
    dispatch_message_id,
    customer_id,
    customer_display_name,
    category_label,
    item,
    quantity,
    amount,
    payment_method,
    customer_service_member=None,
    bot_order_no=None,
) -> None:
    """DC bot 新派單後，把 active 訂單寫進網站資料庫。"""
    try:
        from shared.web_order_sync import upsert_web_order_from_dispatch

        upsert_web_order_from_dispatch(
            ticket_channel_id=ticket_channel_id,
            dispatch_channel_id=dispatch_channel_id,
            dispatch_message_id=dispatch_message_id,
            customer_discord_id=customer_id,
            customer_display_name=customer_display_name,
            category=category_label,
            item=item,
            quantity=quantity,
            amount=amount,
            payment_method=payment_method,
            status="active",
            customer_service_discord_id=getattr(customer_service_member, "id", None),
            customer_service_display_name=getattr(customer_service_member, "display_name", None),
            bot_order_no=bot_order_no,
            note="由 DC bot 派單同步。",
        )

        print(
            f"[web-sync] dispatch upsert ok "
            f"ticket_channel_id={ticket_channel_id} "
            f"dispatch_message_id={dispatch_message_id}"
        )
    except Exception as exc:
        print(
            f"[web-sync] dispatch upsert failed "
            f"ticket_channel_id={ticket_channel_id} "
            f"dispatch_message_id={dispatch_message_id}: {exc}"
        )
'''

if "def sync_web_order_active_from_dispatch_from_bot(" not in text:
    marker = "class PaymentMethodSelect"
    if marker not in text:
        raise RuntimeError("找不到 class PaymentMethodSelect")
    text = text.replace(marker, helper + "\n\n" + marker, 1)
    print("inserted dispatch web sync helper")
else:
    print("helper already exists")

target = """    remember_order_data(interaction.channel.id, data)
    remember_claim_data(dispatch_message.id, ORDER_CLAIMS[dispatch_message.id])
"""

insert = """    remember_order_data(interaction.channel.id, data)
    remember_claim_data(dispatch_message.id, ORDER_CLAIMS[dispatch_message.id])

    customer_member = guild.get_member(customer_id) if customer_id is not None else None
    sync_web_order_active_from_dispatch_from_bot(
        ticket_channel_id=interaction.channel.id,
        dispatch_channel_id=dispatch_channel.id,
        dispatch_message_id=dispatch_message.id,
        customer_id=customer_id,
        customer_display_name=getattr(customer_member, "display_name", None) or str(customer_id),
        category_label=category_label,
        item=item,
        quantity=quantity,
        amount=parsed_amount,
        payment_method=payment_method,
        customer_service_member=interaction.user if isinstance(interaction.user, discord.Member) else None,
        bot_order_no=data.get("order_no"),
    )
"""

if insert not in text:
    if target not in text:
        raise RuntimeError("找不到派單後 remember_order_data / remember_claim_data 區塊")
    text = text.replace(target, insert, 1)
    print("patched new dispatch web upsert")
else:
    print("dispatch web upsert already patched")

path.write_text(text, encoding="utf-8")
print("done")
