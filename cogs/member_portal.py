from __future__ import annotations

import os
import sqlite3
from pathlib import Path

import discord
from discord.ext import commands
from sqlalchemy import text

from services.loyalty_benefits import get_customer_benefit_snapshot
from services.rewards import (
    get_current_reward_points,
    get_customer_reward_data,
    get_effective_member_level,
)
from services.wallet_service import get_wallet_balance
from shared.db import engine


MEMBER_PORTAL_CHANNEL_ID = int(os.getenv("MEMBER_PORTAL_CHANNEL_ID", "1558395213406412801"))
MEMBER_PORTAL_MARKER = "MAWAN_MEMBER_PORTAL_V1"
WEBSITE_PORTAL_URL = "https://mowanentertainment.com/me"
WEB_DB = Path(__file__).resolve().parents[1] / "web_dashboard.db"


def _embed(title: str, description: str = "") -> discord.Embed:
    return discord.Embed(title=title, description=description, color=discord.Color.gold())


def _favorite_names(customer_id: int | str, *, limit: int = 15) -> list[str]:
    try:
        with sqlite3.connect(WEB_DB, timeout=15) as conn:
            conn.row_factory = sqlite3.Row
            table = conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='staff_favorites'"
            ).fetchone()
            if table is None:
                return []
            rows = conn.execute(
                """
                SELECT
                    sf.staff_discord_id,
                    COALESCE(NULLIF(sp.display_name, ''), NULLIF(sf.staff_display_name, ''), sf.staff_discord_id) AS display_name
                FROM staff_favorites sf
                LEFT JOIN staff_profiles sp
                  ON sp.staff_discord_id = sf.staff_discord_id
                WHERE sf.customer_discord_id = ?
                ORDER BY sf.id DESC
                LIMIT ?
                """,
                (str(customer_id), max(1, int(limit))),
            ).fetchall()
            return [str(row["display_name"] or row["staff_discord_id"]) for row in rows]
    except sqlite3.Error:
        return []


class MemberPortalView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(
            discord.ui.Button(
                label="網站我的專區",
                style=discord.ButtonStyle.link,
                url=WEBSITE_PORTAL_URL,
                row=1,
            )
        )

    @discord.ui.button(label="會員 / 點數", style=discord.ButtonStyle.secondary, custom_id="member_portal:member")
    async def member(self, interaction: discord.Interaction, button: discord.ui.Button):
        data = get_customer_reward_data(interaction.user.id)
        level = get_effective_member_level(data)
        points = get_current_reward_points(data)
        try:
            wallet = get_wallet_balance(interaction.user.id)
        except Exception:
            wallet = 0
        embed = _embed("我的會員資料")
        embed.add_field(name="VIP", value=str(level.get("name") or "普通魔丸"), inline=True)
        embed.add_field(name="點數", value=f"{int(points):,} 點", inline=True)
        embed.add_field(name="錢包", value=f"{int(wallet):,}T", inline=True)
        embed.add_field(name="累積有效消費", value=f"{int(data.get('total_spent') or 0):,}T", inline=False)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @discord.ui.button(label="我的福利", style=discord.ButtonStyle.primary, custom_id="member_portal:benefits")
    async def benefits(self, interaction: discord.Interaction, button: discord.ui.Button):
        snapshot = get_customer_benefit_snapshot(interaction.user.id)
        embed = _embed("我的福利", "只顯示已開始累積的項目；新制自 2026/10/10 起計。")
        coupons = snapshot.get("coupons") or []
        progress = snapshot.get("progress") or []
        embed.add_field(
            name=f"可用福利券 · {len(coupons)}",
            value=("\n".join(f"・{item.get('display_name')}" for item in coupons[:10]) or "目前沒有可用福利券"),
            inline=False,
        )
        if progress:
            lines = []
            for item in progress[:10]:
                current = float(item.get("paid_units") or 0)
                threshold = float(item.get("threshold_units") or 0)
                lines.append(
                    f"・{item.get('label')}：{current:g}/{threshold:g} {item.get('unit_label')} → {item.get('reward_label')}"
                )
            embed.add_field(name="累積進度", value="\n".join(lines), inline=False)
        else:
            embed.add_field(name="累積進度", value="完成第一筆符合活動的付費服務後才會顯示。", inline=False)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @discord.ui.button(label="我的訂單", style=discord.ButtonStyle.secondary, custom_id="member_portal:orders")
    async def orders(self, interaction: discord.Interaction, button: discord.ui.Button):
        try:
            with engine.begin() as conn:
                rows = conn.execute(text("""
                    SELECT id, bot_order_no, item, status,
                           COALESCE(customer_pay_amount, amount, 0) AS amount
                    FROM web_orders
                    WHERE CAST(customer_discord_id AS TEXT)=:customer_id
                    ORDER BY id DESC
                    LIMIT 5
                """), {"customer_id": str(interaction.user.id)}).mappings().all()
        except Exception:
            rows = []
        if rows:
            body = "\n".join(
                f"・{row.get('bot_order_no') or 'WEB-' + str(row.get('id'))}｜{row.get('item') or '未紀錄'}｜{int(row.get('amount') or 0):,}T｜{row.get('status') or '未紀錄'}"
                for row in rows
            )
        else:
            body = "目前沒有可顯示的訂單。"
        embed = _embed("最近訂單", body)
        embed.add_field(name="完整訂單", value="到網站「我的專區」可查看完整進度與明細。", inline=False)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @discord.ui.button(label="我的收藏", style=discord.ButtonStyle.secondary, custom_id="member_portal:favorites")
    async def favorites(self, interaction: discord.Interaction, button: discord.ui.Button):
        names = _favorite_names(interaction.user.id)
        embed = _embed(
            "我的收藏",
            "\n".join(f"・{name}" for name in names) if names else "目前還沒有收藏陪玩。",
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)


def build_panel_embed() -> discord.Embed:
    embed = _embed(
        "我的專區",
        "不用輸入指令。按下方按鈕即可私人查看會員資料、累積福利、訂單與收藏。\n查詢結果只有你自己看得到。",
    )
    embed.add_field(name="累積福利", value="計時 10 個付費小時送 30 分鐘；計局 20 個付費局送 1 局。", inline=False)
    embed.set_footer(text=MEMBER_PORTAL_MARKER)
    return embed


async def ensure_member_portal_panel(bot: commands.Bot) -> None:
    await bot.wait_until_ready()
    channel = bot.get_channel(MEMBER_PORTAL_CHANNEL_ID)
    if channel is None:
        try:
            channel = await bot.fetch_channel(MEMBER_PORTAL_CHANNEL_ID)
        except (discord.NotFound, discord.Forbidden, discord.HTTPException):
            return
    if not isinstance(channel, discord.TextChannel):
        return
    existing = None
    try:
        async for message in channel.history(limit=50):
            if message.author.id != bot.user.id:
                continue
            if any(str(getattr(embed.footer, "text", "") or "") == MEMBER_PORTAL_MARKER for embed in message.embeds):
                existing = message
                break
    except (discord.Forbidden, discord.HTTPException):
        return
    if existing is not None:
        try:
            await existing.edit(embed=build_panel_embed(), view=MemberPortalView())
            return
        except discord.HTTPException:
            pass
    try:
        await channel.send(embed=build_panel_embed(), view=MemberPortalView())
    except (discord.Forbidden, discord.HTTPException):
        return


# Registration is intentionally owned by bot.py because this project does not
# dynamically load extension cogs. Keeping the panel helpers here avoids adding
# another second startup path.
