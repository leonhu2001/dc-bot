from __future__ import annotations

import asyncio

from sqlalchemy import text

from services.vip_timer_ops import ensure_vip_timer_ops_tables, record_alert


RUNNING_THRESHOLDS = (2, 4, 6, 8, 12, 24)
PENDING_THRESHOLDS = (
    (30 * 60, "pending_30m", "30 分鐘"),
    (2 * 60 * 60, "pending_2h", "2 小時"),
    (24 * 60 * 60, "pending_24h", "24 小時"),
)
CHECK_INTERVAL_SECONDS = 60


def _sent_alert_keys(db, order_id: int) -> set[str]:
    return {
        str(row[0])
        for row in db.execute(
            text("SELECT alert_key FROM vip_timer_alerts WHERE order_id=:order_id"),
            {"order_id": int(order_id)},
        ).fetchall()
    }


def _live_billable_seconds(db, order_id: int, status: str) -> int:
    from services.vip_timer_ops import _segment_effective_seconds

    rows = db.execute(
        text("SELECT * FROM vip_timer_segments WHERE order_id=:order_id ORDER BY seq"),
        {"order_id": int(order_id)},
    ).mappings().all()
    return sum(_segment_effective_seconds(dict(row), status) for row in rows)


def _due_alerts() -> list[dict]:
    from services import vip_timer as timer

    db = timer.SessionLocal()
    try:
        ensure_vip_timer_ops_tables(db)
        rows = db.execute(text("""
            SELECT s.order_id, s.customer_discord_id, s.ticket_channel_id, s.status,
                   s.ended_at, s.timer_message_id
            FROM vip_timer_sessions s
            WHERE s.status IN ('running','pending_payment')
        """)).mappings().all()
        now = timer.utc_now()
        due: list[dict] = []
        for raw in rows:
            row = dict(raw)
            order_id = int(row["order_id"])
            sent = _sent_alert_keys(db, order_id)
            status = str(row.get("status") or "")
            if status == "running":
                seconds = _live_billable_seconds(db, order_id, status)
                reached = [hours for hours in RUNNING_THRESHOLDS if seconds >= hours * 3600]
                unsent = [hours for hours in reached if f"running_{hours}h" not in sent]
                if unsent:
                    hours = max(unsent)
                    due.append({
                        **row,
                        "alert_key": f"running_{hours}h",
                        "kind": "running",
                        "label": f"{hours} 小時",
                        "seconds": seconds,
                    })
            else:
                ended = timer.parse_dt(row.get("ended_at"))
                if ended is None:
                    continue
                age = max(0, int((now - ended).total_seconds()))
                reached = [item for item in PENDING_THRESHOLDS if age >= item[0]]
                unsent = [item for item in reached if item[1] not in sent]
                if unsent:
                    threshold, key, label = max(unsent, key=lambda item: item[0])
                    due.append({
                        **row,
                        "alert_key": key,
                        "kind": "pending",
                        "label": label,
                        "seconds": age,
                        "escalated": threshold >= 24 * 3600,
                    })
        return due
    finally:
        db.close()


def _pending_rows() -> list[dict]:
    from services import vip_timer as timer

    db = timer.SessionLocal()
    try:
        ensure_vip_timer_ops_tables(db)
        return [
            dict(row)
            for row in db.execute(text("""
                SELECT order_id, ticket_channel_id
                FROM vip_timer_sessions
                WHERE status='pending_payment' AND ticket_channel_id IS NOT NULL
            """)).mappings().all()
        ]
    finally:
        db.close()


def _active_staff_ids(order_id: int) -> list[str]:
    try:
        from shared.order_acceptance import get_acceptance_state

        state = get_acceptance_state(int(order_id))
    except Exception:
        return []
    result: list[str] = []
    for claim in getattr(state, "claims", ()) or ():
        worker_id = str(getattr(claim, "staff_discord_id", "") or "").strip()
        if worker_id and worker_id not in result:
            result.append(worker_id)
    return result


async def _get_channel(bot, channel_id: int):
    channel = bot.get_channel(int(channel_id))
    if channel is not None:
        return channel
    try:
        return await bot.fetch_channel(int(channel_id))
    except Exception:
        return None


async def _send_alert(bot, item: dict) -> bool:
    channel_id = int(item.get("ticket_channel_id") or 0)
    if channel_id <= 0:
        return False
    channel = await _get_channel(bot, channel_id)
    if channel is None:
        return False
    customer_id = str(item.get("customer_discord_id") or "").strip()
    customer_ping = f"<@{customer_id}>" if customer_id else "老闆"
    if item.get("kind") == "running":
        staff_ids = _active_staff_ids(int(item["order_id"]))
        staff_ping = " ".join(f"<@{worker_id}>" for worker_id in staff_ids)
        content = (
            f"⏱️ {customer_ping} {staff_ping}\n"
            f"VIP 自由計時已累積約 **{item['label']}**。請確認目前仍在遊玩；"
            "若已休息或結束，請使用票口的「暫停」或「結束計時」，避免忘記關表。"
        )
    else:
        prefix = "⚠️ **待付款逾期提醒**" if item.get("escalated") else "💳 **VIP 自由計時待付款提醒**"
        content = (
            f"{prefix}\n{customer_ping} 本單結束後已等待 **{item['label']}**，"
            "請使用票口付款面板完成付款。付款完成前無法再建立新的 VIP 自由計時單。"
        )
        if item.get("escalated"):
            content += "\n此單已列入客服待處理清單。"
    try:
        await channel.send(content)
        return True
    except Exception as exc:
        print(
            f"[vip-timer-monitor] send failed order_id={item.get('order_id')}: "
            f"{type(exc).__name__}: {exc}",
            flush=True,
        )
        return False


async def _sync_pending_payment_panel(bot, item: dict) -> None:
    channel_id = int(item.get("ticket_channel_id") or 0)
    if channel_id <= 0:
        return
    channel = await _get_channel(bot, channel_id)
    guild = getattr(channel, "guild", None)
    if guild is None:
        return
    try:
        from services.acceptance.dispatch_refresh import refresh_acceptance_dispatch_from_web_order

        await refresh_acceptance_dispatch_from_web_order(guild, int(item["order_id"]))
    except Exception as exc:
        print(
            f"[vip-timer-monitor] payment panel sync failed order_id={item.get('order_id')}: "
            f"{type(exc).__name__}: {exc}",
            flush=True,
        )


async def _monitor_loop(bot) -> None:
    try:
        await bot.wait_until_ready()
        while not bot.is_closed():
            try:
                due = await asyncio.to_thread(_due_alerts)
                for item in due:
                    if await _send_alert(bot, item):
                        await asyncio.to_thread(
                            record_alert,
                            int(item["order_id"]),
                            str(item["alert_key"]),
                            {
                                "kind": item.get("kind"),
                                "label": item.get("label"),
                                "seconds": int(item.get("seconds") or 0),
                                "escalated": bool(item.get("escalated")),
                            },
                        )

                # The web admin can correct a pending timer while the bot stays
                # online. Refresh from the authoritative web_order once a minute
                # so the Discord payment panel cannot keep a stale pre-correction amount.
                pending = await asyncio.to_thread(_pending_rows)
                for item in pending:
                    await _sync_pending_payment_panel(bot, item)
            except Exception as exc:
                print(
                    f"[vip-timer-monitor] iteration failed: {type(exc).__name__}: {exc}",
                    flush=True,
                )
            await asyncio.sleep(CHECK_INTERVAL_SECONDS)
    except asyncio.CancelledError:
        raise


def install_vip_timer_monitor(bot_instance) -> None:
    if getattr(bot_instance, "_vip_timer_monitor_task", None) is not None:
        return
    ensure_vip_timer_ops_tables()
    try:
        task = asyncio.create_task(_monitor_loop(bot_instance), name="vip-timer-monitor")
    except RuntimeError:
        return
    bot_instance._vip_timer_monitor_task = task


__all__ = ["install_vip_timer_monitor"]
