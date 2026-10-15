from pathlib import Path


PATH = Path("services/self_service_runtime.py")
text = PATH.read_text(encoding="utf-8")
original = text

if (
    'data["provisional_dispatch_message_id"] = dispatch_message.id' in text
    and "cleanup_failed_self_service_dispatch(" in text
):
    print("self_service_runtime.py already patched")
    raise SystemExit(0)


def replace_once(old: str, new: str) -> None:
    global text
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"expected one match, found {count}: {old[:80]!r}")
    text = text.replace(old, new, 1)


# 1. Stable rollback helper is owned by its service module, not bot.py globals.
import_anchor = '''from services.self_service_retract import (
    SelfServiceDispatchedView,
    retract_self_service_dispatch,
)
'''
replace_once(
    import_anchor,
    import_anchor
    + '''from services.self_service_dispatch_cleanup import cleanup_failed_self_service_dispatch
''',
)
replace_once(
    '        "retract_self_service_dispatch",\n',
    '        "retract_self_service_dispatch",\n        "cleanup_failed_self_service_dispatch",\n',
)

# 2. Publish an inert provisional message. It must not expose claim buttons or
#    notify candidates until the canonical WebOrder + acceptance metadata exist.
start = text.index("    dispatch_message = await dispatch_channel.send(\n")
end_marker = "    web_note_parts = []\n"
end = text.index(end_marker, start)
provisional_block = '''    dispatch_message = await dispatch_channel.send(
        content=None,
        embed=embed,
        view=None,
        allowed_mentions=discord.AllowedMentions(
            users=True,
            roles=True,
            everyone=False,
        ),
    )

    data["provisional_dispatch_message_id"] = dispatch_message.id
    data["provisional_dispatch_channel_id"] = dispatch_channel.id
    remember_order_data(interaction.channel.id, data)

'''
text = text[:start] + provisional_block + text[end:]

# 3. Only unlock the claim panel and send smart-dispatch alerts after all
#    canonical order data and local runtime state have been persisted.
persist_anchor = '''    remember_order_data(interaction.channel.id, data)
    remember_claim_data(dispatch_message.id, ORDER_CLAIMS[dispatch_message.id])
    save_bot_data()

'''
unlock_block = persist_anchor + '''    try:
        await dispatch_message.edit(
            view=DispatchClaimView(
                customer_id=customer_id,
                category_label=category_label,
                item=rule.label,
                quantity=quantity,
                payment_method="待付款",
                source_channel_id=interaction.channel.id,
                companion_preference=companion_preference,
                locked=False,
                status=WAITING_ACCEPTANCE,
            ),
            allowed_mentions=discord.AllowedMentions(
                users=True,
                roles=True,
                everyone=False,
            ),
        )
    except (discord.Forbidden, discord.HTTPException) as exc:
        raise RuntimeError("派單訊息建立完成，但接單 Panel 啟用失敗。") from exc

    data.pop("provisional_dispatch_message_id", None)
    data.pop("provisional_dispatch_channel_id", None)
    remember_order_data(interaction.channel.id, data)
    save_bot_data()

    try:
        await send_initial_smart_dispatch_alert(
            guild,
            content=smart_dispatch["content"],
            dispatch_jump_url=dispatch_message.jump_url,
        )
    except (discord.Forbidden, discord.HTTPException) as exc:
        print(f"[smart-dispatch] initial alert failed: {exc}", flush=True)

'''
replace_once(persist_anchor, unlock_block)

# 4. Logging is non-transactional. A log outage must never roll back a fully
#    canonical and already-unlocked order.
log_start_marker = '''    await send_order_log(
        guild,
        title="新自助下單｜等待接單",
'''
log_start = text.index(log_start_marker)
return_marker = '    return f"已送出等待接單：{dispatch_message.jump_url}"\n'
return_pos = text.index(return_marker, log_start)
log_block = '''    try:
        await send_order_log(
            guild,
            title="新自助下單｜等待接單",
            fields=[
                ("顧客", f"<@{customer_id}>", True),
                ("訂單類別", category_label, True),
                ("訂單項目", rule.label, True),
                ("數量", f"{quantity} {get_self_service_quantity_unit(rule.label)}", True),
                ("訂單總價", _format_plain_amount(amount), True),
                ("接單需求", f"{required_staff_count} 位", True),
                ("票口", interaction.channel.mention, False),
                ("派單訊息", dispatch_message.jump_url, False),
            ],
            color=discord.Color.blue(),
        )
    except Exception as exc:
        print(
            f"[self-service-dispatch] order log failed channel_id={channel_id}: "
            f"{type(exc).__name__}: {exc}",
            flush=True,
        )

    try:
        await log_self_service_proxy_action(
            interaction,
            customer_id,
            "送出等待接單",
            f"{category_label}｜{rule.label}｜{quantity} {get_self_service_quantity_unit(rule.label)}｜{_format_plain_amount(amount)}",
        )
    except Exception as exc:
        print(
            f"[self-service-dispatch] proxy log failed channel_id={channel_id}: "
            f"{type(exc).__name__}: {exc}",
            flush=True,
        )

'''
text = text[:log_start] + log_block + text[return_pos:]

# 5. If any canonical creation step fails before unlock, roll back the website
#    order/reservations and provisional Discord message while preserving the draft.
except_start_marker = '''        except Exception as exc:
            print(
                f"[acceptance] 備註後建立 waiting_acceptance 自助單失敗 "
'''
except_start = text.index(except_start_marker)
except_end_marker = '''            await interaction.followup.send("送出等待接單失敗，請通知客服確認後台紀錄。", ephemeral=True)
            return
'''
except_end = text.index(except_end_marker, except_start) + len(except_end_marker)
replacement = '''        except Exception as exc:
            failed_data = SELF_SERVICE_ORDER_SELECTIONS.setdefault(self.channel_id, {})
            cleanup_warnings = await cleanup_failed_self_service_dispatch(
                interaction,
                channel_id=self.channel_id,
                data=failed_data,
                order_claims=ORDER_CLAIMS,
                default_dispatch_channel_id=DISPATCH_CHANNEL_ID,
                remember_order=remember_order_data,
                save_data=save_bot_data,
                delete_claim_row=delete_claim_row_from_db,
            )
            print(
                f"[acceptance] 備註後建立 waiting_acceptance 自助單失敗 "
                f"channel_id={self.channel_id}: {type(exc).__name__}: {exc}",
                flush=True,
            )
            warning_text = ""
            if cleanup_warnings:
                warning_text = "\\n⚠️ " + "；".join(cleanup_warnings)
            await interaction.followup.send(
                "送出等待接單失敗；本次派單已回滾，原本填好的草稿仍保留，可以修正後重新送出。"
                + warning_text,
                ephemeral=True,
            )
            return
'''
text = text[:except_start] + replacement + text[except_end:]

# Guard against accidentally leaving the old early alert in the create path.
create_start = text.index("async def create_waiting_acceptance_order_from_self_service(")
create_end = text.index("async def retract_waiting_acceptance_order_from_self_service(", create_start)
create_source = text[create_start:create_end]
if create_source.count("send_initial_smart_dispatch_alert(") != 1:
    raise RuntimeError("self-service create path must contain exactly one smart-dispatch alert")
if create_source.index("upsert_web_order_from_dispatch(") > create_source.index("dispatch_message.edit("):
    raise RuntimeError("dispatch panel unlock must happen after canonical WebOrder creation")
if create_source.index("create_or_update_acceptance_meta(") > create_source.index("dispatch_message.edit("):
    raise RuntimeError("dispatch panel unlock must happen after acceptance metadata creation")
if create_source.index("dispatch_message.edit(") > create_source.index("send_initial_smart_dispatch_alert("):
    raise RuntimeError("candidate alerts must happen after claim panel unlock")

if text == original:
    raise RuntimeError("patch produced no changes")

PATH.write_text(text, encoding="utf-8")
print("patched self_service_runtime.py")
