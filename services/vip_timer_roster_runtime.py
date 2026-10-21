from __future__ import annotations

from typing import Any

import discord

from services.vip_timer_pause_confirmation import clear_pause_request
from services.vip_timer_roster import (
    adjust_roster,
    has_open_segment,
    resume_with_new_roster_segment,
    roster_capabilities,
)
from shared.order_acceptance import get_acceptance_state


_INSTALLED = False


def _is_support(member: Any) -> bool:
    if not isinstance(member, discord.Member):
        return False
    perms = getattr(member, "guild_permissions", None)
    return bool(perms and (perms.manage_channels or perms.manage_messages or perms.administrator))


def _is_customer_or_support(interaction: discord.Interaction, session: dict) -> bool:
    user_id = str(getattr(interaction.user, "id", "") or "")
    return user_id == str(session.get("customer_discord_id") or "") or _is_support(interaction.user)


def _accepted_ids(order_id: int) -> list[str]:
    state = get_acceptance_state(int(order_id))
    return [str(claim.staff_discord_id) for claim in state.claims]


async def _refresh_timer_message(guild: discord.Guild, order_id: int) -> None:
    from services import vip_timer_runtime as runtime

    session = runtime.get_session(int(order_id)) or {}
    channel_id = int(session.get("ticket_channel_id") or 0)
    message_id = int(session.get("timer_message_id") or 0)
    channel = guild.get_channel(channel_id) if channel_id else None
    if not isinstance(channel, discord.TextChannel) or not message_id:
        return
    try:
        message = await channel.fetch_message(message_id)
        await message.edit(
            embed=runtime.build_vip_timer_embed(int(order_id)),
            view=runtime.VipTimerControlView(status=session.get("status")),
        )
    except (discord.NotFound, discord.Forbidden, discord.HTTPException):
        pass


async def _apply_roster_change(
    interaction: discord.Interaction,
    *,
    order_id: int,
    action: str,
    outgoing_staff_id: str | None = None,
) -> None:
    result = adjust_roster(
        int(order_id),
        action=action,
        actor_id=getattr(interaction.user, "id", None),
        outgoing_staff_id=outgoing_staff_id,
    )
    clear_pause_request(
        int(order_id),
        actor_id=getattr(interaction.user, "id", None),
        reason="roster_changed",
    )

    guild = interaction.guild
    if guild is not None:
        try:
            from services.acceptance.dispatch_refresh import refresh_acceptance_dispatch_from_web_order

            await refresh_acceptance_dispatch_from_web_order(guild, int(order_id))
        except Exception as exc:
            print(
                f"[vip-timer-roster] dispatch refresh failed order_id={order_id}: "
                f"{type(exc).__name__}: {exc}",
                flush=True,
            )
        await _refresh_timer_message(guild, int(order_id))

    if action == "add":
        text_value = (
            f"✅ 已暫停計時並增加 1 個名額。"
            f"目前 {result['accepted_count']}/{result['target_staff_count']}，"
            "等新陪玩接單後再按「繼續」。"
        )
    elif action == "replace":
        text_value = (
            f"✅ 已在當下切斷原陪玩的計費區段並開放補位。"
            f"目前 {result['accepted_count']}/{result['target_staff_count']}，"
            "補位完成後再按「繼續」。"
        )
    else:
        text_value = (
            f"✅ 已在當下結束該陪玩的計費區段並減少 1 位。"
            f"目前人數 {result['accepted_count']}/{result['target_staff_count']}。"
        )
    await interaction.response.edit_message(content=text_value, view=None)


class VipTimerRosterStaffSelect(discord.ui.Select):
    def __init__(self, order_id: int, action: str, *, allowed_staff_ids: set[str] | None = None):
        self.order_id = int(order_id)
        self.action = str(action)
        state = get_acceptance_state(self.order_id)
        options: list[discord.SelectOption] = []
        for claim in state.claims:
            staff_id = str(claim.staff_discord_id)
            if allowed_staff_ids is not None and staff_id not in allowed_staff_ids:
                continue
            label = str(claim.staff_display_name or staff_id)[:100]
            options.append(
                discord.SelectOption(
                    label=label,
                    value=staff_id,
                    description=f"Discord ID：{staff_id}"[:100],
                )
            )
        if not options:
            options = [discord.SelectOption(label="目前沒有可調整的陪玩", value="__none__")]
        super().__init__(
            placeholder="選擇要離開目前計費區段的陪玩",
            min_values=1,
            max_values=1,
            options=options[:25],
        )

    async def callback(self, interaction: discord.Interaction):
        from services import vip_timer_runtime as runtime

        selected = str(self.values[0])
        if selected == "__none__":
            await interaction.response.send_message("目前沒有可調整的陪玩。", ephemeral=True)
            return
        session = runtime.get_session(self.order_id) or {}
        if not runtime._can_operate(interaction, session):
            await interaction.response.send_message("你沒有操作這張計時單的權限。", ephemeral=True)
            return

        manager = _is_customer_or_support(interaction, session)
        caller_id = str(getattr(interaction.user, "id", "") or "")
        if self.action == "reduce" and not manager:
            await interaction.response.send_message("只有老闆或客服可以直接減少陪玩人數。", ephemeral=True)
            return
        if self.action == "replace" and not manager and selected != caller_id:
            await interaction.response.send_message("陪玩只能替自己申請離開／換人。", ephemeral=True)
            return
        try:
            await _apply_roster_change(
                interaction,
                order_id=self.order_id,
                action=self.action,
                outgoing_staff_id=selected,
            )
        except ValueError as exc:
            await interaction.response.send_message(str(exc), ephemeral=True)


class VipTimerRosterStaffView(discord.ui.View):
    def __init__(self, order_id: int, action: str, *, allowed_staff_ids: set[str] | None = None):
        super().__init__(timeout=180)
        self.add_item(
            VipTimerRosterStaffSelect(
                int(order_id),
                action,
                allowed_staff_ids=allowed_staff_ids,
            )
        )


class VipTimerRosterManageView(discord.ui.View):
    def __init__(self, order_id: int):
        super().__init__(timeout=180)
        self.order_id = int(order_id)
        caps = roster_capabilities(self.order_id)
        self.add.disabled = not bool(caps.get("can_add"))
        self.reduce.disabled = not bool(caps.get("can_reduce"))
        self.replace.disabled = not bool(caps.get("can_replace"))

    async def _session(self, interaction: discord.Interaction):
        from services import vip_timer_runtime as runtime

        session = runtime.get_session(self.order_id) or {}
        if not session or not runtime._can_operate(interaction, session):
            await interaction.response.send_message("你沒有操作這張計時單的權限。", ephemeral=True)
            return None
        return session

    @discord.ui.button(label="增加 1 位", style=discord.ButtonStyle.primary)
    async def add(self, interaction: discord.Interaction, button: discord.ui.Button):
        session = await self._session(interaction)
        if session is None:
            return
        if not _is_customer_or_support(interaction, session):
            await interaction.response.send_message("只有老闆或客服可以增加陪玩人數。", ephemeral=True)
            return
        try:
            await _apply_roster_change(interaction, order_id=self.order_id, action="add")
        except ValueError as exc:
            await interaction.response.send_message(str(exc), ephemeral=True)

    @discord.ui.button(label="減少 1 位", style=discord.ButtonStyle.secondary)
    async def reduce(self, interaction: discord.Interaction, button: discord.ui.Button):
        session = await self._session(interaction)
        if session is None:
            return
        if not _is_customer_or_support(interaction, session):
            await interaction.response.send_message("只有老闆或客服可以直接減少陪玩人數。", ephemeral=True)
            return
        await interaction.response.edit_message(
            content="選擇要結束服務的陪玩。按下後會以目前時間切斷他的計費區段：",
            view=VipTimerRosterStaffView(self.order_id, "reduce"),
        )

    @discord.ui.button(label="更換 1 位", style=discord.ButtonStyle.secondary)
    async def replace(self, interaction: discord.Interaction, button: discord.ui.Button):
        session = await self._session(interaction)
        if session is None:
            return
        manager = _is_customer_or_support(interaction, session)
        caller_id = str(getattr(interaction.user, "id", "") or "")
        allowed = None if manager else {caller_id}
        await interaction.response.edit_message(
            content="選擇要離開目前計費區段的陪玩。之後會重新開放 1 個接單名額：",
            view=VipTimerRosterStaffView(self.order_id, "replace", allowed_staff_ids=allowed),
        )


def install_vip_timer_roster_runtime(*, bot_instance, guild_id: int) -> None:
    global _INSTALLED
    if _INSTALLED:
        return

    from services import vip_timer_runtime as runtime
    from services import vip_timer_runtime_guard as guard

    original_view = runtime.VipTimerControlView
    original_resume = runtime.resume_timer
    original_switch = runtime.switch_rule
    original_end = runtime.end_timer

    class VipTimerRosterControlView(original_view):
        @discord.ui.button(
            label="調整陪玩",
            style=discord.ButtonStyle.secondary,
            custom_id="vip_timer:roster",
            row=1,
        )
        async def roster(self, interaction: discord.Interaction, button: discord.ui.Button):
            session = await self._session(interaction)
            if session is None:
                return
            order_id = int(session["order_id"])
            caps = roster_capabilities(order_id)
            state = get_acceptance_state(order_id)
            names = [
                str(claim.staff_display_name or claim.staff_discord_id)
                for claim in state.claims
            ]
            await interaction.response.send_message(
                "**調整陪玩名單**\n"
                f"目前玩法：{caps['rule_label']}\n"
                f"目前人數：{state.accepted_count}/{state.required_staff_count}\n"
                f"目前陪玩：{'、'.join(names) if names else '無'}\n\n"
                "調整時會先以按下操作的時間切斷目前計費區段並暫停；"
                "補位完成後再按「繼續」，新名單會開新的計費區段。",
                view=VipTimerRosterManageView(order_id),
                ephemeral=True,
            )

        def __init__(self, *, status: str | None = None):
            super().__init__(status=status)
            state = str(status or "ready")
            self.roster.disabled = state not in {"running", "paused"}

    def roster_aware_resume(order_id: int, actor_id: Any):
        state = get_acceptance_state(int(order_id))
        if not state.is_full:
            raise ValueError(
                f"陪玩名單尚未補滿（{state.accepted_count}/{state.required_staff_count}），不能繼續計時。"
            )
        if has_open_segment(int(order_id)):
            return original_resume(order_id, actor_id)
        staff_ids = [str(claim.staff_discord_id) for claim in state.claims]
        snapshot = guard._validated_pricing_snapshot(
            bot_instance=bot_instance,
            guild_id=int(guild_id),
            rule_key=str((runtime.get_session(int(order_id)) or {}).get("current_rule_key") or ""),
            staff_ids=staff_ids,
        )
        return resume_with_new_roster_segment(
            int(order_id),
            actor_id=actor_id,
            pricing_snapshot=snapshot,
            staff_ids=staff_ids,
        )

    def roster_aware_switch(order_id: int, new_rule_key: str, actor_id: Any, staff_ids=None):
        state = get_acceptance_state(int(order_id))
        if not state.is_full:
            raise ValueError("陪玩名單尚未補滿，請先完成補位再切換玩法。")
        return original_switch(order_id, new_rule_key, actor_id, staff_ids)

    def roster_aware_end(order_id: int, actor_id: Any):
        state = get_acceptance_state(int(order_id))
        if not state.is_full:
            raise ValueError("陪玩名單尚未補滿，請先完成補位或聯繫客服處理後再結束計時。")
        return original_end(order_id, actor_id)

    runtime.VipTimerControlView = VipTimerRosterControlView
    runtime.resume_timer = roster_aware_resume
    runtime.switch_rule = roster_aware_switch
    runtime.end_timer = roster_aware_end
    _INSTALLED = True


__all__ = ["install_vip_timer_roster_runtime"]
