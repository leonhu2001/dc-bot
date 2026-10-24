from __future__ import annotations

from dataclasses import replace

import discord
from discord.ext import commands

from services import quick_order_v2 as quick
from services.quick_order_v2_assets import public_order_panel_image_url
from services.quick_order_v2_panel_images import (
    cleanup_legacy_artwork_messages,
    panel_image_filename,
    panel_image_url,
)
from services.quick_order_v2_price_lists import add_price_list_control
from services.quick_order_v2_select_display import (
    LEGACY_RESELECT_FLAG,
    apply_quick_order_select_display,
)


_INSTALLED = False
_BASE_PANEL_BUILDER = None
_BASE_VIEW_INIT = None
_CORE_ENTRY_EMBED = quick.build_entry_embed

_FARM_3X3_DETAIL_ORDER = {
    "season_3x3": 0,
    "season_3x3_loss": 1,
    "season_3x3_skin": 2,
    "season_3x3_skin_loss": 3,
    "season_contract": 4,
}
_DELTA_COVER_BY_CATEGORY = {
    "delta_desktop_fun": "delta_fun_panel.png",
}


def _live_vip_timer_eligibility(
    customer_id: int | str,
    *,
    check_open_order: bool = True,
) -> None:
    """Resolve the shared VIP gate at interaction time instead of a stale import."""
    from services import vip_timer_self_service as self_service

    return self_service.assert_vip_timer_self_service_eligible(
        customer_id,
        check_open_order=check_open_order,
    )


def _clean_entry_embed(channel_id: int) -> discord.Embed:
    """Derive public entry copy from core and apply only production presentation."""
    channel_id = int(channel_id)
    embed = _CORE_ENTRY_EMBED(channel_id)

    if channel_id == int(quick.QUICK_ORDER_V2_CHANNELS["delta"]):
        embed.description = "請選擇你要的服務。"

    embed.remove_footer()
    return embed


def _is_existing_entry_panel(message: discord.Message, channel_id: int) -> bool:
    expected_title = _clean_entry_embed(channel_id).title
    legacy_marker = quick._marker(channel_id)

    for embed in message.embeds:
        title = str(getattr(embed, "title", "") or "")
        footer = str(getattr(getattr(embed, "footer", None), "text", "") or "")
        if title == expected_title or footer == legacy_marker:
            return True

        if channel_id == quick.QUICK_ORDER_V2_CHANNELS["delta"] and title == "🟢 三角洲行動｜快速下單":
            return True
        if channel_id == quick.QUICK_ORDER_V2_CHANNELS["vip_timer"] and title == "💎 VIP 自由計時｜快速下單":
            return True
        if channel_id in quick._GAME_ENTRY_META:
            _, old_title = quick._GAME_ENTRY_META[channel_id]
            if title == f"{old_title}｜快速下單":
                return True

    return False


class _PublicDeltaCategoryButton(quick.QuickDeltaCategoryButton):
    """Canonical public Delta button, including the optional category cover."""

    async def callback(self, interaction: discord.Interaction) -> None:
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

        filename = _DELTA_COVER_BY_CATEGORY.get(str(self.category))
        if filename:
            image_url = public_order_panel_image_url(filename)
            if image_url is not None:
                embed.set_image(url=image_url)
            else:
                print(
                    f"[quick-order-v2] delta cover missing/invalid category={self.category} "
                    f"expected={filename}",
                    flush=True,
                )

        await interaction.response.send_message(
            embed=embed,
            view=view,
            ephemeral=True,
        )


def _public_view_for_channel(channel_id: int) -> discord.ui.View:
    """Build the final public entry View without downstream factory patching."""
    channel_id = int(channel_id)

    if channel_id == int(quick.QUICK_ORDER_V2_CHANNELS["delta"]):
        view = discord.ui.View(timeout=None)
        for emoji, label, category, style in quick._DELTA_BUTTONS:
            view.add_item(
                _PublicDeltaCategoryButton(
                    emoji=emoji,
                    label=label,
                    category=category,
                    style=style,
                    row=0,
                )
            )
        return add_price_list_control(view, channel_id)

    if channel_id == int(quick.QUICK_ORDER_V2_CHANNELS["vip_timer"]):
        return quick.QuickVipEntryView()

    category, _ = quick._GAME_ENTRY_META[channel_id]
    view = quick.QuickGameEntryView(
        category=category,
        source_channel_id=channel_id,
    )
    return add_price_list_control(view, channel_id)


async def _clean_ensure_panel(bot: commands.Bot, channel_id: int) -> None:
    """Synchronize one public panel with final copy, controls and static artwork."""
    channel_id = int(channel_id)
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

    bot_user_id = getattr(bot.user, "id", None)
    target: discord.Message | None = None
    try:
        async for message in channel.history(limit=50):
            if bot_user_id is not None and message.author.id != bot_user_id:
                continue
            if _is_existing_entry_panel(message, channel_id):
                target = message
                break
    except (discord.Forbidden, discord.HTTPException):
        pass

    filename = panel_image_filename(channel_id)
    if filename:
        try:
            removed = await cleanup_legacy_artwork_messages(
                channel,
                bot_user_id=bot_user_id,
                filename=filename,
            )
            if removed:
                print(
                    f"[quick-order-panel-image] removed {removed} legacy artwork message(s): "
                    f"{channel_id}",
                    flush=True,
                )
        except (discord.Forbidden, discord.HTTPException):
            pass

    embed = _clean_entry_embed(channel_id)
    if filename:
        image_url = panel_image_url(channel_id)
        if image_url is not None:
            embed.set_image(url=image_url)
        else:
            print(
                f"[quick-order-panel-image] public PNG missing/invalid; kept text-only panel: "
                f"{channel_id} {filename}",
                flush=True,
            )

    view = _public_view_for_channel(channel_id)

    try:
        if target is None:
            await channel.send(embed=embed, view=view)
        else:
            await target.edit(
                embed=embed,
                view=view,
                attachments=[],
            )
    except (discord.Forbidden, discord.HTTPException, ValueError, TypeError) as exc:
        print(
            f"[quick-order-v2] panel sync failed {channel_id}: "
            f"{type(exc).__name__}: {exc}",
            flush=True,
        )


async def _clean_ticket_messages(ticket: discord.TextChannel) -> None:
    """One-time compatibility cleanup for already-open legacy quick-order tickets."""
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


def _install_ticket_ui_policy() -> None:
    """Install the single active Quick Order ticket UI policy."""
    global _BASE_PANEL_BUILDER, _BASE_VIEW_INIT
    if _BASE_PANEL_BUILDER is not None or _BASE_VIEW_INIT is not None:
        return

    from core.database import remember_order_data
    from services import order_runtime
    from services import self_service_runtime as runtime
    from services import self_service_selection_runtime as selection_runtime
    from services import self_service_ui_runtime as ui
    from services.order_rules import ORDER_RULES
    from services.order_ticket_ui_policy import install_payment_finalize_rename_policy
    from services.orders import get_self_service_quantity_meta

    _BASE_PANEL_BUILDER = runtime.build_self_service_panel_embed
    _BASE_VIEW_INIT = ui.SelfServiceOrderView.__init__
    base_builder = _BASE_PANEL_BUILDER
    base_view_init = _BASE_VIEW_INIT

    def ticket_view_init(
        self,
        customer_id: int,
        channel_id: int,
        selected_category: str | None = None,
    ):
        base_view_init(self, customer_id, channel_id, selected_category)
        data = ui.SELF_SERVICE_ORDER_SELECTIONS.get(channel_id, {})
        if not isinstance(data, dict) or not data.get("quick_order_v2"):
            return

        # Customer-service re-dispatch intentionally constructs the view without a
        # fixed category. Persist that mode once so every later refresh keeps the
        # original four selectors instead of falling back to the compact quick UI.
        if selected_category is None and not data.get(LEGACY_RESELECT_FLAG):
            data[LEGACY_RESELECT_FLAG] = True
            try:
                remember_order_data(channel_id, data)
            except Exception as exc:
                print(
                    f"[quick-order-v2] persist classic re-dispatch mode failed "
                    f"channel={channel_id}: {type(exc).__name__}: {exc}",
                    flush=True,
                )

        if data.get(LEGACY_RESELECT_FLAG):
            apply_quick_order_select_display(self, data)
            return

        category = str(data.get("category") or "")
        is_timer = category == quick.VIP_TIMER_CATEGORY
        is_farm = category == "farm"
        item = str(data.get("item") or "").strip()
        rule_key = str(data.get("order_rule_key") or "").strip()
        rule = ORDER_RULES.get(rule_key)

        for child in list(self.children):
            if getattr(child, "custom_id", None) in {
                "self_service_order_category_select",
                "self_service_order_item_select",
            }:
                self.remove_item(child)

        for child in list(self.children):
            custom_id = getattr(child, "custom_id", None)

            if custom_id == "self_service_order_detail_select":
                child.placeholder = (
                    "選擇起始玩法"
                    if is_timer
                    else "請選擇方案"
                    if is_farm
                    else "請選擇規格／陪玩人數"
                )

                if is_farm and hasattr(child, "options"):
                    options = list(child.options)
                    if any(
                        str(getattr(option, "value", "")) in _FARM_3X3_DETAIL_ORDER
                        for option in options
                    ):
                        options.sort(
                            key=lambda option: _FARM_3X3_DETAIL_ORDER.get(
                                str(getattr(option, "value", "")),
                                99,
                            )
                        )
                        child.options.clear()
                        child.options.extend(options)

                    if item and len(options) <= 1:
                        self.remove_item(child)

            elif is_farm and custom_id == "self_service_order_quantity_select":
                if not item:
                    self.remove_item(child)
                    continue

                meta = get_self_service_quantity_meta(
                    data.get("category"),
                    data.get("item_group"),
                    data.get("item_detail_value"),
                )
                if meta and int(meta.get("min") or 1) == int(meta.get("max") or 1):
                    self.remove_item(child)
                else:
                    child.placeholder = "請選擇數量"

            elif is_farm and custom_id == "self_service_order_specified_staff_button":
                self.remove_item(child)

            elif is_farm and custom_id in {
                "self_service_order_point_benefit_button",
                "self_service_order_staff_discount_coupon_button",
            }:
                if not item:
                    self.remove_item(child)

            elif is_farm and custom_id == "self_service_order_staff_price_button":
                if not item or rule is None or str(getattr(rule, "pricing_type", "")) != "manual":
                    self.remove_item(child)

            elif is_farm and custom_id == "self_service_order_go_payment_button" and not item:
                child.disabled = True

        apply_quick_order_select_display(self, data)

    def ticket_panel_builder(
        customer_id: int,
        data: dict,
        guild: discord.Guild | None = None,
    ) -> discord.Embed:
        embed = base_builder(customer_id, data, guild)
        if (
            not isinstance(data, dict)
            or not data.get("quick_order_v2")
            or data.get(LEGACY_RESELECT_FLAG)
            or str(data.get("category") or "") == quick.VIP_TIMER_CATEGORY
        ):
            return embed

        category = str(data.get("category") or "")
        group = str(data.get("item_group") or "尚未選擇")
        embed.title = f"🛒 {quick.ORDER_CATEGORY_LABELS.get(category, category)}"
        embed.description = (
            f"下單用戶：<@{customer_id}>\n\n"
            f"已選服務：**{group}**\n"
            "請完成下方選項。"
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

    ui.SelfServiceOrderView.__init__ = ticket_view_init
    ui.build_self_service_panel_embed = ticket_panel_builder
    runtime.build_self_service_panel_embed = ticket_panel_builder
    selection_runtime.build_self_service_panel_embed = ticket_panel_builder

    state = getattr(order_runtime, "_RUNTIME_STATE", None)
    if state is not None:
        try:
            order_runtime._RUNTIME_STATE = replace(
                state,
                self_service_panel_embed_builder=ticket_panel_builder,
            )
        except Exception as exc:
            print(
                f"[quick-order-v2] runtime panel builder refresh failed: "
                f"{type(exc).__name__}: {exc}",
                flush=True,
            )

    install_payment_finalize_rename_policy(order_runtime)


def install_quick_order_v2_production(bot: commands.Bot) -> None:
    global _INSTALLED
    if _INSTALLED:
        return

    # Setup installs production before quick_order_v2 core. That makes the first
    # persistent-view registration use the final public factory instead of adding
    # another set of views later as a compatibility patch.
    quick.assert_vip_timer_self_service_eligible = _live_vip_timer_eligibility
    quick._view_for_channel = _public_view_for_channel
    quick._ensure_panel = _clean_ensure_panel

    _install_ticket_ui_policy()

    _INSTALLED = True
    print("[quick-order-v2] production public/ticket policy installed", flush=True)


async def repair_existing_quick_order_v2_copy(bot: commands.Bot) -> None:
    await bot.wait_until_ready()

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


__all__ = [
    "install_quick_order_v2_production",
    "repair_existing_quick_order_v2_copy",
]
