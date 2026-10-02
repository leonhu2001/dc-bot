from __future__ import annotations

import asyncio
from typing import Any

import discord

from core.permissions import is_customer_staff
from services.web_support_chat import (
    STATUS_HUMAN,
    STATUS_WAITING_HUMAN,
    SENDER_STAFF,
    SENDER_SYSTEM,
    add_message,
    claim_session,
    close_session,
    get_session,
    get_session_by_notification_message,
    get_session_by_thread_id,
    list_pending_handoffs,
    list_bridged_active_sessions,
    list_messages,
    list_undelivered_customer_messages,
    mark_message_delivered_to_discord,
    recent_customer_text,
    set_discord_bridge,
)

WEB_SUPPORT_CHANNEL_ID = 0
CUSTOMER_SERVICE_ROLE_ID = 0


def configure_web_support_bridge(
    *,
    channel_id: int,
    customer_service_role_id: int,
) -> None:
    global WEB_SUPPORT_CHANNEL_ID, CUSTOMER_SERVICE_ROLE_ID
    WEB_SUPPORT_CHANNEL_ID = int(channel_id or 0)
    CUSTOMER_SERVICE_ROLE_ID = int(customer_service_role_id or 0)


def _display_name(member: discord.abc.User) -> str:
    return str(
        getattr(member, "display_name", None)
        or getattr(member, "global_name", None)
        or getattr(member, "name", None)
        or member.id
    )


def _reason_label(reason: str | None) -> str:
    labels = {
        "customer_requested_human": "顧客文字要求轉接真人",
        "customer_clicked_human": "顧客按下「轉接真人客服」",
        "sensitive_support_topic": "敏感客服議題需真人處理",
    }
    value = str(reason or "").strip()
    return labels.get(value, value or "顧客要求真人協助")


def _customer_text(session: dict[str, Any]) -> str:
    name = str(session.get("customer_display_name") or "").strip()
    discord_id = str(session.get("customer_discord_id") or "").strip()

    if name and discord_id:
        return f"{name} (<@{discord_id}>)"
    if discord_id:
        return f"<@{discord_id}>"
    return name or "網站訪客"


def _latest_customer_message(session_id: int) -> str:
    rows = recent_customer_text(int(session_id), limit=10)
    for item in reversed(rows):
        if str(item.get("sender_type") or "") == "customer":
            return str(item.get("body") or "").strip()[:900]
    return "-"


def build_web_support_embed(session: dict[str, Any]) -> discord.Embed:
    status = str(session.get("status") or STATUS_WAITING_HUMAN)

    if status == STATUS_HUMAN:
        title = "💬 網站真人客服・處理中"
        color = discord.Color.green()
        staff = str(session.get("claimed_by_display_name") or "").strip()
        status_text = f"{staff or '客服'} 已接手"
    elif status == "closed":
        title = "✅ 網站真人客服・已完成"
        color = discord.Color.blue()
        status_text = "本次對話已結束"
    else:
        title = "🔔 網站真人客服請求"
        color = discord.Color.gold()
        status_text = "等待客服接手"

    embed = discord.Embed(
        title=title,
        color=color,
        description=(
            f"顧客：{_customer_text(session)}\n"
            f"狀態：{status_text}"
        ),
    )
    embed.add_field(
        name="轉接原因",
        value=_reason_label(session.get("handoff_reason")),
        inline=False,
    )
    embed.add_field(
        name="最後訊息",
        value=_latest_customer_message(int(session.get("id") or 0)) or "-",
        inline=False,
    )

    customer_id = str(session.get("customer_discord_id") or "").strip()
    if customer_id:
        embed.add_field(
            name="客戶 360°",
            value=f"https://mowanentertainment.com/admin/search/customer/{customer_id}",
            inline=False,
        )

    embed.set_footer(text=f"網站客服 #{int(session.get('id') or 0)}")
    return embed


async def _edit_notification(
    interaction: discord.Interaction,
    session: dict[str, Any],
) -> None:
    if interaction.message is None:
        return
    try:
        await interaction.message.edit(
            embed=build_web_support_embed(session),
            view=WebSupportActionView(),
        )
    except discord.HTTPException:
        pass


class WebSupportClaimButton(discord.ui.Button):
    def __init__(self):
        super().__init__(
            label="接手處理",
            emoji="✅",
            style=discord.ButtonStyle.success,
            custom_id="web_support_claim",
        )

    async def callback(self, interaction: discord.Interaction):
        if interaction.guild is None or not is_customer_staff(interaction.user):
            await interaction.response.send_message(
                "只有客服人員可以接手網站客服。",
                ephemeral=True,
            )
            return

        session = get_session_by_notification_message(
            interaction.message.id if interaction.message else 0
        )
        if session is None:
            await interaction.response.send_message(
                "找不到這筆網站客服對話。",
                ephemeral=True,
            )
            return

        staff_name = _display_name(interaction.user)
        changed = claim_session(
            int(session["id"]),
            staff_discord_id=str(interaction.user.id),
            staff_display_name=staff_name,
        )

        if changed and str(session.get("status") or "") == STATUS_WAITING_HUMAN:
            add_message(
                int(session["id"]),
                sender_type=SENDER_SYSTEM,
                sender_display_name="系統",
                body=f"{staff_name} 已接手，接下來將由真人回覆。",
            )

        latest = get_session(int(session["id"])) or session
        await interaction.response.send_message(
            f"已接手網站客服 #{int(session['id'])}。",
            ephemeral=True,
        )
        await _edit_notification(interaction, latest)

        thread_id = str(latest.get("discord_thread_id") or "").strip()
        if thread_id:
            thread = interaction.guild.get_thread(int(thread_id))
            if thread is not None:
                try:
                    await thread.send(
                        f"✅ {interaction.user.mention} 已接手。直接在這個 Thread 回覆，"
                        "訊息會同步到網站聊天視窗。"
                    )
                except discord.HTTPException:
                    pass


class WebSupportResolveButton(discord.ui.Button):
    def __init__(self):
        super().__init__(
            label="完成處理",
            emoji="☑️",
            style=discord.ButtonStyle.secondary,
            custom_id="web_support_resolve",
        )

    async def callback(self, interaction: discord.Interaction):
        if interaction.guild is None or not is_customer_staff(interaction.user):
            await interaction.response.send_message(
                "只有客服人員可以結束網站客服。",
                ephemeral=True,
            )
            return

        session = get_session_by_notification_message(
            interaction.message.id if interaction.message else 0
        )
        if session is None:
            await interaction.response.send_message(
                "找不到這筆網站客服對話。",
                ephemeral=True,
            )
            return

        staff_name = _display_name(interaction.user)

        if str(session.get("status") or "") == STATUS_WAITING_HUMAN:
            claim_session(
                int(session["id"]),
                staff_discord_id=str(interaction.user.id),
                staff_display_name=staff_name,
            )

        closed = close_session(int(session["id"]))
        if closed:
            add_message(
                int(session["id"]),
                sender_type=SENDER_SYSTEM,
                sender_display_name="系統",
                body=(
                    f"{staff_name} 已結束本次服務。"
                    "如果還有其他問題，可以重新開啟一段客服對話。"
                ),
            )

        latest = get_session(int(session["id"])) or session
        await interaction.response.send_message(
            f"網站客服 #{int(session['id'])} 已完成。",
            ephemeral=True,
        )
        await _edit_notification(interaction, latest)

        thread_id = str(latest.get("discord_thread_id") or "").strip()
        if thread_id:
            thread = interaction.guild.get_thread(int(thread_id))
            if thread is not None:
                try:
                    await thread.send(
                        f"☑️ {interaction.user.mention} 已完成本次網站客服。"
                    )
                    await thread.edit(archived=True)
                except discord.HTTPException:
                    pass


class WebSupportActionView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(WebSupportClaimButton())
        self.add_item(WebSupportResolveButton())


async def web_support_bridge_loop(bot: discord.Client) -> None:
    await bot.wait_until_ready()

    while not bot.is_closed():
        try:
            if not WEB_SUPPORT_CHANNEL_ID:
                await asyncio.sleep(5)
                continue

            channel = bot.get_channel(WEB_SUPPORT_CHANNEL_ID)
            if channel is None:
                try:
                    channel = await bot.fetch_channel(WEB_SUPPORT_CHANNEL_ID)
                except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                    channel = None

            if not isinstance(channel, discord.TextChannel):
                await asyncio.sleep(5)
                continue

            for session in list_pending_handoffs(limit=50):
                role = (
                    channel.guild.get_role(CUSTOMER_SERVICE_ROLE_ID)
                    if CUSTOMER_SERVICE_ROLE_ID
                    else None
                )
                mention = role.mention if role is not None else ""

                notification = await channel.send(
                    content=(
                        f"{mention}\n🔔 有新的網站真人客服請求。"
                    ).strip(),
                    embed=build_web_support_embed(session),
                    view=WebSupportActionView(),
                    allowed_mentions=discord.AllowedMentions(
                        users=False,
                        roles=True,
                        everyone=False,
                    ),
                )

                thread_name = (
                    f"網站客服-{int(session['id'])}-"
                    f"{str(session.get('customer_display_name') or '訪客')[:30]}"
                )
                try:
                    thread = await notification.create_thread(
                        name=thread_name[:95],
                        auto_archive_duration=1440,
                    )
                except discord.HTTPException:
                    try:
                        thread = await channel.create_thread(
                            name=thread_name[:95],
                            type=discord.ChannelType.private_thread,
                            auto_archive_duration=1440,
                        )
                    except discord.HTTPException:
                        await notification.edit(
                            content=(
                                f"{mention}\n⚠️ 網站客服通知已建立，但 Thread 建立失敗。"
                            ).strip(),
                        )
                        set_discord_bridge(
                            int(session["id"]),
                            channel_id=channel.id,
                            thread_id="0",
                            notification_message_id=notification.id,
                        )
                        continue

                set_discord_bridge(
                    int(session["id"]),
                    channel_id=channel.id,
                    thread_id=thread.id,
                    notification_message_id=notification.id,
                )

                await thread.send(
                    "這個 Thread 已和網站客服視窗連線。\n"
                    "客服直接在這裡輸入訊息即可同步給客人；"
                    "第一則真人回覆會自動視為接手。"
                )

                history = list_messages(
                    int(session["id"]),
                    limit=12,
                )
                transcript_lines: list[str] = []
                for item in history:
                    sender = str(item.get("sender_type") or "")
                    body = str(item.get("body") or "").strip()
                    if not body:
                        continue
                    label = {
                        "customer": "客人",
                        "ai": "AI",
                        "system": "系統",
                        "staff": "客服",
                    }.get(sender, sender or "訊息")
                    transcript_lines.append(
                        f"**{label}：** {body[:500]}"
                    )

                if transcript_lines:
                    transcript = "\n".join(transcript_lines)
                    await thread.send(
                        "### 轉接前對話\n"
                        + transcript[:1800]
                    )

                for item in history:
                    if str(item.get("sender_type") or "") == "customer":
                        mark_message_delivered_to_discord(
                            int(item["id"])
                        )

            for session in list_bridged_active_sessions(limit=100):
                thread_id = str(session.get("discord_thread_id") or "").strip()
                if not thread_id:
                    continue

                thread = channel.guild.get_thread(int(thread_id))
                if thread is None:
                    try:
                        fetched = await bot.fetch_channel(int(thread_id))
                        thread = fetched if isinstance(fetched, discord.Thread) else None
                    except (
                        discord.NotFound,
                        discord.Forbidden,
                        discord.HTTPException,
                    ):
                        thread = None

                if thread is None:
                    continue

                for item in list_undelivered_customer_messages(
                    int(session["id"]),
                    limit=50,
                ):
                    body = str(item.get("body") or "").strip()
                    if not body:
                        mark_message_delivered_to_discord(int(item["id"]))
                        continue

                    customer_name = str(
                        session.get("customer_display_name")
                        or "網站訪客"
                    ).strip()
                    sent = await thread.send(
                        f"🌐 **{customer_name}：** {body[:1700]}"
                    )
                    mark_message_delivered_to_discord(
                        int(item["id"]),
                        discord_message_id=sent.id,
                    )

        except Exception as exc:
            print(
                f"[web-support] bridge loop error: {type(exc).__name__}: {exc}",
                flush=True,
            )

        await asyncio.sleep(3)


async def handle_web_support_thread_message(message: discord.Message) -> None:
    if message.author.bot or not isinstance(message.channel, discord.Thread):
        return

    session = get_session_by_thread_id(message.channel.id)
    if session is None:
        return

    if not isinstance(message.author, discord.Member):
        return

    if not is_customer_staff(message.author):
        return

    text = str(message.content or "").strip()
    attachment_urls = [
        str(item.url)
        for item in message.attachments
        if getattr(item, "url", None)
    ]
    if attachment_urls:
        suffix = "\n".join(f"[附件] {url}" for url in attachment_urls)
        text = (text + "\n" + suffix).strip()

    if not text:
        return

    staff_name = _display_name(message.author)

    if str(session.get("status") or "") == STATUS_WAITING_HUMAN:
        claimed = claim_session(
            int(session["id"]),
            staff_discord_id=str(message.author.id),
            staff_display_name=staff_name,
        )
        if claimed:
            add_message(
                int(session["id"]),
                sender_type=SENDER_SYSTEM,
                sender_display_name="系統",
                body=f"真人客服 {staff_name} 已接手，接下來將由真人回覆。",
            )

    add_message(
        int(session["id"]),
        sender_type=SENDER_STAFF,
        sender_discord_id=str(message.author.id),
        sender_display_name=staff_name,
        body=text,
        discord_message_id=str(message.id),
    )
