from __future__ import annotations

from typing import Any, Callable, Awaitable

import discord

from views.support import ComplaintModal, FeedbackModal

# Dependencies configured by bot.py after IDs and helper functions are available.
EXAM_CATEGORY_ID: int | None = None
CUSTOMER_ROLE_ID: int | None = None
EXAMINER_ROLE_ID: int | None = None
MANAGER_ROLE_ID: int | None = None
RECRUIT_APPLICANT_ROLE_ID: int | None = None

safe_channel_name: Callable[[str, discord.Member], str] | None = None
create_private_channel: Callable[..., Awaitable[Any]] | None = None
recruit_control_view_factory: Callable[[], discord.ui.View] | None = None


def build_main_panel_embed() -> discord.Embed:
    return discord.Embed(
        title="魔丸娛樂｜客服中心",
        description=(
            "歡迎來到魔丸娛樂，請選擇下方需要的服務。\n"
            "入職、客訴與顧客意見皆可由此進入。\n"
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

    Old ordering-related keyword arguments are intentionally ignored so the main
    bot wiring remains backward compatible while the removed legacy order entry
    is no longer kept alive inside this view module.
    """
    globals()["EXAM_CATEGORY_ID"] = exam_category_id
    globals()["CUSTOMER_ROLE_ID"] = customer_role_id
    globals()["EXAMINER_ROLE_ID"] = examiner_role_id
    globals()["MANAGER_ROLE_ID"] = manager_role_id
    globals()["RECRUIT_APPLICANT_ROLE_ID"] = recruit_applicant_role_id
    globals()["safe_channel_name"] = safe_channel_name
    globals()["create_private_channel"] = create_private_channel
    globals()["recruit_control_view_factory"] = recruit_control_view_factory


def _require_configured(name: str, value):
    if value is None:
        raise RuntimeError(f"views.panels 尚未設定 {name}")
    return value


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
