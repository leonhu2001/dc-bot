from __future__ import annotations

from typing import Awaitable, Callable

import discord


async def revoke_order_credential_messages(
    order_id: int,
    *,
    reason: str,
    ticket_channel: discord.TextChannel | None = None,
    notify_customer: bool = True,
    to_int: Callable[..., int | None],
    resolve_user: Callable[[discord.Guild | None, int], Awaitable[discord.Member | discord.User | None]],
    fallback_guild: discord.Guild | None,
    taipei_now_iso: Callable[[], str],
) -> dict:
    """Revoke credential DMs and optionally notify the customer.

    Credential contents are never persisted here. This service only operates on
    non-secret delivery metadata and Discord message IDs recorded by the order
    credential flow.
    """
    from services.order_credentials import (
        get_order_context,
        list_active_deliveries,
        mark_delivery_revoked,
    )

    deliveries = list_active_deliveries(int(order_id))
    context = get_order_context(int(order_id)) or {}
    guild = ticket_channel.guild if ticket_channel is not None else fallback_guild

    deleted_count = 0
    failed_count = 0
    recipient_lines: list[str] = []

    for delivery in deliveries:
        recipient_id = to_int(delivery.get("recipient_discord_id"))
        message_id = to_int(delivery.get("dm_message_id"))
        recipient_type = str(delivery.get("recipient_type") or "recipient")
        recipient_name = str(
            delivery.get("recipient_display_name")
            or delivery.get("recipient_discord_id")
            or "未知"
        )

        label = "店長" if recipient_type == "owner" else "接單人員"
        recipient_lines.append(f"・{label}：{recipient_name}")

        if recipient_id is None or message_id is None:
            mark_delivery_revoked(
                int(delivery["id"]),
                status="metadata_missing",
                reason=reason,
            )
            deleted_count += 1
            continue

        user = await resolve_user(guild, int(recipient_id))
        if user is None:
            failed_count += 1
            continue

        try:
            dm_channel = getattr(user, "dm_channel", None)
            if dm_channel is None:
                dm_channel = await user.create_dm()

            try:
                message = await dm_channel.fetch_message(int(message_id))
                await message.delete()
                revoke_status = "deleted"
            except discord.NotFound:
                revoke_status = "already_missing"

            mark_delivery_revoked(
                int(delivery["id"]),
                status=revoke_status,
                reason=reason,
            )
            deleted_count += 1
        except (discord.Forbidden, discord.HTTPException):
            failed_count += 1
        except Exception:
            failed_count += 1

    if notify_customer and deliveries:
        customer_id = to_int(context.get("customer_discord_id"))
        order_no = str(context.get("bot_order_no") or f"WEB-{order_id}")
        unique_recipient_lines = list(dict.fromkeys(recipient_lines))

        if failed_count == 0:
            body = (
                f"✅ **帳號資料已銷毀**\n"
                f"訂單：**{order_no}**\n\n"
                "系統已撤回所有由魔丸娛樂機器人發送的帳號密碼訊息。\n"
                "本次帳號與密碼內容從未寫入魔丸娛樂資料庫；"
                "系統只保留不含帳密的授權與撤回紀錄。"
            )
        else:
            body = (
                f"⚠️ **帳號資料撤回未完全成功**\n"
                f"訂單：**{order_no}**\n\n"
                f"已撤回 **{deleted_count}** 則，另有 **{failed_count}** 則 Discord 私訊目前無法確認撤回。\n"
                "魔丸娛樂系統本身未保存帳號或密碼內容。"
            )

        if unique_recipient_lines:
            body += "\n\n原授權人員：\n" + "\n".join(unique_recipient_lines)

        body += (
            f"\n\n處理時間：{taipei_now_iso()}\n"
            "🔒 為了最高帳號安全性，服務完成後仍建議更換密碼。"
        )

        delivered_notice = False
        if customer_id is not None:
            customer_user = await resolve_user(guild, int(customer_id))
            if customer_user is not None:
                try:
                    await customer_user.send(body)
                    delivered_notice = True
                except Exception:
                    delivered_notice = False

        if not delivered_notice and ticket_channel is not None:
            try:
                mention = f"<@{customer_id}> " if customer_id is not None else ""
                await ticket_channel.send(
                    mention + body,
                    allowed_mentions=discord.AllowedMentions(
                        users=True,
                        roles=False,
                        everyone=False,
                    ),
                )
            except Exception:
                pass

    return {
        "total": len(deliveries),
        "deleted": deleted_count,
        "failed": failed_count,
    }
