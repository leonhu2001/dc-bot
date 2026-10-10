from __future__ import annotations

import discord

from core.discord_settings import (
    CUSTOMER_SERVICE_ROLE_ID,
    GENERAL_MANAGER_ROLE_ID,
)
from services.loyalty_benefits import list_customer_loyalty
from services.vip_monthly_benefits import (
    BLACK_DIAMOND_CHOICES,
    benefit_status_label,
    bind_black_diamond_reservation_channel,
    get_customer_vip_monthly_snapshot,
    redeem_black_diamond_choice,
    release_black_diamond_choice,
    reserve_black_diamond_choice,
)
from web.app.config import config
from web.app.services.customer_portal import build_customer_portal_snapshot
from web.app.services.site_data import get_member_summary


MEMBER_PORTAL_CHANNEL_ID = 1558395213406412801
# Hidden footer marker lets the sync job find and update the existing panel without
# exposing an internal identifier to customers.
MEMBER_PORTAL_MARKER = "\u200b"
MEMBER_PORTAL_URL = "https://mowanentertainment.com/me"


def build_member_portal_embed() -> discord.Embed:
    embed = discord.Embed(
        title="👤 我的專區",
        description=(
            "查詢訂單、錢包、點數 / VIP 與會員福利。\n"
            "查詢結果僅自己可見。"
        ),
        color=discord.Color.purple(),
    )
    embed.set_footer(text=MEMBER_PORTAL_MARKER)
    return embed


def _member_id(interaction: discord.Interaction) -> str:
    return str(getattr(interaction.user, "id", "") or "")


def _format_progress(item: dict) -> str:
    pricing_type = str(item.get("pricing_type") or "")
    unit = "局" if pricing_type == "game" else "小時"
    current = float(item.get("progress_units") or 0)
    threshold = float(item.get("threshold_units") or 0)
    return f"{item.get('title') or item.get('rule_label')}：**{current:g} / {threshold:g} {unit}**"


def _status_icon(status: object) -> str:
    text = str(status or "").strip()
    lowered = text.lower()
    if "完成" in text or lowered in {"completed", "closed", "done"}:
        return "✅"
    if "取消" in text or "退款" in text or lowered in {"cancelled", "canceled", "refunded"}:
        return "❌"
    if "進行" in text or "服務" in text or lowered in {"active", "in_progress", "servicing"}:
        return "🎮"
    if "待" in text or "付款" in text or lowered in {"pending", "awaiting_payment", "unpaid"}:
        return "⏳"
    return "•"


def _link_view(label: str, url: str) -> discord.ui.View:
    view = discord.ui.View(timeout=300)
    view.add_item(
        discord.ui.Button(
            label=label,
            emoji="🌐",
            style=discord.ButtonStyle.link,
            url=url,
        )
    )
    return view


def _is_vip_redemption_staff(member: object) -> bool:
    if not isinstance(member, discord.Member):
        return False
    if member.guild_permissions.manage_guild or member.guild_permissions.administrator:
        return True
    role_ids = {int(role.id) for role in getattr(member, "roles", [])}
    return bool(
        role_ids
        & {
            int(CUSTOMER_SERVICE_ROLE_ID),
            int(GENERAL_MANAGER_ROLE_ID),
        }
    )


def _parse_black_ticket_topic(channel: object) -> tuple[str, str] | None:
    topic = str(getattr(channel, "topic", "") or "")
    values: dict[str, str] = {}
    for part in topic.split(";"):
        key, sep, value = part.partition("=")
        if sep:
            values[key.strip()] = value.strip()
    customer_id = values.get("vip_black_customer_id", "")
    month_key = values.get("vip_black_month", "")
    if not customer_id or not month_key:
        return None
    return customer_id, month_key


class BlackDiamondRedemptionControlView(discord.ui.View):
    """Persistent staff controls used inside a black-diamond redemption ticket."""

    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(
        label="完成兌換",
        emoji="✅",
        style=discord.ButtonStyle.success,
        custom_id="mawan_black_diamond_redeem_complete_v1",
        row=0,
    )
    async def complete(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not _is_vip_redemption_staff(interaction.user):
            await interaction.response.send_message("只有客服 / 總管可以確認兌換完成。", ephemeral=True)
            return
        parsed = _parse_black_ticket_topic(interaction.channel)
        if parsed is None:
            await interaction.response.send_message("找不到這張黑鑽兌換單的識別資料。", ephemeral=True)
            return
        customer_id, month_key = parsed
        if not redeem_black_diamond_choice(customer_id, month_key=month_key):
            await interaction.response.send_message("這筆福利不是兌換中狀態，可能已經處理過。", ephemeral=True)
            return
        await interaction.response.edit_message(
            content=(
                f"✅ **黑鑽尊享福利已完成兌換**\n"
                f"處理客服：{interaction.user.mention}\n"
                "本月次數已正式使用，下個月 1 日才會恢復。"
            ),
            view=None,
            allowed_mentions=discord.AllowedMentions(users=False, roles=False, everyone=False),
        )

    @discord.ui.button(
        label="取消兌換・退回次數",
        emoji="↩️",
        style=discord.ButtonStyle.danger,
        custom_id="mawan_black_diamond_redeem_cancel_v1",
        row=0,
    )
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not _is_vip_redemption_staff(interaction.user):
            await interaction.response.send_message("只有客服 / 總管可以取消兌換。", ephemeral=True)
            return
        parsed = _parse_black_ticket_topic(interaction.channel)
        if parsed is None:
            await interaction.response.send_message("找不到這張黑鑽兌換單的識別資料。", ephemeral=True)
            return
        customer_id, month_key = parsed
        if not release_black_diamond_choice(customer_id, month_key=month_key):
            await interaction.response.send_message("這筆福利不是兌換中狀態，可能已經處理過。", ephemeral=True)
            return
        await interaction.response.edit_message(
            content=(
                f"↩️ **黑鑽尊享福利兌換已取消**\n"
                f"處理客服：{interaction.user.mention}\n"
                "本月兌換次數已退回，老闆可以重新選擇。"
            ),
            view=None,
            allowed_mentions=discord.AllowedMentions(users=False, roles=False, everyone=False),
        )


async def _create_black_diamond_ticket(
    interaction: discord.Interaction,
    *,
    choice_key: str,
) -> None:
    from views import panels

    guild = interaction.guild
    member = interaction.user
    if guild is None or not isinstance(member, discord.Member):
        await interaction.response.send_message("這個功能只能在伺服器內使用。", ephemeral=True)
        return

    category_id = panels.CUSTOMER_CATEGORY_ID
    customer_role_id = panels.CUSTOMER_ROLE_ID
    name_builder = panels.safe_channel_name
    notes_formatter = panels.format_customer_notes_for_ticket
    order_view_factory = panels.order_control_view_factory
    if (
        category_id is None
        or customer_role_id is None
        or name_builder is None
        or notes_formatter is None
        or order_view_factory is None
    ):
        await interaction.response.send_message("點單系統尚未完成初始化，請稍後再試。", ephemeral=True)
        return

    choice_label = BLACK_DIAMOND_CHOICES.get(choice_key)
    if not choice_label:
        await interaction.response.send_message("找不到這個黑鑽福利選項。", ephemeral=True)
        return

    try:
        reserved = reserve_black_diamond_choice(member.id, choice_key)
    except ValueError as exc:
        await interaction.response.send_message(str(exc), ephemeral=True)
        return

    if not interaction.response.is_done():
        await interaction.response.defer(ephemeral=True, thinking=True)

    month_key = str(reserved.get("month_key") or "")
    try:
        category = guild.get_channel(int(category_id))
        if not isinstance(category, discord.CategoryChannel):
            raise RuntimeError("找不到點單類別")

        customer_role = guild.get_role(int(customer_role_id))
        overwrites = {
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
            guild.me: discord.PermissionOverwrite(
                view_channel=True,
                send_messages=True,
                manage_channels=True,
                read_message_history=True,
                attach_files=True,
            ),
        }
        if customer_role is not None:
            overwrites[customer_role] = discord.PermissionOverwrite(
                view_channel=True,
                send_messages=True,
                read_message_history=True,
                attach_files=True,
            )

        topic = (
            f"order_customer_id={member.id};"
            f"vip_black_customer_id={member.id};"
            f"vip_black_month={month_key};"
            f"vip_black_choice={choice_key}"
        )
        channel = await guild.create_text_channel(
            name=name_builder("黑鑽兌換", member),
            category=category,
            overwrites=overwrites,
            topic=topic,
            reason=f"{member} opened a black diamond monthly benefit redemption",
        )
        bind_black_diamond_reservation_channel(member.id, channel.id, month_key=month_key)

        intro = (
            f"👑 **黑鑽會員專屬福利兌換**\n\n"
            f"兌換人：{member.mention}\n"
            f"本月：**{month_key}**\n"
            f"選擇福利：**{choice_label}**\n"
            "狀態：**已保留本月 1 次黑鑽尊享福利**\n\n"
            "請用下方點單面板完成服務需求；客服確認服務成立後，再按「完成兌換」。\n"
            "若本次取消，請按「取消兌換・退回次數」，本月次數會恢復。"
            f"{notes_formatter(member.id)}"
        )
        await channel.send(
            intro,
            allowed_mentions=discord.AllowedMentions(users=True, roles=False, everyone=False),
        )
        await channel.send(
            "🛒 **開始建立兌換訂單**\n黑鑽福利由店內吸收福利部分成本；超出福利範圍的加購照正常價格計算。",
            view=order_view_factory(),
        )
        await channel.send(
            "客服處理區｜服務成立並確認福利內容後再完成兌換。",
            view=BlackDiamondRedemptionControlView(),
        )
        await interaction.followup.send(
            f"已保留本月黑鑽福利並建立兌換票口：{channel.mention}",
            ephemeral=True,
        )
    except Exception as exc:
        release_black_diamond_choice(member.id, month_key=month_key)
        await interaction.followup.send(
            f"建立黑鑽兌換票口失敗，本月次數已退回：{exc}",
            ephemeral=True,
        )


class BlackDiamondBenefitSelect(discord.ui.Select):
    def __init__(self):
        super().__init__(
            placeholder="選擇本月要兌換的黑鑽福利",
            min_values=1,
            max_values=1,
            options=[
                discord.SelectOption(
                    label="機密航天保底 1000w",
                    value="secret_space_1000w",
                    emoji="🎮",
                    description="本月黑鑽尊享福利，與娛樂陪 2H 二選一",
                ),
                discord.SelectOption(
                    label="娛樂陪 2H",
                    value="entertainment_2h",
                    emoji="🎧",
                    description="1 位陪玩 2 小時；額外人數 / 時數正常計價",
                ),
            ],
        )

    async def callback(self, interaction: discord.Interaction):
        await _create_black_diamond_ticket(
            interaction,
            choice_key=str(self.values[0]),
        )


class BlackDiamondBenefitSelectView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=180)
        self.add_item(BlackDiamondBenefitSelect())


class BlackDiamondRedeemButton(discord.ui.Button):
    def __init__(self, *, disabled: bool, label: str):
        super().__init__(
            label=label,
            emoji="👑",
            style=discord.ButtonStyle.primary,
            disabled=disabled,
            row=0,
        )

    async def callback(self, interaction: discord.Interaction):
        snapshot = get_customer_vip_monthly_snapshot(_member_id(interaction))
        if not snapshot.get("black_diamond_available"):
            await interaction.response.send_message(
                "本月黑鑽尊享福利目前不可兌換，可能已使用、兌換中或暫停發放。",
                ephemeral=True,
            )
            return
        embed = discord.Embed(
            title="👑 黑鑽會員專屬兌換",
            description=(
                "本月可從下列福利中 **二選一**。\n"
                "選擇後會先保留本月次數並建立兌換票口；取消時可由客服退回次數。"
            ),
            color=discord.Color.gold(),
        )
        await interaction.response.send_message(
            embed=embed,
            view=BlackDiamondBenefitSelectView(),
            ephemeral=True,
        )


class MemberBenefitsView(discord.ui.View):
    def __init__(self, monthly: dict):
        super().__init__(timeout=300)
        self.add_item(
            discord.ui.Button(
                label="查看我的福利",
                emoji="🌐",
                style=discord.ButtonStyle.link,
                url=f"{MEMBER_PORTAL_URL}#benefits",
                row=0,
            )
        )

        black = monthly.get("black_diamond") or {}
        if monthly.get("black_diamond_entitled") or black:
            status = str(black.get("status") or "")
            if monthly.get("black_diamond_suspended"):
                label = "黑鑽福利暫停"
                disabled = True
            elif status == "reserved":
                label = "黑鑽福利兌換中"
                disabled = True
            elif status == "redeemed":
                label = "黑鑽福利本月已兌換"
                disabled = True
            else:
                label = "黑鑽會員專屬兌換"
                disabled = not bool(monthly.get("black_diamond_available"))
            self.add_item(BlackDiamondRedeemButton(disabled=disabled, label=label))


class MemberPortalView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(
            discord.ui.Button(
                label="網站專區",
                emoji="🌐",
                style=discord.ButtonStyle.link,
                url=MEMBER_PORTAL_URL,
                row=0,
            )
        )

    @discord.ui.button(
        label="我的訂單",
        emoji="📋",
        style=discord.ButtonStyle.primary,
        custom_id="mawan_member_portal_orders_v1",
        row=0,
    )
    async def orders(self, interaction: discord.Interaction, button: discord.ui.Button):
        customer_id = _member_id(interaction)
        portal = build_customer_portal_snapshot(
            customer_id,
            guild_id=config.DISCORD_GUILD_ID,
        )
        recent = portal.get("recent_orders") or []
        lines = []
        for order in recent[:5]:
            status = order.get("status_label") or order.get("status") or "未知"
            lines.append(
                f"{_status_icon(status)} **{order.get('order_no') or '訂單'}**\n"
                f"{order.get('item') or '服務'}｜{status}｜{order.get('amount_text') or '0T'}"
            )

        embed = discord.Embed(
            title="📋 我的訂單",
            color=discord.Color.blurple(),
        )
        embed.add_field(
            name="訂單摘要",
            value=f"進行中：**{int(portal.get('open_count') or 0)}**",
            inline=False,
        )
        embed.add_field(
            name="最近 5 筆",
            value="\n\n".join(lines) if lines else "目前沒有訂單紀錄。",
            inline=False,
        )
        await interaction.response.send_message(
            embed=embed,
            view=_link_view("查看完整訂單", f"{MEMBER_PORTAL_URL}/orders"),
            ephemeral=True,
        )

    @discord.ui.button(
        label="我的錢包",
        emoji="💰",
        style=discord.ButtonStyle.secondary,
        custom_id="mawan_member_portal_wallet_v1",
        row=0,
    )
    async def wallet(self, interaction: discord.Interaction, button: discord.ui.Button):
        member = get_member_summary(_member_id(interaction))
        embed = discord.Embed(
            title="💰 我的錢包",
            description=(
                "目前可用餘額\n"
                f"**{member.get('wallet_balance_text') or '0T'}**"
            ),
            color=discord.Color.gold(),
        )
        embed.add_field(
            name="儲值",
            value="請使用 Discord 的儲值中心。",
            inline=False,
        )
        await interaction.response.send_message(
            embed=embed,
            view=_link_view("查看錢包紀錄", f"{MEMBER_PORTAL_URL}/wallet"),
            ephemeral=True,
        )

    @discord.ui.button(
        label="點數 / VIP",
        emoji="👑",
        style=discord.ButtonStyle.secondary,
        custom_id="mawan_member_portal_vip_v1",
        row=0,
    )
    async def vip(self, interaction: discord.Interaction, button: discord.ui.Button):
        member = get_member_summary(_member_id(interaction))
        vip_progress = member.get("vip_progress") or {}
        next_name = str(vip_progress.get("next_name") or "").strip()
        if next_name:
            progress_text = (
                f"下一級：**{next_name}**\n"
                f"尚差：**{int(vip_progress.get('remaining') or 0):,}T**"
            )
        else:
            progress_text = "已達最高 VIP 等級 👑"

        embed = discord.Embed(
            title="👑 點數 / VIP",
            color=discord.Color.gold(),
        )
        embed.add_field(
            name="目前等級",
            value=f"**{member.get('vip_name') or '普通魔丸'}**",
            inline=True,
        )
        embed.add_field(
            name="可用點數",
            value=f"**{int(member.get('points') or 0):,} 點**",
            inline=True,
        )
        embed.add_field(
            name="升級進度",
            value=progress_text,
            inline=False,
        )
        await interaction.response.send_message(
            embed=embed,
            view=_link_view("查看 VIP 專區", f"{MEMBER_PORTAL_URL}#vip"),
            ephemeral=True,
        )

    @discord.ui.button(
        label="我的福利",
        emoji="🎁",
        style=discord.ButtonStyle.success,
        custom_id="mawan_member_portal_benefits_v1",
        row=0,
    )
    async def benefits(self, interaction: discord.Interaction, button: discord.ui.Button):
        customer_id = _member_id(interaction)
        benefits = list_customer_loyalty(customer_id)
        monthly = get_customer_vip_monthly_snapshot(customer_id)
        coupons = benefits.get("coupons") or []
        progress = benefits.get("progress") or []
        embed = discord.Embed(
            title="🎁 我的福利",
            description="VIP 月福利每月 1 日刷新，**未使用次數不會累積到下個月**。",
            color=discord.Color.green(),
        )

        cash_rows = monthly.get("cash_benefits") or []
        if cash_rows:
            cash_lines = []
            for item in cash_rows:
                status = benefit_status_label(item.get("status"))
                cash_lines.append(f"🎟️ **{item.get('benefit_label')}**｜{status}")
            embed.add_field(
                name=f"VIP 每月福利 · {monthly.get('month_key')}",
                value="\n".join(cash_lines) + "\n月底未使用即失效，不會累積。",
                inline=False,
            )
        else:
            embed.add_field(
                name=f"VIP 每月福利 · {monthly.get('month_key')}",
                value="目前 VIP 等級沒有可用的月度折現券。",
                inline=False,
            )

        black = monthly.get("black_diamond") or {}
        if monthly.get("black_diamond_entitled") or black:
            if monthly.get("black_diamond_suspended"):
                black_text = "保級已到期、等待人工審核，本月新福利暫停發放。"
            elif black:
                black_status = benefit_status_label(black.get("status"))
                choice = BLACK_DIAMOND_CHOICES.get(str(black.get("choice_key") or ""), "")
                black_text = f"本月次數：**{black_status}**"
                if choice:
                    black_text += f"\n已選擇：**{choice}**"
                if str(black.get("status")) == "available":
                    black_text += "\n可按下方「黑鑽會員專屬兌換」二選一。"
            else:
                black_text = "本月黑鑽尊享福利尚未入帳，請稍後再試。"
            embed.add_field(
                name="👑 黑鑽尊享｜每月 1 次",
                value=(
                    black_text
                    + "\n可選：機密航天保底 1000w / 娛樂陪 2H。"
                    + "\n兩者共用同一個月度次數。"
                ),
                inline=False,
            )

        if coupons:
            embed.add_field(
                name=f"累積消費福利券 · {len(coupons)} 張",
                value="\n".join(
                    f"🎟️ **{item.get('title')}**\n有效至 {item.get('expires_at_text') or '—'}"
                    for item in coupons[:10]
                ),
                inline=False,
            )
        else:
            embed.add_field(
                name="累積消費福利券",
                value="目前沒有可用的累積消費福利券。",
                inline=False,
            )

        if progress:
            embed.add_field(
                name="累積進度",
                value="\n".join(f"• {_format_progress(item)}" for item in progress[:10]),
                inline=False,
            )
        else:
            embed.add_field(
                name="累積進度",
                value="尚未開始累積。\n完成符合活動的付費服務後才會顯示。",
                inline=False,
            )
        await interaction.response.send_message(
            embed=embed,
            view=MemberBenefitsView(monthly),
            ephemeral=True,
        )
