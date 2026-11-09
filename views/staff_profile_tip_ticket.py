from __future__ import annotations

import discord



def profile_tip_ids(channel: discord.abc.GuildChannel | None) -> tuple[int, int] | None:
    topic = str(getattr(channel, "topic", "") or "")
    parts = topic.split(";")
    if len(parts) != 2:
        return None
    if not parts[0].startswith("profile_tip_customer_id="):
        return None
    if not parts[1].startswith("profile_tip_staff_id="):
        return None
    customer = parts[0].split("=", 1)[1]
    staff = parts[1].split("=", 1)[1]
    if not customer.isdigit() or not staff.isdigit():
        return None
    return int(customer), int(staff)


class WorkerTipProfileCloseView(discord.ui.View):
    """Persistent, owner/staff-only ticket close action with second confirmation."""

    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(
        label="🔒 關閉票口",
        style=discord.ButtonStyle.danger,
        custom_id="worker_tip_profile_close",
    )
    async def close(self, interaction: discord.Interaction, button: discord.ui.Button):
        channel = interaction.channel
        if not isinstance(channel, discord.TextChannel):
            await interaction.response.send_message("只能在雞腿票口關閉。", ephemeral=True)
            return
        ids = profile_tip_ids(channel)
        if ids is None:
            await interaction.response.send_message("這不是有效的雞腿票口。", ephemeral=True)
            return
        from core.permissions import is_customer_staff
        if (interaction.user.id != ids[0] and not (
            isinstance(interaction.user, discord.Member)
            and is_customer_staff(interaction.user)
        )):
            await interaction.response.send_message(
                "只有開票老闆或客服可以關閉此票口。", ephemeral=True,
            )
            return
        from views.review import ConfirmCloseTicketView
        await interaction.response.send_message(
            "確定要關閉這張雞腿票口嗎？關閉前會封存完整聊天紀錄。"
            "如有待審核雞腿款項，系統會阻止關閉。",
            view=ConfirmCloseTicketView(customer_id=ids[0]),
            ephemeral=True,
        )


class WorkerTipProfileTicketView(discord.ui.View):
    """Initial ticket: both tip amount and close actions."""

    def __init__(self):
        super().__init__(timeout=None)
        for item in WorkerTipProfileStartView().children:
            self.add_item(item)
        self.add_item(WorkerTipProfileCloseButton())


class WorkerTipProfileCloseButton(discord.ui.Button):
    def __init__(self):
        super().__init__(
            label="🔒 關閉票口",
            style=discord.ButtonStyle.danger,
            custom_id="worker_tip_profile_ticket_close",
        )

    async def callback(self, interaction: discord.Interaction):
        close = WorkerTipProfileCloseView()
        button = close.children[0]
        await close.close(interaction, button)


async def send_profile_tip_completion(channel: discord.TextChannel, tip_row) -> None:
    """Present a post-tip completion prompt after actual payment succeeds."""
    if profile_tip_ids(channel) is None or tip_row is None:
        return
    from services.worker_tips import get_worker_tip
    tip_id = int(tip_row["id"])
    verified = get_worker_tip(tip_id)
    if verified is None or str(verified["payment_status"]) != "paid":
        return
    await channel.send(
        (
            "✅ **雞腿已完成**\\n"
            f"老闆：<@{verified['customer_discord_id']}>\\n"
            f"指定陪玩：<@{verified['worker_discord_id']}>\\n"
            f"雞腿：**{int(verified['amount']):,}T**\\n"
            "此筆已列入指定陪玩的薪資明細（待發放），100% 歸陪玩。\\n\\n"
            "可以繼續加雞腿，或點下方按鈕關閉票口。"
        ),
        view=WorkerTipProfileCloseView(),
        allowed_mentions=discord.AllowedMentions(
            users=True, roles=False, everyone=False,
        ),
    )


class WorkerTipProfileStartView(discord.ui.View):
    """Persistent button for a private chicken-leg ticket opened from a staff card."""

    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(
        label="🍗 加雞腿／輸入金額",
        style=discord.ButtonStyle.primary,
        custom_id="worker_tip_profile_start",
    )
    async def start(self, interaction: discord.Interaction, button: discord.ui.Button):
        channel = interaction.channel
        if not isinstance(channel, discord.TextChannel):
            await interaction.response.send_message("請在私密雞腿票口操作。", ephemeral=True)
            return

        topic = str(channel.topic or "")
        segments = topic.split(";")
        if (len(segments) != 2
                or not segments[0].startswith("profile_tip_customer_id=")
                or not segments[1].startswith("profile_tip_staff_id=")):
            await interaction.response.send_message("這不是有效的雞腿票口。", ephemeral=True)
            return

        customer_id = segments[0].split("=", 1)[1]
        staff_id = segments[1].split("=", 1)[1]
        if (not customer_id.isdigit() or not staff_id.isdigit()
                or interaction.user.id != int(customer_id)):
            await interaction.response.send_message("只有開票的老闆可以加雞腿。", ephemeral=True)
            return

        from views.staff_profiles import get_staff_profile
        from views.worker_tips import WorkerTipAmountModal
        profile = get_staff_profile(staff_id)
        display_name = (
            str(profile.get("display_name") or staff_id)
            if profile is not None else staff_id
        )
        await interaction.response.send_modal(
            WorkerTipAmountModal(
                customer_id=int(customer_id),
                ticket_channel_id=channel.id,
                target={"staff_id": staff_id, "display_name": display_name},
                standalone=True,
            )
        )


async def create_staff_profile_tip_ticket(
    *,
    interaction: discord.Interaction,
    staff_id: str,
    create_private_channel,
    customer_role_id: int,
    customer_category_id: int,
) -> None:
    """Open a private tip ticket without creating or posting a regular order."""
    guild, member = interaction.guild, interaction.user
    if guild is None or not isinstance(member, discord.Member):
        raise ValueError("雞腿功能僅支援伺服器內的成員名片。")

    from views.staff_profiles import get_staff_profile
    profile = get_staff_profile(staff_id)
    if profile is None:
        raise ValueError("找不到這位陪玩的名片，請重新整理。")

    staff_id_text = str(staff_id or "").strip()
    if not staff_id_text.isdigit():
        raise ValueError("陪玩 ID 無效，不能建立雞腿票口。")

    staff_member = guild.get_member(int(staff_id_text))
    if staff_member is None:
        try:
            staff_member = await guild.fetch_member(int(staff_id_text))
        except (discord.Forbidden, discord.NotFound, discord.HTTPException):
            staff_member = None
    if staff_member is None:
        raise ValueError("這位陪玩目前不在伺服器，無法加雞腿。")

    customer_role = guild.get_role(customer_role_id)
    if customer_role is None:
        raise ValueError("找不到客服身分組，請通知管理員。")

    await create_private_channel(
        interaction=interaction,
        category_id=customer_category_id,
        channel_name=f"雞腿-{member.id}",
        allowed_roles=[customer_role],
        intro_message=(
            f"🍗 **名片加雞腿**\n"
            f"老闆：{member.mention}\n"
            f"指定陪玩：{staff_member.mention}\n\n"
            "這是獨立雞腿票口，不會建立一般陪玩訂單。\n"
            "雞腿金額 100% 歸指定陪玩；點擊下方按鈕輸入金額與付款方式。\n"
            "街口／銀行轉帳須附付款截圖，客服確認後入帳。"
        ),
        view=WorkerTipProfileTicketView(),
        allowed_members=[staff_member],
        topic=(
            f"profile_tip_customer_id={member.id};"
            f"profile_tip_staff_id={staff_id_text}"
        ),
        mention_roles_in_intro=False,
        order_log_status="名片加雞腿票口",
    )
