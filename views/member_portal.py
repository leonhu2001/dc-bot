from __future__ import annotations

import discord

from services.loyalty_benefits import list_customer_loyalty
from web.app.config import config
from web.app.services.customer_portal import build_customer_portal_snapshot
from web.app.services.site_data import get_member_summary


MEMBER_PORTAL_CHANNEL_ID = 1558395213406412801
# Hidden footer marker lets the sync job find and update the existing panel without
# exposing an internal identifier such as MAWAN_MEMBER_PORTAL_V1 to customers.
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
    return f"{item.get('title') or item.get('rule_label')}：{current:g}/{threshold:g} {unit}"


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
            lines.append(
                f"**{order.get('order_no') or '訂單'}**｜{order.get('item') or '服務'}｜"
                f"{order.get('status_label') or order.get('status') or '未知'}｜{order.get('amount_text') or '0T'}"
            )
        if not lines:
            lines.append("目前沒有訂單紀錄。")
        embed = discord.Embed(
            title="📋 我的訂單",
            description="\n".join(lines),
            color=discord.Color.blurple(),
        )
        embed.add_field(
            name="目前進行中",
            value=str(int(portal.get("open_count") or 0)),
            inline=True,
        )
        embed.add_field(
            name="完整紀錄",
            value=f"{MEMBER_PORTAL_URL}/orders",
            inline=False,
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @discord.ui.button(
        label="錢包 / 儲值",
        emoji="💰",
        style=discord.ButtonStyle.secondary,
        custom_id="mawan_member_portal_wallet_v1",
        row=0,
    )
    async def wallet(self, interaction: discord.Interaction, button: discord.ui.Button):
        member = get_member_summary(_member_id(interaction))
        embed = discord.Embed(
            title="💰 我的錢包",
            color=discord.Color.gold(),
        )
        embed.add_field(
            name="目前餘額",
            value=str(member.get("wallet_balance_text") or "0T"),
            inline=False,
        )
        embed.add_field(
            name="儲值 / 紀錄",
            value=f"{MEMBER_PORTAL_URL}/wallet",
            inline=False,
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

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
                f"下一級：{next_name}｜尚差 {int(vip_progress.get('remaining') or 0):,}T"
            )
        else:
            progress_text = "已達最高 VIP 等級"
        embed = discord.Embed(
            title="👑 點數 / VIP",
            color=discord.Color.gold(),
        )
        embed.add_field(
            name="目前等級",
            value=str(member.get("vip_name") or "普通魔丸"),
            inline=True,
        )
        embed.add_field(
            name="可用點數",
            value=f"{int(member.get('points') or 0):,} 點",
            inline=True,
        )
        embed.add_field(
            name="升級進度",
            value=progress_text,
            inline=False,
        )
        embed.add_field(
            name="完整專區",
            value=f"{MEMBER_PORTAL_URL}#vip",
            inline=False,
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @discord.ui.button(
        label="我的福利",
        emoji="🎁",
        style=discord.ButtonStyle.success,
        custom_id="mawan_member_portal_benefits_v1",
        row=0,
    )
    async def benefits(self, interaction: discord.Interaction, button: discord.ui.Button):
        benefits = list_customer_loyalty(_member_id(interaction))
        coupons = benefits.get("coupons") or []
        progress = benefits.get("progress") or []
        embed = discord.Embed(
            title="🎁 我的福利",
            color=discord.Color.green(),
        )
        if coupons:
            embed.add_field(
                name=f"可用福利券（{len(coupons)}）",
                value="\n".join(
                    f"• {item.get('title')}｜有效至 {item.get('expires_at_text') or '—'}"
                    for item in coupons[:10]
                ),
                inline=False,
            )
        else:
            embed.add_field(name="可用福利券", value="目前沒有可用福利券。", inline=False)

        if progress:
            embed.add_field(
                name="累積進度",
                value="\n".join(f"• {_format_progress(item)}" for item in progress[:10]),
                inline=False,
            )
        else:
            embed.add_field(
                name="累積進度",
                value="完成符合活動的付費服務後，這裡才會開始顯示進度。",
                inline=False,
            )
        embed.add_field(
            name="官網",
            value=f"{MEMBER_PORTAL_URL}#benefits",
            inline=False,
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)
