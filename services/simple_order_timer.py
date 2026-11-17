from __future__ import annotations

"""A display-only, staff-operated clock for game hourly orders.

No charges, payout, report, VIP timer, or order status are calculated here.
Clock state is persisted in web_dashboard.db so restarts cannot reset elapsed time.
"""

import asyncio
import json
import sqlite3
import time
from collections.abc import Mapping
from pathlib import Path

import discord

from services.order_rules import get_rule

ROOT = Path(__file__).resolve().parents[1]
DATABASE = ROOT / "web_dashboard.db"
# Delta: cover all ordinary desktop/mobile hourly products, including Black Tide
# and legacy hourly tickets. Exclude all fun, internal wash and VIP timer SKUs.
SUPPORTED_GAMES = frozenset({
    "lol", "apex", "valorant", "steam",
    "delta_desktop_basic", "delta_mobile_basic", "basic", "farm",
})
DELTA_FUN_CATEGORIES = frozenset({"delta_desktop_fun", "fun"})
# The ordinary timer is created and operable only after canonical payment.
# Acceptance and pending-payment states must never expose an operational clock.
ACTIVE_TICKET_STATUSES = frozenset({"active"})
UNPAID_TICKET_STATUSES = frozenset({
    "pending_cs_dispatch", "waiting_acceptance", "accepted_pending_pay",
})
_PANEL_LOCKS: dict[int, asyncio.Lock] = {}
_ORDER_SELECTIONS: Mapping[int, dict] | None = None
TERMINAL_STATUSES = frozenset({"closed", "cancelled", "canceled", "stored"})
FOOTER_PREFIX = "SIMPLE-HOURLY-TIMER:"

def eligible_hourly_rule(rule_key: str, rule_snapshot_json: str | None = None) -> bool:
    """Only real hourly game orders; no Delta fun, VIP, or manual services."""
    try:
        rule = get_rule(str(rule_key or ""))
    except (KeyError, ValueError):
        return False
    category = str(getattr(rule, "category", "") or "")
    if category in DELTA_FUN_CATEGORIES or category not in SUPPORTED_GAMES:
        return False
    if (
        str(getattr(rule, "catalog_group_label", "") or "").strip() == "趣味單"
        or str(getattr(rule, "key", "") or "").startswith("fun_")
    ):
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
    if str(user_id) in {str(row[0]) for row in rows}:
        return True
    # Keep accepted/claimed workers eligible after payment if assignment sync
    # is lagging.  change_clock already forbids all prepayment statuses.
    has_claim_table = db.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' "
        "AND name='order_acceptance_claims'"
    ).fetchone()
    if not has_claim_table:
        return False
    return db.execute(
        "SELECT 1 FROM order_acceptance_claims "
        "WHERE order_id=? AND staff_discord_id=? AND is_active=1 LIMIT 1",
        (int(order_id), str(user_id)),
    ).fetchone() is not None


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
        if str(row["order_status"]).lower() not in ACTIVE_TICKET_STATUSES:
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
        # Old moved panels must never remain usable, even if Discord retained a copy.
        session = _session(interaction.channel_id)
        live_id = str((session or {}).get("timer_message_id") or "")
        pressed_id = str(getattr(interaction.message, "id", "") or "")
        if not live_id or pressed_id != live_id:
            await interaction.response.send_message(
                "這個計時器面板已更新，請使用票口最下方的新面板。", ephemeral=True
            )
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
            "FROM web_orders WHERE status='active' "
            "AND ticket_channel_id IS NOT NULL "
            "AND ticket_channel_id!='' ORDER BY id DESC"
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
    return bool(row and str(row[0] or "") in {"", "0"})


def _operation_panel_id(channel_id: int, *, status: str = "active") -> int | None:
    """Require a real, paid Discord operation panel before posting a timer."""
    if _ORDER_SELECTIONS is None:
        # Compatible with standalone tests; production always injects selections.
        return None
    data = _ORDER_SELECTIONS.get(int(channel_id))
    if not isinstance(data, dict) or str(data.get("status") or "").lower() != status:
        return None
    try:
        value = int(data.get("operation_panel_message_id") or 0)
        return value if value > 0 else None
    except (ValueError, TypeError):
        return None


def _order_for_panel(channel_id: int, *, allow_stored: bool = False) -> dict | None:
    if not DATABASE.is_file():
        return None
    permitted = ("active", "stored") if allow_stored else ("active",)
    with _connect() as db:
        row = db.execute(
            "SELECT id, ticket_channel_id, order_rule_key, rule_snapshot_json, status "
            "FROM web_orders WHERE ticket_channel_id=? ORDER BY id DESC LIMIT 1",
            (str(channel_id),),
        ).fetchone()
    if row is None:
        return None
    order = dict(row)
    if str(order["status"]).lower() not in permitted:
        return None
    return order if eligible_hourly_rule(
        order["order_rule_key"], order["rule_snapshot_json"]
    ) else None


async def ensure_timer_panel_after_operation(
    channel: discord.TextChannel, *,
    order_id: int | None = None,
    reposition: bool = False,
    expected_status: str = "active",
) -> int | None:
    """Keep one timer directly below the operation panel, preserving elapsed time.

    Payment calls with reposition=False after the operation panel is persisted.
    Store/resume calls reposition=True once the operation panel was moved.
    """
    if expected_status not in {"active", "stored"} or not DATABASE.is_file():
        return None
    operation_id = _operation_panel_id(channel.id, status=expected_status)
    if operation_id is None:
        return None
    order = _order_for_panel(channel.id, allow_stored=expected_status == "stored")
    if order is None or str(order["status"]).lower() != expected_status:
        return None
    if order_id is not None and int(order["id"]) != int(order_id):
        return None

    lock = _PANEL_LOCKS.setdefault(int(channel.id), asyncio.Lock())
    async with lock:
        # Recheck after acquiring the lock so an unpaid/stored transition cannot
        # create a timer on a stale callback.
        current = _order_for_panel(channel.id, allow_stored=expected_status == "stored")
        if current is None or current["id"] != order["id"] or str(current["status"]).lower() != expected_status:
            return None

        if expected_status == "active":
            ensure_tables()
            _register_order(order)
        else:
            # Store pauses any running clock without zeroing accumulated time.
            _finish_non_active()

        session = _session(channel.id)
        if session is None or int(session["order_id"]) != int(order["id"]):
            return None
        message_id = int(session.get("timer_message_id") or 0)
        if message_id:
            try:
                old = await channel.fetch_message(message_id)
            except discord.NotFound:
                old = None
                _set_message_id(order["id"], 0)
            except (discord.Forbidden, discord.HTTPException):
                return None  # Do not make a duplicate if the old panel is inaccessible.
            if old is not None:
                if reposition or int(old.id) < operation_id:
                    try:
                        await old.delete()
                    except (discord.NotFound,):
                        pass
                    except (discord.Forbidden, discord.HTTPException):
                        return None
                    _set_message_id(order["id"], 0)
                else:
                    if session["state"] == "running":
                        await old.edit(
                            embed=timer_embed(session),
                            view=SimpleHourlyTimerView(session["state"]),
                        )
                    return int(old.id)

        existing = await _find_existing(channel, int(order["id"]))
        if existing is not None:
            if int(existing.id) > operation_id:
                _set_message_id(order["id"], existing.id)
                return int(existing.id)
            try:
                await existing.delete()
            except discord.NotFound:
                pass
            except (discord.Forbidden, discord.HTTPException):
                return None

        created = await channel.send(
            embed=timer_embed(session),
            view=SimpleHourlyTimerView(session["state"]),
            allowed_mentions=discord.AllowedMentions.none(),
        )
        _set_message_id(order["id"], created.id)
        return int(created.id)


async def hide_early_unpaid_timer_panels(bot: discord.Client) -> None:
    """Remove previously emitted prepayment panels without deleting timer state."""
    if not DATABASE.is_file():
        return
    with _connect() as db:
        rows = db.execute(
            "SELECT t.order_id, t.ticket_channel_id, t.timer_message_id "
            "FROM simple_order_timers t JOIN web_orders o ON o.id=t.order_id "
            "WHERE o.status IN ('pending_cs_dispatch','waiting_acceptance','accepted_pending_pay') "
            "AND t.timer_message_id IS NOT NULL AND t.timer_message_id!='0'"
        ).fetchall()
    for row in rows:
        ticket_id = str(row["ticket_channel_id"])
        channel = await _channel(bot, ticket_id)
        if not isinstance(channel, discord.TextChannel):
            continue
        lock = _PANEL_LOCKS.setdefault(int(channel.id), asyncio.Lock())
        async with lock:
            with _connect() as db:
                fresh = db.execute(
                    "SELECT t.timer_message_id, o.status FROM simple_order_timers t "
                    "JOIN web_orders o ON o.id=t.order_id WHERE t.order_id=?",
                    (int(row["order_id"]),),
                ).fetchone()
            if not fresh or str(fresh["status"]) not in UNPAID_TICKET_STATUSES:
                continue
            message_id = int(fresh["timer_message_id"] or 0)
            if not message_id:
                continue
            try:
                message = await channel.fetch_message(message_id)
                await message.delete()
            except discord.NotFound:
                pass
            except (discord.Forbidden, discord.HTTPException):
                continue
            with _connect() as db:
                db.execute(
                    "UPDATE simple_order_timers SET "
                    "elapsed_seconds=elapsed_seconds + CASE WHEN state='running' "
                    "THEN MAX(0, ? - COALESCE(running_since, ?)) ELSE 0 END, "
                    "state=CASE WHEN state='running' THEN 'paused' ELSE state END, "
                    "running_since=NULL, timer_message_id='0', updated_at=? "
                    "WHERE order_id=?",
                    (time.time(), time.time(), time.time(), int(row["order_id"])),
                )


def _set_message_id(order_id: int, message_id: int) -> None:
    with _connect() as db:
        db.execute(
            "UPDATE simple_order_timers SET timer_message_id=?, updated_at=? "
            "WHERE order_id=?",
            (str(message_id), time.time(), int(order_id)),
        )


def _finish_non_active() -> list[tuple[int, str]]:
    """Pause stored orders; freeze completed/cancelled orders without deleting time."""
    now = time.time()
    with _connect() as db:
        db.execute(
            "UPDATE simple_order_timers SET "
            "elapsed_seconds=elapsed_seconds + MAX(0, ? - COALESCE(running_since, ?)), "
            "state='paused', running_since=NULL, updated_at=? "
            "WHERE state='running' AND order_id IN "
            "(SELECT id FROM web_orders WHERE status='stored')",
            (now, now, now),
        )
        ended = db.execute(
            "SELECT t.order_id, t.ticket_channel_id FROM simple_order_timers t "
            "LEFT JOIN web_orders o ON o.id=t.order_id "
            "WHERE t.state!='finished' AND "
            "(o.id IS NULL OR o.status IN ('closed','cancelled','canceled'))"
        ).fetchall()
        db.execute(
            "UPDATE simple_order_timers SET "
            "elapsed_seconds=elapsed_seconds + CASE WHEN state='running' "
            "THEN MAX(0, ? - COALESCE(running_since, ?)) ELSE 0 END, "
            "state='finished', running_since=NULL, updated_at=? "
            "WHERE state!='finished' AND order_id IN "
            "(SELECT t.order_id FROM simple_order_timers t "
            "LEFT JOIN web_orders o ON o.id=t.order_id "
            "WHERE o.id IS NULL OR o.status IN ('closed','cancelled','canceled'))",
            (now, now, now),
        )
        return [(int(r[0]), str(r[1])) for r in ended]


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
    """Refresh paid clocks, never opening an unpaid panel before order operations."""
    ensure_tables()
    if not DATABASE.is_file():
        return
    await hide_early_unpaid_timer_panels(bot)
    finished = _finish_non_active()
    for order_id, ticket_id in finished:
        session = _session(ticket_id)
        if not session or not session.get("timer_message_id"):
            continue
        channel = await _channel(bot, ticket_id)
        if not isinstance(channel, discord.TextChannel):
            continue
        try:
            msg = await channel.fetch_message(int(session["timer_message_id"]))
            await msg.edit(embed=timer_embed(session), view=SimpleHourlyTimerView("finished"))
        except (discord.NotFound, discord.Forbidden, discord.HTTPException, ValueError):
            pass
    for order in _eligible_orders():
        # Operation panel is the source of placement: never race payment
        # finalization or recreate a timer in an unpaid ticket.
        if _operation_panel_id(int(order["ticket_channel_id"])) is None:
            continue
        channel = await _channel(bot, order["ticket_channel_id"])
        if not isinstance(channel, discord.TextChannel):
            continue
        try:
            await ensure_timer_panel_after_operation(channel, order_id=int(order["id"]))
        except (discord.Forbidden, discord.NotFound, discord.HTTPException) as exc:
            print(f"[simple-order-timer] refresh failed order={order['id']}: {type(exc).__name__}", flush=True)

async def timer_worker(bot: discord.Client) -> None:
    await bot.wait_until_ready()
    while not bot.is_closed():
        try:
            await sync_once(bot)
        except Exception as exc:
            print(f"[simple-order-timer] sync error: {type(exc).__name__}: {exc}", flush=True)
        await asyncio.sleep(60)


def install_simple_order_timer(
    bot: discord.Client, order_selections: Mapping[int, dict] | None = None
) -> None:
    global _ORDER_SELECTIONS
    if order_selections is not None:
        _ORDER_SELECTIONS = order_selections
    if not getattr(bot, "_simple_order_timer_view_registered", False):
        bot.add_view(SimpleHourlyTimerView())
        bot._simple_order_timer_view_registered = True


def ensure_simple_order_timer_worker_started(bot: discord.Client) -> None:
    if not getattr(bot, "_simple_order_timer_worker_started", False):
        bot._simple_order_timer_worker_started = True
        bot.loop.create_task(timer_worker(bot))
