from __future__ import annotations

import discord


def profile_tip_ticket_ids(channel: discord.TextChannel | None) -> tuple[int, int] | None:
    if not isinstance(channel, discord.TextChannel):
        return None
    segments = str(channel.topic or "").split(";")
    if (len(segments) != 2
            or not segments[0].startswith("profile_tip_customer_id=")
            or not segments[1].startswith("profile_tip_staff_id=")):
        return None
    customer = segments[0].split("=", 1)[1]
    worker = segments[1].split("=", 1)[1]
    if not customer.isdigit() or not worker.isdigit():
        return None
    return int(customer), int(worker)


async def request_profile_tip_close(interaction: discord.Interaction) -> None:
    ids = profile_tip_ticket_ids(interaction.channel)
    if ids is None:
        await interaction.response.send_message(
            "這不是有效的名片雞腿票口。", ephemeral=True,
        )
        return

    from core.permissions import is_customer_staff
    customer_id, _ = ids
    staff = (
        isinstance(interaction.user, discord.Member)
        and is_customer_staff(interaction.user)
    )
    if interaction.user.id != customer_id and not staff:
        await interaction.response.send_message(
            "只有這張票口的老闆或客服可以關閉票口。", ephemeral=True,
        )
        return

    from views.review import ConfirmCloseTicketView
    await interaction.response.send_message(
        "⚠️ **確定要關閉這張雞腿票口嗎？**\n"
        "關閉前會封存對話與付款紀錄；若有待審核雞腿，則會禁止關閉。",
        view=ConfirmCloseTicketView(customer_id=customer_id),
        ephemeral=True,
    )


class WorkerTipProfileCloseView(discord.ui.View):
    """Reusable close button on confirmed profile-tip payment receipts."""

    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(
        label="🔒 關閉票口",
        style=discord.ButtonStyle.danger,
        custom_id="worker_tip_profile_paid_close",
    )
    async def close(self, interaction: discord.Interaction, button: discord.ui.Button):
        await request_profile_tip_close(interaction)


async def send_profile_tip_paid_panel(channel, tip_row) -> None:
    """New independent tip receipt, with the same paid-tip summary as post-close."""
    if profile_tip_ticket_ids(channel) is None:
        return
    if tip_row is None or str(tip_row["payment_status"] or "") != "paid":
        return
    amount = int(tip_row["amount"] or 0)
    await channel.send(
        "✅ **雞腿付款完成**\n"
        f"老闆：<@{tip_row['customer_discord_id']}>\n"
        f"指定陪玩：<@{tip_row['worker_discord_id']}>\n"
        f"🍗 **雞腿**｜{amount:,}T 已付款\n"
        f"🍗 **雞腿總覽**｜已付款 {amount:,}T\n"
        f"付款方式：{tip_row['payment_method']}\n"
        "此筆雞腿 100% 歸指定陪玩，已列入薪資明細。"
        "\n確認紀錄無誤後，可按下方按鈕關閉票口。",
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
    @discord.ui.button(
        label="🔒 關閉票口",
        style=discord.ButtonStyle.danger,
        custom_id="worker_tip_profile_open_close",
    )
    async def close(self, interaction: discord.Interaction, button: discord.ui.Button):
        await request_profile_tip_close(interaction)

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
        # The channel-creation helper accepts both Role and Member overwrite
        # targets. Grant the selected worker explicit view/send access.
        allowed_roles=[customer_role, staff_member],
        intro_message=(
            f"🍗 **名片加雞腿**\n"
            f"老闆：{member.mention}\n"
            f"指定陪玩：{staff_member.mention}\n\n"
            "這是獨立雞腿票口，不會建立一般陪玩訂單。\n"
            "雞腿金額 100% 歸指定陪玩；點擊下方按鈕輸入金額與付款方式。\n"
            "街口／銀行轉帳須附付款截圖，客服確認後入帳。"
        ),
        view=WorkerTipProfileStartView(),
        topic=(
            f"profile_tip_customer_id={member.id};"
            f"profile_tip_staff_id={staff_id_text}"
        ),
        mention_roles_in_intro=False,
        order_log_status="名片加雞腿票口",
    )
