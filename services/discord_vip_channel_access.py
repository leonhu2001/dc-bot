from __future__ import annotations

import discord


_INSTALLED = False


def install_discord_vip_channel_access() -> None:
    """Use Discord channel visibility as the VIP access gate.

    The VIP timer remains protected against duplicate open sessions, but Discord
    quick-order and ticket interactions do not re-check a member's stored VIP
    level because the dedicated source channel already has role overwrites.
    Non-Discord callers keep their existing policy functions untouched unless
    they route through the Discord self-service module.
    """
    global _INSTALLED
    if _INSTALLED:
        return

    from services import quick_order_v2 as quick
    from services import quick_order_v2_production as production
    from services import vip_timer_self_service as self_service
    from services.vip_timer import has_open_vip_timer

    def discord_timer_access(
        customer_id: int | str,
        *,
        check_open_order: bool = True,
    ) -> None:
        if check_open_order and has_open_vip_timer(str(customer_id)):
            raise ValueError(
                "你目前已有一張進行中或待付款的 VIP 自由計時單，請先完成上一張。"
            )

    # quick_order_v2 imported the function directly, so update both references.
    self_service.assert_vip_timer_self_service_eligible = discord_timer_access
    quick.assert_vip_timer_self_service_eligible = discord_timer_access

    original_timer_panel = self_service.build_vip_timer_self_service_panel_embed

    def timer_panel_without_membership_copy(
        customer_id: int,
        data: dict,
        guild: discord.Guild | None = None,
    ) -> discord.Embed:
        embed = original_timer_panel(customer_id, data, guild)
        if embed.description:
            embed.description = (
                str(embed.description)
                .replace("白金級會員以上限定。", "")
                .replace("金級會員以上限定。", "")
            )
        return embed

    self_service.build_vip_timer_self_service_panel_embed = timer_panel_without_membership_copy

    # Production owns the public quick-order panel copy. Keep that panel free of
    # a second membership gate as well; visibility of the channel is authoritative.
    original_entry_embed = production._clean_entry_embed

    def entry_embed_without_membership_copy(channel_id: int) -> discord.Embed:
        embed = original_entry_embed(channel_id)
        if channel_id == quick.QUICK_ORDER_V2_CHANNELS["vip_timer"] and embed.description:
            lines = str(embed.description).splitlines()
            if lines:
                lines[0] = "請選擇起始遊戲；進入客服中心後再選擇起始玩法。"
                # Production's existing second line already says the same thing.
                # Deduplicate it while preserving the timing/settlement guidance.
                if len(lines) > 1 and lines[1] == lines[0]:
                    lines.pop(1)
            embed.description = "\n".join(lines)
        return embed

    production._clean_entry_embed = entry_embed_without_membership_copy
    quick.build_entry_embed = entry_embed_without_membership_copy

    _INSTALLED = True
    print("[discord-vip-access] channel permission policy installed", flush=True)


__all__ = ["install_discord_vip_channel_access"]
