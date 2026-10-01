from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Awaitable, Callable

import discord

from core.permissions import GENERAL_MANAGER_ROLE_ID, is_customer_staff
from services.support_calls import (
    cancel_support_call,
    claim_support_call,
    create_or_get_active_support_call,
    get_support_call,
    get_support_call_by_notification,
    list_active_support_calls,
    mark_support_call_reminder,
    resolve_support_call,
    set_support_call_notification,
)

CUSTOMER_SERVICE_ROLE_ID = 0
MANAGER_ROLE_ID = 0
_send_order_log_callback: Callable[..., Awaitable[object]] | None = None


def configure_support_call_views(
    *,
    customer_service_role_id: int,
    manager_role_id: int,
    send_order_log_callback: Callable[..., Awaitable[object]] | None = None,
) -> None:
    global CUSTOMER_SERVICE_ROLE_ID, MANAGER_ROLE_ID, _send_order_log_callback

    CUSTOMER_SERVICE_ROLE_ID = int(customer_service_role_id)
    MANAGER_ROLE_ID = int(manager_role_id)
    _send_order_log_callback = send_order_log_callback


def _display_name(member: discord.abc.User) -> str:
    return str(
        getattr(member, "display_name", None)
        or getattr(member, "global_name", None)
        or getattr(member, "name", None)
        or member.id
    )


def _ticket_customer_id(channel: discord.TextChannel) -> int | None:
    topic = str(channel.topic or "")
    for part in topic.split(";"):
        if "=" not in part:
            continue
        key, value = part.split("=", 1)
        if key.strip() != "order_customer_id":
            continue
        try:
            return int(value.strip())
        except (TypeError, ValueError):
            return None
    return None


def _timestamp(value: str | None) -> int | None:
    text = str(value or "").strip()
    if not text:
        return None

    if text.endswith("Z"):
        text = text[:-1] + "+00:00"

    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None

    return int(parsed.timestamp())


def _response_seconds(call: dict) -> int | None:
    called_ts = _timestamp(call.get("called_at"))
    claimed_ts = _timestamp(call.get("claimed_at"))
    if called_ts is None or claimed_ts is None:
        return None
    return max(0, claimed_ts - called_ts)


def _duration_text(seconds: int | None) -> str:
    if seconds is None:
        return "-"
    minutes, secs = divmod(max(0, int(seconds)), 60)
    if minutes < 60:
        return f"{minutes} 分 {secs} 秒"
    hours, minutes = divmod(minutes, 60)
    return f"{hours} 小時 {minutes} 分"


def build_support_call_embed(call: dict) -> discord.Embed:
    status = str(call.get("status") or "open")
    called_ts = _timestamp(call.get("called_at"))
    customer_id = str(call.get("customer_discord_id") or "").strip()
    customer_text = f"<@{customer_id}>" if customer_id else "未知顧客"

    if status == "open":
        title = "🔔 客服鈴"
        color = discord.Color.gold()
        status_text = "等待客服接手"
    elif status == "claimed":
        title = "🔔 客服鈴・處理中"
        color = discord.Color.green()
        staff_id = str(call.get("claimed_by_discord_id") or "").strip()
        status_text = (
            f"已由 <@{staff_id}> 接手"
            if staff_id
            else "已由客服接手"
        )
    elif status == "resolved":
        title = "✅ 客服鈴・已完成"
        color = discord.Color.blue()
        staff_id = str(call.get("resolved_by_discord_id") or "").strip()
        status_text = (
            f"已由 <@{staff_id}> 完成處理"
            if staff_id
            else "已完成處理"
        )
    else:
        title = "客服鈴"
        color = discord.Color.light_grey()
        status_text = status

    embed = discord.Embed(
        title=title,
        description=(
            f"顧客：{customer_text}\n"
            f"狀態：{status_text}"
        ),
        color=color,
    )

    embed.add_field(
        name="呼叫時間",
        value=(f"<t:{called_ts}:F>\n<t:{called_ts}:R>" if called_ts else "-"),
        inline=True,
    )

    response = _response_seconds(call)
    embed.add_field(
        name="接手耗時",
        value=_duration_text(response),
        inline=True,
    )

    embed.set_footer(text=f"客服鈴 #{int(call.get('id') or 0)}")
    return embed


def _support_role_mentions(guild: discord.Guild, *, escalated: bool = False) -> str:
    role_ids = [CUSTOMER_SERVICE_ROLE_ID]

    if escalated:
        role_ids.extend(
            [
                MANAGER_ROLE_ID,
                GENERAL_MANAGER_ROLE_ID,
            ]
        )

    mentions: list[str] = []
    seen: set[int] = set()

    for role_id in role_ids:
        role_id = int(role_id or 0)
        if not role_id or role_id in seen:
            continue
        seen.add(role_id)
        role = guild.get_role(role_id)
        if role is not None:
            mentions.append(role.mention)

    return " ".join(mentions)


class SupportCallButton(discord.ui.Button):
    def __init__(self):
        super().__init__(
            label="呼叫客服",
            emoji="🔔",
            style=discord.ButtonStyle.primary,
            custom_id="order_support_call",
            row=1,
        )

    async def callback(self, interaction: discord.Interaction):
        if (
            interaction.guild is None
            or not isinstance(interaction.channel, discord.TextChannel)
        ):
            await interaction.response.send_message(
                "客服鈴只能在下單票口內使用。",
                ephemeral=True,
            )
            return

        customer_id = _ticket_customer_id(interaction.channel)
        if customer_id is None:
            await interaction.response.send_message(
                "這張票口缺少顧客識別資料，請直接標記客服協助。",
                ephemeral=True,
            )
            return

        if int(interaction.user.id) != int(customer_id):
            await interaction.response.send_message(
                "只有這張票口的下單顧客可以使用客服鈴。",
                ephemeral=True,
            )
            return

        call, created = create_or_get_active_support_call(
            ticket_channel_id=interaction.channel.id,
            customer_discord_id=customer_id,
            customer_display_name=_display_name(interaction.user),
        )

        if not created:
            status = str(call.get("status") or "")
            if status == "claimed":
                staff_id = str(call.get("claimed_by_discord_id") or "").strip()
                message = (
                    f"客服鈴已由 <@{staff_id}> 接手處理。"
                    if staff_id
                    else "客服鈴已由客服接手處理。"
                )
            else:
                message = "客服鈴已經送出，目前正在等待客服接手，不會重複通知。"

            await interaction.response.send_message(
                message,
                ephemeral=True,
                allowed_mentions=discord.AllowedMentions.none(),
            )
            return

        role_mentions = _support_role_mentions(interaction.guild)

        try:
            notification = await interaction.channel.send(
                content=(
                    f"{role_mentions}\n"
                    f"🔔 {interaction.user.mention} 呼叫客服，請可處理的人員按 **接手處理**。"
                ).strip(),
                embed=build_support_call_embed(call),
                view=SupportCallActionView(),
                allowed_mentions=discord.AllowedMentions(
                    users=True,
                    roles=True,
                    everyone=False,
                ),
            )
            set_support_call_notification(
                int(call["id"]),
                notification.id,
            )
        except Exception:
            cancel_support_call(
                int(call["id"]),
                "notification_send_failed",
            )
            await interaction.response.send_message(
                "客服鈴送出失敗，請直接標記客服協助。",
                ephemeral=True,
            )
            return

        await interaction.response.send_message(
            "🔔 已呼叫客服。客服接手後，這裡會顯示接手人員與回應時間。",
            ephemeral=True,
        )


class SupportCallActionView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    def _disabled_copy(self) -> "SupportCallActionView":
        view = SupportCallActionView()
        for item in view.children:
            if isinstance(item, discord.ui.Button):
                item.disabled = True
        return view

    @discord.ui.button(
        label="接手處理",
        emoji="✅",
        style=discord.ButtonStyle.success,
        custom_id="support_call_claim",
        row=0,
    )
    async def claim_button(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ):
        if not isinstance(interaction.user, discord.Member):
            await interaction.response.send_message(
                "無法確認你的身分組。",
                ephemeral=True,
            )
            return

        if not is_customer_staff(interaction.user):
            await interaction.response.send_message(
                "只有客服或總管可以接手客服鈴。",
                ephemeral=True,
            )
            return

        if interaction.message is None:
            await interaction.response.send_message(
                "找不到客服鈴訊息。",
                ephemeral=True,
            )
            return

        call = get_support_call_by_notification(interaction.message.id)
        if call is None:
            await interaction.response.send_message(
                "找不到這筆客服鈴紀錄，可能是舊訊息。",
                ephemeral=True,
            )
            return

        latest, changed = claim_support_call(
            int(call["id"]),
            staff_discord_id=interaction.user.id,
            staff_display_name=_display_name(interaction.user),
        )

        if not changed:
            status = str(latest.get("status") or "")
            if status == "claimed":
                staff_id = str(latest.get("claimed_by_discord_id") or "").strip()
                message = (
                    f"這筆已由 <@{staff_id}> 接手。"
                    if staff_id
                    else "這筆已由其他客服接手。"
                )
            elif status == "resolved":
                message = "這筆客服鈴已完成處理。"
            else:
                message = f"這筆目前狀態為 {status or '未知'}。"

            await interaction.response.send_message(
                message,
                ephemeral=True,
                allowed_mentions=discord.AllowedMentions.none(),
            )
            return

        await interaction.response.edit_message(
            content=f"✅ {interaction.user.mention} 已接手這筆客服需求。",
            embed=build_support_call_embed(latest),
            view=self,
            allowed_mentions=discord.AllowedMentions(
                users=True,
                roles=False,
                everyone=False,
            ),
        )

    @discord.ui.button(
        label="完成處理",
        emoji="☑️",
        style=discord.ButtonStyle.secondary,
        custom_id="support_call_resolve",
        row=0,
    )
    async def resolve_button(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ):
        if not isinstance(interaction.user, discord.Member):
            await interaction.response.send_message(
                "無法確認你的身分組。",
                ephemeral=True,
            )
            return

        if not is_customer_staff(interaction.user):
            await interaction.response.send_message(
                "只有客服或總管可以完成客服鈴。",
                ephemeral=True,
            )
            return

        if interaction.message is None:
            await interaction.response.send_message(
                "找不到客服鈴訊息。",
                ephemeral=True,
            )
            return

        call = get_support_call_by_notification(interaction.message.id)
        if call is None:
            await interaction.response.send_message(
                "找不到這筆客服鈴紀錄，可能是舊訊息。",
                ephemeral=True,
            )
            return

        status = str(call.get("status") or "")
        if status == "open":
            await interaction.response.send_message(
                "請先按「接手處理」，再完成這筆客服需求。",
                ephemeral=True,
            )
            return

        latest, changed = resolve_support_call(
            int(call["id"]),
            staff_discord_id=interaction.user.id,
            staff_display_name=_display_name(interaction.user),
        )

        if not changed:
            await interaction.response.send_message(
                "這筆客服鈴已經不是處理中狀態。",
                ephemeral=True,
            )
            return

        await interaction.response.edit_message(
            content=f"☑️ {interaction.user.mention} 已完成這筆客服需求。",
            embed=build_support_call_embed(latest),
            view=self._disabled_copy(),
            allowed_mentions=discord.AllowedMentions(
                users=True,
                roles=False,
                everyone=False,
            ),
        )



def _message_has_component(
    message: discord.Message,
    custom_id: str,
) -> bool:
    for row in getattr(message, "components", []) or []:
        for child in getattr(row, "children", []) or []:
            if str(getattr(child, "custom_id", "") or "") == str(custom_id):
                return True
    return False


async def refresh_existing_order_ticket_support_buttons(
    guild: discord.Guild,
    *,
    category_id: int,
    order_control_view_factory: Callable[[], discord.ui.View],
) -> int:
    category = guild.get_channel(int(category_id))
    if not isinstance(category, discord.CategoryChannel):
        return 0

    refreshed = 0

    channels = sorted(
        category.text_channels,
        key=lambda item: int(item.id),
        reverse=True,
    )[:120]

    for channel in channels:
        topic = str(channel.topic or "")
        if "order_customer_id=" not in topic:
            continue

        lowered_name = str(channel.name or "").lower()
        if lowered_name.startswith(("已結單", "已取消")):
            continue

        try:
            async for message in channel.history(limit=60):
                if not _message_has_component(message, "order_control_select"):
                    continue

                if _message_has_component(message, "order_support_call"):
                    break

                await message.edit(
                    view=order_control_view_factory(),
                )
                refreshed += 1
                break
        except (discord.Forbidden, discord.HTTPException):
            continue

    return refreshed


async def support_call_sla_loop(bot: discord.Client) -> None:
    await bot.wait_until_ready()

    while not bot.is_closed():
        try:
            now_ts = int(datetime.now().timestamp())

            for call in list_active_support_calls(limit=300):
                if str(call.get("status") or "") != "open":
                    continue

                called_ts = _timestamp(call.get("called_at"))
                if called_ts is None:
                    continue

                age_seconds = max(0, now_ts - called_ts)
                current_stage = int(call.get("reminder_stage") or 0)

                target_stage = 0
                escalated = False

                if age_seconds >= 15 * 60 and current_stage < 2:
                    target_stage = 2
                    escalated = True
                elif age_seconds >= 5 * 60 and current_stage < 1:
                    target_stage = 1

                if not target_stage:
                    continue

                if not mark_support_call_reminder(int(call["id"]), target_stage):
                    continue

                latest = get_support_call(int(call["id"]))
                if latest is None or str(latest.get("status") or "") != "open":
                    continue

                channel_id = int(str(call.get("ticket_channel_id") or "0"))
                channel = bot.get_channel(channel_id)
                if not isinstance(channel, discord.TextChannel):
                    cancel_support_call(
                        int(call["id"]),
                        "ticket_channel_missing",
                    )
                    continue

                mentions = _support_role_mentions(
                    channel.guild,
                    escalated=escalated,
                )

                if escalated:
                    message = (
                        f"{mentions}\n"
                        f"🚨 客服鈴 #{int(call['id'])} 已等待超過 **15 分鐘**仍未接手，"
                        "請優先處理。"
                    ).strip()
                else:
                    message = (
                        f"{mentions}\n"
                        f"🔔 客服鈴 #{int(call['id'])} 已等待超過 **5 分鐘**，"
                        "目前仍未有人接手。"
                    ).strip()

                await channel.send(
                    message,
                    allowed_mentions=discord.AllowedMentions(
                        users=False,
                        roles=True,
                        everyone=False,
                    ),
                )

                if escalated and _send_order_log_callback is not None:
                    try:
                        await _send_order_log_callback(
                            channel.guild,
                            title="客服鈴 SLA 升級提醒",
                            fields=[
                                ("票口", channel.mention, True),
                                ("客服鈴", f"#{int(call['id'])}", True),
                                ("等待時間", "超過 15 分鐘", True),
                                ("狀態", "尚未接手", False),
                            ],
                            color=discord.Color.red(),
                        )
                    except Exception as exc:
                        print(
                            f"[support-call] escalation log failed "
                            f"call_id={call['id']}: {exc}",
                            flush=True,
                        )

        except Exception as exc:
            print(
                f"[support-call] SLA loop error: {type(exc).__name__}: {exc}",
                flush=True,
            )

        await asyncio.sleep(60)
