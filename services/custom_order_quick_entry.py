from __future__ import annotations

import discord
from discord.ext import commands

from services.quick_order_v2 import CUSTOMER_CATEGORY_ID, CUSTOMER_ROLE_ID
from services.rewards import (
    format_customer_notes_for_ticket,
    get_customer_reward_data,
    get_effective_member_level,
)
from services.ticket_identity import build_ticket_channel_name


CUSTOM_ORDER_QUICK_CHANNEL_ID = 1563459313635168256
CUSTOM_ORDER_PANEL_MARKER = "custom-order-quick-entry:v1"
_CUSTOM_ORDER_LEVELS = frozenset(
    {
        "金級魔丸",
        "白金魔丸",
        "鑽石魔丸",
        "白鑽魔丸",
        "黑鑽魔丸",
    }
)


def custom_order_level_name(customer_id: int | str) -> str:
    try:
        data = get_customer_reward_data(int(customer_id))
        level = get_effective_member_level(data)
    except Exception:
        return "普通魔丸"
    return str((level or {}).get("name") or "普通魔丸")


def is_custom_order_level_eligible(level_name: str | None) -> bool:
    return str(level_name or "").strip() in _CUSTOM_ORDER_LEVELS


def assert_custom_order_eligible(customer_id: int | str) -> str:
    level_name = custom_order_level_name(customer_id)
    if not is_custom_order_level_eligible(level_name):
        raise ValueError("自訂單為金級會員以上專屬福利。")
    return level_name


def build_custom_order_entry_embed() -> discord.Embed:
    embed = discord.Embed(
        title="✨ VIP 自訂單｜快速下單",
        description=(
            "**金級會員以上**可提出自訂單需求。\n\n"
            "填寫你想玩的遊戲、玩法／規則與目標後，系統會建立私人客服中心。\n"
            "客服確認內容與價格後，才會正式成立訂單；送出需求本身不會扣款或派單。"
        ),
        color=discord.Color.purple(),
    )
    embed.add_field(
        name="建議先準備",
        value="遊戲／服務內容、玩法或機制、方案／目標，以及其他特殊需求。",
        inline=False,
    )
    embed.set_footer(text=CUSTOM_ORDER_PANEL_MARKER)
    return embed


def _existing_request_channel(
    guild: discord.Guild,
    customer_id: int,
) -> discord.TextChannel | None:
    marker = f"custom_order_customer_id={int(customer_id)};"
    for channel in guild.text_channels:
        if marker in str(channel.topic or ""):
            return channel
    return None


async def _create_custom_order_request_ticket(
    interaction: discord.Interaction,
    *,
    game_or_service: str,
    gameplay_rules: str,
    goal_plan: str,
    extra_request: str,
) -> discord.TextChannel | None:
    guild = interaction.guild
    member = interaction.user
    if guild is None or not isinstance(member, discord.Member):
        await interaction.edit_original_response(content="這個功能只能在伺服器內使用。")
        return None

    try:
        level_name = assert_custom_order_eligible(member.id)
    except ValueError as exc:
        await interaction.edit_original_response(content=str(exc))
        return None

    existing = _existing_request_channel(guild, member.id)
    if existing is not None:
        await interaction.edit_original_response(
            content=f"你目前已有一個自訂單需求客服中心：{existing.mention}\n請先在原票口繼續討論。"
        )
        return existing

    ticket_category = guild.get_channel(CUSTOMER_CATEGORY_ID)
    if not isinstance(ticket_category, discord.CategoryChannel):
        await interaction.edit_original_response(content="找不到下單票口類別，請通知客服。")
        return None

    support_role = guild.get_role(CUSTOMER_ROLE_ID)
    overwrites: dict[discord.abc.Snowflake, discord.PermissionOverwrite] = {
        guild.default_role: discord.PermissionOverwrite(view_channel=False),
        member: discord.PermissionOverwrite(
            view_channel=True,
            send_messages=True,
            read_message_history=True,
            attach_files=True,
            embed_links=True,
        ),
    }
    if support_role is not None:
        overwrites[support_role] = discord.PermissionOverwrite(
            view_channel=True,
            send_messages=True,
            read_message_history=True,
            attach_files=True,
            embed_links=True,
        )
    if guild.me is not None:
        overwrites[guild.me] = discord.PermissionOverwrite(
            view_channel=True,
            send_messages=True,
            read_message_history=True,
            manage_channels=True,
            manage_messages=True,
        )

    ticket: discord.TextChannel | None = None
    try:
        ticket = await guild.create_text_channel(
            name=build_ticket_channel_name("自訂單", member),
            category=ticket_category,
            overwrites=overwrites,
            topic=(
                f"custom_order_customer_id={member.id};"
                f"custom_order_request=1;"
                f"source_channel_id={CUSTOM_ORDER_QUICK_CHANNEL_ID}"
            ),
        )

        embed = discord.Embed(
            title="✨ 自訂單需求",
            description=(
                f"申請人：{member.mention}\n"
                f"目前等級：**{level_name}**\n\n"
                "此票口目前是**需求確認階段**。客服確認內容與價格後，才會正式成立訂單。"
            ),
            color=discord.Color.purple(),
        )
        embed.add_field(name="遊戲／服務內容", value=game_or_service[:1024], inline=False)
        embed.add_field(name="玩法／規則／機制", value=gameplay_rules[:1024], inline=False)
        embed.add_field(name="方案／目標", value=goal_plan[:1024], inline=False)
        if extra_request.strip():
            embed.add_field(name="其他需求", value=extra_request.strip()[:1024], inline=False)

        notes = format_customer_notes_for_ticket(member.id).strip()
        if notes:
            embed.add_field(name="會員資訊", value=notes[:1024], inline=False)

        embed.set_footer(text="自訂單需求｜尚未報價、尚未成立正式訂單")
        await ticket.send(
            content=member.mention,
            embed=embed,
            allowed_mentions=discord.AllowedMentions(
                users=True,
                roles=False,
                everyone=False,
            ),
        )
    except (discord.Forbidden, discord.HTTPException) as exc:
        if ticket is not None:
            try:
                await ticket.delete(reason="自訂單需求建立失敗，自動清理")
            except (discord.Forbidden, discord.HTTPException):
                pass
        await interaction.edit_original_response(
            content=f"建立自訂單客服中心失敗：{type(exc).__name__}。請通知客服。"
        )
        return None

    await interaction.edit_original_response(
        content=f"自訂單需求已送出：{ticket.mention}\n請到私人客服中心等待客服確認內容與價格。"
    )
    return ticket


class CustomOrderRequestModal(discord.ui.Modal):
    def __init__(self) -> None:
        super().__init__(title="VIP 自訂單需求", timeout=300)
        self.game_or_service = discord.ui.TextInput(
            label="遊戲／服務內容",
            placeholder="例如：三角洲端遊／其他遊戲／特殊服務",
            max_length=200,
        )
        self.gameplay_rules = discord.ui.TextInput(
            label="玩法／規則／機制",
            placeholder="請說明想玩的玩法、規則、機制或限制",
            style=discord.TextStyle.paragraph,
            max_length=1000,
        )
        self.goal_plan = discord.ui.TextInput(
            label="方案／目標",
            placeholder="例如：希望達成什麼目標、預計時數／局數等",
            style=discord.TextStyle.paragraph,
            max_length=1000,
        )
        self.extra_request = discord.ui.TextInput(
            label="其他需求（選填）",
            placeholder="指定時段、偏好、補充說明等",
            style=discord.TextStyle.paragraph,
            required=False,
            max_length=1000,
        )
        self.add_item(self.game_or_service)
        self.add_item(self.gameplay_rules)
        self.add_item(self.goal_plan)
        self.add_item(self.extra_request)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True)
        await _create_custom_order_request_ticket(
            interaction,
            game_or_service=str(self.game_or_service.value).strip(),
            gameplay_rules=str(self.gameplay_rules.value).strip(),
            goal_plan=str(self.goal_plan.value).strip(),
            extra_request=str(self.extra_request.value or "").strip(),
        )


class CustomOrderQuickEntryView(discord.ui.View):
    def __init__(self) -> None:
        super().__init__(timeout=None)

    @discord.ui.button(
        label="提出自訂需求",
        emoji="✨",
        style=discord.ButtonStyle.primary,
        custom_id="custom_order_quick_entry:open",
    )
    async def open_request(
        self,
        interaction: discord.Interaction,
        _button: discord.ui.Button,
    ) -> None:
        if not isinstance(interaction.user, discord.Member):
            await interaction.response.send_message(
                "這個功能只能在伺服器內使用。",
                ephemeral=True,
            )
            return
        try:
            assert_custom_order_eligible(interaction.user.id)
        except ValueError as exc:
            await interaction.response.send_message(str(exc), ephemeral=True)
            return
        await interaction.response.send_modal(CustomOrderRequestModal())


async def ensure_custom_order_quick_panel(bot: commands.Bot) -> None:
    await bot.wait_until_ready()
    channel = bot.get_channel(CUSTOM_ORDER_QUICK_CHANNEL_ID)
    if not isinstance(channel, discord.TextChannel):
        try:
            fetched = await bot.fetch_channel(CUSTOM_ORDER_QUICK_CHANNEL_ID)
            channel = fetched if isinstance(fetched, discord.TextChannel) else None
        except (discord.NotFound, discord.Forbidden, discord.HTTPException):
            channel = None

    if not isinstance(channel, discord.TextChannel):
        print(
            f"[custom-order-quick] channel not found: {CUSTOM_ORDER_QUICK_CHANNEL_ID}",
            flush=True,
        )
        return

    target: discord.Message | None = None
    try:
        async for message in channel.history(limit=50):
            if bot.user is not None and message.author.id != bot.user.id:
                continue
            for embed in message.embeds:
                footer = str(getattr(getattr(embed, "footer", None), "text", "") or "")
                title = str(getattr(embed, "title", "") or "")
                if footer == CUSTOM_ORDER_PANEL_MARKER or title in {
                    "✨ VIP 自訂單｜快速下單",
                    "✨ VIP 自訂單｜下單",
                }:
                    target = message
                    break
            if target is not None:
                break
    except (discord.Forbidden, discord.HTTPException):
        pass

    try:
        if target is None:
            await channel.send(
                embed=build_custom_order_entry_embed(),
                view=CustomOrderQuickEntryView(),
            )
        else:
            await target.edit(
                embed=build_custom_order_entry_embed(),
                view=CustomOrderQuickEntryView(),
            )
    except (discord.Forbidden, discord.HTTPException) as exc:
        print(
            f"[custom-order-quick] panel sync failed: {type(exc).__name__}: {exc}",
            flush=True,
        )


def install_custom_order_quick_entry(bot: commands.Bot) -> None:
    if not getattr(bot, "_custom_order_quick_view_registered", False):
        bot.add_view(CustomOrderQuickEntryView())
        bot._custom_order_quick_view_registered = True

    if not getattr(bot, "_custom_order_quick_panel_task_started", False):
        bot._custom_order_quick_panel_task_started = True
        bot.loop.create_task(ensure_custom_order_quick_panel(bot))


__all__ = [
    "CUSTOM_ORDER_QUICK_CHANNEL_ID",
    "CustomOrderQuickEntryView",
    "assert_custom_order_eligible",
    "build_custom_order_entry_embed",
    "install_custom_order_quick_entry",
    "is_custom_order_level_eligible",
]
