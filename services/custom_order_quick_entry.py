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
    return discord.Embed(
        title="✨ VIP 自訂單｜快速下單",
        description=(
            "先選擇 **1～4 位陪玩**，再填寫遊戲／服務、玩法／規則、方案／目標與其他需求。\n"
            "客服確認內容與價格後再正式送單。指定不另收費，價格以客服填寫為準。"
        ),
        color=discord.Color.purple(),
    )


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


def _message_component_ids(message: discord.Message) -> set[str]:
    custom_ids: set[str] = set()
    for component in getattr(message, "components", ()):
        component_id = str(getattr(component, "custom_id", "") or "")
        if component_id:
            custom_ids.add(component_id)
        for child in getattr(component, "children", ()):
            child_id = str(getattr(child, "custom_id", "") or "")
            if child_id:
                custom_ids.add(child_id)
    return custom_ids


def _message_has_order_controls(message: discord.Message) -> bool:
    return {
        "order_control_select",
        "order_control_confirm",
    }.issubset(_message_component_ids(message))


def _message_has_self_service_panel(message: discord.Message) -> bool:
    return any(
        str(getattr(embed, "title", "") or "").startswith("自助下單")
        for embed in getattr(message, "embeds", ())
    )


def _message_has_custom_order_intro_embed(message: discord.Message) -> bool:
    return any(
        str(getattr(embed, "title", "") or "") == "✨ 自訂單需求"
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
        sync_custom_order_headcount_detail,
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
    sync_custom_order_headcount_detail(data)

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
        f"目前陪玩人數：**{int(data.get('player_count') or 1)} 位**。\n"
        "第三欄負責選擇 1～4 位陪玩，規格統一顯示「自訂」；時數也可修改。\n"
        "自訂單指定免費，所有服務收費以客服填寫價格為準；再依折扣計算應付金額。\n"
        "客服使用「客服填價格」完成報價，確認後再送出等待接單。\n"
        "上方文字需求保留遊戲、玩法與目標，這張面板負責正式訂單規格。"
    )
    return embed


def _custom_order_intro_text(
    *,
    support_mention: str,
    member_mention: str,
    level_name: str,
    companion_count: int,
    game_or_service: str,
    gameplay_rules: str,
    goal_plan: str,
    extra_request: str = "",
    customer_notes: str = "",
) -> str:
    lines = [
        f"{support_mention} {member_mention} 自訂單票口已建立。",
        f"目前等級：**{level_name}**",
        f"陪玩人數：**{max(1, min(4, int(companion_count or 1)))} 位**",
        f"遊戲／服務內容：{str(game_or_service or '未填寫').strip()}",
        f"玩法／規則／機制：{str(gameplay_rules or '未填寫').strip()}",
        f"方案／目標：{str(goal_plan or '未填寫').strip()}",
    ]
    if str(extra_request or "").strip():
        lines.append(f"其他需求：{str(extra_request).strip()}")
    lines.extend(
        [
            "",
            "目前為需求確認階段，客服確認內容與價格後再正式送出等待接單。",
        ]
    )
    notes = str(customer_notes or "").strip()
    if notes:
        lines.extend(["", notes])
    return "\n".join(lines)


def _split_custom_order_intro_text(text: str, *, limit: int = 1800) -> list[str]:
    """Preserve all requirements while keeping each Discord message under 2,000 chars.

    The form allows multiple 1,000-character fields; a single intro message
    cannot safely contain all fields, especially with VIP notes appended.
    """
    if limit <= 0 or limit > 1900:
        raise ValueError("訊息分段長度無效")
    remaining = str(text)
    if not remaining:
        return [""]
    chunks: list[str] = []
    while len(remaining) > limit:
        # Prefer a paragraph/field boundary, but preserve every character.
        boundary = remaining.rfind("\n", 0, limit + 1)
        if boundary < limit // 2:
            boundary = limit
        else:
            boundary += 1
        chunks.append(remaining[:boundary])
        remaining = remaining[boundary:]
    if remaining:
        chunks.append(remaining)
    return chunks


def _intro_text_from_embed(
    embed: discord.Embed,
    *,
    support_mention: str,
    customer_id: int,
    companion_count: int,
) -> str:
    values = {
        str(field.name or "").strip(): str(field.value or "").strip()
        for field in getattr(embed, "fields", ())
    }
    return _custom_order_intro_text(
        support_mention=support_mention,
        member_mention=f"<@{int(customer_id)}>",
        level_name=custom_order_level_name(customer_id),
        companion_count=companion_count,
        game_or_service=values.get("遊戲／服務內容", "未填寫"),
        gameplay_rules=values.get("玩法／規則／機制", "未填寫"),
        goal_plan=values.get("方案／目標", "未填寫"),
        extra_request=values.get("其他需求", ""),
        customer_notes=values.get("會員資訊", ""),
    )


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
    stage = "create_channel"
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

        stage = "prepare_intro"
        support_mention = support_role.mention if support_role is not None else "客服"
        try:
            customer_notes = format_customer_notes_for_ticket(member.id)
        except Exception as notes_exc:
            # A malformed legacy VIP note must not cancel the owner's ticket.
            print(
                f"[custom-order-quick] notes unavailable customer_id={member.id} "
                f"error={type(notes_exc).__name__}",
                flush=True,
            )
            customer_notes = "會員備註暫時無法顯示，請客服至會員資料查看。"

        intro_text = _custom_order_intro_text(
            support_mention=support_mention,
            member_mention=member.mention,
            level_name=level_name,
            companion_count=count,
            game_or_service=game_or_service,
            gameplay_rules=gameplay_rules,
            goal_plan=goal_plan,
            extra_request=extra_request,
            customer_notes=customer_notes,
        )
        intro_chunks = _split_custom_order_intro_text(intro_text)
        intro_text = intro_chunks[0]

        stage = "send_intro"
        await ticket.send(
            content=intro_text,
            view=_order_control_view(interaction.client),
            allowed_mentions=discord.AllowedMentions(
                users=True,
                roles=True,
                everyone=False,
            ),
        )
        for followup_text in intro_chunks[1:]:
            await ticket.send(
                content=followup_text,
                allowed_mentions=discord.AllowedMentions.none(),
            )

        stage = "send_self_service_panel"
        await _send_custom_order_self_service_panel(
            ticket,
            customer_id=member.id,
            companion_count=count,
            game_or_service=game_or_service,
            gameplay_rules=gameplay_rules,
            goal_plan=goal_plan,
            extra_request=extra_request,
        )
    except Exception as exc:
        # Ticket creation is a committed user action. Never silently delete a
        # newly created channel because a later message or UI panel fails.
        print(
            f"[custom-order-quick] setup failed stage={stage} "
            f"customer_id={member.id} ticket_id={getattr(ticket, 'id', None)} "
            f"exception={type(exc).__name__} "
            f"http_status={getattr(exc, 'status', None)} "
            f"discord_code={getattr(exc, 'code', None)}",
            flush=True,
        )
        if ticket is not None:
            try:
                await ticket.send(
                    "⚠️ 自訂單票口已建立，但部分下單資訊初始化失敗。"
                    "票口會保留，請客服協助確認需求並重新載入下單面板。",
                    allowed_mentions=discord.AllowedMentions.none(),
                )
            except (discord.Forbidden, discord.HTTPException):
                pass
            await interaction.edit_original_response(
                content=(
                    f"自訂單票口已保留：{ticket.mention}\n"
                    "部分下單面板初始化失敗，已通知客服協助處理；請勿重複開票。"
                )
            )
            return ticket
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

    async def on_error(
        self,
        interaction: discord.Interaction,
        error: Exception,
        item: discord.ui.Item,
    ) -> None:
        # Old public panels reuse this persistent custom_id. A callback error
        # must be actionable and visible rather than a silent Discord timeout.
        print(
            f"[custom-order-quick] button failed "
            f"user_id={getattr(interaction.user, 'id', None)} "
            f"channel_id={getattr(interaction, 'channel_id', None)} "
            f"exception={type(error).__name__} "
            f"http_status={getattr(error, 'status', None)} "
            f"discord_code={getattr(error, 'code', None)}",
            flush=True,
        )
        message = "自訂單按鈕處理失敗，請稍後再試；若持續發生請通知客服。"
        try:
            if interaction.response.is_done():
                await interaction.followup.send(message, ephemeral=True)
            else:
                await interaction.response.send_message(message, ephemeral=True)
        except (discord.HTTPException, discord.InteractionResponded):
            pass

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
                content=None,
                embed=build_custom_order_entry_embed(),
                view=CustomOrderQuickEntryView(),
            )
    except (discord.Forbidden, discord.HTTPException) as exc:
        print(
            f"[custom-order-quick] panel sync failed: {type(exc).__name__}: {exc}",
            flush=True,
        )


async def repair_existing_custom_order_ticket_controls(bot: commands.Bot) -> None:
    """Backfill canonical controls, plain-text intro, and self-service panel."""
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
    repaired_intros = 0

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
        intro_message: discord.Message | None = None
        self_service_message: discord.Message | None = None
        setup_warning_message: discord.Message | None = None
        try:
            async for message in channel.history(limit=50):
                if bot.user is not None and message.author.id != bot.user.id:
                    continue
                has_controls = has_controls or _message_has_order_controls(message)
                if _message_has_self_service_panel(message):
                    has_self_service = True
                    if self_service_message is None:
                        self_service_message = message
                if intro_message is None and _message_has_custom_order_intro_embed(message):
                    intro_message = message
                if (
                    setup_warning_message is None
                    and "自訂單票口已建立，但部分下單資訊初始化失敗"
                    in str(getattr(message, "content", "") or "")
                ):
                    setup_warning_message = message
        except (discord.Forbidden, discord.HTTPException):
            continue

        if intro_message is not None and intro_message.embeds:
            support_role = channel.guild.get_role(CUSTOMER_ROLE_ID)
            support_mention = support_role.mention if support_role is not None else "客服"
            try:
                await intro_message.edit(
                    content=_intro_text_from_embed(
                        intro_message.embeds[0],
                        support_mention=support_mention,
                        customer_id=customer_id,
                        companion_count=companion_count,
                    ),
                    embed=None,
                    view=_order_control_view(bot),
                    allowed_mentions=discord.AllowedMentions(
                        users=False,
                        roles=False,
                        everyone=False,
                    ),
                )
                repaired_intros += 1
                has_controls = True
            except (discord.Forbidden, discord.HTTPException):
                pass

        panel_ready = False
        if has_self_service and self_service_message is not None:
            try:
                # Reconcile legacy players_1 selector with current player_count,
                # preserving the staff-entered quote and existing discounts.
                data = _seed_custom_order_self_service(
                    channel.id,
                    customer_id=customer_id,
                    companion_count=companion_count,
                )
                from services import self_service_ui_runtime as ui

                original_embed = (
                    self_service_message.embeds[0]
                    if getattr(self_service_message, "embeds", None)
                    else None
                )
                needs_refresh = bool(
                    original_embed is None
                    or not any(
                        str(field.name) == "第三欄｜規格"
                        and str(field.value) == "自訂"
                        for field in getattr(original_embed, "fields", ())
                    )
                    or setup_warning_message is not None
                )
                if needs_refresh:
                    await self_service_message.edit(
                        embed=_build_custom_order_self_service_embed(
                            customer_id, data, channel.guild
                        ),
                        view=ui.SelfServiceOrderView(
                            customer_id=customer_id,
                            channel_id=channel.id,
                            selected_category=CUSTOM_ORDER_CATEGORY,
                        ),
                        allowed_mentions=discord.AllowedMentions.none(),
                    )
                    repaired_panels += 1
                panel_ready = True
            except Exception as exc:
                print(
                    f"[custom-order-quick] existing panel refresh failed "
                    f"channel={channel.id} error={type(exc).__name__}",
                    flush=True,
                )

        if not has_self_service:
            try:
                await _send_custom_order_self_service_panel(
                    channel,
                    customer_id=customer_id,
                    companion_count=companion_count,
                )
                has_self_service = True
                panel_ready = True
                repaired_panels += 1
            except Exception as exc:
                print(
                    f"[custom-order-quick] self-service panel repair failed "
                    f"channel={channel.id}: {type(exc).__name__}: {exc}",
                    flush=True,
                )

        if panel_ready and setup_warning_message is not None:
            try:
                await setup_warning_message.edit(
                    content=(
                        "✅ 自訂單下單面板已恢復，可以繼續確認陪玩人數、"
                        "由客服填寫價格後再送出；先前的初始化警告已解除。"
                    ),
                    allowed_mentions=discord.AllowedMentions.none(),
                )
            except (discord.Forbidden, discord.HTTPException) as exc:
                print(
                    f"[custom-order-quick] warning clearance failed "
                    f"channel={channel.id} error={type(exc).__name__}",
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

    if repaired_panels or repaired_controls or repaired_intros:
        print(
            "[custom-order-quick] repaired "
            f"intros={repaired_intros} self_service_panels={repaired_panels} "
            f"staff_controls={repaired_controls}",
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
