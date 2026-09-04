from __future__ import annotations

import inspect

import discord
from discord import app_commands

from core.permissions import (
    has_role,
    is_customer_staff,
)


REQUIRED_COMMAND_PATHS = (
    "order_search",
    "stored_orders",
    "reward customer_points",
    "customer notes",
    "wallet_history",
    "stats today",
    "stats month",
    "stats top_customers",
    "audit data",
)


def _manager_role_id(interaction: discord.Interaction) -> int:
    return int(
        getattr(
            interaction.client,
            "manager_role_id_value",
            0,
        )
        or 0
    )


def is_staff_operator(
    interaction: discord.Interaction,
) -> bool:
    member = interaction.user

    if not isinstance(member, discord.Member):
        return False

    return bool(
        is_customer_staff(member)
        or has_role(
            member,
            _manager_role_id(interaction),
        )
        or member.guild_permissions.administrator
    )


async def require_staff(
    interaction: discord.Interaction,
) -> bool:
    if is_staff_operator(interaction):
        return True

    message = (
        "只有客服、店長或管理員可以使用客服管理中心。"
    )

    if interaction.response.is_done():
        await interaction.followup.send(
            message,
            ephemeral=True,
        )
    else:
        await interaction.response.send_message(
            message,
            ephemeral=True,
        )

    return False


def resolve_command(
    tree: app_commands.CommandTree,
    path: str,
    guild_id: int | None = None,
):
    parts = [
        item.strip()
        for item in path.split()
        if item.strip()
    ]

    if not parts:
        return None

    command = None

    if guild_id:
        command = tree.get_command(
            parts[0],
            guild=discord.Object(
                id=int(guild_id),
            ),
        )

    if command is None:
        command = tree.get_command(
            parts[0]
        )

    if command is None:
        return None

    for part in parts[1:]:
        getter = getattr(
            command,
            "get_command",
            None,
        )

        if getter is None:
            return None

        command = getter(part)

        if command is None:
            return None

    return command


def validate_staff_panel_commands(
    bot,
    guild_id: int | None,
) -> list[str]:
    missing = []

    for path in REQUIRED_COMMAND_PATHS:
        command = resolve_command(
            bot.tree,
            path,
            guild_id,
        )

        if command is None:
            missing.append(path)

    return missing


async def invoke_existing_command(
    interaction: discord.Interaction,
    path: str,
    **kwargs,
):
    if not await require_staff(interaction):
        return

    command = resolve_command(
        interaction.client.tree,
        path,
        interaction.guild_id,
    )

    if command is None:
        await interaction.response.send_message(
            (
                "找不到對應的系統功能："
                f"`{path}`\n"
                "請通知管理員重新同步機器人指令。"
            ),
            ephemeral=True,
        )
        return

    callback = getattr(
        command,
        "callback",
        None,
    )

    if callback is None:
        await interaction.response.send_message(
            "這個功能目前無法由 Panel 執行。",
            ephemeral=True,
        )
        return

    binding = getattr(
        command,
        "binding",
        None,
    )

    if binding is None:
        result = callback(
            interaction,
            **kwargs,
        )
    else:
        result = callback(
            binding,
            interaction,
            **kwargs,
        )

    if inspect.isawaitable(result):
        await result


def build_menu_embed(
    title: str,
    description: str,
) -> discord.Embed:
    return discord.Embed(
        title=title,
        description=description,
        color=discord.Color.from_rgb(
            95,
            75,
            145,
        ),
    )


class OrderSearchModal(
    discord.ui.Modal,
    title="搜尋訂單",
):
    keyword = discord.ui.TextInput(
        label="關鍵字",
        placeholder="訂單編號、顧客 ID、服務項目；可留空",
        required=False,
        max_length=100,
    )

    status = discord.ui.TextInput(
        label="訂單狀態",
        placeholder="進行中 / 存單 / 結單 / 取消；可留空",
        required=False,
        max_length=20,
    )

    limit = discord.ui.TextInput(
        label="顯示筆數",
        placeholder="1 - 20",
        default="10",
        required=True,
        max_length=2,
    )

    async def on_submit(
        self,
        interaction: discord.Interaction,
    ):
        if not await require_staff(interaction):
            return

        try:
            limit_value = int(
                str(self.limit.value).strip()
                or "10"
            )
        except ValueError:
            await interaction.response.send_message(
                "顯示筆數請輸入 1 到 20 的數字。",
                ephemeral=True,
            )
            return

        limit_value = max(
            1,
            min(
                limit_value,
                20,
            ),
        )

        raw_status = str(
            self.status.value
            or ""
        ).strip().lower()

        aliases = {
            "": "",
            "active": "active",
            "進行中": "active",
            "處理中": "active",
            "stored": "stored",
            "存單": "stored",
            "closed": "closed",
            "結單": "closed",
            "已結單": "closed",
            "cancelled": "cancelled",
            "canceled": "cancelled",
            "取消": "cancelled",
            "已取消": "cancelled",
        }

        if raw_status not in aliases:
            await interaction.response.send_message(
                (
                    "訂單狀態請填："
                    "進行中、存單、結單、取消，"
                    "或留空搜尋全部。"
                ),
                ephemeral=True,
            )
            return

        await invoke_existing_command(
            interaction,
            "order_search",
            keyword=(
                str(self.keyword.value).strip()
                or None
            ),
            status=(
                aliases[raw_status]
                or None
            ),
            limit=limit_value,
        )


class OrderMenuView(discord.ui.View):
    def __init__(self):
        super().__init__(
            timeout=180,
        )

    @discord.ui.button(
        label="搜尋訂單",
        emoji="🔎",
        style=discord.ButtonStyle.primary,
    )
    async def search_order(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ):
        if not await require_staff(interaction):
            return

        await interaction.response.send_modal(
            OrderSearchModal()
        )

    @discord.ui.button(
        label="最近進行中",
        emoji="📋",
        style=discord.ButtonStyle.secondary,
    )
    async def active_orders(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ):
        await invoke_existing_command(
            interaction,
            "order_search",
            keyword=None,
            status="active",
            limit=20,
        )

    @discord.ui.button(
        label="最近已結單",
        emoji="✅",
        style=discord.ButtonStyle.secondary,
    )
    async def closed_orders(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ):
        await invoke_existing_command(
            interaction,
            "order_search",
            keyword=None,
            status="closed",
            limit=20,
        )


class StoredMenuView(discord.ui.View):
    def __init__(self):
        super().__init__(
            timeout=180,
        )

    @discord.ui.button(
        label="管理目前存單",
        emoji="💤",
        style=discord.ButtonStyle.primary,
    )
    async def manage_stored(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ):
        await invoke_existing_command(
            interaction,
            "stored_orders",
            limit=25,
        )

    @discord.ui.button(
        label="搜尋存單",
        emoji="🔎",
        style=discord.ButtonStyle.secondary,
    )
    async def search_stored(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ):
        await invoke_existing_command(
            interaction,
            "order_search",
            keyword=None,
            status="stored",
            limit=20,
        )


async def resolve_selected_member(
    interaction: discord.Interaction,
    value,
) -> discord.Member | None:
    if isinstance(
        value,
        discord.Member,
    ):
        return value

    guild = interaction.guild

    if guild is None:
        return None

    member = guild.get_member(
        int(value.id)
    )

    if member is not None:
        return member

    try:
        return await guild.fetch_member(
            int(value.id)
        )
    except (
        discord.NotFound,
        discord.Forbidden,
        discord.HTTPException,
    ):
        return None


class CustomerReadOnlyView(discord.ui.View):
    def __init__(
        self,
        member: discord.Member,
    ):
        super().__init__(
            timeout=180,
        )

        self.member = member

    @discord.ui.button(
        label="會員資料",
        emoji="💳",
        style=discord.ButtonStyle.primary,
    )
    async def member_info(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ):
        await invoke_existing_command(
            interaction,
            "reward customer_points",
            customer=self.member,
        )

    @discord.ui.button(
        label="顧客備註",
        emoji="📝",
        style=discord.ButtonStyle.secondary,
    )
    async def notes(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ):
        await invoke_existing_command(
            interaction,
            "customer notes",
            customer=self.member,
        )


class MemberWalletReadOnlyView(
    discord.ui.View
):
    def __init__(
        self,
        member: discord.Member,
    ):
        super().__init__(
            timeout=180,
        )

        self.member = member

    @discord.ui.button(
        label="會員資料",
        emoji="💳",
        style=discord.ButtonStyle.primary,
    )
    async def member_info(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ):
        await invoke_existing_command(
            interaction,
            "reward customer_points",
            customer=self.member,
        )

    @discord.ui.button(
        label="錢包流水",
        emoji="💰",
        style=discord.ButtonStyle.secondary,
    )
    async def wallet_history(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ):
        await invoke_existing_command(
            interaction,
            "wallet_history",
            customer=self.member,
            limit=10,
        )


class CustomerSelect(
    discord.ui.UserSelect
):
    def __init__(
        self,
        mode: str,
    ):
        self.mode = mode

        super().__init__(
            placeholder="選擇要操作的顧客",
            min_values=1,
            max_values=1,
        )

    async def callback(
        self,
        interaction: discord.Interaction,
    ):
        if not await require_staff(interaction):
            return

        member = await resolve_selected_member(
            interaction,
            self.values[0],
        )

        if member is None:
            await interaction.response.send_message(
                "找不到這位伺服器成員。",
                ephemeral=True,
            )
            return

        if self.mode == "wallet":
            view = MemberWalletReadOnlyView(
                member
            )

            title = "會員 / 錢包"
            description = (
                f"已選擇：{member.mention}\n"
                "選擇要查看的會員資料。"
            )

        else:
            view = CustomerReadOnlyView(
                member
            )

            title = "顧客管理"
            description = (
                f"已選擇：{member.mention}\n"
                "選擇要查看的顧客資料。"
            )

        await interaction.response.send_message(
            embed=build_menu_embed(
                title,
                description,
            ),
            view=view,
            ephemeral=True,
            allowed_mentions=discord.AllowedMentions(
                users=False,
                roles=False,
                everyone=False,
            ),
        )


class CustomerSelectView(discord.ui.View):
    def __init__(
        self,
        mode: str,
    ):
        super().__init__(
            timeout=180,
        )

        self.add_item(
            CustomerSelect(mode)
        )


class StatsMenuView(discord.ui.View):
    def __init__(self):
        super().__init__(
            timeout=180,
        )

    @discord.ui.button(
        label="今日統計",
        emoji="📅",
        style=discord.ButtonStyle.primary,
    )
    async def today(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ):
        await invoke_existing_command(
            interaction,
            "stats today",
        )

    @discord.ui.button(
        label="本月統計",
        emoji="📊",
        style=discord.ButtonStyle.secondary,
    )
    async def month(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ):
        await invoke_existing_command(
            interaction,
            "stats month",
        )

    @discord.ui.button(
        label="顧客 TOP 10",
        emoji="🏆",
        style=discord.ButtonStyle.secondary,
    )
    async def top_customers(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ):
        await invoke_existing_command(
            interaction,
            "stats top_customers",
        )


class SystemMenuView(discord.ui.View):
    def __init__(self):
        super().__init__(
            timeout=180,
        )

    @discord.ui.button(
        label="資料健康檢查",
        emoji="🩺",
        style=discord.ButtonStyle.primary,
    )
    async def audit_data(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ):
        await invoke_existing_command(
            interaction,
            "audit data",
            limit=10,
        )


class StaffManagementPanelView(
    discord.ui.View
):
    def __init__(self):
        super().__init__(
            timeout=None,
        )

    @discord.ui.button(
        label="訂單管理",
        emoji="📦",
        style=discord.ButtonStyle.primary,
        custom_id="mowan_staff_panel_orders_v1",
        row=0,
    )
    async def orders(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ):
        if not await require_staff(interaction):
            return

        await interaction.response.send_message(
            embed=build_menu_embed(
                "📦 訂單管理",
                (
                    "搜尋訂單或快速查看目前"
                    "進行中／已結單訂單。"
                ),
            ),
            view=OrderMenuView(),
            ephemeral=True,
        )

    @discord.ui.button(
        label="存單管理",
        emoji="💤",
        style=discord.ButtonStyle.secondary,
        custom_id="mowan_staff_panel_stored_v1",
        row=0,
    )
    async def stored(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ):
        if not await require_staff(interaction):
            return

        await interaction.response.send_message(
            embed=build_menu_embed(
                "💤 存單管理",
                (
                    "查看目前所有存單，"
                    "並使用現有存單管理功能。"
                ),
            ),
            view=StoredMenuView(),
            ephemeral=True,
        )

    @discord.ui.button(
        label="顧客管理",
        emoji="👤",
        style=discord.ButtonStyle.secondary,
        custom_id="mowan_staff_panel_customers_v1",
        row=0,
    )
    async def customers(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ):
        if not await require_staff(interaction):
            return

        await interaction.response.send_message(
            embed=build_menu_embed(
                "👤 顧客管理",
                "先選擇要查看的顧客。",
            ),
            view=CustomerSelectView(
                "customer"
            ),
            ephemeral=True,
        )

    @discord.ui.button(
        label="會員 / 錢包",
        emoji="💰",
        style=discord.ButtonStyle.secondary,
        custom_id="mowan_staff_panel_wallet_v1",
        row=1,
    )
    async def wallet(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ):
        if not await require_staff(interaction):
            return

        await interaction.response.send_message(
            embed=build_menu_embed(
                "💰 會員 / 錢包",
                "先選擇要查看的顧客。",
            ),
            view=CustomerSelectView(
                "wallet"
            ),
            ephemeral=True,
        )

    @discord.ui.button(
        label="營運查詢",
        emoji="📊",
        style=discord.ButtonStyle.secondary,
        custom_id="mowan_staff_panel_stats_v1",
        row=1,
    )
    async def stats(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ):
        if not await require_staff(interaction):
            return

        await interaction.response.send_message(
            embed=build_menu_embed(
                "📊 營運查詢",
                (
                    "查看今日、本月營運統計"
                    "與顧客累積消費排行。"
                ),
            ),
            view=StatsMenuView(),
            ephemeral=True,
        )

    @discord.ui.button(
        label="系統工具",
        emoji="🛠️",
        style=discord.ButtonStyle.secondary,
        custom_id="mowan_staff_panel_system_v1",
        row=1,
    )
    async def system(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ):
        if not await require_staff(interaction):
            return

        await interaction.response.send_message(
            embed=build_menu_embed(
                "🛠️ 系統工具",
                (
                    "執行訂單、會員、存單"
                    "與接單資料健康檢查。"
                ),
            ),
            view=SystemMenuView(),
            ephemeral=True,
        )