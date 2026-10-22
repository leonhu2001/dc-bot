from __future__ import annotations

from dataclasses import replace

import discord
from discord.ext import commands

from services import quick_order_v2 as quick


_INSTALLED = False
_ORIGINAL_CREATE_TICKET = None
_ORIGINAL_PANEL_BUILDER = None


def _clean_entry_embed(channel_id: int) -> discord.Embed:
    if channel_id == quick.QUICK_ORDER_V2_CHANNELS["delta"]:
        return discord.Embed(
            title="🟢 三角洲行動｜下單",
            description=(
                "請先選擇服務類型，再選擇服務。\n\n"
                "🖥️ **端遊**｜一般陪玩、技術陪、甜蜜單、教學等\n"
                "📱 **手遊**｜手遊陪玩與相關方案\n"
                "🎉 **趣味單**｜特殊趣味玩法\n"
                "🛠️ **代肝代解**｜賽季、任務與代解服務"
            ),
            color=discord.Color.green(),
        )

    if channel_id == quick.QUICK_ORDER_V2_CHANNELS["vip_timer"]:
        return discord.Embed(
            title="💎 VIP 自由計時｜下單",
            description=(
                "金級會員以上限定。\n"
                "請選擇起始遊戲；進入客服中心後再選擇起始玩法。\n"
                "接滿後開始計時，中途可切換遊戲／玩法，結束後依實際時間結算。"
            ),
            color=discord.Color.gold(),
        )

    _, title = quick._GAME_ENTRY_META[channel_id]
    return discord.Embed(
        title=f"{title}｜下單",
        description="請選擇你要的服務。",
        color=discord.Color.purple(),
    )


def _is_existing_entry_panel(message: discord.Message, channel_id: int) -> bool:
    expected_title = _clean_entry_embed(channel_id).title
    legacy_marker = quick._marker(channel_id)

    for embed in message.embeds:
        title = str(getattr(embed, "title", "") or "")
        footer = str(getattr(getattr(embed, "footer", None), "text", "") or "")
        if title == expected_title or footer == legacy_marker:
            return True

        # First production restart also recognizes the pre-cleanup titles.
        if channel_id == quick.QUICK_ORDER_V2_CHANNELS["delta"] and title == "🟢 三角洲行動｜快速下單":
            return True
        if channel_id == quick.QUICK_ORDER_V2_CHANNELS["vip_timer"] and title == "💎 VIP 自由計時｜快速下單":
            return True
        if channel_id in quick._GAME_ENTRY_META:
            _, old_title = quick._GAME_ENTRY_META[channel_id]
            if title == f"{old_title}｜快速下單":
                return True

    return False


async def _clean_ensure_panel(bot: commands.Bot, channel_id: int) -> None:
    channel = bot.get_channel(channel_id)
    if not isinstance(channel, discord.TextChannel):
        try:
            fetched = await bot.fetch_channel(channel_id)
            channel = fetched if isinstance(fetched, discord.TextChannel) else None
        except (discord.NotFound, discord.Forbidden, discord.HTTPException):
            channel = None

    if not isinstance(channel, discord.TextChannel):
        print(f"[quick-order-v2] channel not found: {channel_id}", flush=True)
        return

    target: discord.Message | None = None
    try:
        async for message in channel.history(limit=50):
            if bot.user is not None and message.author.id != bot.user.id:
                continue
            if _is_existing_entry_panel(message, channel_id):
                target = message
                break
    except (discord.Forbidden, discord.HTTPException):
        pass

    try:
        if target is None:
            await channel.send(
                embed=_clean_entry_embed(channel_id),
                view=quick._view_for_channel(channel_id),
            )
        else:
            await target.edit(
                embed=_clean_entry_embed(channel_id),
                view=quick._view_for_channel(channel_id),
            )
    except (discord.Forbidden, discord.HTTPException) as exc:
        print(
            f"[quick-order-v2] panel sync failed {channel_id}: "
            f"{type(exc).__name__}: {exc}",
            flush=True,
        )


async def _clean_delta_callback(self, interaction: discord.Interaction) -> None:
    if not quick._options(self.category):
        await interaction.response.send_message(
            "這個分類目前沒有可下單服務。",
            ephemeral=True,
        )
        return

    embed = discord.Embed(
        title=f"{self.category_emoji} 三角洲行動｜{self.category_label}",
        description="請選擇服務。",
        color=discord.Color.green(),
    )
    view = discord.ui.View(timeout=180)
    view.add_item(
        quick.QuickServiceSelect(
            category=self.category,
            source_channel_id=quick.QUICK_ORDER_V2_CHANNELS["delta"],
            persistent=False,
        )
    )
    await interaction.response.send_message(embed=embed, view=view, ephemeral=True)


async def _clean_confirmation(
    interaction: discord.Interaction,
    *,
    category: str,
    item_group: str,
    source_channel_id: int,
) -> None:
    if not isinstance(interaction.user, discord.Member):
        await interaction.response.send_message(
            "這個功能只能在伺服器內使用。",
            ephemeral=True,
        )
        return

    timer = category == quick.VIP_TIMER_CATEGORY
    category_label = (
        quick.VIP_TIMER_CATEGORY_LABEL
        if timer
        else quick.ORDER_CATEGORY_LABELS.get(category, category)
    )
    embed = discord.Embed(
        title="💎 VIP 自由計時｜確認" if timer else "🛒 確認下單",
        description=(
            f"**遊戲／類型：** {category_label}\n"
            f"**{'起始遊戲' if timer else '服務'}：** {item_group}\n\n"
            "確認後建立私人客服中心。"
        ),
        color=discord.Color.green(),
    )

    await interaction.response.send_message(
        embed=embed,
        view=quick.QuickOrderConfirmView(
            customer_id=interaction.user.id,
            category=category,
            item_group=item_group,
            source_channel_id=source_channel_id,
        ),
        ephemeral=True,
    )


async def _clean_ticket_messages(ticket: discord.TextChannel) -> None:
    try:
        async for message in ticket.history(limit=20, oldest_first=True):
            content = str(message.content or "")
            if "新版快速下單票口已建立" in content or "已選：**" in content:
                lines = []
                if message.mentions:
                    lines.append(message.mentions[0].mention)
                selected_line = next(
                    (line for line in content.splitlines() if line.startswith("已選：**")),
                    None,
                )
                if selected_line:
                    lines.append(selected_line.replace("已選：", "已選服務：", 1))
                lines.append("請完成下方選項。")

                # Keep customer notes appended by the original ticket creator.
                note_index = content.find("💎 VIP 客戶資訊")
                if note_index >= 0:
                    lines.append("")
                    lines.append(content[note_index:].strip())

                await message.edit(content="\n".join(lines))
                continue

            if not message.embeds:
                continue
            embed = message.embeds[0]
            title = str(embed.title or "")
            if not title.startswith("快速下單｜"):
                continue

            clean_embed = discord.Embed.from_dict(embed.to_dict())
            clean_embed.title = title.replace("快速下單｜", "🛒 ", 1)
            description = str(clean_embed.description or "")
            kept_lines = []
            for line in description.splitlines():
                if "不需要重新選遊戲或服務" in line:
                    continue
                if "送出後先進入等待接單" in line:
                    continue
                kept_lines.append(line)
            clean_embed.description = "\n".join(kept_lines).strip()
            clean_embed.remove_footer()
            await message.edit(embed=clean_embed)
    except (discord.Forbidden, discord.HTTPException):
        return


def _install_create_ticket_cleanup() -> None:
    global _ORIGINAL_CREATE_TICKET
    if _ORIGINAL_CREATE_TICKET is not None:
        return

    _ORIGINAL_CREATE_TICKET = quick._create_ticket
    original = _ORIGINAL_CREATE_TICKET

    async def create_ticket_cleaned(
        interaction: discord.Interaction,
        *,
        category: str,
        item_group: str,
        source_channel_id: int,
    ) -> discord.TextChannel | None:
        ticket = await original(
            interaction,
            category=category,
            item_group=item_group,
            source_channel_id=source_channel_id,
        )
        if isinstance(ticket, discord.TextChannel):
            await _clean_ticket_messages(ticket)
        return ticket

    quick._create_ticket = create_ticket_cleaned


def _install_panel_builder_cleanup() -> None:
    global _ORIGINAL_PANEL_BUILDER
    if _ORIGINAL_PANEL_BUILDER is not None:
        return

    from services import order_runtime
    from services import self_service_runtime as runtime
    from services import self_service_selection_runtime as selection_runtime
    from services import self_service_ui_runtime as ui

    _ORIGINAL_PANEL_BUILDER = runtime.build_self_service_panel_embed
    original = _ORIGINAL_PANEL_BUILDER

    def clean_builder(
        customer_id: int,
        data: dict,
        guild: discord.Guild | None = None,
    ) -> discord.Embed:
        embed = original(customer_id, data, guild)
        if not data.get("quick_order_v2"):
            return embed
        if str(data.get("category") or "") == quick.VIP_TIMER_CATEGORY:
            return embed

        category = str(data.get("category") or "")
        group = str(data.get("item_group") or "尚未選擇")
        embed.title = f"🛒 {quick.ORDER_CATEGORY_LABELS.get(category, category)}"
        embed.description = (
            f"下單用戶：<@{customer_id}>\n\n"
            f"已選服務：**{group}**\n"
            "請完成下方選項。"
        )
        embed.remove_footer()
        return embed

    ui.build_self_service_panel_embed = clean_builder
    runtime.build_self_service_panel_embed = clean_builder
    selection_runtime.build_self_service_panel_embed = clean_builder

    state = getattr(order_runtime, "_RUNTIME_STATE", None)
    if state is not None:
        try:
            order_runtime._RUNTIME_STATE = replace(
                state,
                self_service_panel_embed_builder=clean_builder,
            )
        except Exception:
            pass


async def repair_existing_quick_order_v2_copy(bot: commands.Bot) -> None:
    await bot.wait_until_ready()

    # Refresh public entry panels in place, removing the old test marker/footer.
    for channel_id in quick.QUICK_ORDER_V2_CHANNELS.values():
        await _clean_ensure_panel(bot, channel_id)

    category_id = int(getattr(quick, "CUSTOMER_CATEGORY_ID", 0) or 0)
    category = bot.get_channel(category_id)
    if not isinstance(category, discord.CategoryChannel):
        return

    for channel in list(category.text_channels):
        if "quick_order_v2=1" not in str(channel.topic or ""):
            continue
        await _clean_ticket_messages(channel)


def install_quick_order_v2_production(bot: commands.Bot) -> None:
    global _INSTALLED
    if _INSTALLED:
        return

    quick.build_entry_embed = _clean_entry_embed
    quick._ensure_panel = _clean_ensure_panel
    quick._send_confirmation = _clean_confirmation
    quick.QuickDeltaCategoryButton.callback = _clean_delta_callback

    _install_create_ticket_cleanup()
    _install_panel_builder_cleanup()

    if not getattr(bot, "_quick_order_v2_copy_repair_started", False):
        bot._quick_order_v2_copy_repair_started = True
        bot.loop.create_task(repair_existing_quick_order_v2_copy(bot))

    _INSTALLED = True
    print("[quick-order-v2] production copy installed", flush=True)


__all__ = ["install_quick_order_v2_production", "repair_existing_quick_order_v2_copy"]
