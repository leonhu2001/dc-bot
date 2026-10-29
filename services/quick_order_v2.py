from __future__ import annotations

from dataclasses import replace

import discord
from discord.ext import commands

from core.config import config_int
from core.database import remember_order_data
from services.orders import ORDER_CATEGORY_LABELS, ORDER_ITEM_GROUPS_BY_CATEGORY
from services.rewards import format_customer_notes_for_ticket
from services.ticket_identity import build_ticket_channel_name
from services.vip_timer import VIP_TIMER_CATEGORY, VIP_TIMER_CATEGORY_LABEL
from services.vip_timer_self_service import (
    assert_vip_timer_self_service_eligible,
    prepare_vip_timer_draft,
    refresh_vip_timer_self_service_catalog,
)


QUICK_ORDER_V2_CHANNELS = {
    "delta": 1562940108246753331,
    "valorant": 1562940127976890509,
    "lol": 1562940161313087498,
    "apex": 1562940146632888450,
    "steam": 1562940249171042415,
    "vip_timer": 1562941512504053822,
}

CUSTOMER_CATEGORY_ID = config_int("CUSTOMER_CATEGORY_ID", 1483895536938651809)
CUSTOMER_ROLE_ID = config_int("CUSTOMER_ROLE_ID", 1482084782031638548)
_PANEL_MARKER_PREFIX = "quick-order-v2"
_PATCH_INSTALLED = False
_ORIGINAL_VIEW_INIT = None
_ORIGINAL_PANEL_BUILDER = None
VIP_TIMER_CUSTOM_ORDER_VALUE = "__vip_timer_custom_order__"

_GAME_ENTRY_META = {
    QUICK_ORDER_V2_CHANNELS["valorant"]: ("valorant", "🎯 特戰英豪"),
    QUICK_ORDER_V2_CHANNELS["lol"]: ("lol", "⚔️ 英雄聯盟"),
    QUICK_ORDER_V2_CHANNELS["apex"]: ("apex", "🔺 APEX"),
    QUICK_ORDER_V2_CHANNELS["steam"]: ("steam", "🎮 STEAM 遊戲"),
}

_DELTA_BUTTONS = (
    ("🖥️", "端遊", "delta_desktop_basic", discord.ButtonStyle.primary),
    ("📱", "手遊", "delta_mobile_basic", discord.ButtonStyle.success),
    ("🎉", "趣味單", "delta_desktop_fun", discord.ButtonStyle.secondary),
    ("🛠️", "代肝代解", "farm", discord.ButtonStyle.secondary),
)

_VIP_TIMER_GAME_ORDER = (
    "三角洲｜端遊",
    "三角洲｜手遊",
    "特戰英豪",
    "英雄聯盟",
    "APEX",
    "STEAM",
)


def _marker(channel_id: int) -> str:
    return f"{_PANEL_MARKER_PREFIX}:{channel_id}"


def _groups(category: str) -> list[str]:
    result: list[str] = []
    for value in ORDER_ITEM_GROUPS_BY_CATEGORY.get(category, []):
        text = str(value or "").strip()
        if text and text not in result:
            result.append(text)
    return result


def _options(category: str) -> list[discord.SelectOption]:
    category_label = str(ORDER_CATEGORY_LABELS.get(category, category))
    return [
        discord.SelectOption(
            label=group[:100],
            value=group[:100],
            description=category_label[:100],
        )
        for group in _groups(category)[:25]
    ]


def _vip_timer_game_display_label(group_label: str) -> str:
    text = str(group_label or "").strip()
    if "三角洲" in text and "端遊" in text:
        return "三角洲｜端遊"
    if "三角洲" in text and "手遊" in text:
        return "三角洲｜手遊"
    if text.upper().startswith("STEAM"):
        return "STEAM"
    return text


def _vip_timer_entry_rows() -> list[tuple[str, str]]:
    """Return (display label, catalog group value) for the public timer entry."""
    refresh_vip_timer_self_service_catalog()
    from services.orders import SELF_SERVICE_ORDER_CATALOG

    rows: list[tuple[str, str]] = []
    seen_values: set[str] = set()
    for group in list(SELF_SERVICE_ORDER_CATALOG.get(VIP_TIMER_CATEGORY, ()) or ()):
        if not isinstance(group, dict):
            continue
        value = str(group.get("label") or "").strip()
        details = list(group.get("details") or ())
        if not value or not details or value in seen_values:
            continue
        if "自訂" in value or value in {"其他", "其他／自訂", "其他/自訂"}:
            continue
        display = _vip_timer_game_display_label(value)
        if not display:
            continue
        seen_values.add(value)
        rows.append((display, value))

    preferred = {label: index for index, label in enumerate(_VIP_TIMER_GAME_ORDER)}
    rows.sort(key=lambda row: (preferred.get(row[0], len(preferred)), row[0]))
    rows = rows[:24]
    rows.append(("自訂單", VIP_TIMER_CUSTOM_ORDER_VALUE))
    return rows


def build_entry_embed(channel_id: int) -> discord.Embed:
    if channel_id == QUICK_ORDER_V2_CHANNELS["delta"]:
        embed = discord.Embed(
            title="🟢 三角洲行動｜下單",
            description=(
                "先選服務類型，再選服務；**確認後才會建立私人票口**。\n"
                "票口內再選規格、陪玩人數與時長／數量。\n\n"
                "🖥️ **端遊**｜一般陪玩、技術陪、甜蜜單、教學等\n"
                "📱 **手遊**｜手遊陪玩與相關方案\n"
                "🎉 **趣味單**｜特殊趣味玩法\n"
                "🛠️ **代肝代解**｜賽季、任務與代解服務"
            ),
            color=discord.Color.green(),
        )
    elif channel_id == QUICK_ORDER_V2_CHANNELS["vip_timer"]:
        embed = discord.Embed(
            title="💎 VIP 自由計時｜下單",
            description=(
                "請先選擇**遊戲類型**，確認後建立私人票口。\n"
                "一般遊戲會在票口內再選起始玩法；接滿後開始計時，中途可切換遊戲／玩法。\n"
                "也可選 **自訂單**，改由自訂需求流程填寫內容並由客服報價。\n"
                "自由計時結束後依實際遊玩時間結算，先玩後付。"
            ),
            color=discord.Color.gold(),
        )
    else:
        _, title = _GAME_ENTRY_META[channel_id]
        embed = discord.Embed(
            title=f"{title}｜下單",
            description=(
                "請選擇你要的服務，確認後才會建立私人票口。\n"
                "票口內再選規格、陪玩人數與時長／局數。"
            ),
            color=discord.Color.purple(),
        )

    embed.set_footer(text=_marker(channel_id))
    return embed


class QuickServiceSelect(discord.ui.Select):
    def __init__(self, *, category: str, source_channel_id: int, persistent: bool):
        self.category = category
        self.source_channel_id = source_channel_id
        options = _options(category)
        disabled = not options
        if not options:
            options = [
                discord.SelectOption(
                    label="目前沒有可下單服務",
                    value="__empty__",
                )
            ]

        super().__init__(
            placeholder="請選擇服務",
            options=options,
            min_values=1,
            max_values=1,
            disabled=disabled,
            custom_id=(
                f"quick_order_v2_service_{category}"
                if persistent
                else f"quick_order_v2_service_tmp_{category}"
            ),
        )

    async def callback(self, interaction: discord.Interaction):
        if not self.values or self.values[0] == "__empty__":
            await interaction.response.defer()
            return

        await _send_confirmation(
            interaction,
            category=self.category,
            item_group=self.values[0],
            source_channel_id=self.source_channel_id,
        )


class QuickGameEntryView(discord.ui.View):
    def __init__(self, *, category: str, source_channel_id: int):
        super().__init__(timeout=None)
        self.add_item(
            QuickServiceSelect(
                category=category,
                source_channel_id=source_channel_id,
                persistent=True,
            )
        )


class QuickDeltaCategoryButton(discord.ui.Button):
    def __init__(
        self,
        *,
        emoji: str,
        label: str,
        category: str,
        style: discord.ButtonStyle,
        row: int,
    ):
        self.category = category
        self.category_label = label
        self.category_emoji = emoji
        super().__init__(
            label=label,
            emoji=emoji,
            style=style,
            row=row,
            custom_id=f"quick_order_v2_delta_{category}",
        )

    async def callback(self, interaction: discord.Interaction):
        if not _options(self.category):
            await interaction.response.send_message(
                "這個分類目前沒有可下單服務。",
                ephemeral=True,
            )
            return

        embed = discord.Embed(
            title=f"{self.category_emoji} 三角洲行動｜{self.category_label}",
            description="請選擇服務。選完後會先讓你確認，不會立刻開票口。",
            color=discord.Color.green(),
        )
        view = discord.ui.View(timeout=180)
        view.add_item(
            QuickServiceSelect(
                category=self.category,
                source_channel_id=QUICK_ORDER_V2_CHANNELS["delta"],
                persistent=False,
            )
        )
        await interaction.response.send_message(
            embed=embed,
            view=view,
            ephemeral=True,
        )


class QuickDeltaEntryView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        for index, (emoji, label, category, style) in enumerate(_DELTA_BUTTONS):
            self.add_item(
                QuickDeltaCategoryButton(
                    emoji=emoji,
                    label=label,
                    category=category,
                    style=style,
                    row=0 if index < 3 else 1,
                )
            )


class QuickVipGameSelect(discord.ui.Select):
    def __init__(self):
        rows = _vip_timer_entry_rows()
        options = [
            discord.SelectOption(
                label=label[:100],
                value=value[:100],
                description=(
                    "自訂需求｜客服報價"
                    if value == VIP_TIMER_CUSTOM_ORDER_VALUE
                    else "自由計時｜起始遊戲"
                ),
            )
            for label, value in rows
        ]
        disabled = not options
        if not options:
            options = [
                discord.SelectOption(
                    label="目前沒有可用計時方案",
                    value="__empty__",
                )
            ]

        super().__init__(
            placeholder="請選擇遊戲類型",
            options=options,
            min_values=1,
            max_values=1,
            disabled=disabled,
            custom_id="quick_order_v2_vip_timer_game",
        )

    async def callback(self, interaction: discord.Interaction):
        if not self.values or self.values[0] == "__empty__":
            await interaction.response.defer()
            return
        if not isinstance(interaction.user, discord.Member):
            await interaction.response.send_message(
                "無法確認你的會員身分。",
                ephemeral=True,
            )
            return

        selected = self.values[0]
        if selected == VIP_TIMER_CUSTOM_ORDER_VALUE:
            from services.custom_order_quick_entry import CustomOrderCompanionCountView

            await interaction.response.send_message(
                "先選擇這張自訂單需要幾位陪玩，再填寫遊戲、玩法／規則與目標。\n"
                "客服確認需求後會在自訂單票口完成報價。",
                view=CustomOrderCompanionCountView(interaction.user.id),
                ephemeral=True,
            )
            return

        try:
            assert_vip_timer_self_service_eligible(
                interaction.user.id,
                check_open_order=True,
            )
        except ValueError as exc:
            await interaction.response.send_message(str(exc), ephemeral=True)
            return

        await _send_confirmation(
            interaction,
            category=VIP_TIMER_CATEGORY,
            item_group=selected,
            source_channel_id=QUICK_ORDER_V2_CHANNELS["vip_timer"],
        )


class QuickVipEntryView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(QuickVipGameSelect())


class QuickOrderConfirmView(discord.ui.View):
    def __init__(
        self,
        *,
        customer_id: int,
        category: str,
        item_group: str,
        source_channel_id: int,
    ):
        super().__init__(timeout=180)
        self.customer_id = customer_id
        self.category = category
        self.item_group = item_group
        self.source_channel_id = source_channel_id
        self.opening = False

    @discord.ui.button(
        label="已閱讀下單須知，建立票口",
        emoji="✅",
        style=discord.ButtonStyle.success,
    )
    async def confirm(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ):
        if interaction.user.id != self.customer_id:
            await interaction.response.send_message(
                "這不是你的下單確認畫面。",
                ephemeral=True,
            )
            return
        if self.opening:
            await interaction.response.send_message(
                "票口正在建立，請勿重複點擊。",
                ephemeral=True,
            )
            return

        self.opening = True
        button.disabled = True
        try:
            await _create_ticket(
                interaction,
                category=self.category,
                item_group=self.item_group,
                source_channel_id=self.source_channel_id,
            )
        finally:
            self.opening = False

    @discord.ui.button(
        label="尚未閱讀",
        emoji="📖",
        style=discord.ButtonStyle.secondary,
    )
    async def cancel(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ):
        if interaction.user.id != self.customer_id:
            await interaction.response.send_message(
                "這不是你的下單確認畫面。",
                ephemeral=True,
            )
            return

        await interaction.response.send_message(
            "請先閱讀店內下單須知；確認看完後，再按「已閱讀下單須知，建立票口」。",
            ephemeral=True,
        )


async def _send_confirmation(
    interaction: discord.Interaction,
    *,
    category: str,
    item_group: str,
    source_channel_id: int,
):
    if not isinstance(interaction.user, discord.Member):
        await interaction.response.send_message(
            "這個功能只能在伺服器內使用。",
            ephemeral=True,
        )
        return

    timer = category == VIP_TIMER_CATEGORY
    category_label = (
        VIP_TIMER_CATEGORY_LABEL
        if timer
        else ORDER_CATEGORY_LABELS.get(category, category)
    )
    embed = discord.Embed(
        title="📖 下單須知確認",
        description=(
            f"**遊戲／類型：** {category_label}\n"
            f"**{'起始遊戲' if timer else '服務'}：** {item_group}\n\n"
            "開票前請先確認：**你是否已閱讀店內下單須知？**\n"
            "只有確認已閱讀後才會建立私人票口。\n\n"
            "票口建立後會沿用目前選擇的服務，再完成規格、陪玩人數與時長／數量。"
        ),
        color=discord.Color.gold(),
    )

    await interaction.response.send_message(
        embed=embed,
        view=QuickOrderConfirmView(
            customer_id=interaction.user.id,
            category=category,
            item_group=item_group,
            source_channel_id=source_channel_id,
        ),
        ephemeral=True,
    )


def _build_order_control_view() -> discord.ui.View | None:
    """Build the normal customer-service control row at ticket creation time."""
    try:
        from services import self_service_runtime as runtime

        state = runtime._require_runtime_state()
        view_type = state.order_control_view_type
        return view_type() if view_type is not None else None
    except Exception as exc:
        print(
            f"[quick-order-v2] cannot resolve order control view: "
            f"{type(exc).__name__}: {exc}",
            flush=True,
        )
        return None


async def _create_ticket(
    interaction: discord.Interaction,
    *,
    category: str,
    item_group: str,
    source_channel_id: int,
) -> discord.TextChannel | None:
    guild = interaction.guild
    member = interaction.user
    if guild is None or not isinstance(member, discord.Member):
        await interaction.response.send_message(
            "這個功能只能在伺服器內使用。",
            ephemeral=True,
        )
        return None

    if category == VIP_TIMER_CATEGORY:
        try:
            assert_vip_timer_self_service_eligible(
                member.id,
                check_open_order=True,
            )
        except ValueError as exc:
            await interaction.response.send_message(str(exc), ephemeral=True)
            return None
        refresh_vip_timer_self_service_catalog()

    await interaction.response.defer(ephemeral=True)

    ticket_category = guild.get_channel(CUSTOMER_CATEGORY_ID)
    if not isinstance(ticket_category, discord.CategoryChannel):
        await interaction.edit_original_response(
            content="找不到下單票口類別，請通知客服。",
            embed=None,
            view=None,
        )
        return None

    role = guild.get_role(CUSTOMER_ROLE_ID)
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

    if role is not None:
        overwrites[role] = discord.PermissionOverwrite(
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
            attach_files=True,
            embed_links=True,
        )

    ticket: discord.TextChannel | None = None
    try:
        ticket = await guild.create_text_channel(
            name=build_ticket_channel_name("下單", member),
            category=ticket_category,
            overwrites=overwrites,
            topic=(
                f"order_customer_id={member.id};"
                f"quick_order_v2=1;"
                f"source_channel_id={source_channel_id}"
            ),
            reason=f"Order ticket opened by {member}",
        )

        from services import self_service_selection_state as selection_state
        from services import self_service_ui_runtime as ui

        data = {"customer_id": member.id}
        selection_state.apply_self_service_category_selection(data, category)
        if category == VIP_TIMER_CATEGORY:
            prepare_vip_timer_draft(data)

        selection_state.apply_self_service_item_group_selection(data, item_group)
        if category == VIP_TIMER_CATEGORY:
            data["vip_timer_order"] = True

        data.update(
            quick_order_v2=True,
            quick_order_source_channel_id=source_channel_id,
            quick_order_started_category=category,
            quick_order_started_group=item_group,
        )

        ui.SELF_SERVICE_ORDER_SELECTIONS[ticket.id] = data
        remember_order_data(ticket.id, data)

        selected_label = (
            f"{VIP_TIMER_CATEGORY_LABEL}｜{item_group}"
            if category == VIP_TIMER_CATEGORY
            else f"{ORDER_CATEGORY_LABELS.get(category, category)}｜{item_group}"
        )
        support_mention = role.mention if role is not None else "客服"

        await ticket.send(
            f"{support_mention} {member.mention} 下單票口已建立。\n"
            f"已選服務：**{selected_label}**\n"
            "請在下方面板完成剩餘選項後送出等待接單。"
            f"{format_customer_notes_for_ticket(member.id)}",
            view=_build_order_control_view(),
            allowed_mentions=discord.AllowedMentions(
                users=True,
                roles=True,
                everyone=False,
            ),
        )

        await ticket.send(
            embed=ui.build_self_service_panel_embed(member.id, data, guild),
            view=ui.SelfServiceOrderView(
                customer_id=member.id,
                channel_id=ticket.id,
                selected_category=data.get("category"),
            ),
            allowed_mentions=discord.AllowedMentions(
                users=True,
                roles=False,
                everyone=False,
            ),
        )
    except Exception as exc:
        if ticket is not None:
            try:
                await ticket.delete(reason="Order ticket setup failed")
            except (discord.Forbidden, discord.HTTPException):
                pass

        print(
            f"[quick-order-v2] create ticket failed: "
            f"{type(exc).__name__}: {exc}",
            flush=True,
        )
        await interaction.edit_original_response(
            content=(
                f"建立下單票口失敗：{type(exc).__name__}。"
                "請稍後重試或通知客服。"
            ),
            embed=None,
            view=None,
        )
        return None

    await interaction.edit_original_response(
        content=f"✅ 票口已建立：{ticket.mention}",
        embed=None,
        view=None,
    )
    return ticket


def _install_ticket_patch() -> None:
    global _PATCH_INSTALLED, _ORIGINAL_VIEW_INIT, _ORIGINAL_PANEL_BUILDER
    if _PATCH_INSTALLED:
        return

    from services import order_runtime
    from services import self_service_runtime as runtime
    from services import self_service_selection_runtime as selection_runtime
    from services import self_service_ui_runtime as ui

    _ORIGINAL_VIEW_INIT = ui.SelfServiceOrderView.__init__
    _ORIGINAL_PANEL_BUILDER = runtime.build_self_service_panel_embed

    def quick_view_init(
        self,
        customer_id: int,
        channel_id: int,
        selected_category: str | None = None,
    ):
        _ORIGINAL_VIEW_INIT(self, customer_id, channel_id, selected_category)
        data = ui.SELF_SERVICE_ORDER_SELECTIONS.get(channel_id, {})
        if not data.get("quick_order_v2"):
            return

        for child in list(self.children):
            if getattr(child, "custom_id", None) in {
                "self_service_order_category_select",
                "self_service_order_item_select",
            }:
                self.remove_item(child)

        is_timer = str(data.get("category") or "") == VIP_TIMER_CATEGORY
        for child in self.children:
            if getattr(child, "custom_id", None) == "self_service_order_detail_select":
                child.placeholder = (
                    "選擇起始玩法"
                    if is_timer
                    else "請選擇規格／陪玩人數"
                )

    def quick_panel_builder(
        customer_id: int,
        data: dict,
        guild: discord.Guild | None = None,
    ):
        embed = _ORIGINAL_PANEL_BUILDER(customer_id, data, guild)
        if (
            not data.get("quick_order_v2")
            or str(data.get("category") or "") == VIP_TIMER_CATEGORY
        ):
            return embed

        category = str(data.get("category") or "")
        group = str(data.get("item_group") or "尚未選擇")
        embed.title = "自助下單"
        embed.description = (
            f"下單用戶：<@{customer_id}>\n\n"
            f"已選服務：**{group}**\n"
            "請完成規格／陪玩人數與時長／數量。\n"
            "送出後先進入等待接單，人數滿後才開放付款。"
        )

        for index, name in enumerate(("遊戲", "服務", "規格", "數量")):
            if index >= len(embed.fields):
                break
            field = embed.fields[index]
            embed.set_field_at(
                index,
                name=name,
                value=field.value,
                inline=field.inline,
            )

        embed.remove_footer()
        return embed

    ui.SelfServiceOrderView.__init__ = quick_view_init
    ui.build_self_service_panel_embed = quick_panel_builder
    runtime.build_self_service_panel_embed = quick_panel_builder
    selection_runtime.build_self_service_panel_embed = quick_panel_builder

    state = getattr(order_runtime, "_RUNTIME_STATE", None)
    if state is not None:
        try:
            order_runtime._RUNTIME_STATE = replace(
                state,
                self_service_panel_embed_builder=quick_panel_builder,
            )
        except Exception:
            pass

    _PATCH_INSTALLED = True
    print("[quick-order-v2] ticket patch installed", flush=True)


def _view_for_channel(channel_id: int) -> discord.ui.View:
    if channel_id == QUICK_ORDER_V2_CHANNELS["delta"]:
        return QuickDeltaEntryView()
    if channel_id == QUICK_ORDER_V2_CHANNELS["vip_timer"]:
        return QuickVipEntryView()

    category, _ = _GAME_ENTRY_META[channel_id]
    return QuickGameEntryView(
        category=category,
        source_channel_id=channel_id,
    )


async def _ensure_panel(bot: commands.Bot, channel_id: int) -> None:
    channel = bot.get_channel(channel_id)
    if not isinstance(channel, discord.TextChannel):
        try:
            fetched = await bot.fetch_channel(channel_id)
            channel = fetched if isinstance(fetched, discord.TextChannel) else None
        except (discord.NotFound, discord.Forbidden, discord.HTTPException):
            channel = None

    if not isinstance(channel, discord.TextChannel):
        print(
            f"[quick-order-v2] channel not found: {channel_id}",
            flush=True,
        )
        return

    target: discord.Message | None = None
    try:
        async for message in channel.history(limit=50):
            if bot.user is not None and message.author.id != bot.user.id:
                continue
            if any(
                str(getattr(embed.footer, "text", "") or "") == _marker(channel_id)
                for embed in message.embeds
            ):
                target = message
                break
    except (discord.Forbidden, discord.HTTPException):
        pass

    try:
        view = _view_for_channel(channel_id)
        embed = build_entry_embed(channel_id)
        if target is None:
            await channel.send(embed=embed, view=view)
        else:
            await target.edit(embed=embed, view=view)
    except (discord.Forbidden, discord.HTTPException) as exc:
        print(
            f"[quick-order-v2] panel sync failed {channel_id}: "
            f"{type(exc).__name__}: {exc}",
            flush=True,
        )


async def ensure_quick_order_v2_panels(bot: commands.Bot) -> None:
    await bot.wait_until_ready()
    for channel_id in QUICK_ORDER_V2_CHANNELS.values():
        await _ensure_panel(bot, channel_id)


def install_quick_order_v2(bot: commands.Bot) -> None:
    _install_ticket_patch()

    if not getattr(bot, "_quick_order_v2_views_registered", False):
        for channel_id in QUICK_ORDER_V2_CHANNELS.values():
            bot.add_view(_view_for_channel(channel_id))
        bot._quick_order_v2_views_registered = True
        print("[quick-order-v2] persistent views registered", flush=True)

    if not getattr(bot, "_quick_order_v2_panel_task_started", False):
        bot._quick_order_v2_panel_task_started = True
        bot.loop.create_task(ensure_quick_order_v2_panels(bot))
