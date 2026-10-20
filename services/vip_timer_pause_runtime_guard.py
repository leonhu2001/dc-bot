from __future__ import annotations

import discord

from services.vip_timer_billing_guard import VIP_TIMER_MINIMUM_SECONDS
from services.vip_timer_pause_confirmation import (
    get_pause_request,
    request_or_confirm_pause,
)


_INSTALLED = False
_ORIGINAL_VIEW_INIT = None
_ORIGINAL_BUILD_EMBED = None


def _waiting_text(side: str) -> str:
    if str(side) == "customer":
        return "老闆已提出暫停，等待任一位本單打手確認；確認前仍持續計時。"
    return "打手已提出暫停，等待老闆確認；確認前仍持續計時。"


async def _pause_with_confirmation(view, interaction: discord.Interaction, button: discord.ui.Button) -> None:
    session = await view._session(interaction)
    if session is None:
        return

    await interaction.response.defer(ephemeral=True)

    from services import vip_timer_runtime as runtime

    order_id = int(session["order_id"])
    staff_ids = runtime._accepted_staff_ids(order_id)
    try:
        result = request_or_confirm_pause(order_id, interaction.user.id, staff_ids)
    except ValueError as exc:
        await interaction.followup.send(str(exc), ephemeral=True)
        return
    except Exception as exc:
        print(
            f"[vip-timer] pause confirmation failed order_id={order_id}: "
            f"{type(exc).__name__}: {exc}",
            flush=True,
        )
        await interaction.followup.send("暫停確認失敗，請再試一次。", ephemeral=True)
        return

    state = str(result.get("state") or "")
    if state == "paused":
        message = "✅ 雙方已確認，計時已暫停。"
    else:
        message = _waiting_text(str(result.get("requester_side") or ""))

    await runtime._refresh_control_message(interaction, order_id)
    await interaction.followup.send(message, ephemeral=True)


def install_vip_timer_pause_runtime_guard() -> None:
    """Patch the Discord pause button to require customer/staff confirmation."""
    global _INSTALLED, _ORIGINAL_VIEW_INIT, _ORIGINAL_BUILD_EMBED
    if _INSTALLED:
        return

    from services import vip_timer_runtime as runtime

    if _ORIGINAL_VIEW_INIT is None:
        _ORIGINAL_VIEW_INIT = runtime.VipTimerControlView.__init__
    if _ORIGINAL_BUILD_EMBED is None:
        _ORIGINAL_BUILD_EMBED = runtime.build_vip_timer_embed

    original_init = _ORIGINAL_VIEW_INIT
    original_build_embed = _ORIGINAL_BUILD_EMBED

    def guarded_init(self, *, status: str | None = None):
        original_init(self, status=status)
        for child in self.children:
            if str(getattr(child, "custom_id", "") or "") != "vip_timer:pause":
                continue

            async def callback(interaction: discord.Interaction, _child=child, _view=self):
                await _pause_with_confirmation(_view, interaction, _child)

            child.callback = callback
            break

    def guarded_build_embed(order_id: int) -> discord.Embed:
        embed = original_build_embed(int(order_id))
        minimum_minutes = VIP_TIMER_MINIMUM_SECONDS // 60
        embed.add_field(
            name="計費／暫停規則",
            value=(
                f"整張單最低計費 {minimum_minutes} 分鐘，之後依實際秒數換算。\n"
                "暫停需老闆與打手雙方確認；多人打手任一位代表確認即可。"
            ),
            inline=False,
        )

        request = get_pause_request(int(order_id))
        if request:
            requester_id = str(request.get("requester_discord_id") or "")
            requester = f"<@{requester_id}>" if requester_id else "—"
            side = str(request.get("requester_side") or "")
            embed.add_field(
                name="⏸️ 暫停待確認",
                value=f"提出人：{requester}\n{_waiting_text(side)}",
                inline=False,
            )
        return embed

    runtime.VipTimerControlView.__init__ = guarded_init
    runtime.build_vip_timer_embed = guarded_build_embed
    _INSTALLED = True


__all__ = ["install_vip_timer_pause_runtime_guard"]
