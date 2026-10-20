from __future__ import annotations

import math
from typing import Any

import discord

from services.self_service_financials import _format_plain_amount
from services.vip_timer import (
    VIP_TIMER_CATEGORY_LABEL,
    attach_ticket,
    end_timer,
    get_session,
    get_session_by_ticket,
    list_segments,
    public_hourly_rules,
    resume_timer,
    start_timer,
    switch_rule,
    is_vip_timer_order_data,
)
from services.vip_timer_pause_confirmation import (
    clear_pause_request,
    get_pause_request,
    request_or_confirm_pause,
)


_ORIGINAL_ENSURE_PAYMENT_PANEL = None
_HOOK_INSTALLED = False


def _unix(value: Any) -> int | None:
    from services.vip_timer import parse_dt

    parsed = parse_dt(value)
    return int(parsed.timestamp()) if parsed is not None else None


def _duration_text(seconds: int) -> str:
    seconds = max(0, int(seconds or 0))
    minutes = seconds // 60
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours} 小時 {minutes} 分"
    if minutes:
        return f"{minutes} 分"
    return f"{seconds} 秒"


def _accepted_staff_ids(order_id: int) -> list[str]:
    try:
        from shared.order_acceptance import get_acceptance_state

        state = get_acceptance_state(int(order_id))
    except Exception:
        return []
    result: list[str] = []
    for claim in getattr(state, "claims", ()) or ():
        value = str(getattr(claim, "staff_discord_id", "") or "").strip()
        if value and value not in result:
            result.append(value)
    return result


def _can_operate(interaction: discord.Interaction, session: dict) -> bool:
    user_id = str(getattr(interaction.user, "id", "") or "")
    if user_id == str(session.get("customer_discord_id") or ""):
        return True
    if user_id in _accepted_staff_ids(int(session["order_id"])):
        return True
    member = interaction.user
    if isinstance(member, discord.Member):
        perms = getattr(member, "guild_permissions", None)
        if perms and (perms.manage_channels or perms.manage_messages or perms.administrator):
            return True
        channel = interaction.channel
        if isinstance(channel, discord.TextChannel):
            channel_perms = channel.permissions_for(member)
            # Order tickets are private to the customer, accepted staff and support staff.
            if channel_perms.view_channel and channel_perms.send_messages:
                return True
    return False


def build_vip_timer_embed(order_id: int) -> discord.Embed:
    session = get_session(int(order_id)) or {}
    status = str(session.get("status") or "waiting_staff")
    pause_request = get_pause_request(int(order_id)) if status == "running" else None
    status_text = {
        "waiting_staff": "🟡 等待接單",
        "ready": "🟡 等待開始",
        "running": "🟢 計時中",
        "paused": "🟠 已暫停",
        "pending_payment": "🟠 待付款",
        "paid": "✅ 已付款",
    }.get(status, status)
    if pause_request is not None:
        status_text = "🟢 計時中｜等待暫停確認"

    embed = discord.Embed(
        title="👑 VIP 自由計時",
        description=(
            "只計實際遊玩時間，可在同一張單中切換遊戲／玩法。\n"
            "計時與金額以系統保存的時間戳為準，Discord 相對時間僅供顯示。"
        ),
        color=(discord.Color.green() if status == "running" else discord.Color.gold()),
    )
    embed.add_field(name="狀態", value=status_text, inline=True)
    embed.add_field(
        name="目前玩法",
        value=(
            f"{session.get('current_category_label') or '—'}\n"
            f"{session.get('current_rule_label') or '—'}"
        ),
        inline=True,
    )
    embed.add_field(
        name="目前時薪",
        value=(f"{int(session.get('current_hourly_rate') or 0):,}T / H"),
        inline=True,
    )

    started_unix = _unix(session.get("started_at"))
    if started_unix is not None:
        embed.add_field(
            name="本單開始",
            value=f"<t:{started_unix}:t>\n<t:{started_unix}:R>",
            inline=True,
        )
    paused_unix = _unix(session.get("paused_at"))
    if status == "paused" and paused_unix is not None:
        embed.add_field(
            name="暫停於",
            value=f"<t:{paused_unix}:t>\n<t:{paused_unix}:R>",
            inline=True,
        )

    if pause_request is not None:
        requester_id = str(pause_request.get("requester_discord_id") or "").strip()
        requester = f"<@{requester_id}>" if requester_id else "其中一方"
        requester_side = str(pause_request.get("requester_side") or "")
        waiting_for = "任一位已接單陪玩" if requester_side == "customer" else "老闆"
        requested_unix = _unix(pause_request.get("requested_at"))
        requested_text = f"\n申請：<t:{requested_unix}:R>" if requested_unix is not None else ""
        embed.add_field(
            name="⏸️ 暫停申請",
            value=(
                f"{requester} 已申請暫停，等待 **{waiting_for}** 再按一次「暫停」確認。"
                f"{requested_text}\n確認前仍會繼續計時。"
            ),
            inline=False,
        )

    segments = list_segments(int(order_id))
    if segments:
        lines: list[str] = []
        for segment in segments[-8:]:
            seconds = int(segment.get("billable_seconds") or 0)
            active_unix = _unix(segment.get("active_started_at"))
            suffix = (
                f"＋ <t:{active_unix}:R>"
                if active_unix is not None and status == "running" and not segment.get("ended_at")
                else ""
            )
            lines.append(
                f"`#{int(segment.get('seq') or 0)}` "
                f"{segment.get('category_label') or ''}｜{segment.get('rule_label') or ''}\n"
                f"{int(segment.get('hourly_rate') or 0):,}T/H｜已記 {_duration_text(seconds)} {suffix}".rstrip()
            )
        embed.add_field(name="計時區段", value="\n".join(lines)[:1024], inline=False)

    if status == "pending_payment":
        embed.add_field(
            name="應付金額",
            value=_format_plain_amount(int(session.get("final_amount") or 0)),
            inline=False,
        )
        embed.description = "計時已結束，請使用下方付款面板完成付款。"

    embed.set_footer(text=f"VIP-TIMER｜WEB-{int(order_id)}")
    return embed


async def _refresh_control_message(interaction: discord.Interaction, order_id: int) -> None:
    message = interaction.message
    if message is None:
        return
    try:
        await message.edit(
            embed=build_vip_timer_embed(order_id),
            view=VipTimerControlView(status=(get_session(order_id) or {}).get("status")),
        )
    except discord.HTTPException:
        pass


class VipTimerControlView(discord.ui.View):
    def __init__(self, *, status: str | None = None):
        super().__init__(timeout=None)
        state = str(status or "ready")
        self.start.disabled = state not in {"waiting_staff", "ready"}
        self.pause.disabled = state != "running"
        self.resume.disabled = state != "paused"
        self.switch.disabled = state not in {"running", "paused"}
        self.end.disabled = state not in {"running", "paused"}
        if state in {"pending_payment", "paid"}:
            for child in self.children:
                if isinstance(child, discord.ui.Button):
                    child.disabled = True

    async def _session(self, interaction: discord.Interaction) -> dict | None:
        session = get_session_by_ticket(interaction.channel_id or 0)
        if session is None:
            await interaction.response.send_message("找不到這張 VIP 計時單的狀態。", ephemeral=True)
            return None
        if not _can_operate(interaction, session):
            await interaction.response.send_message("你沒有操作這張計時單的權限。", ephemeral=True)
            return None
        return session

    @discord.ui.button(label="開始計時", style=discord.ButtonStyle.success, custom_id="vip_timer:start")
    async def start(self, interaction: discord.Interaction, button: discord.ui.Button):
        session = await self._session(interaction)
        if session is None:
            return
        order_id = int(session["order_id"])
        try:
            start_timer(order_id, interaction.user.id, _accepted_staff_ids(order_id))
        except ValueError as exc:
            await interaction.response.send_message(str(exc), ephemeral=True)
            return
        clear_pause_request(order_id, actor_id=interaction.user.id, reason="timer_started")
        await interaction.response.defer()
        await _refresh_control_message(interaction, order_id)

    @discord.ui.button(label="暫停", style=discord.ButtonStyle.secondary, custom_id="vip_timer:pause")
    async def pause(self, interaction: discord.Interaction, button: discord.ui.Button):
        session = await self._session(interaction)
        if session is None:
            return
        order_id = int(session["order_id"])
        try:
            result = request_or_confirm_pause(
                order_id,
                interaction.user.id,
                _accepted_staff_ids(order_id),
            )
        except ValueError as exc:
            await interaction.response.send_message(str(exc), ephemeral=True)
            return

        if str(result.get("state") or "") == "pending":
            waiting_for = "任一位陪玩" if result.get("waiting_for") == "staff" else "老闆"
            if result.get("already_requested"):
                text = f"暫停申請已送出，仍在等待{waiting_for}按「暫停」確認。計時目前持續中。"
            else:
                text = f"已送出暫停申請，等待{waiting_for}按「暫停」確認。確認前仍會繼續計時。"
            await interaction.response.send_message(text, ephemeral=True)
        else:
            await interaction.response.defer()

        await _refresh_control_message(interaction, order_id)

    @discord.ui.button(label="繼續", style=discord.ButtonStyle.success, custom_id="vip_timer:resume")
    async def resume(self, interaction: discord.Interaction, button: discord.ui.Button):
        session = await self._session(interaction)
        if session is None:
            return
        order_id = int(session["order_id"])
        try:
            resume_timer(order_id, interaction.user.id)
        except ValueError as exc:
            await interaction.response.send_message(str(exc), ephemeral=True)
            return
        clear_pause_request(order_id, actor_id=interaction.user.id, reason="timer_resumed")
        await interaction.response.defer()
        await _refresh_control_message(interaction, order_id)

    @discord.ui.button(label="切換遊戲／玩法", style=discord.ButtonStyle.primary, custom_id="vip_timer:switch")
    async def switch(self, interaction: discord.Interaction, button: discord.ui.Button):
        session = await self._session(interaction)
        if session is None:
            return
        await interaction.response.send_message(
            "選擇要切換到的遊戲分類：",
            view=VipTimerCategoryView(int(session["order_id"])),
            ephemeral=True,
        )

    @discord.ui.button(label="結束計時", style=discord.ButtonStyle.danger, custom_id="vip_timer:end")
    async def end(self, interaction: discord.Interaction, button: discord.ui.Button):
        session = await self._session(interaction)
        if session is None:
            return
        await interaction.response.send_message(
            "確定要結束這張 VIP 自由計時單嗎？結束後會立即產生待付款金額。",
            view=VipTimerEndConfirmView(int(session["order_id"])),
            ephemeral=True,
        )


class VipTimerCategorySelect(discord.ui.Select):
    def __init__(self, order_id: int):
        self.order_id = int(order_id)
        grouped: dict[str, str] = {}
        for row in public_hourly_rules():
            grouped[str(row["category"])] = str(row["category_label"])
        options = [
            discord.SelectOption(label=label[:100], value=key)
            for key, label in sorted(grouped.items(), key=lambda item: item[1])
        ][:25]
        super().__init__(
            placeholder="選擇遊戲分類",
            min_values=1,
            max_values=1,
            options=options or [discord.SelectOption(label="目前沒有可切換的方案", value="__none__")],
        )

    async def callback(self, interaction: discord.Interaction):
        category = self.values[0]
        if category == "__none__":
            await interaction.response.send_message("目前沒有可切換的小時計價方案。", ephemeral=True)
            return
        await interaction.response.edit_message(
            content="選擇新的玩法：",
            view=VipTimerRulePageView(self.order_id, category, page=0),
        )


class VipTimerCategoryView(discord.ui.View):
    def __init__(self, order_id: int):
        super().__init__(timeout=180)
        self.add_item(VipTimerCategorySelect(order_id))


class VipTimerRuleSelect(discord.ui.Select):
    def __init__(self, order_id: int, category: str, page: int):
        self.order_id = int(order_id)
        self.category = str(category)
        self.page = max(0, int(page))
        rows = [row for row in public_hourly_rules() if str(row["category"]) == self.category]
        start = self.page * 24
        page_rows = rows[start:start + 24]
        options = [
            discord.SelectOption(
                label=str(row["label"])[:100],
                value=str(row["rule_key"]),
                description=f"{int(row['hourly_rate']):,}T/H"[:100],
            )
            for row in page_rows
        ]
        if not options:
            options = [discord.SelectOption(label="這一頁沒有方案", value="__none__")]
        super().__init__(placeholder="選擇玩法", min_values=1, max_values=1, options=options)

    async def callback(self, interaction: discord.Interaction):
        rule_key = self.values[0]
        if rule_key == "__none__":
            await interaction.response.send_message("這一頁沒有可用方案。", ephemeral=True)
            return
        session = get_session(self.order_id)
        if session is None or not _can_operate(interaction, session):
            await interaction.response.send_message("你沒有操作這張計時單的權限。", ephemeral=True)
            return
        try:
            switch_rule(self.order_id, rule_key, interaction.user.id, _accepted_staff_ids(self.order_id))
        except ValueError as exc:
            await interaction.response.send_message(str(exc), ephemeral=True)
            return
        clear_pause_request(self.order_id, actor_id=interaction.user.id, reason="rule_switched")
        await interaction.response.edit_message(content="✅ 已切換玩法，新的計費區段已開始。", view=None)
        channel = interaction.channel
        if isinstance(channel, discord.TextChannel):
            session = get_session(self.order_id) or {}
            message_id = int(session.get("timer_message_id") or 0)
            if message_id:
                try:
                    message = await channel.fetch_message(message_id)
                    await message.edit(
                        embed=build_vip_timer_embed(self.order_id),
                        view=VipTimerControlView(status=session.get("status")),
                    )
                except (discord.NotFound, discord.HTTPException):
                    pass


class VipTimerRulePageView(discord.ui.View):
    def __init__(self, order_id: int, category: str, page: int = 0):
        super().__init__(timeout=180)
        self.order_id = int(order_id)
        self.category = str(category)
        self.page = max(0, int(page))
        rows = [row for row in public_hourly_rules() if str(row["category"]) == self.category]
        self.pages = max(1, math.ceil(len(rows) / 24))
        if self.page >= self.pages:
            self.page = self.pages - 1
        self.add_item(VipTimerRuleSelect(self.order_id, self.category, self.page))
        if self.pages > 1:
            prev = discord.ui.Button(label="上一頁", style=discord.ButtonStyle.secondary, disabled=self.page <= 0)
            next_button = discord.ui.Button(
                label="下一頁",
                style=discord.ButtonStyle.secondary,
                disabled=self.page >= self.pages - 1,
            )

            async def prev_cb(interaction: discord.Interaction):
                await interaction.response.edit_message(
                    view=VipTimerRulePageView(self.order_id, self.category, self.page - 1)
                )

            async def next_cb(interaction: discord.Interaction):
                await interaction.response.edit_message(
                    view=VipTimerRulePageView(self.order_id, self.category, self.page + 1)
                )

            prev.callback = prev_cb
            next_button.callback = next_cb
            self.add_item(prev)
            self.add_item(next_button)


class VipTimerEndConfirmView(discord.ui.View):
    def __init__(self, order_id: int):
        super().__init__(timeout=90)
        self.order_id = int(order_id)

    @discord.ui.button(label="確認結束", style=discord.ButtonStyle.danger)
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        session = get_session(self.order_id)
        if session is None or not _can_operate(interaction, session):
            await interaction.response.send_message("你沒有操作這張計時單的權限。", ephemeral=True)
            return
        try:
            result = end_timer(self.order_id, interaction.user.id)
        except ValueError as exc:
            await interaction.response.send_message(str(exc), ephemeral=True)
            return
        clear_pause_request(self.order_id, actor_id=interaction.user.id, reason="timer_ended")
        await interaction.response.edit_message(
            content=f"✅ 計時已結束，應付 {_format_plain_amount(int(result['final_amount']))}。",
            view=None,
        )
        await _finish_to_payment(interaction, self.order_id, result)

    @discord.ui.button(label="取消", style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(content="已取消結束計時。", view=None)


async def _finish_to_payment(interaction: discord.Interaction, order_id: int, result: dict) -> None:
    global _ORIGINAL_ENSURE_PAYMENT_PANEL
    channel = interaction.channel
    guild = interaction.guild
    if not isinstance(channel, discord.TextChannel) or guild is None:
        return
    session = get_session(order_id) or {}
    message_id = int(session.get("timer_message_id") or 0)
    if message_id:
        try:
            message = await channel.fetch_message(message_id)
            await message.edit(
                embed=build_vip_timer_embed(order_id),
                view=VipTimerControlView(status="pending_payment"),
            )
        except (discord.NotFound, discord.HTTPException):
            pass

    try:
        from services.acceptance import dispatch_refresh as dispatch_module
        from shared.order_acceptance import get_acceptance_state

        data = dispatch_module.SELF_SERVICE_ORDER_SELECTIONS.setdefault(channel.id, {})
        amount = int(result.get("final_amount") or 0)
        data.update(
            {
                "vip_timer_order": True,
                "vip_timer_pending_payment": True,
                "amount": amount,
                "total_amount": amount,
                "original_amount": amount,
                "payout_base_amount": amount,
                "customer_pay_amount": amount,
                "amount_text": _format_plain_amount(amount),
                "payment_method": None,
            }
        )
        state = get_acceptance_state(int(order_id))
        if _ORIGINAL_ENSURE_PAYMENT_PANEL is not None:
            await _ORIGINAL_ENSURE_PAYMENT_PANEL(
                guild=guild,
                ticket_channel=channel,
                data=data,
                payment_method_view_type=dispatch_module.PaymentMethodView,
                customer_id=int(session.get("customer_discord_id") or 0),
                category_label=VIP_TIMER_CATEGORY_LABEL,
                item="VIP 自由計時單",
                quantity=1,
                companion_preference=data.get("companion_preference") or "不指定陪玩/打手",
                amount=amount,
                state=state,
                log_title="VIP 自由計時結束｜開放付款",
            )
            from core.database import remember_order_data, save_bot_data

            remember_order_data(channel.id, data)
            save_bot_data()
    except Exception as exc:
        print(
            f"[vip-timer] payment panel failed order_id={order_id}: {type(exc).__name__}: {exc}",
            flush=True,
        )


async def ensure_vip_timer_panel(*, guild, ticket_channel, data, customer_id, state, **kwargs):
    order_id = int(getattr(state, "order_id", 0) or data.get("web_order_id") or 0)
    if order_id <= 0:
        raise ValueError("VIP 計時單缺少 order_id。")
    data["vip_timer_order"] = True
    attach_ticket(order_id, ticket_channel_id=ticket_channel.id)
    session = get_session(order_id) or {}
    embed = build_vip_timer_embed(order_id)
    message = None
    stored_id = int(session.get("timer_message_id") or 0)
    if stored_id:
        try:
            message = await ticket_channel.fetch_message(stored_id)
            await message.edit(embed=embed, view=VipTimerControlView(status=session.get("status")))
        except (discord.NotFound, discord.HTTPException):
            message = None
    if message is None:
        message = await ticket_channel.send(
            content=f"<@{int(customer_id)}> 接單人數已滿，可以開始 VIP 自由計時。",
            embed=embed,
            view=VipTimerControlView(status=session.get("status")),
            allowed_mentions=discord.AllowedMentions(users=True, roles=False, everyone=False),
        )
        attach_ticket(order_id, ticket_channel_id=ticket_channel.id, timer_message_id=message.id)
    return message


def install_acceptance_payment_hook() -> None:
    global _ORIGINAL_ENSURE_PAYMENT_PANEL, _HOOK_INSTALLED
    if _HOOK_INSTALLED:
        return
    _HOOK_INSTALLED = True
    from services.acceptance import payment_panel as payment_module
    from services.acceptance import dispatch_refresh as dispatch_module

    original = payment_module.ensure_acceptance_payment_panel
    _ORIGINAL_ENSURE_PAYMENT_PANEL = original

    async def vip_aware_ensure(*args, **kwargs):
        data = kwargs.get("data")
        if is_vip_timer_order_data(data) and not bool((data or {}).get("vip_timer_pending_payment")):
            return await ensure_vip_timer_panel(*args, **kwargs)
        return await original(*args, **kwargs)

    payment_module.ensure_acceptance_payment_panel = vip_aware_ensure
    dispatch_module.ensure_acceptance_payment_panel = vip_aware_ensure
