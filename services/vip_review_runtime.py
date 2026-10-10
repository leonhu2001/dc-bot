from __future__ import annotations

import time
import traceback
from datetime import datetime, timedelta, timezone

import discord

import services.rewards as rewards
from core.discord_settings import (
    CUSTOMER_SERVICE_REVIEW_CHANNEL_ID,
    CUSTOMER_SERVICE_ROLE_ID,
    VIP_MONTHLY_ANNOUNCEMENT_CHANNEL_ID,
)
from core.vip_levels import BASE_MEMBER_LEVELS
from services.vip_monthly_benefits import (
    mark_month_announcement_sent,
    sync_current_month_vip_benefits,
)
from services.vip_review_store import (
    build_vip_retention_status,
    build_vip_review_snapshot,
    claim_pending_vip_review_actions,
    clear_vip_protection,
    get_last_digest_date,
    get_vip_protection,
    list_new_due_notifications,
    mark_digest_sent,
    mark_due_notifications_sent,
    mark_vip_review_action_done,
    mark_vip_review_action_failed,
    set_vip_protection,
)

TAIPEI_TZ = timezone(timedelta(hours=8))
VIP_REVIEW_URL = "https://mowanentertainment.com/admin/customer-center/vip?view=pending"
VIP_REVIEW_SCAN_SECONDS = 300
VIP_DAILY_DIGEST_HOUR = 10
_LAST_REVIEW_SCAN_MONOTONIC = 0.0


def _now() -> datetime:
    return datetime.now(TAIPEI_TZ)


def _parse_datetime(value) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=TAIPEI_TZ)
    return parsed.astimezone(TAIPEI_TZ)


async def _get_review_channel(bot: discord.Client):
    channel = bot.get_channel(CUSTOMER_SERVICE_REVIEW_CHANNEL_ID)
    if channel is None:
        try:
            channel = await bot.fetch_channel(CUSTOMER_SERVICE_REVIEW_CHANNEL_ID)
        except Exception:
            channel = None
    if channel is None or not hasattr(channel, "send"):
        raise RuntimeError(
            f"找不到客服審核通知頻道 {CUSTOMER_SERVICE_REVIEW_CHANNEL_ID}"
        )
    return channel


async def _get_monthly_announcement_channel(bot: discord.Client):
    channel = bot.get_channel(VIP_MONTHLY_ANNOUNCEMENT_CHANNEL_ID)
    if channel is None:
        try:
            channel = await bot.fetch_channel(VIP_MONTHLY_ANNOUNCEMENT_CHANNEL_ID)
        except Exception:
            channel = None
    if channel is None or not hasattr(channel, "send"):
        raise RuntimeError(
            f"找不到 VIP 月福利公告頻道 {VIP_MONTHLY_ANNOUNCEMENT_CHANNEL_ID}"
        )
    return channel


async def _sync_member_benefits(bot: discord.Client, customer_id: int, data: dict) -> None:
    guilds = list(getattr(bot, "guilds", []) or [])
    guild = guilds[0] if guilds else None
    if guild is None:
        return

    member = await rewards.fetch_member_safely(guild, customer_id)
    if member is not None:
        await rewards.ensure_reward_member_benefits(guild, member, data)


def _append_manual_downgrade_log(
    data: dict,
    *,
    old_index: int,
    new_index: int,
    operator_id: str,
    operator_name: str,
    reason: str,
) -> None:
    logs = data.get("vip_downgrade_logs")
    if not isinstance(logs, list):
        logs = []

    now_text = _now().isoformat(timespec="seconds")
    logs.append(
        {
            "checked_at": now_text,
            "source": "manual_vip_review",
            "old_level_index": int(old_index),
            "old_level": str(BASE_MEMBER_LEVELS[old_index]["name"]),
            "new_level_index": int(new_index),
            "new_level": str(BASE_MEMBER_LEVELS[new_index]["name"]),
            "operator_discord_id": str(operator_id),
            "operator_display_name": str(operator_name or ""),
            "reason": str(reason or ""),
        }
    )
    data["vip_downgrade_logs"] = logs[-100:]


async def _process_action(bot: discord.Client, row: dict) -> None:
    action_id = int(row["id"])
    customer_id_text = str(row.get("customer_id") or "").strip()
    operator_id = str(row.get("operator_discord_id") or "").strip()
    operator_name = str(row.get("operator_display_name") or "").strip()
    reason = str(row.get("reason") or "").strip()
    is_manager = bool(int(row.get("operator_is_manager") or 0))

    try:
        if not customer_id_text.isdigit():
            raise ValueError("顧客 Discord ID 無效")
        customer_id = int(customer_id_text)

        data = rewards.get_customer_reward_data(customer_id)
        protection = get_vip_protection(customer_id)
        status = build_vip_retention_status(
            data,
            protection_until=(protection or {}).get("protected_until"),
        )
        old_index = int(status["current_index"])
        action = str(row.get("action") or "").strip().lower()

        if action == "set_level":
            target_index = int(row.get("target_level_index"))
            if target_index < 0 or target_index >= len(BASE_MEMBER_LEVELS):
                raise ValueError("VIP 階級無效")

            if not is_manager and abs(target_index - old_index) > 1:
                raise PermissionError("客服每次只能調整一個 VIP 階級")

            total_spent = max(0, int(data.get("total_spent", 0) or 0))
            now_text = _now().isoformat(timespec="seconds")

            # 人工指定的是新的真實起點。重設進度基準可避免歷史累積消費
            # 立刻把剛降階的會員拉回原等級，也避免連續自動跳階。
            data["vip_level_index"] = target_index
            data["vip_progress_base_total_spent"] = total_spent
            data["vip_progress_reset_active"] = True
            data["last_level_manual_fixed_at"] = now_text
            data["last_level_manual_fixed_by"] = operator_id
            data["last_level_manual_fixed_reason"] = reason

            if target_index < old_index:
                _append_manual_downgrade_log(
                    data,
                    old_index=old_index,
                    new_index=target_index,
                    operator_id=operator_id,
                    operator_name=operator_name,
                    reason=reason,
                )

            clear_vip_protection(customer_id)
            await _sync_member_benefits(bot, customer_id, data)

            if rewards._SAVE_BOT_DATA is not None:
                rewards._SAVE_BOT_DATA()

            print(
                "[vip-review] level adjusted "
                f"user={customer_id} {old_index}->{target_index} by={operator_id}",
                flush=True,
            )

        elif action == "extend":
            if old_index <= 0:
                raise ValueError("普通會員沒有保級期限可延長")

            days = int(row.get("extend_days") or 0)
            max_days = 365 if is_manager else 30
            if days < 1 or days > max_days:
                raise PermissionError(f"延長天數需為 1～{max_days} 天")

            now = _now()
            expiry = _parse_datetime(status.get("expiry_at"))
            protected_until = _parse_datetime((protection or {}).get("protected_until"))
            anchors = [now]
            if expiry is not None:
                anchors.append(expiry)
            if protected_until is not None:
                anchors.append(protected_until)
            next_until = max(anchors) + timedelta(days=days)

            set_vip_protection(
                customer_id,
                next_until,
                reason=reason,
                operator_discord_id=operator_id,
                operator_display_name=operator_name,
            )
            print(
                "[vip-review] retention extended "
                f"user={customer_id} days={days} until={next_until.isoformat()} by={operator_id}",
                flush=True,
            )
        else:
            raise ValueError("不支援的 VIP 操作")

        mark_vip_review_action_done(action_id)
    except Exception as exc:
        mark_vip_review_action_failed(action_id, str(exc))
        print(
            f"[vip-review] action failed id={action_id}\n{traceback.format_exc()}",
            flush=True,
        )


async def _process_pending_actions(bot: discord.Client) -> None:
    rows = claim_pending_vip_review_actions(limit=20)
    for row in rows:
        await _process_action(bot, row)


def _level_summary(rows: list[dict]) -> str:
    counts: dict[str, int] = {}
    for row in rows:
        level = str(row.get("current_level") or "未知")
        counts[level] = counts.get(level, 0) + 1

    ordered_names = [str(level["name"]) for level in BASE_MEMBER_LEVELS[1:]]
    parts = [f"{name} {counts[name]} 位" for name in ordered_names if counts.get(name)]
    return "｜".join(parts) if parts else "無"


def _candidate_lines(rows: list[dict], limit: int = 8) -> str:
    lines = []
    for row in rows[:limit]:
        customer_id = str(row.get("customer_id") or "")
        overdue = int(row.get("days_overdue") or 0)
        current_level = str(row.get("current_level") or "VIP")
        suggested = str(row.get("suggested_level") or "普通魔丸")
        lines.append(
            f"<@{customer_id}>｜{current_level} → {suggested}｜逾期 {overdue} 天"
        )
    remaining = len(rows) - len(lines)
    if remaining > 0:
        lines.append(f"…另有 {remaining} 位，請至後台查看")
    return "\n".join(lines) or "—"


async def _send_review_message(
    bot: discord.Client,
    *,
    rows: list[dict],
    title: str,
    description: str,
) -> None:
    channel = await _get_review_channel(bot)
    embed = discord.Embed(
        title=title,
        description=description,
        color=discord.Color.purple(),
    )
    embed.add_field(name="待審核", value=f"**{len(rows)} 位**", inline=True)
    embed.add_field(name="階級分布", value=_level_summary(rows), inline=False)
    embed.add_field(name="名單", value=_candidate_lines(rows), inline=False)
    embed.set_footer(text="僅提醒，不會自動降階；實際變更需由客服 / 總管在後台確認。")

    view = discord.ui.View(timeout=None)
    view.add_item(
        discord.ui.Button(
            label="前往 VIP 審核",
            style=discord.ButtonStyle.link,
            url=VIP_REVIEW_URL,
        )
    )

    await channel.send(
        content=f"<@&{CUSTOMER_SERVICE_ROLE_ID}> 有 VIP 保級名單需要審核。",
        embed=embed,
        view=view,
        allowed_mentions=discord.AllowedMentions(
            everyone=False,
            users=False,
            roles=True,
        ),
    )


async def _scan_and_notify(bot: discord.Client) -> None:
    snapshot = build_vip_review_snapshot(view="pending")
    pending_rows = list(snapshot.get("rows") or [])
    if not pending_rows:
        return

    new_due = list_new_due_notifications(pending_rows)
    today = _now().date().isoformat()

    if new_due:
        await _send_review_message(
            bot,
            rows=new_due,
            title="💎 新增 VIP 保級待審核",
            description="以下會員剛超過目前 VIP 的保級期限，請人工確認是否降一階或延長保級。",
        )
        mark_due_notifications_sent(new_due)
        # 當天已因新名單提醒過，就不再額外洗一則日報。
        mark_digest_sent(today)
        return

    if _now().hour < VIP_DAILY_DIGEST_HOUR:
        return
    if get_last_digest_date() == today:
        return

    await _send_review_message(
        bot,
        rows=pending_rows,
        title="💎 VIP 保級待審核日報",
        description="目前仍有未處理的 VIP 保級名單。這是每日一次的彙總提醒。",
    )
    mark_digest_sent(today)


async def _sync_monthly_benefits_and_announce(bot: discord.Client) -> None:
    result = sync_current_month_vip_benefits()
    if result.get("issued_count"):
        print(
            "[vip-monthly] issued "
            f"month={result['month_key']} count={result['issued_count']} "
            f"eligible={result['eligible_customer_count']}",
            flush=True,
        )

    if not result.get("announcement_needed"):
        return

    channel = await _get_monthly_announcement_channel(bot)
    month = str(result.get("month_key") or "")
    try:
        year_text, month_text = month.split("-", 1)
        display_month = f"{int(year_text)} 年 {int(month_text)} 月"
    except Exception:
        display_month = month

    embed = discord.Embed(
        title=f"👑 {display_month} VIP 每月福利已刷新",
        description=(
            "新月份 VIP 專屬福利次數已恢復。\n"
            "白金以上會員可於「我的專區 → 我的福利」查看本月折現券；"
            "黑鑽會員的每月尊享兌換也已重新開放。"
        ),
        color=discord.Color.gold(),
    )
    embed.add_field(
        name="每月福利規則",
        value=(
            "• 200T / 500T VIP 折現券依目前會員等級發放\n"
            "• 黑鑽尊享福利每月 1 次，可二選一兌換\n"
            "• 月度福利不累積，未使用次數不會帶到下個月"
        ),
        inline=False,
    )
    embed.set_footer(text="保級已到期、進入待審核的會員會暫停新月份福利；恢復有效後會補發當月應有福利。")

    await channel.send(embed=embed)
    mark_month_announcement_sent(month)
    print(f"[vip-monthly] announcement sent month={month}", flush=True)


async def process_vip_review_tick(bot: discord.Client) -> None:
    """Process queued staff actions immediately and throttle review scans.

    This function is called from the existing top-up worker. It never performs
    an automatic downgrade; only explicit queued staff actions can mutate VIP.
    The same throttled tick also keeps monthly VIP benefits idempotently synced.
    """
    global _LAST_REVIEW_SCAN_MONOTONIC

    await _process_pending_actions(bot)

    now_monotonic = time.monotonic()
    if (
        _LAST_REVIEW_SCAN_MONOTONIC
        and now_monotonic - _LAST_REVIEW_SCAN_MONOTONIC < VIP_REVIEW_SCAN_SECONDS
    ):
        return

    _LAST_REVIEW_SCAN_MONOTONIC = now_monotonic

    try:
        await _sync_monthly_benefits_and_announce(bot)
    except Exception:
        print(
            f"[vip-monthly] sync/announcement failed\n{traceback.format_exc()}",
            flush=True,
        )

    try:
        await _scan_and_notify(bot)
    except Exception:
        print(
            f"[vip-review] notification scan failed\n{traceback.format_exc()}",
            flush=True,
        )
