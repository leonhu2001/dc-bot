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
CUSTOM_ORDER_PANEL_MARKER = "custom-order-quick-entry:v2"
CUSTOM_ORDER_CATEGORY = "custom"
CUSTOM_ORDER_GROUP = "自訂"
CUSTOM_ORDER_RULE_KEY = "custom_custom_order"
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
    """Return the policy entitlement only; Discord access is enforced by channel permissions."""
    return str(level_name or "").strip() in _CUSTOM_ORDER_LEVELS


def assert_custom_order_eligible(customer_id: int | str) -> str:
    """Compatibility helper for non-Discord callers that still want policy validation."""
    level_name = custom_order_level_name(customer_id)
    if not is_custom_order_level_eligible(level_name):
        raise ValueError("自訂單為金級會員以上專屬福利。")
    return level_name


def build_custom_order_entry_embed() -> discord.Embed:
    embed = discord.Embed(
        title="✨ VIP 自訂單｜快速下單",
        description=(
            "此專屬頻道可直接提出自訂單需求。\n\n"
            "先選擇 **1～4 位陪玩**，再填寫遊戲、玩法／規則與目標。\n"
            "建立私人票口後會直接開啟 **自助下單** 面板；客服確認內容與價格後再正式送單。\n"
            "送出需求本身不會扣款或派單。"
        ),
        color=discord.Color.purple(),
    )
    embed.add_field(
        name="建議先準備",
        value="陪玩人數、遊戲／服務內容、玩法或機制、方案／目標，以及其他特殊需求。",
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


def _order_control_view(client: discord.Client) -> discord.ui.View | None:
    """Clone the already-registered canonical order control view."""
    for view in getattr(client, "persistent_views", ()):
        custom_ids = {
            str(getattr(child, "custom_id", "") or "")
            for child in getattr(view, "children", ())
        }
        if {
            "order_control_select",
            "order_control_confirm",
        }.issubset(custom_ids):
            try:
                return type(view)()
            except Exception:
                continue
    return None


def _message_has_order_controls(message: discord.Message) -> bool:
    custom_ids: set[str] = set()
    for component in getattr(message, "components", ()):
        component_id = str(getattr(component, "custom_id", "") or "")
        if component_id:
            custom_ids.add(component_id)
        for child in getattr(component, "children", ()):
            child_id = str(getattr(child, "custom_id", "") or "")
            if child_id:
                custom_ids.add(child_id)
    return {
        "order_control_select",
        "order_control_confirm",
    }.issubset(custom_ids)


def _message_has_self_service_panel(message: discord.Message) -> bool:
    return any(
        str(getattr(embed, "title", "") or "").startswith("自助下單")
        for embed in getattr(message, "embeds", ())
    )


def _topic_int(topic: str | None, marker: str) -> int | None:
    text = str(topic or "")
    token = f"{marker}="
    if token not in text:
        return None
    raw = text.split(token, 1)[1].split(";", 1)[0].strip()
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None


def _custom_order_customer_id_from_topic(topic: str | None) -> int | None:
    return _topic_int(topic, "custom_order_customer_id")


def _custom_order_companion_count_from_topic(topic: str | None) -> int | None:
    value = _topic_int(topic, "custom_order_companion_count")
    if value is None:
        return None
    return max(1, min(4, int(value)))


def _custom_order_detail(companion_count: int) -> dict:
    from services.orders import get_order_item_details_for_group

    count = max(1, min(4, int(companion_count or 1)))
    for detail in get_order_item_details_for_group(
        CUSTOM_ORDER_CATEGORY,
        CUSTOM_ORDER_GROUP,
    ):
        try:
            detail_count = int(detail.get("player_count") or 0)
        except (TypeError, ValueError):
            detail_count = 0
        if (
            str(detail.get("rule_key") or "") == CUSTOM_ORDER_RULE_KEY
            and detail_count == count
        ):
            return dict(detail)
    raise RuntimeError(f"找不到自訂單 {count} 人規格。")


def _seed_custom_order_self_service(
    channel_id: int,
    *,
    customer_id: int,
    companion_count: int,
    game_or_service: str = "",
    gameplay_rules: str = "",
    goal_plan: str = "",
    extra_request: str = "",
) -> dict:
    from core.database import remember_order_data
    from services import self_service_ui_runtime as ui
    from services.self_service_selection_state import (
        apply_self_service_category_selection,
        apply_self_service_detail_selection,
        apply_self_service_item_group_selection,
    )

    count = max(1, min(4, int(companion_count or 1)))
    data = ui.SELF_SERVICE_ORDER_SELECTIONS.setdefault(int(channel_id), {})

    if str(data.get("order_rule_key") or "") != CUSTOM_ORDER_RULE_KEY:
        apply_self_service_category_selection(data, CUSTOM_ORDER_CATEGORY)
        apply_self_service_item_group_selection(data, CUSTOM_ORDER_GROUP)
        apply_self_service_detail_selection(data, _custom_order_detail(count))
    elif not data.get("player_count"):
        apply_self_service_detail_selection(data, _custom_order_detail(count))

    data["customer_id"] = int(customer_id)
    data["custom_order_request"] = True
    data["custom_order_companion_count"] = int(data.get("player_count") or count)

    if game_or_service:
        data["custom_order_game_or_service"] = str(game_or_service).strip()
    if gameplay_rules:
        data["custom_order_gameplay_rules"] = str(gameplay_rules).strip()
    if goal_plan:
        data["custom_order_goal_plan"] = str(goal_plan).strip()
    if extra_request:
        data["custom_order_extra_request"] = str(extra_request).strip()

    remember_order_data(int(channel_id), data)
    return data


def _build_custom_order_self_service_embed(
    customer_id: int,
    data: dict,
    guild: discord.Guild | None,
) -> discord.Embed:
    from services import self_service_ui_runtime as ui

    embed = ui.build_self_service_panel_embed(int(customer_id), data, guild)
    embed.title = "自助下單｜自訂單"
    embed.description = (
        f"下單用戶：<@{int(customer_id)}>\n\n"
        "陪玩人數可在 **1～4 位**之間調整；時數／數量也可在此修改。\n"
        "自訂單由客服使用「客服填價格」完成報價，確認後再送出等待接單。\n"
        "上方需求單保留遊戲、玩法與目標，這張面板負責正式訂單規格。"
    )
    return embed


async def _send_custom_order_self_service_panel(
    channel: discord.TextChannel,
    *,
    customer_id: int,
    companion_count: int,
    game_or_service: str = "",
    gameplay_rules: str = "",
    goal_plan: str = "",
    extra_request: str = "",
) -> discord.Message:
    from services import self_service_ui_runtime as ui

    data = _seed_custom_order_self_service(
        channel.id,
        customer_id=int(customer_id),
        companion_count=int(companion_count),
        game_or_service=game_or_service,
        gameplay_rules=gameplay_rules,
        goal_plan=goal_plan,
        extra_request=extra_request,
    )
    return await channel.send(
        embed=_build_custom_order_self_service_embed(customer_id, data, channel.guild),
        view=ui.SelfServiceOrderView(
            customer_id=int(customer_id),
            channel_id=channel.id,
            selected_category=CUSTOM_ORDER_CATEGORY,
        ),
        allowed_mentions=discord.AllowedMentions(
            users=True,
            roles=False,
            everyone=False,
        ),
    )


async def _create_custom_order_request_ticket(
    interaction: discord.Interaction,
    *,
    companion_count: int,
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

    count = max(1, min(4, int(companion_count or 1)))
    level_name = custom_order_level_name(member.id)

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
                f"order_customer_id={member.id};"
                f"custom_order_customer_id={member.id};"
                f"custom_order_companion_count={count};"
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
        embed.add_field(name="陪玩人數", value=f"{count} 位", inline=True)
        embed.add_field(name="遊戲／服務內容", value=game_or_service[:1024], inline=False)
        embed.add_field(name="玩法／規則／機制", value=gameplay_rules[:1024], inline=False)
        embed.add_field(name="方案／目標", value=goal_plan[:1024], inline=False)
        if extra_request.strip():
            embed.add_field(name="其他需求", value=extra_request.strip()[:1024], inline=False)

        notes = format_customer_notes_for_ticket(member.id).strip()
        if notes:
            embed.add_field(name="會員資訊", value=notes[:1024], inline=False)

        embed.set_footer(text="自訂單需求｜尚未報價、尚未成立正式訂單")
        support_mention = support_role.mention if support_role is not None else "客服"
        await ticket.send(
            content=f"{support_mention} {member.mention}",
            embed=embed,
            view=_order_control_view(interaction.client),
            allowed_mentions=discord.AllowedMentions(
                users=True,
                roles=True,
                everyone=False,
            ),
        )

        await _send_custom_order_self_service_panel(
            ticket,
            customer_id=member.id,
            companion_count=count,
            game_or_service=game_or_service,
            gameplay_rules=gameplay_rules,
            goal_plan=goal_plan,
            extra_request=extra_request,
        )
    except (discord.Forbidden, discord.HTTPException, RuntimeError) as exc:
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
        content=f"自訂單需求已送出：{ticket.mention}\n請到私人客服中心確認自助下單規格並等待客服報價。"
    )
    return ticket


class CustomOrderRequestModal(discord.ui.Modal):
    def __init__(self, *, companion_count: int) -> None:
        self.companion_count = max(1, min(4, int(companion_count or 1)))
        super().__init__(
            title=f"VIP 自訂單需求｜{self.companion_count} 位陪玩",
            timeout=300,
        )
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
            companion_count=self.companion_count,
            game_or_service=str(self.game_or_service.value).strip(),
            gameplay_rules=str(self.gameplay_rules.value).strip(),
            goal_plan=str(self.goal_plan.value).strip(),
            extra_request=str(self.extra_request.value or "").strip(),
        )


class CustomOrderCompanionCountSelect(discord.ui.Select):
    def __init__(self, customer_id: int) -> None:
        self.customer_id = int(customer_id)
        super().__init__(
            placeholder="先選擇陪玩人數（1～4 位）",
            min_values=1,
            max_values=1,
            options=[
                discord.SelectOption(
                    label=f"{count} 位陪玩",
                    value=str(count),
                    description=f"這張自訂單需要 {count} 位接單人員",
                )
                for count in range(1, 5)
            ],
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        if interaction.user.id != self.customer_id:
            await interaction.response.send_message(
                "這不是你的自訂單設定畫面。",
                ephemeral=True,
            )
            return
        try:
            count = int(self.values[0])
        except (TypeError, ValueError, IndexError):
            await interaction.response.send_message(
                "陪玩人數選擇異常，請重新操作。",
                ephemeral=True,
            )
            return
        await interaction.response.send_modal(
            CustomOrderRequestModal(companion_count=count)
        )


class CustomOrderCompanionCountView(discord.ui.View):
    def __init__(self, customer_id: int) -> None:
        super().__init__(timeout=180)
        self.add_item(CustomOrderCompanionCountSelect(customer_id))


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
        await interaction.response.send_message(
            "先選擇這張自訂單需要幾位陪玩，再填寫需求。",
            view=CustomOrderCompanionCountView(interaction.user.id),
            ephemeral=True,
        )


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
                if footer in {CUSTOM_ORDER_PANEL_MARKER, "custom-order-quick-entry:v1"} or title in {
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


async def repair_existing_custom_order_ticket_controls(bot: commands.Bot) -> None:
    """Backfill canonical controls and the self-service panel onto existing custom tickets."""
    await bot.wait_until_ready()
    category = bot.get_channel(CUSTOMER_CATEGORY_ID)
    if not isinstance(category, discord.CategoryChannel):
        try:
            fetched = await bot.fetch_channel(CUSTOMER_CATEGORY_ID)
            category = fetched if isinstance(fetched, discord.CategoryChannel) else None
        except (discord.NotFound, discord.Forbidden, discord.HTTPException):
            category = None
    if not isinstance(category, discord.CategoryChannel):
        return

    repaired_controls = 0
    repaired_panels = 0

    for channel in list(category.text_channels):
        topic = str(channel.topic or "")
        if "custom_order_request=1" not in topic:
            continue

        customer_id = _custom_order_customer_id_from_topic(topic)
        if customer_id is None:
            continue
        companion_count = _custom_order_companion_count_from_topic(topic) or 1

        topic_updates: list[str] = []
        if "order_customer_id=" not in topic:
            topic_updates.append(f"order_customer_id={customer_id}")
        if "custom_order_companion_count=" not in topic:
            topic_updates.append(f"custom_order_companion_count={companion_count}")
        if topic_updates:
            try:
                topic = ";".join(topic_updates) + ";" + topic
                await channel.edit(
                    topic=topic,
                    reason="Restore canonical custom-order ticket identity",
                )
            except (discord.Forbidden, discord.HTTPException):
                pass

        has_controls = False
        has_self_service = False
        try:
            async for message in channel.history(limit=50):
                if bot.user is not None and message.author.id != bot.user.id:
                    continue
                has_controls = has_controls or _message_has_order_controls(message)
                has_self_service = has_self_service or _message_has_self_service_panel(message)
                if has_controls and has_self_service:
                    break
        except (discord.Forbidden, discord.HTTPException):
            continue

        if not has_self_service:
            try:
                await _send_custom_order_self_service_panel(
                    channel,
                    customer_id=customer_id,
                    companion_count=companion_count,
                )
                repaired_panels += 1
            except (discord.Forbidden, discord.HTTPException, RuntimeError) as exc:
                print(
                    f"[custom-order-quick] self-service panel repair failed "
                    f"channel={channel.id}: {type(exc).__name__}: {exc}",
                    flush=True,
                )

        if not has_controls:
            view = _order_control_view(bot)
            if view is None:
                print(
                    f"[custom-order-quick] canonical staff controls unavailable: {channel.id}",
                    flush=True,
                )
                continue
            try:
                await channel.send(
                    "客服操作｜請從下方清單選擇操作後按確認。",
                    view=view,
                )
                repaired_controls += 1
            except (discord.Forbidden, discord.HTTPException):
                continue

    if repaired_panels or repaired_controls:
        print(
            "[custom-order-quick] repaired "
            f"self_service_panels={repaired_panels} staff_controls={repaired_controls}",
            flush=True,
        )


def install_custom_order_quick_entry(bot: commands.Bot) -> None:
    if not getattr(bot, "_custom_order_quick_view_registered", False):
        bot.add_view(CustomOrderQuickEntryView())
        bot._custom_order_quick_view_registered = True

    if not getattr(bot, "_custom_order_quick_panel_task_started", False):
        bot._custom_order_quick_panel_task_started = True
        bot.loop.create_task(ensure_custom_order_quick_panel(bot))

    if not getattr(bot, "_custom_order_control_repair_started", False):
        bot._custom_order_control_repair_started = True
        bot.loop.create_task(repair_existing_custom_order_ticket_controls(bot))


__all__ = [
    "CUSTOM_ORDER_QUICK_CHANNEL_ID",
    "CUSTOM_ORDER_RULE_KEY",
    "CustomOrderCompanionCountSelect",
    "CustomOrderCompanionCountView",
    "CustomOrderQuickEntryView",
    "assert_custom_order_eligible",
    "build_custom_order_entry_embed",
    "install_custom_order_quick_entry",
    "is_custom_order_level_eligible",
    "repair_existing_custom_order_ticket_controls",
]
