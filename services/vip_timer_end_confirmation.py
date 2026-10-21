from __future__ import annotations

import discord

from services.vip_timer_ops import (
    clear_end_request,
    get_end_request,
    request_or_confirm_end,
)
from services.vip_timer_pause_confirmation import clear_pause_request


_INSTALLED = False


def _unix(value) -> int | None:
    from services.vip_timer import parse_dt

    parsed = parse_dt(value)
    return int(parsed.timestamp()) if parsed is not None else None


async def _refresh_control(interaction: discord.Interaction, order_id: int) -> None:
    from services import vip_timer_runtime as runtime

    channel = interaction.channel
    session = runtime.get_session(int(order_id)) or {}
    message_id = int(session.get("timer_message_id") or 0)
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


class VipTimerEndConfirmView(discord.ui.View):
    def __init__(self, order_id: int):
        super().__init__(timeout=90)
        self.order_id = int(order_id)

    @discord.ui.button(label="確認結束", style=discord.ButtonStyle.danger)
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        from services import vip_timer_runtime as runtime

        session = runtime.get_session(self.order_id)
        if session is None or not runtime._can_operate(interaction, session):
            await interaction.response.send_message("你沒有操作這張計時單的權限。", ephemeral=True)
            return
        try:
            confirmation = request_or_confirm_end(
                self.order_id,
                interaction.user.id,
                runtime._accepted_staff_ids(self.order_id),
            )
        except ValueError as exc:
            await interaction.response.send_message(str(exc), ephemeral=True)
            return

        if not confirmation.get("confirmed"):
            waiting_for = "任一位已接單陪玩" if confirmation.get("waiting_for") == "staff" else "老闆"
            if confirmation.get("already_requested"):
                text = f"結束申請已存在，仍在等待 **{waiting_for}** 確認。確認前會維持目前計時狀態。"
            else:
                text = f"已送出結束申請，等待 **{waiting_for}** 也按「結束計時 → 確認結束」。確認前不會結算。"
            await interaction.response.edit_message(content=text, view=None)
            await _refresh_control(interaction, self.order_id)
            return

        try:
            result = runtime.end_timer(self.order_id, interaction.user.id)
        except ValueError as exc:
            await interaction.response.send_message(str(exc), ephemeral=True)
            return
        clear_pause_request(self.order_id, actor_id=interaction.user.id, reason="timer_ended")
        clear_end_request(self.order_id, actor_id=interaction.user.id, reason="timer_ended")
        await interaction.response.edit_message(
            content=f"✅ 雙方已確認結束，應付 {runtime._format_plain_amount(int(result['final_amount']))}。",
            view=None,
        )
        await runtime._finish_to_payment(interaction, self.order_id, result)

    @discord.ui.button(label="取消", style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(content="已取消這次操作；既有的另一方結束申請不會因此被代替確認。", view=None)


def install_vip_timer_end_confirmation() -> None:
    global _INSTALLED
    if _INSTALLED:
        return

    from services import vip_timer_runtime as runtime
    from services import vip_timer_roster_runtime as roster_runtime

    runtime.VipTimerEndConfirmView = VipTimerEndConfirmView
    original_embed = runtime.build_vip_timer_embed
    original_resume = runtime.resume_timer
    original_switch = runtime.switch_rule
    original_adjust_roster = roster_runtime.adjust_roster

    def build_embed(order_id: int):
        embed = original_embed(int(order_id))
        request = get_end_request(int(order_id))
        if request is not None:
            requester_id = str(request.get("requester_discord_id") or "").strip()
            requester = f"<@{requester_id}>" if requester_id else "其中一方"
            side = str(request.get("requester_side") or "")
            waiting_for = "任一位已接單陪玩" if side == "customer" else "老闆"
            requested_unix = _unix(request.get("requested_at"))
            requested_text = f"｜<t:{requested_unix}:R>" if requested_unix is not None else ""
            embed.add_field(
                name="🛑 結束申請",
                value=(
                    f"{requester} 已申請結束，等待 **{waiting_for}** 確認{requested_text}。\n"
                    "雙方確認前不會產生結算；若仍在計時，計時會繼續。"
                ),
                inline=False,
            )
        return embed

    def resume_with_clear(order_id: int, actor_id):
        result = original_resume(int(order_id), actor_id)
        clear_end_request(int(order_id), actor_id=actor_id, reason="timer_resumed")
        return result

    def switch_with_clear(order_id: int, new_rule_key: str, actor_id, staff_ids=None):
        result = original_switch(int(order_id), new_rule_key, actor_id, staff_ids)
        clear_end_request(int(order_id), actor_id=actor_id, reason="rule_switched")
        return result

    def adjust_roster_with_clear(order_id: int, *args, **kwargs):
        result = original_adjust_roster(int(order_id), *args, **kwargs)
        clear_end_request(
            int(order_id),
            actor_id=kwargs.get("actor_id"),
            reason="roster_changed",
        )
        return result

    runtime.build_vip_timer_embed = build_embed
    runtime.resume_timer = resume_with_clear
    runtime.switch_rule = switch_with_clear
    roster_runtime.adjust_roster = adjust_roster_with_clear
    _INSTALLED = True


__all__ = ["VipTimerEndConfirmView", "install_vip_timer_end_confirmation"]
