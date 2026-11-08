from __future__ import annotations

"""A display-only, staff-operated clock for non-Delta hourly orders.

No charges, payout, report, VIP timer, or order status are calculated here.
Clock state is persisted in web_dashboard.db so restarts cannot reset elapsed time.
"""

import asyncio
import json
import sqlite3
import time
from pathlib import Path

import discord

from services.order_rules import get_rule

ROOT = Path(__file__).resolve().parents[1]
DATABASE = ROOT / "web_dashboard.db"
SUPPORTED_GAMES = frozenset({"lol", "apex", "valorant", "steam"})
TERMINAL_STATUSES = frozenset({"closed", "cancelled", "canceled", "stored"})
FOOTER_PREFIX = "SIMPLE-HOURLY-TIMER:"

def eligible_hourly_rule(rule_key: str, rule_snapshot_json: str | None = None) -> bool:
    """Only four named games, explicitly priced hourly; never Delta or VIP."""
    try:
        rule = get_rule(str(rule_key or ""))
    except (KeyError, ValueError):
        return False
    if rule.category not in SUPPORTED_GAMES:
        return False
    if str(rule.pricing_type) != "hourly":
        return False
    if rule_snapshot_json:
        try:
            snapshot = json.loads(rule_snapshot_json)
        except (TypeError, ValueError):
            snapshot = {}
        if isinstance(snapshot, dict):
            frozen = snapshot.get("rule") if isinstance(snapshot.get("rule"), dict) else snapshot
            if frozen.get("pricing_type") not in (None, "", "hourly"):
                return False
    return True


def _connect() -> sqlite3.Connection:
    connection = sqlite3.connect(str(DATABASE), timeout=10)
    connection.row_factory = sqlite3.Row
    return connection


def ensure_tables() -> None:
    if not DATABASE.exists():
        return
    with _connect() as connection:
        connection.execute("""
            CREATE TABLE IF NOT EXISTS simple_order_timers (
                order_id INTEGER PRIMARY KEY,
                ticket_channel_id TEXT NOT NULL,
                timer_message_id TEXT,
                state TEXT NOT NULL DEFAULT 'ready',
                elapsed_seconds REAL NOT NULL DEFAULT 0,
                running_since REAL,
                updated_at REAL NOT NULL
            )
        """)
        connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_simple_timer_channel "
            "ON simple_order_timers(ticket_channel_id)"
        )


def _session(ticket_channel_id: int | str) -> dict | None:
    with _connect() as db:
        row = db.execute(
            "SELECT t.*, o.status AS order_status, o.item, o.quantity "
            "FROM simple_order_timers t JOIN web_orders o ON o.id=t.order_id "
            "WHERE t.ticket_channel_id=? ORDER BY t.order_id DESC LIMIT 1",
            (str(ticket_channel_id),),
        ).fetchone()
    return dict(row) if row else None


def recorded_seconds(session: dict, *, now: float | None = None) -> int:
    seconds = float(session.get("elapsed_seconds") or 0)
    if str(session.get("state")) == "running" and session.get("running_since") is not None:
        seconds += max(0, (time.time() if now is None else now) - float(session["running_since"]))
    return max(0, int(seconds))


def _duration(seconds: int) -> str:
    h, remainder = divmod(max(0, int(seconds)), 3600)
    m, s = divmod(remainder, 60)
    return f"{h:02d}:{m:02d}:{s:02d}"


def _authorized_staff(db: sqlite3.Connection, order_id: int, user_id: int) -> bool:
    rows = db.execute(
        "SELECT worker_discord_id FROM order_assignments "
        "WHERE order_id=? AND is_active=1",
        (int(order_id),),
    ).fetchall()
    return str(user_id) in {str(row[0]) for row in rows}


def change_clock(channel_id: int, user_id: int, action: str, *, now: float | None = None) -> dict:
    """Atomic, worker-only start / pause. Customer and CS cannot operate it."""
    if action not in {"start", "pause"}:
        raise ValueError("不支援的計時操作。")
    clock = time.time() if now is None else float(now)
    with _connect() as db:
        db.execute("BEGIN IMMEDIATE")
        row = db.execute(
            "SELECT t.*, o.status AS order_status FROM simple_order_timers t "
            "JOIN web_orders o ON o.id=t.order_id "
            "WHERE t.ticket_channel_id=? ORDER BY t.order_id DESC LIMIT 1",
            (str(channel_id),),
        ).fetchone()
        if row is None:
            raise ValueError("找不到這張訂單的計時器。")
        if str(row["order_status"]).lower() != "active":
            raise ValueError("訂單目前不是進行中，無法操作計時。")
        if not _authorized_staff(db, int(row["order_id"]), user_id):
            raise PermissionError("只有這張訂單目前的接單陪玩可以操作計時器。")
        state = str(row["state"])
        if action == "start":
            if state not in {"ready", "paused"}:
                raise ValueError("目前已經在計時，不能重複開始。")
            db.execute(
                "UPDATE simple_order_timers SET state='running', running_since=?, "
                "updated_at=? WHERE order_id=?",
                (clock, clock, int(row["order_id"])),
            )
        else:
            if state != "running":
                raise ValueError("計時器目前沒有運行。")
            elapsed = float(row["elapsed_seconds"] or 0) + max(
                0, clock - float(row["running_since"] or clock)
            )
            db.execute(
                "UPDATE simple_order_timers SET state='paused', running_since=NULL, "
                "elapsed_seconds=?, updated_at=? WHERE order_id=?",
                (elapsed, clock, int(row["order_id"])),
            )
        db.commit()
    return _session(channel_id) or {}


def timer_embed(session: dict, *, now: float | None = None) -> discord.Embed:
    status = str(session.get("state") or "ready")
    title_status = {
        "ready": "尚未開始",
        "running": "計時中",
        "paused": "已暫停",
        "finished": "已結束",
    }.get(status, status)
    embed = discord.Embed(
        title="⏱️ 陪玩時數紀錄",
        description="僅供記錄實際遊玩時間，不會自動修改訂單金額、薪資或 VIP 累積。\n"
                    "只需接單陪玩操作，無須老闆或客服雙方確認。",
        color=discord.Color.green() if status == "running" else discord.Color.blurple(),
    )
    embed.add_field(name="目前狀態", value=title_status, inline=True)
    embed.add_field(name="累積遊玩時間", value=_duration(recorded_seconds(session, now=now)), inline=True)
    embed.add_field(name="訂購時數", value=f"{int(session.get('quantity') or 0)} 小時", inline=True)
    if status == "running" and session.get("running_since"):
        embed.add_field(
            name="本次開始",
            value=f"<t:{int(session['running_since'])}:t>",
            inline=False,
        )
    embed.set_footer(text=f"{FOOTER_PREFIX}{int(session['order_id'])}")
    return embed


class SimpleHourlyTimerView(discord.ui.View):
    def __init__(self, state: str | None = None):
        super().__init__(timeout=None)
        if state == "running":
            self.start.disabled = True
            self.pause.disabled = False
        elif state == "finished":
            self.start.disabled = True
            self.pause.disabled = True
        else:
            self.start.disabled = False
            self.pause.disabled = True
            self.start.label = "繼續計時" if state == "paused" else "開始計時"

    async def _run(self, interaction: discord.Interaction, action: str) -> None:
        if interaction.channel_id is None:
            await interaction.response.send_message("無法辨識票口。", ephemeral=True)
            return
        try:
            current = change_clock(interaction.channel_id, interaction.user.id, action)
        except (ValueError, PermissionError) as exc:
            await interaction.response.send_message(str(exc), ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        if interaction.message:
            try:
                await interaction.message.edit(
                    embed=timer_embed(current),
                    view=SimpleHourlyTimerView(current["state"]),
                )
            except (discord.Forbidden, discord.NotFound, discord.HTTPException):
                pass
        await interaction.followup.send(
            "已開始／繼續記錄遊玩時間。" if action == "start" else "已暫停，累積時間已保存。",
            ephemeral=True,
        )

    @discord.ui.button(label="開始計時", style=discord.ButtonStyle.success,
                       custom_id="simple_hourly_timer:start")
    async def start(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await self._run(interaction, "start")

    @discord.ui.button(label="暫停", style=discord.ButtonStyle.secondary,
                       custom_id="simple_hourly_timer:pause")
    async def pause(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await self._run(interaction, "pause")


def _eligible_orders() -> list[dict]:
    if not DATABASE.is_file():
        return []
    with _connect() as db:
        orders = db.execute(
            "SELECT id, ticket_channel_id, order_rule_key, rule_snapshot_json "
            "FROM web_orders WHERE status='active' AND ticket_channel_id IS NOT NULL "
            "AND ticket_channel_id!='' ORDER BY id DESC LIMIT 200"
        ).fetchall()
    return [
        dict(o) for o in orders
        if eligible_hourly_rule(o["order_rule_key"], o["rule_snapshot_json"])
    ]


def _register_order(order: dict) -> bool:
    """Idempotent; returning True means the message is not yet linked."""
    with _connect() as db:
        db.execute(
            "INSERT OR IGNORE INTO simple_order_timers "
            "(order_id, ticket_channel_id, state, elapsed_seconds, updated_at) "
            "VALUES (?, ?, 'ready', 0, ?)",
            (int(order["id"]), str(order["ticket_channel_id"]), time.time()),
        )
        row = db.execute(
            "SELECT timer_message_id FROM simple_order_timers WHERE order_id=?",
            (int(order["id"]),),
        ).fetchone()
    return bool(row and not row[0])


def _set_message_id(order_id: int, message_id: int) -> None:
    with _connect() as db:
        db.execute(
            "UPDATE simple_order_timers SET timer_message_id=?, updated_at=? "
            "WHERE order_id=?",
            (str(message_id), time.time(), int(order_id)),
        )


def _finish_non_active() -> None:
    now = time.time()
    with _connect() as db:
        db.execute(
            "UPDATE simple_order_timers SET "
            "elapsed_seconds=elapsed_seconds + CASE WHEN state='running' "
            "THEN MAX(0, ? - COALESCE(running_since, ?)) ELSE 0 END, "
            "state='finished', running_since=NULL, updated_at=? "
            "WHERE state!='finished' AND order_id IN "
            "(SELECT t.order_id FROM simple_order_timers t "
            "LEFT JOIN web_orders o ON o.id=t.order_id "
            "WHERE o.id IS NULL OR o.status IN ('closed','cancelled','canceled','stored'))",
            (now, now, now),
        )


async def _channel(bot: discord.Client, channel_id: str):
    try:
        ident = int(channel_id)
    except (TypeError, ValueError):
        return None
    channel = bot.get_channel(ident)
    if channel is not None:
        return channel
    try:
        return await bot.fetch_channel(ident)
    except (discord.NotFound, discord.Forbidden, discord.HTTPException):
        return None


async def _find_existing(channel: discord.TextChannel, order_id: int):
    try:
        async for message in channel.history(limit=60):
            if message.author.id != channel.guild.me.id:
                continue
            if any(str(getattr(e.footer, "text", "")) ==
                   f"{FOOTER_PREFIX}{order_id}" for e in message.embeds):
                return message
    except (discord.Forbidden, discord.HTTPException, AttributeError):
        return None
    return None


async def sync_once(bot: discord.Client) -> None:
    """Create only missing panels and refresh running times. Safe after restarts."""
    ensure_tables()
    if not DATABASE.exists():
        return
    _finish_non_active()
    for order in _eligible_orders():
        order_id = int(order["id"])
        needs_message = _register_order(order)
        session = _session(order["ticket_channel_id"])
        if session is None:
            continue
        channel = await _channel(bot, order["ticket_channel_id"])
        if not isinstance(channel, discord.TextChannel):
            continue
        if needs_message:
            existing = await _find_existing(channel, order_id)
            if existing is None:
                existing = await channel.send(
                    embed=timer_embed(session),
                    view=SimpleHourlyTimerView(session["state"]),
                    allowed_mentions=discord.AllowedMentions.none(),
                )
            _set_message_id(order_id, existing.id)
        elif session["state"] == "running":
            try:
                message = await channel.fetch_message(int(session["timer_message_id"]))
                await message.edit(
                    embed=timer_embed(session),
                    view=SimpleHourlyTimerView(session["state"]),
                )
            except (discord.NotFound, discord.Forbidden, discord.HTTPException, ValueError):
                # Restore missing panels on the next pass without resetting the clock.
                _set_message_id(order_id, 0)


async def timer_worker(bot: discord.Client) -> None:
    await bot.wait_until_ready()
    while not bot.is_closed():
        try:
            await sync_once(bot)
        except Exception as exc:
            print(f"[simple-order-timer] sync error: {type(exc).__name__}: {exc}", flush=True)
        await asyncio.sleep(60)


def install_simple_order_timer(bot: discord.Client) -> None:
    if not getattr(bot, "_simple_order_timer_view_registered", False):
        bot.add_view(SimpleHourlyTimerView())
        bot._simple_order_timer_view_registered = True


def ensure_simple_order_timer_worker_started(bot: discord.Client) -> None:
    if not getattr(bot, "_simple_order_timer_worker_started", False):
        bot._simple_order_timer_worker_started = True
        bot.loop.create_task(timer_worker(bot))
