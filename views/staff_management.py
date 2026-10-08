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
    "fix_order_amount",
    "fix_order_customer",
    "resend_dispatch",
    "reward customer_points",
    "reward adjust_points",
    "reward add_purchase",
    "customer notes",
    "customer add_note",
    "customer remove_note",
    "wallet_history",
    "wallet_add",
    "wallet_adjust",
    "wallet_refund",
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



def parse_yes_no(
    value: str,
    *,
    default: bool = True,
) -> bool | None:
    text = str(
        value
        or ""
    ).strip().lower()

    if not text:
        return default

    yes_values = {
        "是",
        "要",
        "有",
        "yes",
        "y",
        "true",
        "1",
    }

    no_values = {
        "否",
        "不要",
        "沒有",
        "no",
        "n",
        "false",
        "0",
    }

    if text in yes_values:
        return True

    if text in no_values:
        return False

    return None


class ConfirmCommandView(
    discord.ui.View
):
    def __init__(
        self,
        *,
        actor_id: int,
        command_path: str,
        command_kwargs: dict,
    ):
        super().__init__(
            timeout=60,
        )

        self.actor_id = int(
            actor_id
        )

        self.command_path = str(
            command_path
        )

        self.command_kwargs = dict(
            command_kwargs
        )

        self.completed = False

    async def interaction_check(
        self,
        interaction: discord.Interaction,
    ) -> bool:
        if int(
            interaction.user.id
        ) == self.actor_id:
            return True

        await interaction.response.send_message(
            "這個確認操作只能由原本發起的客服執行。",
            ephemeral=True,
        )

        return False

    @discord.ui.button(
        label="確認執行",
        emoji="✅",
        style=discord.ButtonStyle.danger,
    )
    async def confirm(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ):
        if self.completed:
            await interaction.response.send_message(
                "這個操作已經處理過了。",
                ephemeral=True,
            )
            return

        self.completed = True

        for item in self.children:
            item.disabled = True

        try:
            await invoke_existing_command(
                interaction,
                self.command_path,
                **self.command_kwargs,
            )

        except Exception as exc:
            self.completed = False

            for item in self.children:
                item.disabled = False

            message = (
                "執行失敗："
                f"{type(exc).__name__}: {exc}"
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

    @discord.ui.button(
        label="取消",
        emoji="✖️",
        style=discord.ButtonStyle.secondary,
    )
    async def cancel(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ):
        if self.completed:
            await interaction.response.send_message(
                "這個操作已經處理過了。",
                ephemeral=True,
            )
            return

        self.completed = True

        await interaction.response.edit_message(
            embed=build_menu_embed(
                "已取消",
                "沒有修改任何資料。",
            ),
            view=None,
        )


async def show_confirmation(
    interaction: discord.Interaction,
    *,
    title: str,
    description: str,
    command_path: str,
    command_kwargs: dict,
):
    if not await require_staff(
        interaction
    ):
        return

    embed = discord.Embed(
        title=f"⚠️ {title}",
        description=(
            description
            + "\n\n"
            + "**請再次確認後再執行。**"
        ),
        color=discord.Color.orange(),
    )

    await interaction.response.send_message(
        embed=embed,
        view=ConfirmCommandView(
            actor_id=interaction.user.id,
            command_path=command_path,
            command_kwargs=command_kwargs,
        ),
        ephemeral=True,
        allowed_mentions=discord.AllowedMentions(
            users=False,
            roles=False,
            everyone=False,
        ),
    )


class FixOrderAmountModal(
    discord.ui.Modal,
    title="修正訂單金額",
):
    order = discord.ui.TextInput(
        label="訂單編號或票口 ID",
        placeholder="MO2026... 或票口頻道 ID",
        max_length=100,
    )

    amount = discord.ui.TextInput(
        label="新金額",
        placeholder="例如 1275",
        max_length=12,
    )

    adjust_customer = discord.ui.TextInput(
        label="同步會員累積",
        placeholder="是 / 否",
        default="是",
        max_length=10,
    )

    async def on_submit(
        self,
        interaction: discord.Interaction,
    ):
        try:
            amount = int(
                str(
                    self.amount.value
                )
                .replace(
                    ",",
                    "",
                )
                .strip()
            )

        except ValueError:
            await interaction.response.send_message(
                "新金額請輸入數字。",
                ephemeral=True,
            )
            return

        if amount < 0:
            await interaction.response.send_message(
                "新金額不能小於 0。",
                ephemeral=True,
            )
            return

        adjust = parse_yes_no(
            str(
                self.adjust_customer.value
            ),
            default=True,
        )

        if adjust is None:
            await interaction.response.send_message(
                "同步會員累積請輸入「是」或「否」。",
                ephemeral=True,
            )
            return

        order = str(
            self.order.value
        ).strip()

        await show_confirmation(
            interaction,
            title="修正訂單金額",
            description=(
                f"訂單：`{order}`\n"
                f"新金額：**{amount:,}T**\n"
                f"同步會員累積："
                f"{'是' if adjust else '否'}"
            ),
            command_path="fix_order_amount",
            command_kwargs={
                "order": order,
                "amount": amount,
                "adjust_customer": adjust,
            },
        )


class ResendDispatchModal(
    discord.ui.Modal,
    title="重新派單",
):
    channel_id = discord.ui.TextInput(
        label="票口頻道 ID",
        placeholder="例如 1506962556928131112",
        max_length=30,
    )

    async def on_submit(
        self,
        interaction: discord.Interaction,
    ):
        channel_id = str(
            self.channel_id.value
        ).strip()

        if not channel_id.isdigit():
            await interaction.response.send_message(
                "票口頻道 ID 請輸入純數字。",
                ephemeral=True,
            )
            return

        await show_confirmation(
            interaction,
            title="重新派單",
            description=(
                f"票口頻道 ID："
                f"`{channel_id}`\n\n"
                "系統會清理這張票口的舊接單暫存，"
                "並重新建立新的派單面板。"
            ),
            command_path="resend_dispatch",
            command_kwargs={
                "order_channel_id": channel_id,
            },
        )


class FixOrderCustomerSelect(
    discord.ui.UserSelect
):
    def __init__(
        self,
        *,
        order: str,
        adjust_customer: bool,
    ):
        self.order = order

        self.adjust_customer = bool(
            adjust_customer
        )

        super().__init__(
            placeholder="選擇正確的顧客",
            min_values=1,
            max_values=1,
        )

    async def callback(
        self,
        interaction: discord.Interaction,
    ):
        if not await require_staff(
            interaction
        ):
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

        await show_confirmation(
            interaction,
            title="修正訂單顧客",
            description=(
                f"訂單：`{self.order}`\n"
                f"新顧客：{member.mention}\n"
                "若訂單已結單，"
                f"會員累積搬移："
                f"{'是' if self.adjust_customer else '否'}"
            ),
            command_path="fix_order_customer",
            command_kwargs={
                "order": self.order,
                "customer": member,
                "adjust_customer":
                    self.adjust_customer,
            },
        )


class FixOrderCustomerSelectView(
    discord.ui.View
):
    def __init__(
        self,
        *,
        order: str,
        adjust_customer: bool,
    ):
        super().__init__(
            timeout=120,
        )

        self.add_item(
            FixOrderCustomerSelect(
                order=order,
                adjust_customer=adjust_customer,
            )
        )


class FixOrderCustomerModal(
    discord.ui.Modal,
    title="修正訂單顧客",
):
    order = discord.ui.TextInput(
        label="訂單編號或票口 ID",
        placeholder="MO2026... 或票口頻道 ID",
        max_length=100,
    )

    adjust_customer = discord.ui.TextInput(
        label="搬移已結單會員累積",
        placeholder="是 / 否",
        default="是",
        max_length=10,
    )

    async def on_submit(
        self,
        interaction: discord.Interaction,
    ):
        adjust = parse_yes_no(
            str(
                self.adjust_customer.value
            ),
            default=True,
        )

        if adjust is None:
            await interaction.response.send_message(
                "搬移會員累積請輸入「是」或「否」。",
                ephemeral=True,
            )
            return

        order = str(
            self.order.value
        ).strip()

        await interaction.response.send_message(
            embed=build_menu_embed(
                "修正訂單顧客",
                (
                    f"訂單：`{order}`\n"
                    "請選擇正確的顧客。"
                ),
            ),
            view=FixOrderCustomerSelectView(
                order=order,
                adjust_customer=adjust,
            ),
            ephemeral=True,
        )


class AddCustomerNoteModal(
    discord.ui.Modal
):
    def __init__(
        self,
        member: discord.Member,
    ):
        super().__init__(
            title="新增顧客備註"
        )

        self.member = member

        self.note = discord.ui.TextInput(
            label="備註內容",
            style=discord.TextStyle.paragraph,
            max_length=500,
        )

        self.blacklist = discord.ui.TextInput(
            label="標記黑名單 / 高風險",
            placeholder="是 / 否",
            default="否",
            max_length=10,
        )

        self.add_item(
            self.note
        )

        self.add_item(
            self.blacklist
        )

    async def on_submit(
        self,
        interaction: discord.Interaction,
    ):
        blacklist = parse_yes_no(
            str(
                self.blacklist.value
            ),
            default=False,
        )

        if blacklist is None:
            await interaction.response.send_message(
                "黑名單欄位請輸入「是」或「否」。",
                ephemeral=True,
            )
            return

        note = str(
            self.note.value
        ).strip()

        if not note:
            await interaction.response.send_message(
                "備註內容不能空白。",
                ephemeral=True,
            )
            return

        await show_confirmation(
            interaction,
            title="新增顧客備註",
            description=(
                f"顧客：{self.member.mention}\n"
                f"黑名單 / 高風險："
                f"{'是' if blacklist else '否'}\n"
                f"備註：{note}"
            ),
            command_path="customer add_note",
            command_kwargs={
                "customer": self.member,
                "note": note,
                "blacklist": blacklist,
            },
        )


class RemoveCustomerNoteModal(
    discord.ui.Modal
):
    def __init__(
        self,
        member: discord.Member,
    ):
        super().__init__(
            title="刪除顧客備註"
        )

        self.member = member

        self.index = discord.ui.TextInput(
            label="備註編號",
            placeholder="先查看備註，再輸入要刪除的編號",
            max_length=4,
        )

        self.add_item(
            self.index
        )

    async def on_submit(
        self,
        interaction: discord.Interaction,
    ):
        try:
            index = int(
                str(
                    self.index.value
                ).strip()
            )

        except ValueError:
            await interaction.response.send_message(
                "備註編號請輸入數字。",
                ephemeral=True,
            )
            return

        if index < 1:
            await interaction.response.send_message(
                "備註編號必須從 1 開始。",
                ephemeral=True,
            )
            return

        await show_confirmation(
            interaction,
            title="刪除顧客備註",
            description=(
                f"顧客：{self.member.mention}\n"
                f"刪除第 **{index}** 筆備註"
            ),
            command_path="customer remove_note",
            command_kwargs={
                "customer": self.member,
                "index": index,
            },
        )


class WalletActionModal(
    discord.ui.Modal
):
    MODES = {
        "topup": {
            "title": "客服儲值",
            "command": "wallet_add",
            "positive": True,
        },
        "adjust": {
            "title": "修正錢包餘額",
            "command": "wallet_adjust",
            "positive": False,
        },
        "refund": {
            "title": "退款到錢包",
            "command": "wallet_refund",
            "positive": True,
        },
    }

    def __init__(
        self,
        member: discord.Member,
        mode: str,
    ):
        config = self.MODES[
            mode
        ]

        super().__init__(
            title=config["title"]
        )

        self.member = member
        self.mode = mode
        self.config = config

        self.amount = discord.ui.TextInput(
            label="金額",
            placeholder=(
                "例如 12000"
                if mode != "adjust"
                else "例如 500 或 -300"
            ),
            max_length=12,
        )

        self.note = discord.ui.TextInput(
            label="原因 / 備註",
            required=False,
            max_length=200,
        )

        self.add_item(
            self.amount
        )

        self.add_item(
            self.note
        )

    async def on_submit(
        self,
        interaction: discord.Interaction,
    ):
        try:
            amount = int(
                str(
                    self.amount.value
                )
                .replace(
                    ",",
                    "",
                )
                .strip()
            )

        except ValueError:
            await interaction.response.send_message(
                "金額請輸入整數。",
                ephemeral=True,
            )
            return

        if self.config["positive"]:

            if amount <= 0:
                await interaction.response.send_message(
                    "金額必須大於 0。",
                    ephemeral=True,
                )
                return

        elif amount == 0:
            await interaction.response.send_message(
                "異動金額不能為 0。",
                ephemeral=True,
            )
            return

        note = str(
            self.note.value
            or ""
        ).strip() or None

        amount_display = (
            f"{amount:,}T"
            if self.mode != "adjust"
            else f"{amount:+,}T"
        )

        await show_confirmation(
            interaction,
            title=self.config["title"],
            description=(
                f"顧客：{self.member.mention}\n"
                f"金額：**{amount_display}**\n"
                f"備註：{note or '未填寫'}"
            ),
            command_path=self.config["command"],
            command_kwargs={
                "customer": self.member,
                "amount": amount,
                "note": note,
            },
        )


class AdjustPointsModal(
    discord.ui.Modal
):
    def __init__(
        self,
        member: discord.Member,
    ):
        super().__init__(
            title="調整會員點數"
        )

        self.member = member

        self.points = discord.ui.TextInput(
            label="點數異動",
            placeholder="例如 10 或 -10",
            max_length=10,
        )

        self.reason = discord.ui.TextInput(
            label="原因",
            required=False,
            max_length=200,
        )

        self.add_item(
            self.points
        )

        self.add_item(
            self.reason
        )

    async def on_submit(
        self,
        interaction: discord.Interaction,
    ):
        try:
            points = int(
                str(
                    self.points.value
                ).strip()
            )

        except ValueError:
            await interaction.response.send_message(
                "點數請輸入整數。",
                ephemeral=True,
            )
            return

        if points == 0:
            await interaction.response.send_message(
                "點數異動不能為 0。",
                ephemeral=True,
            )
            return

        reason = str(
            self.reason.value
            or ""
        ).strip() or None

        await show_confirmation(
            interaction,
            title="調整會員點數",
            description=(
                f"顧客：{self.member.mention}\n"
                f"點數異動："
                f"**{points:+,} 點**\n"
                f"原因：{reason or '未填寫'}"
            ),
            command_path="reward adjust_points",
            command_kwargs={
                "customer": self.member,
                "points": points,
                "reason": reason,
            },
        )


class AddPurchaseModal(
    discord.ui.Modal
):
    def __init__(
        self,
        member: discord.Member,
    ):
        super().__init__(
            title="補登歷史消費"
        )

        self.member = member

        self.amount = discord.ui.TextInput(
            label="消費金額",
            placeholder="例如 900",
            max_length=12,
        )

        self.date = discord.ui.TextInput(
            label="完成日期",
            placeholder="例如 20260905",
            max_length=20,
        )

        self.note = discord.ui.TextInput(
            label="備註",
            required=False,
            max_length=200,
        )

        self.add_item(
            self.amount
        )

        self.add_item(
            self.date
        )

        self.add_item(
            self.note
        )

    async def on_submit(
        self,
        interaction: discord.Interaction,
    ):
        try:
            amount = int(
                str(
                    self.amount.value
                )
                .replace(
                    ",",
                    "",
                )
                .strip()
            )

        except ValueError:
            await interaction.response.send_message(
                "消費金額請輸入整數。",
                ephemeral=True,
            )
            return

        if amount <= 0:
            await interaction.response.send_message(
                "消費金額必須大於 0。",
                ephemeral=True,
            )
            return

        date = str(
            self.date.value
        ).strip()

        if not date:
            await interaction.response.send_message(
                "完成日期不能空白。",
                ephemeral=True,
            )
            return

        note = str(
            self.note.value
            or ""
        ).strip() or None

        await show_confirmation(
            interaction,
            title="補登歷史消費",
            description=(
                f"顧客：{self.member.mention}\n"
                f"金額：**{amount:,}T**\n"
                f"日期：`{date}`\n"
                f"備註：{note or '未填寫'}"
            ),
            command_path="reward add_purchase",
            command_kwargs={
                "customer": self.member,
                "amount": amount,
                "date": date,
                "note": note,
            },
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
        row=0,
    )
    async def search_order(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ):
        if not await require_staff(
            interaction
        ):
            return

        await interaction.response.send_modal(
            OrderSearchModal()
        )

    @discord.ui.button(
        label="最近進行中",
        emoji="📋",
        style=discord.ButtonStyle.secondary,
        row=0,
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
        row=0,
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

    @discord.ui.button(
        label="修正金額",
        emoji="💵",
        style=discord.ButtonStyle.secondary,
        row=1,
    )
    async def fix_amount(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ):
        if not await require_staff(
            interaction
        ):
            return

        await interaction.response.send_modal(
            FixOrderAmountModal()
        )

    @discord.ui.button(
        label="修正顧客",
        emoji="👤",
        style=discord.ButtonStyle.secondary,
        row=1,
    )
    async def fix_customer(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ):
        if not await require_staff(
            interaction
        ):
            return

        await interaction.response.send_modal(
            FixOrderCustomerModal()
        )

    @discord.ui.button(
        label="重新派單",
        emoji="🔄",
        style=discord.ButtonStyle.secondary,
        row=1,
    )
    async def resend(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ):
        if not await require_staff(
            interaction
        ):
            return

        await interaction.response.send_modal(
            ResendDispatchModal()
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
        row=0,
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
        row=0,
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

    @discord.ui.button(
        label="新增備註",
        emoji="➕",
        style=discord.ButtonStyle.secondary,
        row=1,
    )
    async def add_note(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ):
        if not await require_staff(
            interaction
        ):
            return

        await interaction.response.send_modal(
            AddCustomerNoteModal(
                self.member
            )
        )

    @discord.ui.button(
        label="刪除備註",
        emoji="🗑️",
        style=discord.ButtonStyle.danger,
        row=1,
    )
    async def remove_note(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ):
        if not await require_staff(
            interaction
        ):
            return

        await interaction.response.send_modal(
            RemoveCustomerNoteModal(
                self.member
            )
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
        row=0,
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
        emoji="📒",
        style=discord.ButtonStyle.secondary,
        row=0,
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

    @discord.ui.button(
        label="客服儲值",
        emoji="💰",
        style=discord.ButtonStyle.success,
        row=1,
    )
    async def wallet_topup(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ):
        if not await require_staff(
            interaction
        ):
            return

        await interaction.response.send_modal(
            WalletActionModal(
                self.member,
                "topup",
            )
        )

    @discord.ui.button(
        label="錢包調整",
        emoji="🧮",
        style=discord.ButtonStyle.secondary,
        row=1,
    )
    async def wallet_adjust(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ):
        if not await require_staff(
            interaction
        ):
            return

        await interaction.response.send_modal(
            WalletActionModal(
                self.member,
                "adjust",
            )
        )

    @discord.ui.button(
        label="退款",
        emoji="↩️",
        style=discord.ButtonStyle.danger,
        row=1,
    )
    async def wallet_refund(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ):
        if not await require_staff(
            interaction
        ):
            return

        await interaction.response.send_modal(
            WalletActionModal(
                self.member,
                "refund",
            )
        )

    @discord.ui.button(
        label="調整點數",
        emoji="⭐",
        style=discord.ButtonStyle.secondary,
        row=2,
    )
    async def points(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ):
        if not await require_staff(
            interaction
        ):
            return

        await interaction.response.send_modal(
            AdjustPointsModal(
                self.member
            )
        )

    @discord.ui.button(
        label="補登消費",
        emoji="🧾",
        style=discord.ButtonStyle.secondary,
        row=2,
    )
    async def purchase(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ):
        if not await require_staff(
            interaction
        ):
            return

        await interaction.response.send_modal(
            AddPurchaseModal(
                self.member
            )
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
                "選擇要查看或操作的會員功能。"
            )

        else:
            view = CustomerReadOnlyView(
                member
            )

            title = "顧客管理"
            description = (
                f"已選擇：{member.mention}\n"
                "選擇要查看或操作的顧客功能。"
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