from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands

from core.permissions import has_role, is_customer_staff
from services.rewards import format_t_amount
from services.wallet_discord_presenter import (
    build_customer_info_with_wallet_embed,
    build_wallet_history_embed,
    wallet_transaction_history,
    wallet_transaction_type_label,
)
from services.wallet_discord_runtime import (
    adjust_customer_wallet_balance,
    send_wallet_log,
)


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
