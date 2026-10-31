from __future__ import annotations

import traceback

import discord

from core.discord_settings import VIP_MONTHLY_ANNOUNCEMENT_CHANNEL_ID
from core.vip_levels import VIP_LEVELS
from services.vip_monthly_benefits import MONTHLY_CASH_AMOUNTS
from services.vip_monthly_order_discount import VIP_MONTHLY_CASH_ORDER_MINIMUMS


NOVEMBER_2026_ANNOUNCEMENT_MESSAGE_ID = 1566120120735236107
NOVEMBER_2026_MONTH_KEY = "2026-11"

_INSTALLED = False
_NOVEMBER_RECONCILED = False


def _display_month(month_key: str) -> str:
    month = str(month_key or "").strip()
    try:
        year_text, month_text = month.split("-", 1)
        return f"{int(year_text)} 年 {int(month_text)} 月"
    except (TypeError, ValueError):
        return month


def _current_tier_cash_lines() -> list[str]:
    lines: list[str] = []
    for level in VIP_LEVELS:
        level_name = str(level.get("name") or "").strip()
        benefit_keys = [
            str(key)
            for key in level.get("benefit_keys", [])
            if str(key) in MONTHLY_CASH_AMOUNTS
        ]
        if not level_name or not benefit_keys:
            continue

        parts = [
            f"{int(MONTHLY_CASH_AMOUNTS[key]):,}T 折現券 ×1"
            for key in benefit_keys
        ]
        lines.append(f"• {level_name}：{' + '.join(parts)}")
    return lines


def _current_cash_usage_lines() -> list[str]:
    rows: list[tuple[int, int]] = []
    for benefit_key, amount in MONTHLY_CASH_AMOUNTS.items():
        minimum = int(VIP_MONTHLY_CASH_ORDER_MINIMUMS.get(benefit_key, 0) or 0)
        rows.append((int(amount), minimum))
    rows.sort()

    lines = [
        f"• {amount:,}T 折現券：原始服務金額滿 {minimum:,}T"
        for amount, minimum in rows
        if minimum > 0
    ]
    lines.append("• VIP 月券與點數福利同張訂單擇一使用")
    return lines


def build_vip_monthly_announcement_embed(month_key: str) -> discord.Embed:
    """Build the public announcement from the active monthly cash entitlement source."""
    embed = discord.Embed(
        title=f"👑 {_display_month(month_key)} VIP 每月福利已刷新",
        description=(
            "本月 VIP 月福利已發放。\n"
            "白金以上會員可至「我的專區 → 我的福利」查看與使用。"
        ),
        color=discord.Color.gold(),
    )
    embed.add_field(
        name="本月發放",
        value="\n".join(_current_tier_cash_lines()) or "本月無月福利券。",
        inline=False,
    )
    embed.add_field(
        name="使用門檻",
        value="\n".join(_current_cash_usage_lines()),
        inline=False,
    )
    embed.add_field(
        name="效期",
        value="月度福利不累積，未使用的福利不會帶到下個月。",
        inline=False,
    )
    embed.set_footer(
        text="保級已到期、進入待審核的會員會暫停新月份福利；恢復有效後會補發當月應有福利。"
    )
    return embed


async def _reconcile_november_2026_message(bot: discord.Client, channel) -> None:
    """Edit the already-posted November announcement in place; never repost it."""
    global _NOVEMBER_RECONCILED
    if _NOVEMBER_RECONCILED:
        return
    if int(getattr(channel, "id", 0) or 0) != VIP_MONTHLY_ANNOUNCEMENT_CHANNEL_ID:
        return
    if not hasattr(channel, "fetch_message"):
        raise RuntimeError("VIP 月福利公告頻道不支援讀取指定訊息")

    message = await channel.fetch_message(NOVEMBER_2026_ANNOUNCEMENT_MESSAGE_ID)
    bot_user = getattr(bot, "user", None)
    if bot_user is None or int(getattr(message.author, "id", 0) or 0) != int(bot_user.id):
        raise RuntimeError("指定的 2026-11 VIP 月福利公告不是目前 Bot 發送的訊息")

    target_embed = build_vip_monthly_announcement_embed(NOVEMBER_2026_MONTH_KEY)
    existing_embed = message.embeds[0] if message.embeds else None
    if existing_embed is None or existing_embed.to_dict() != target_embed.to_dict():
        await message.edit(embed=target_embed)
        print(
            "[vip-monthly] reconciled existing announcement "
            f"channel={VIP_MONTHLY_ANNOUNCEMENT_CHANNEL_ID} "
            f"message={NOVEMBER_2026_ANNOUNCEMENT_MESSAGE_ID}",
            flush=True,
        )

    _NOVEMBER_RECONCILED = True


def install_vip_monthly_announcement_policy() -> None:
    """Use current monthly entitlements for future announcements and repair Nov 2026."""
    global _INSTALLED
    if _INSTALLED:
        return

    from services import vip_review_runtime as runtime

    async def sync_monthly_benefits_and_announce(bot: discord.Client) -> None:
        result = runtime.sync_current_month_vip_benefits()
        if result.get("issued_count"):
            print(
                "[vip-monthly] issued "
                f"month={result['month_key']} count={result['issued_count']} "
                f"eligible={result['eligible_customer_count']}",
                flush=True,
            )

        channel = None
        if not _NOVEMBER_RECONCILED:
            try:
                channel = await runtime._get_monthly_announcement_channel(bot)
                await _reconcile_november_2026_message(bot, channel)
            except Exception:
                print(
                    "[vip-monthly] November announcement reconciliation failed\n"
                    f"{traceback.format_exc()}",
                    flush=True,
                )

        if not result.get("announcement_needed"):
            return

        if channel is None:
            channel = await runtime._get_monthly_announcement_channel(bot)
        month = str(result.get("month_key") or "")
        await channel.send(
            embed=build_vip_monthly_announcement_embed(month),
            allowed_mentions=discord.AllowedMentions.none(),
        )
        runtime.mark_month_announcement_sent(month)
        print(f"[vip-monthly] announcement sent month={month}", flush=True)

    runtime._sync_monthly_benefits_and_announce = sync_monthly_benefits_and_announce
    _INSTALLED = True


__all__ = [
    "NOVEMBER_2026_ANNOUNCEMENT_MESSAGE_ID",
    "build_vip_monthly_announcement_embed",
    "install_vip_monthly_announcement_policy",
]
