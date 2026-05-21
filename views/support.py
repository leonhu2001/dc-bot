import asyncio
from typing import Awaitable, Callable

import discord

from core.permissions import is_exam_staff, is_complaint_staff

COMPLAINT_RECEIVE_CHANNEL_ID = 0
_remove_recruit_applicant_role: Callable[[discord.Guild | None, discord.TextChannel], Awaitable[None]] | None = None


def configure_support_views(
    *,
    complaint_receive_channel_id: int,
    remove_recruit_applicant_role: Callable[[discord.Guild | None, discord.TextChannel], Awaitable[None]],
) -> None:
    global COMPLAINT_RECEIVE_CHANNEL_ID, _remove_recruit_applicant_role
    COMPLAINT_RECEIVE_CHANNEL_ID = int(complaint_receive_channel_id)
    _remove_recruit_applicant_role = remove_recruit_applicant_role


async def _remove_recruit_role(guild: discord.Guild | None, channel: discord.TextChannel) -> None:
    if _remove_recruit_applicant_role is None:
        return
    await _remove_recruit_applicant_role(guild, channel)


# ========= 入職操作 Modal / 按鈕 =========

class RecruitControlView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(
        label="已完成考核",
        style=discord.ButtonStyle.success,
        custom_id="recruit_exam_completed_button"
    )
    async def exam_completed(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not isinstance(interaction.user, discord.Member):
            await interaction.response.send_message("無法確認你的身分組。", ephemeral=True)
            return

        if not is_exam_staff(interaction.user):
            await interaction.response.send_message("只有考官或店長可以操作。", ephemeral=True)
            return

        channel = interaction.channel

        await interaction.response.send_message(
            f"此入職申請已由 {interaction.user.mention} 標記為已完成考核。\n"
            "頻道將在 3 秒後關閉。",
            ephemeral=False,
            allowed_mentions=discord.AllowedMentions(
                users=True,
                roles=False,
                everyone=False
            )
        )

        await asyncio.sleep(3)

        if isinstance(channel, discord.TextChannel):
            await _remove_recruit_role(interaction.guild, channel)
            await channel.delete(reason=f"Recruit exam completed by {interaction.user}")


# ========= 客訴 Modal / 按鈕 =========

class ComplaintModal(discord.ui.Modal, title="客訴單"):
    complaint_content = discord.ui.TextInput(
        label="客訴內容",
        placeholder="請輸入你的客訴內容",
        style=discord.TextStyle.paragraph,
        required=True,
        max_length=1500
    )

    async def on_submit(self, interaction: discord.Interaction):
        guild = interaction.guild

        if guild is None:
            await interaction.response.send_message("這個功能只能在伺服器內使用。", ephemeral=True)
            return

        receive_channel = guild.get_channel(COMPLAINT_RECEIVE_CHANNEL_ID)

        if receive_channel is None or not isinstance(receive_channel, discord.TextChannel):
            await interaction.response.send_message(
                "找不到客訴接收頻道，請確認 COMPLAINT_RECEIVE_CHANNEL_ID 是否正確。",
                ephemeral=True
            )
            return

        boss_mention = interaction.user.mention
        boss_id = interaction.user.id

        embed = discord.Embed(
            title="客訴",
            description=(
                f"有一則來自 {boss_mention} 的客訴!\n"
                f"申請人 ID：{boss_id}\n\n"
                f"客訴內容：\n{self.complaint_content.value}"
            ),
            color=discord.Color.red()
        )

        await receive_channel.send(
            embed=embed,
            view=ComplaintResolveView(),
            allowed_mentions=discord.AllowedMentions(
                users=False,
                roles=False,
                everyone=False
            )
        )

        await interaction.response.send_message(
            "你的客訴已送出，會由相關人員處理。",
            ephemeral=True
        )


class ComplaintPanelView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(
        label="客訴單",
        style=discord.ButtonStyle.danger,
        custom_id="complaint_form_button"
    )
    async def complaint_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(ComplaintModal())


class ComplaintResolveView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(
        label="已解決",
        style=discord.ButtonStyle.success,
        custom_id="complaint_resolved_button"
    )
    async def resolved_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not isinstance(interaction.user, discord.Member):
            await interaction.response.send_message("無法確認你的身分組。", ephemeral=True)
            return

        if not is_complaint_staff(interaction.user):
            await interaction.response.send_message("只有客服或店長可以標記已解決。", ephemeral=True)
            return

        button.disabled = True
        button.label = "已解決"

        embed = interaction.message.embeds[0] if interaction.message.embeds else None

        if embed is not None:
            embed.color = discord.Color.green()
            embed.add_field(
                name="處理狀態",
                value=f"已由 {interaction.user.mention} 標記為已解決",
                inline=False
            )

            await interaction.response.edit_message(embed=embed, view=self)
        else:
            await interaction.response.edit_message(
                content=f"此客訴已由 {interaction.user.mention} 標記為已解決。",
                view=self
            )


# ========= 顧客意見箱 Modal / 按鈕 =========

class FeedbackModal(discord.ui.Modal, title="顧客意見箱"):
    feedback_content = discord.ui.TextInput(
        label="意見內容",
        placeholder="請輸入你的意見或建議",
        style=discord.TextStyle.paragraph,
        required=True,
        max_length=1500
    )

    async def on_submit(self, interaction: discord.Interaction):
        guild = interaction.guild

        if guild is None:
            await interaction.response.send_message("這個功能只能在伺服器內使用。", ephemeral=True)
            return

        receive_channel = guild.get_channel(COMPLAINT_RECEIVE_CHANNEL_ID)

        if receive_channel is None or not isinstance(receive_channel, discord.TextChannel):
            await interaction.response.send_message(
                "找不到意見接收頻道，請確認 COMPLAINT_RECEIVE_CHANNEL_ID 是否正確。",
                ephemeral=True
            )
            return

        boss_mention = interaction.user.mention
        boss_id = interaction.user.id

        embed = discord.Embed(
            title="顧客意見箱",
            description=(
                f"有一則來自 {boss_mention} 的顧客意見。\n"
                f"申請人 ID：{boss_id}\n\n"
                f"意見內容：\n{self.feedback_content.value}"
            ),
            color=discord.Color.blue()
        )

        await receive_channel.send(
            embed=embed,
            view=ComplaintResolveView(),
            allowed_mentions=discord.AllowedMentions(
                users=False,
                roles=False,
                everyone=False
            )
        )

        await interaction.response.send_message(
            "你的意見已送出，感謝闆闆回饋！",
            ephemeral=True
        )


class FeedbackPanelView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(
        label="填寫意見",
        style=discord.ButtonStyle.primary,
        custom_id="feedback_form_button"
    )
    async def feedback_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(FeedbackModal())


