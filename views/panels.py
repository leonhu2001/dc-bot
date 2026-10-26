from __future__ import annotations

from typing import Any, Callable, Awaitable

import discord

from services.support_calls import (
    cancel_support_call,
    create_or_get_active_support_call,
    set_support_call_notification,
)
from views.support import ComplaintModal, FeedbackModal
from views.support_calls import SupportCallActionView, build_support_call_embed

# Dependencies configured by bot.py after IDs and helper functions are available.
EXAM_CATEGORY_ID: int | None = None
CUSTOMER_CATEGORY_ID: int | None = None
CUSTOMER_ROLE_ID: int | None = None
EXAMINER_ROLE_ID: int | None = None
MANAGER_ROLE_ID: int | None = None
RECRUIT_APPLICANT_ROLE_ID: int | None = None

safe_channel_name: Callable[[str, discord.Member], str] | None = None
create_private_channel: Callable[..., Awaitable[Any]] | None = None
recruit_control_view_factory: Callable[[], discord.ui.View] | None = None
format_customer_notes_for_ticket: Callable[[int], str] | None = None
order_control_view_factory: Callable[[], discord.ui.View] | None = None


def build_main_panel_embed() -> discord.Embed:
    return discord.Embed(
        title="魔丸娛樂｜聯絡客服",
        description=(
            "歡迎來到魔丸娛樂，請選擇下方需要的服務。\n"
            "需要真人客服時可按 **🔔 呼叫客服**，系統會建立 / 開啟你的私人客服票口並通知客服。\n"
            "客服服務時間：**AM 10:00－隔日 AM 2:00**"
        ),
        color=discord.Color.purple(),
    )


def configure_panel_views(
    *,
    exam_category_id: int,
    customer_role_id: int,
    examiner_role_id: int,
    manager_role_id: int,
    recruit_applicant_role_id: int,
    safe_channel_name: Callable[[str, discord.Member], str],
    create_private_channel: Callable[..., Awaitable[Any]],
    recruit_control_view_factory: Callable[[], discord.ui.View],
    **_legacy_order_kwargs,
) -> None:
    """Configure the customer-service panel.

    Ordering-related dependencies are still captured for the member portal and
    black-diamond redemption flow, while the public service lobby itself keeps
    only customer-service actions.
    """
    globals()["EXAM_CATEGORY_ID"] = exam_category_id
    globals()["CUSTOMER_CATEGORY_ID"] = int(
        _legacy_order_kwargs.get("customer_category_id") or 0
    ) or None
    globals()["CUSTOMER_ROLE_ID"] = customer_role_id
    globals()["EXAMINER_ROLE_ID"] = examiner_role_id
    globals()["MANAGER_ROLE_ID"] = manager_role_id
    globals()["RECRUIT_APPLICANT_ROLE_ID"] = recruit_applicant_role_id
    globals()["safe_channel_name"] = safe_channel_name
    globals()["create_private_channel"] = create_private_channel
    globals()["recruit_control_view_factory"] = recruit_control_view_factory
    globals()["format_customer_notes_for_ticket"] = _legacy_order_kwargs.get(
        "format_customer_notes_for_ticket"
    )
    globals()["order_control_view_factory"] = _legacy_order_kwargs.get(
        "order_control_view_factory"
    )


def _require_configured(name: str, value):
    if value is None:
        raise RuntimeError(f"views.panels 尚未設定 {name}")
    return value


def _support_channel_for_member(
    category: discord.CategoryChannel,
    member_id: int,
) -> discord.TextChannel | None:
    marker = f"support_customer_id={int(member_id)}"
    for channel in category.text_channels:
        if marker in str(channel.topic or ""):
            return channel
    return None


async def _open_or_ring_support(interaction: discord.Interaction) -> None:
    guild = interaction.guild
    member = interaction.user
    if guild is None or not isinstance(member, discord.Member):
        await interaction.response.send_message(
            "客服鈴只能在伺服器內使用。",
            ephemeral=True,
        )
        return

    category_id = _require_configured("CUSTOMER_CATEGORY_ID", CUSTOMER_CATEGORY_ID)
    support_role_id = _require_configured("CUSTOMER_ROLE_ID", CUSTOMER_ROLE_ID)
    name_builder = _require_configured("safe_channel_name", safe_channel_name)

    category = guild.get_channel(int(category_id))
    support_role = guild.get_role(int(support_role_id))
    if not isinstance(category, discord.CategoryChannel) or support_role is None:
        await interaction.response.send_message(
            "客服票口尚未完成設定，請直接標記客服協助。",
            ephemeral=True,
        )
        return

    await interaction.response.defer(ephemeral=True, thinking=True)

    channel = _support_channel_for_member(category, member.id)
    created_channel = False
    if channel is None:
        bot_member = guild.me
        if bot_member is None:
            await interaction.followup.send("目前無法建立客服票口，請稍後再試。", ephemeral=True)
            return

        overwrites: dict[discord.abc.Snowflake, discord.PermissionOverwrite] = {
            guild.default_role: discord.PermissionOverwrite(
                view_channel=False,
                send_messages=False,
                read_message_history=False,
            ),
            member: discord.PermissionOverwrite(
                view_channel=True,
                send_messages=True,
                read_message_history=True,
                attach_files=True,
            ),
            support_role: discord.PermissionOverwrite(
                view_channel=True,
                send_messages=True,
                read_message_history=True,
                attach_files=True,
            ),
            bot_member: discord.PermissionOverwrite(
                view_channel=True,
                send_messages=True,
                read_message_history=True,
                attach_files=True,
                manage_channels=True,
                manage_messages=True,
            ),
        }
        manager_role = guild.get_role(int(MANAGER_ROLE_ID or 0))
        if manager_role is not None and manager_role.id != support_role.id:
            overwrites[manager_role] = discord.PermissionOverwrite(
                view_channel=True,
                send_messages=True,
                read_message_history=True,
                attach_files=True,
            )

        try:
            channel = await guild.create_text_channel(
                name=name_builder("客服", member),
                category=category,
                overwrites=overwrites,
                topic=f"support_customer_id={member.id};support_source=main_panel",
                reason=f"{member} opened a customer-service ticket",
            )
            created_channel = True
            await channel.send(
                f"👋 {member.mention}，這裡是你的私人客服票口。\n"
                "請直接描述需要協助的事情；按下客服鈴後會通知目前可處理的客服。",
                allowed_mentions=discord.AllowedMentions(
                    users=True,
                    roles=False,
                    everyone=False,
                ),
            )
        except (discord.Forbidden, discord.HTTPException):
            await interaction.followup.send(
                "建立客服票口失敗，請直接標記客服協助。",
                ephemeral=True,
            )
            return

    call, created_call = create_or_get_active_support_call(
        ticket_channel_id=channel.id,
        customer_discord_id=member.id,
        customer_display_name=str(member.display_name or member.name),
    )

    if created_call:
        try:
            notification = await channel.send(
                content=(
                    f"{support_role.mention}\n"
                    f"🔔 {member.mention} 呼叫客服，請可處理的人員按 **接手處理**。"
                ),
                embed=build_support_call_embed(call),
                view=SupportCallActionView(),
                allowed_mentions=discord.AllowedMentions(
                    users=True,
                    roles=True,
                    everyone=False,
                ),
            )
            set_support_call_notification(int(call["id"]), notification.id)
        except Exception:
            cancel_support_call(int(call["id"]), "notification_send_failed")
            await interaction.followup.send(
                f"客服票口已建立：{channel.mention}\n但客服鈴通知失敗，請在票口直接標記客服。",
                ephemeral=True,
            )
            return

        message = (
            f"🔔 已呼叫客服，請到 {channel.mention} 描述需要協助的事情。"
            if not created_channel
            else f"🔔 已建立客服票口並呼叫客服：{channel.mention}"
        )
    else:
        status = str(call.get("status") or "")
        if status == "claimed":
            staff_id = str(call.get("claimed_by_discord_id") or "").strip()
            state = f"已由 <@{staff_id}> 接手" if staff_id else "已由客服接手"
        else:
            state = "已送出，正在等待客服接手"
        message = f"你的客服鈴{state}。請到 {channel.mention} 繼續說明問題。"

    await interaction.followup.send(
        message,
        ephemeral=True,
        allowed_mentions=discord.AllowedMentions.none(),
    )


class RecruitModal(discord.ui.Modal, title="我要入職"):
    nickname = discord.ui.TextInput(
        label="暱稱",
        placeholder="請輸入你的暱稱",
        required=True,
        max_length=50,
    )

    age = discord.ui.TextInput(
        label="年齡",
        placeholder="請輸入你的年齡",
        required=True,
        max_length=20,
    )

    play_time = discord.ui.TextInput(
        label="可遊玩時段",
        placeholder="例如：平日晚上、假日整天",
        required=True,
        max_length=100,
    )

    position = discord.ui.TextInput(
        label="應徵職位",
        placeholder="例如：陪玩、接待、客服、其他",
        required=True,
        max_length=100,
    )

    async def on_submit(self, interaction: discord.Interaction):
        guild = interaction.guild
        member = interaction.user

        if guild is None or not isinstance(member, discord.Member):
            await interaction.response.send_message("這個功能只能在伺服器內使用。", ephemeral=True)
            return

        exam_category_id = _require_configured("EXAM_CATEGORY_ID", EXAM_CATEGORY_ID)
        examiner_role_id = _require_configured("EXAMINER_ROLE_ID", EXAMINER_ROLE_ID)
        manager_role_id = _require_configured("MANAGER_ROLE_ID", MANAGER_ROLE_ID)
        customer_role_id = _require_configured("CUSTOMER_ROLE_ID", CUSTOMER_ROLE_ID)
        applicant_role_id = _require_configured("RECRUIT_APPLICANT_ROLE_ID", RECRUIT_APPLICANT_ROLE_ID)
        name_builder = _require_configured("safe_channel_name", safe_channel_name)
        channel_creator = _require_configured("create_private_channel", create_private_channel)
        recruit_view_factory = _require_configured("recruit_control_view_factory", recruit_control_view_factory)

        examiner_role = guild.get_role(examiner_role_id)
        manager_role = guild.get_role(manager_role_id)
        customer_role = guild.get_role(customer_role_id)
        applicant_role = guild.get_role(applicant_role_id)

        recruit_staff_roles = []
        seen_role_ids = set()

        for role in (examiner_role, manager_role, customer_role):
            if role is None or role.id in seen_role_ids:
                continue

            seen_role_ids.add(role.id)
            recruit_staff_roles.append(role)

        if applicant_role is not None:
            try:
                await member.add_roles(applicant_role, reason="Recruit ticket opened")
            except discord.Forbidden:
                print("Bot 權限不足，無法給予入職申請暫時身分組。請確認 Bot 身分組位置高於該身分組。")
            except discord.HTTPException as e:
                print(f"給予入職申請暫時身分組失敗：{e}")

        intro = (
            f"這裡有人想入職。\n\n"
            f"申請人：{member.mention}\n"
            f"暱稱：{self.nickname.value}\n"
            f"年齡：{self.age.value}\n"
            f"可遊玩時段：{self.play_time.value}\n"
            f"應徵職位：{self.position.value}"
        )

        await channel_creator(
            interaction=interaction,
            category_id=exam_category_id,
            channel_name=name_builder("入職", member),
            allowed_roles=recruit_staff_roles,
            intro_message=intro,
            view=recruit_view_factory(),
            topic=f"recruit_member_id={member.id};recruit_nickname={self.nickname.value};recruit_position={self.position.value}",
        )


class MainPanelView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(
        label="呼叫客服",
        emoji="🔔",
        style=discord.ButtonStyle.primary,
        custom_id="mawan_main_panel_support_call_v1",
        row=0,
    )
    async def support_call_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await _open_or_ring_support(interaction)

    @discord.ui.button(
        label="我要入職",
        emoji="💼",
        style=discord.ButtonStyle.success,
        custom_id="mawan_main_panel_recruit_button",
        row=0,
    )
    async def recruit_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(RecruitModal())

    @discord.ui.button(
        label="我要客訴",
        emoji="⚠️",
        style=discord.ButtonStyle.danger,
        custom_id="mawan_main_panel_complaint_button",
        row=0,
    )
    async def complaint_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(ComplaintModal())

    @discord.ui.button(
        label="顧客意見",
        emoji="💬",
        style=discord.ButtonStyle.secondary,
        custom_id="mawan_main_panel_feedback_button",
        row=0,
    )
    async def feedback_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(FeedbackModal())
