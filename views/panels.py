from __future__ import annotations

from typing import Any, Callable, Awaitable

import discord

# Dependencies configured by bot.py after IDs and helper functions are available.
CUSTOMER_CATEGORY_ID: int | None = None
EXAM_CATEGORY_ID: int | None = None
CUSTOMER_ROLE_ID: int | None = None
EXAMINER_ROLE_ID: int | None = None
MANAGER_ROLE_ID: int | None = None
RECRUIT_APPLICANT_ROLE_ID: int | None = None

safe_channel_name: Callable[[str, discord.Member], str] | None = None
is_agree_answer: Callable[[str], bool] | None = None
format_customer_notes_for_ticket: Callable[[int], str] | None = None
create_private_channel: Callable[..., Awaitable[Any]] | None = None
order_control_view_factory: Callable[[], discord.ui.View] | None = None
recruit_control_view_factory: Callable[[], discord.ui.View] | None = None

PANEL_SELECTIONS: dict[int, str] = {}


def configure_panel_views(
    *,
    customer_category_id: int,
    exam_category_id: int,
    customer_role_id: int,
    examiner_role_id: int,
    manager_role_id: int,
    recruit_applicant_role_id: int,
    safe_channel_name: Callable[[str, discord.Member], str],
    is_agree_answer: Callable[[str], bool],
    format_customer_notes_for_ticket: Callable[[int], str],
    create_private_channel: Callable[..., Awaitable[Any]],
    order_control_view_factory: Callable[[], discord.ui.View],
    recruit_control_view_factory: Callable[[], discord.ui.View],
) -> None:
    globals()["CUSTOMER_CATEGORY_ID"] = customer_category_id
    globals()["EXAM_CATEGORY_ID"] = exam_category_id
    globals()["CUSTOMER_ROLE_ID"] = customer_role_id
    globals()["EXAMINER_ROLE_ID"] = examiner_role_id
    globals()["MANAGER_ROLE_ID"] = manager_role_id
    globals()["RECRUIT_APPLICANT_ROLE_ID"] = recruit_applicant_role_id
    globals()["safe_channel_name"] = safe_channel_name
    globals()["is_agree_answer"] = is_agree_answer
    globals()["format_customer_notes_for_ticket"] = format_customer_notes_for_ticket
    globals()["create_private_channel"] = create_private_channel
    globals()["order_control_view_factory"] = order_control_view_factory
    globals()["recruit_control_view_factory"] = recruit_control_view_factory


def _require_configured(name: str, value):
    if value is None:
        raise RuntimeError(f"views.panels 尚未設定 {name}")
    return value


class OrderModal(discord.ui.Modal, title="我要下單"):
    rule_confirm = discord.ui.TextInput(
        label="是否已詳閱規章內容",
        placeholder="請輸入：是",
        required=True,
        max_length=20,
    )

    async def on_submit(self, interaction: discord.Interaction):
        agree_checker = _require_configured("is_agree_answer", is_agree_answer)

        if not agree_checker(self.rule_confirm.value):
            await interaction.response.send_message(
                "你尚未詳閱規章內容，暫時無法下單。請詳閱規章後再重新開單。",
                ephemeral=True,
            )
            return

        guild = interaction.guild
        member = interaction.user

        if guild is None or not isinstance(member, discord.Member):
            await interaction.response.send_message("這個功能只能在伺服器內使用。", ephemeral=True)
            return

        customer_role_id = _require_configured("CUSTOMER_ROLE_ID", CUSTOMER_ROLE_ID)
        customer_category_id = _require_configured("CUSTOMER_CATEGORY_ID", CUSTOMER_CATEGORY_ID)
        name_builder = _require_configured("safe_channel_name", safe_channel_name)
        notes_formatter = _require_configured("format_customer_notes_for_ticket", format_customer_notes_for_ticket)
        channel_creator = _require_configured("create_private_channel", create_private_channel)
        order_view_factory = _require_configured("order_control_view_factory", order_control_view_factory)

        customer_role = guild.get_role(customer_role_id)

        intro = (
            f"這裡有闆闆開單。\n\n"
            f"開單人：{member.mention}\n"
            f"狀態：已確認詳閱規章內容"
            f"{notes_formatter(member.id)}"
        )

        await channel_creator(
            interaction=interaction,
            category_id=customer_category_id,
            channel_name=name_builder("下單", member),
            allowed_roles=[customer_role],
            intro_message=intro,
            view=order_view_factory(),
            topic=f"order_customer_id={member.id}",
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
            allowed_roles=[examiner_role, manager_role, customer_role],
            intro_message=intro,
            view=recruit_view_factory(),
            topic=f"recruit_member_id={member.id};recruit_nickname={self.nickname.value};recruit_position={self.position.value}",
        )


class MainPanelSelect(discord.ui.Select):
    def __init__(self):
        options = [
            discord.SelectOption(
                label="我要下單",
                value="order",
                description="開啟下單票口",
            ),
            discord.SelectOption(
                label="我要入職",
                value="recruit",
                description="開啟入職申請票口",
            ),
        ]

        super().__init__(
            placeholder="請選擇你要辦理的項目",
            min_values=1,
            max_values=1,
            options=options,
            custom_id="mawan_main_panel_select",
            row=0,
        )

    async def callback(self, interaction: discord.Interaction):
        PANEL_SELECTIONS[interaction.user.id] = self.values[0]
        await interaction.response.defer()


class MainPanelView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(MainPanelSelect())

    @discord.ui.button(
        label="確認",
        style=discord.ButtonStyle.success,
        custom_id="mawan_main_panel_confirm",
        row=1,
    )
    async def confirm_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        selected = PANEL_SELECTIONS.get(interaction.user.id)

        if selected is None:
            await interaction.response.send_message(
                "請先從下拉式清單選擇項目，再按確認。",
                ephemeral=True,
            )
            return

        PANEL_SELECTIONS.pop(interaction.user.id, None)

        if selected == "order":
            await interaction.response.send_modal(OrderModal())
        elif selected == "recruit":
            await interaction.response.send_modal(RecruitModal())
        else:
            await interaction.response.send_message(
                "選擇項目異常，請重新選擇一次。",
                ephemeral=True,
            )
