from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands

from core.permissions import has_role, is_customer_staff
from services.rewards import (
    build_member_info_embed,
    format_customer_notes_for_staff,
    format_t_amount,
    get_customer_reward_data,
)
from services.wallet_discord_runtime import (
    adjust_customer_wallet_balance,
    send_wallet_log,
)
from services.wallet_service import get_wallet_balance, get_wallet_transactions


def wallet_transaction_type_label(tx_type: str) -> str:
    mapping = {
        "topup": "儲值",
        "payment": "訂單扣款",
        "tip_payment": "雞腿扣款",
        "refund": "退款",
        "adjustment": "修正",
    }
    return mapping.get(str(tx_type or "").strip(), str(tx_type or "未知"))


def build_customer_info_with_wallet_embed(
    member: discord.Member,
    *,
    show_staff_notes: bool = True,
) -> discord.Embed:
    data = get_customer_reward_data(member.id)
    embed = build_member_info_embed(member, data, show_points=True)

    wallet_balance = get_wallet_balance(member.id)
    embed.add_field(
        name="錢包餘額",
        value=format_t_amount(wallet_balance),
        inline=True,
    )

    if show_staff_notes:
        note_text = format_customer_notes_for_staff(member.id)
        if note_text:
            embed.add_field(
                name="客服備註",
                value=note_text[:1024],
                inline=False,
            )

    return embed


def wallet_transaction_history(customer_id, limit: int = 10) -> list[dict]:
    return get_wallet_transactions(customer_id, limit=limit)


def build_wallet_history_embed(
    customer: discord.Member | discord.User,
    *,
    limit: int = 10,
    staff_view: bool = False,
) -> discord.Embed:
    balance = get_wallet_balance(customer.id)
    transactions = wallet_transaction_history(customer.id, limit=limit)

    embed = discord.Embed(
        title=f"錢包流水｜{getattr(customer, 'display_name', getattr(customer, 'name', customer.id))}",
        color=discord.Color.gold(),
    )

    embed.add_field(
        name="顧客",
        value=getattr(customer, "mention", f"<@{customer.id}>"),
        inline=True,
    )
    embed.add_field(name="目前餘額", value=format_t_amount(balance), inline=True)

    if not transactions:
        embed.add_field(name="最近流水", value="目前沒有錢包流水。", inline=False)
        return embed

    blocks: list[str] = []

    for index, tx in enumerate(transactions, start=1):
        amount = int(tx.get("amount") or 0)
        sign = "+" if amount > 0 else "-"
        tx_type = wallet_transaction_type_label(str(tx.get("type") or ""))
        before = int(tx.get("balance_before") or 0)
        after = int(tx.get("balance_after") or 0)
        created_at = str(tx.get("created_at") or "未紀錄時間")
        order_no = str(tx.get("order_no") or "").strip()
        note = str(tx.get("note") or "").strip()
        operator_id = str(tx.get("operator_discord_id") or "").strip()
        operator_name = str(tx.get("operator_display_name") or "").strip()

        if len(note) > 300:
            note = note[:297] + "…"

        block = [
            f"**{index}. {tx_type}｜{sign}{format_t_amount(abs(amount))}**",
            f"{format_t_amount(before)} → {format_t_amount(after)}",
        ]

        if order_no:
            block.append(f"訂單：`{order_no}`")

        if staff_view and operator_id:
            block.append(f"操作人：<@{operator_id}>")
        elif staff_view and operator_name:
            block.append(f"操作人：{operator_name}")

        if note:
            block.append(f"備註：{note}")

        block.append(f"時間：{created_at}")
        blocks.append("\n".join(block))

    chunks: list[str] = []
    current = ""

    for block in blocks:
        if len(block) > 1000:
            block = block[:997] + "…"

        candidate = block if not current else current + "\n\n" + block
        if len(candidate) <= 1000:
            current = candidate
        else:
            if current:
                chunks.append(current)
            current = block

    if current:
        chunks.append(current)

    for page, chunk in enumerate(chunks, start=1):
        field_name = f"最近 {len(transactions)} 筆流水"
        if len(chunks) > 1:
            field_name += f"（{page}/{len(chunks)}）"
        embed.add_field(name=field_name, value=chunk, inline=False)

    return embed


class WalletCommands(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    def require_customer_staff_or_manager(
        self,
        interaction: discord.Interaction,
    ) -> bool:
        manager_role_id = int(getattr(self.bot, "manager_role_id_value", 0) or 0)
        return (
            isinstance(interaction.user, discord.Member)
            and (
                is_customer_staff(interaction.user)
                or has_role(interaction.user, manager_role_id)
                or interaction.user.guild_permissions.administrator
            )
        )

    @app_commands.command(name="wallet_add", description="客服幫顧客錢包儲值")
    @app_commands.describe(
        customer="要儲值的顧客",
        amount="儲值金額，只能輸入正數",
        note="備註，例如街口儲值、轉帳儲值",
    )
    @app_commands.default_permissions(manage_messages=True)
    async def wallet_add(
        self,
        interaction: discord.Interaction,
        customer: discord.Member,
        amount: int,
        note: str | None = None,
    ):
        if not self.require_customer_staff_or_manager(interaction):
            await interaction.response.send_message(
                "只有客服、店長或管理員可以操作錢包。",
                ephemeral=True,
            )
            return

        if amount <= 0:
            await interaction.response.send_message("儲值金額必須大於 0。", ephemeral=True)
            return

        tx = adjust_customer_wallet_balance(
            customer_id=customer.id,
            amount=amount,
            tx_type="topup",
            operator=interaction.user,
            note=note or "客服儲值",
        )

        embed = build_customer_info_with_wallet_embed(customer, show_staff_notes=True)
        embed.title = "錢包儲值完成"

        await interaction.response.send_message(embed=embed, ephemeral=True)
        await send_wallet_log(
            interaction.guild,
            title="錢包儲值",
            customer=customer,
            operator=interaction.user,
            tx=tx,
        )

    @app_commands.command(
        name="wallet_adjust",
        description="客服修正顧客錢包餘額，基於目前餘額加減",
    )
    @app_commands.describe(
        customer="要修正錢包的顧客",
        amount="異動金額，可正可負，例如 500 或 -300",
        note="修正原因",
    )
    @app_commands.default_permissions(manage_messages=True)
    async def wallet_adjust(
        self,
        interaction: discord.Interaction,
        customer: discord.Member,
        amount: int,
        note: str | None = None,
    ):
        if not self.require_customer_staff_or_manager(interaction):
            await interaction.response.send_message(
                "只有客服、店長或管理員可以操作錢包。",
                ephemeral=True,
            )
            return

        if amount == 0:
            await interaction.response.send_message("異動金額不能為 0。", ephemeral=True)
            return

        try:
            tx = adjust_customer_wallet_balance(
                customer_id=customer.id,
                amount=amount,
                tx_type="adjustment",
                operator=interaction.user,
                note=note or "客服修正",
            )
        except ValueError as exc:
            await interaction.response.send_message(str(exc), ephemeral=True)
            return

        embed = build_customer_info_with_wallet_embed(customer, show_staff_notes=True)
        embed.title = "錢包餘額已修正"

        await interaction.response.send_message(embed=embed, ephemeral=True)
        await send_wallet_log(
            interaction.guild,
            title="錢包餘額修正",
            customer=customer,
            operator=interaction.user,
            tx=tx,
        )

    @app_commands.command(name="wallet_refund", description="客服手動退回顧客錢包餘額")
    @app_commands.describe(
        customer="要退款的顧客",
        amount="退款金額，只能輸入正數",
        note="退款原因",
    )
    @app_commands.default_permissions(manage_messages=True)
    async def wallet_refund(
        self,
        interaction: discord.Interaction,
        customer: discord.Member,
        amount: int,
        note: str | None = None,
    ):
        if not self.require_customer_staff_or_manager(interaction):
            await interaction.response.send_message(
                "只有客服、店長或管理員可以操作錢包。",
                ephemeral=True,
            )
            return

        if amount <= 0:
            await interaction.response.send_message("退款金額必須大於 0。", ephemeral=True)
            return

        tx = adjust_customer_wallet_balance(
            customer_id=customer.id,
            amount=amount,
            tx_type="refund",
            operator=interaction.user,
            note=note or "客服退款",
        )

        embed = build_customer_info_with_wallet_embed(customer, show_staff_notes=True)
        embed.title = "錢包退款完成"

        await interaction.response.send_message(embed=embed, ephemeral=True)
        await send_wallet_log(
            interaction.guild,
            title="錢包退款",
            customer=customer,
            operator=interaction.user,
            tx=tx,
        )

    @app_commands.command(name="wallet_history", description="客服查詢顧客錢包流水")
    @app_commands.describe(
        customer="要查詢的顧客",
        limit="顯示最近幾筆，最多 25 筆",
    )
    @app_commands.default_permissions(manage_messages=True)
    async def wallet_history(
        self,
        interaction: discord.Interaction,
        customer: discord.Member,
        limit: int = 10,
    ):
        if not self.require_customer_staff_or_manager(interaction):
            await interaction.response.send_message(
                "只有客服、店長或管理員可以查詢錢包流水。",
                ephemeral=True,
            )
            return

        embed = build_wallet_history_embed(customer, limit=limit, staff_view=True)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="my_wallet_history", description="查詢自己的錢包流水")
    @app_commands.describe(limit="顯示最近幾筆，最多 25 筆")
    async def my_wallet_history(
        self,
        interaction: discord.Interaction,
        limit: int = 10,
    ):
        if not isinstance(interaction.user, discord.Member):
            await interaction.response.send_message(
                "無法確認你的伺服器身分。",
                ephemeral=True,
            )
            return

        embed = build_wallet_history_embed(interaction.user, limit=limit, staff_view=False)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(
        name="wallet_refund_order",
        description="客服針對指定訂單手動退款到顧客錢包",
    )
    @app_commands.describe(
        customer="要退款的顧客",
        order_no="訂單編號，例如 MO20260610001",
        amount="退款金額，只能輸入正數",
        note="退款原因",
    )
    @app_commands.default_permissions(manage_messages=True)
    async def wallet_refund_order(
        self,
        interaction: discord.Interaction,
        customer: discord.Member,
        order_no: str,
        amount: int,
        note: str | None = None,
    ):
        if not self.require_customer_staff_or_manager(interaction):
            await interaction.response.send_message(
                "只有客服、店長或管理員可以操作錢包退款。",
                ephemeral=True,
            )
            return

        order_no = str(order_no or "").strip()

        if not order_no:
            await interaction.response.send_message("請填寫訂單編號。", ephemeral=True)
            return

        if amount <= 0:
            await interaction.response.send_message("退款金額必須大於 0。", ephemeral=True)
            return

        refund_note = str(note or "").strip() or f"訂單 {order_no} 手動退款"

        tx = adjust_customer_wallet_balance(
            customer_id=customer.id,
            amount=amount,
            tx_type="refund",
            operator=interaction.user,
            order_no=order_no,
            note=refund_note,
        )

        embed = build_wallet_history_embed(customer, limit=5, staff_view=True)
        embed.title = "訂單退款已加回錢包"
        embed.add_field(name="退款訂單", value=f"`{order_no}`", inline=True)
        embed.add_field(name="退款金額", value=format_t_amount(amount), inline=True)

        await interaction.response.send_message(embed=embed, ephemeral=True)
        await send_wallet_log(
            interaction.guild,
            title="錢包訂單退款",
            customer=customer,
            operator=interaction.user,
            tx=tx,
        )

    @app_commands.command(
        name="my_info",
        description="查詢自己的會員資訊、點數與錢包餘額",
    )
    async def my_info(self, interaction: discord.Interaction):
        if not isinstance(interaction.user, discord.Member):
            await interaction.response.send_message(
                "無法確認你的伺服器身分。",
                ephemeral=True,
            )
            return

        embed = build_customer_info_with_wallet_embed(
            interaction.user,
            show_staff_notes=False,
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(WalletCommands(bot))
    guild_id = int(getattr(bot, "guild_id_value", 0) or 0)
    if guild_id:
        bot.tree.copy_global_to(guild=discord.Object(id=guild_id))
