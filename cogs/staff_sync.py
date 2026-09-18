import asyncio
import os
import sqlite3
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import discord
from discord import app_commands
from discord.ext import commands, tasks

from shared.db import SessionLocal, create_all_tables
from web.app.config import config
from web.app.services.staff_service import sync_staff_members_from_discord


DEFAULT_SYNC_INTERVAL_MINUTES = 30
SECURITY_MAINTENANCE_SECONDS = 30
STALE_TOPUP_MINUTES = 5
TAIPEI_TZ = timezone(timedelta(hours=8))
BOT_DB_PATH = Path(__file__).resolve().parents[1] / "bot.db"
VOICE_REGISTRY_TABLE = "temp_voice_room_registry"


def _get_sync_interval_minutes() -> int:
    raw_value = os.getenv("STAFF_SYNC_INTERVAL_MINUTES", "")

    try:
        value = int(raw_value)
    except (TypeError, ValueError):
        value = DEFAULT_SYNC_INTERVAL_MINUTES

    return max(5, value)


def _is_admin_member(member: discord.Member) -> bool:
    role_ids = {str(role.id) for role in getattr(member, "roles", [])}
    allowed = set(config.ADMIN_ROLE_IDS) | set(config.CUSTOMER_SERVICE_ROLE_IDS)
    return bool(role_ids & allowed)


def _security_db() -> sqlite3.Connection:
    conn = sqlite3.connect(BOT_DB_PATH, timeout=15)
    conn.row_factory = sqlite3.Row
    return conn


def _ensure_security_tables() -> None:
    with _security_db() as conn:
        conn.execute(
            f"""
            CREATE TABLE IF NOT EXISTS {VOICE_REGISTRY_TABLE} (
                channel_id TEXT PRIMARY KEY,
                guild_id TEXT NOT NULL,
                room_type TEXT NOT NULL,
                owner_id TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            f"CREATE INDEX IF NOT EXISTS idx_{VOICE_REGISTRY_TABLE}_guild "
            f"ON {VOICE_REGISTRY_TABLE}(guild_id)"
        )
        conn.commit()


def _parse_datetime(value: object) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None

    try:
        dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None

    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=TAIPEI_TZ)
    return dt


def _recover_stale_crediting_topups() -> int:
    """Recover rows left in crediting by a hard process/VPS stop.

    The normal topup worker is idempotent by topup_no for wallet transactions and
    VIP reward keys, so returning a stale row to approved_pending_credit is safe.
    """
    cutoff = datetime.now(TAIPEI_TZ) - timedelta(minutes=STALE_TOPUP_MINUTES)

    with _security_db() as conn:
        table_exists = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='topup_orders' LIMIT 1"
        ).fetchone()
        if table_exists is None:
            return 0

        rows = conn.execute(
            "SELECT id, updated_at FROM topup_orders WHERE status='crediting'"
        ).fetchall()

        stale_ids: list[int] = []
        for row in rows:
            updated_at = _parse_datetime(row["updated_at"])
            if updated_at is None or updated_at <= cutoff:
                stale_ids.append(int(row["id"]))

        if not stale_ids:
            return 0

        now_text = datetime.now(TAIPEI_TZ).isoformat(timespec="seconds")
        recovered = 0
        for topup_id in stale_ids:
            cur = conn.execute(
                """
                UPDATE topup_orders
                SET status='approved_pending_credit', updated_at=?
                WHERE id=? AND status='crediting'
                """,
                (now_text, topup_id),
            )
            recovered += int(cur.rowcount or 0)

        conn.commit()
        return recovered


def _main_bot_module():
    return sys.modules.get("__main__")


def _runtime_room_type(channel_id: int) -> str | None:
    module = _main_bot_module()
    if module is None:
        return None

    mappings = (
        ("TEMP_PLAY_VOICE_CHANNEL_IDS", "play"),
        ("TEMP_VIP_VOICE_CHANNEL_IDS", "vip"),
        ("TEMP_PUBLIC_VOICE_CHANNEL_IDS", "public"),
    )
    for attr_name, room_type in mappings:
        values = getattr(module, attr_name, None)
        try:
            if values is not None and int(channel_id) in values:
                return room_type
        except Exception:
            continue
    return None


def _canonical_room_type(channel: discord.VoiceChannel) -> str | None:
    name = str(channel.name or "")
    if name.startswith("🎮┃") and name.endswith("的陪玩頻道"):
        return "play"
    if name.startswith("👑┃") and name.endswith("的𝙑𝙄𝙋頻道"):
        return "vip"
    if name.startswith("➕┃") and name.endswith("的公共房間"):
        return "public"
    return None


def _registry_row(channel_id: int) -> dict | None:
    _ensure_security_tables()
    with _security_db() as conn:
        row = conn.execute(
            f"SELECT * FROM {VOICE_REGISTRY_TABLE} WHERE channel_id=? LIMIT 1",
            (str(channel_id),),
        ).fetchone()
        return dict(row) if row else None


def _managed_room_type(channel: discord.VoiceChannel) -> str | None:
    runtime_type = _runtime_room_type(channel.id)
    if runtime_type:
        return runtime_type

    row = _registry_row(channel.id)
    if row:
        return str(row.get("room_type") or "") or None

    # One-time discovery also adopts rooms created before this persistence guard was
    # deployed. After adoption, renaming no longer affects cleanup because ID is stored.
    return _canonical_room_type(channel)


def _runtime_owner_id(channel_id: int) -> int | None:
    module = _main_bot_module()
    if module is None:
        return None

    panels = getattr(module, "TEMP_VOICE_CONTROL_PANELS", None)
    if not isinstance(panels, dict):
        return None

    data = panels.get(int(channel_id))
    if not isinstance(data, dict):
        return None

    try:
        owner_id = int(data.get("owner_id") or 0)
    except (TypeError, ValueError):
        return None
    return owner_id or None


def _upsert_voice_room(
    channel: discord.VoiceChannel,
    room_type: str,
    owner_id: int | None = None,
) -> None:
    _ensure_security_tables()
    now_text = datetime.now(timezone.utc).isoformat(timespec="seconds")
    owner_value = str(owner_id) if owner_id else None

    with _security_db() as conn:
        conn.execute(
            f"""
            INSERT INTO {VOICE_REGISTRY_TABLE}(
                channel_id, guild_id, room_type, owner_id, created_at, updated_at
            ) VALUES(?,?,?,?,?,?)
            ON CONFLICT(channel_id) DO UPDATE SET
                guild_id=excluded.guild_id,
                room_type=excluded.room_type,
                owner_id=COALESCE(excluded.owner_id, {VOICE_REGISTRY_TABLE}.owner_id),
                updated_at=excluded.updated_at
            """,
            (
                str(channel.id),
                str(channel.guild.id),
                str(room_type),
                owner_value,
                now_text,
                now_text,
            ),
        )
        conn.commit()


def _delete_registry_row(channel_id: int) -> None:
    _ensure_security_tables()
    with _security_db() as conn:
        conn.execute(
            f"DELETE FROM {VOICE_REGISTRY_TABLE} WHERE channel_id=?",
            (str(channel_id),),
        )
        conn.commit()


def _guild_registry_rows(guild_id: int) -> list[dict]:
    _ensure_security_tables()
    with _security_db() as conn:
        rows = conn.execute(
            f"SELECT * FROM {VOICE_REGISTRY_TABLE} WHERE guild_id=?",
            (str(guild_id),),
        ).fetchall()
        return [dict(row) for row in rows]


def _forget_runtime_room(channel_id: int) -> None:
    module = _main_bot_module()
    if module is None:
        return

    for attr_name in (
        "TEMP_PLAY_VOICE_CHANNEL_IDS",
        "TEMP_VIP_VOICE_CHANNEL_IDS",
        "TEMP_PUBLIC_VOICE_CHANNEL_IDS",
    ):
        values = getattr(module, attr_name, None)
        try:
            if values is not None:
                values.discard(int(channel_id))
        except Exception:
            pass

    panels = getattr(module, "TEMP_VOICE_CONTROL_PANELS", None)
    if isinstance(panels, dict):
        panels.pop(int(channel_id), None)


def _registry_age_seconds(row: dict) -> float:
    created_at = _parse_datetime(row.get("created_at"))
    if created_at is None:
        return 999999.0
    now = datetime.now(created_at.tzinfo or timezone.utc)
    return max(0.0, (now - created_at).total_seconds())


class StaffSyncCog(commands.Cog):
    staff = app_commands.Group(name="staff", description="人員同步")

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        _ensure_security_tables()
        self.sync_staff_members_loop.change_interval(minutes=_get_sync_interval_minutes())
        self.sync_staff_members_loop.start()
        self.security_maintenance_loop.start()

    def cog_unload(self) -> None:
        self.sync_staff_members_loop.cancel()
        self.security_maintenance_loop.cancel()

    async def _sync_once(self) -> dict:
        def run_sync() -> dict:
            create_all_tables()
            db = SessionLocal()

            try:
                result = sync_staff_members_from_discord(db)
                db.commit()
                return result
            except Exception:
                db.rollback()
                raise
            finally:
                db.close()

        return await asyncio.to_thread(run_sync)

    async def _delete_managed_voice_room(
        self,
        channel: discord.VoiceChannel,
        *,
        reason: str,
    ) -> bool:
        # VIP 房現在是永久房：空房、孤兒掃描都不得刪除。
        # 真正 VIP 失效的刪除由 bot.py 的 VIP lifecycle 流程負責。
        room_type = _managed_room_type(channel)
        if room_type == "vip":
            print(
                f"[voice-guard] skip empty delete for persistent VIP room "
                f"channel={channel.id} reason={reason}",
                flush=True,
            )
            return False

        if channel.members:
            return False

        for attempt in range(1, 4):
            try:
                if channel.members:
                    return False
                await channel.delete(reason=reason)
                _delete_registry_row(channel.id)
                _forget_runtime_room(channel.id)
                return True
            except discord.NotFound:
                _delete_registry_row(channel.id)
                _forget_runtime_room(channel.id)
                return True
            except (discord.Forbidden, discord.HTTPException) as exc:
                if attempt >= 3:
                    print(
                        f"[voice-guard] delete failed channel={channel.id} "
                        f"attempt={attempt}: {exc}",
                        flush=True,
                    )
                    return False
                await asyncio.sleep(2)

        return False

    @commands.Cog.listener()
    async def on_voice_state_update(
        self,
        member: discord.Member,
        before: discord.VoiceState,
        after: discord.VoiceState,
    ) -> None:
        if isinstance(after.channel, discord.VoiceChannel):
            room_type = _managed_room_type(after.channel)
            if room_type:
                owner_id = _runtime_owner_id(after.channel.id)
                if owner_id is None and _runtime_room_type(after.channel.id):
                    owner_id = member.id
                _upsert_voice_room(after.channel, room_type, owner_id)

        if isinstance(before.channel, discord.VoiceChannel) and not before.channel.members:
            room_type = _managed_room_type(before.channel)
            if room_type:
                _upsert_voice_room(
                    before.channel,
                    room_type,
                    _runtime_owner_id(before.channel.id),
                )
                if room_type != "vip":
                    await self._delete_managed_voice_room(
                        before.channel,
                        reason="Persistent temporary voice room is empty",
                    )

    @commands.Cog.listener()
    async def on_guild_channel_update(
        self,
        before: discord.abc.GuildChannel,
        after: discord.abc.GuildChannel,
    ) -> None:
        if not isinstance(before, discord.VoiceChannel) or not isinstance(after, discord.VoiceChannel):
            return

        room_type = _managed_room_type(before) or _managed_room_type(after)
        if room_type:
            _upsert_voice_room(
                after,
                room_type,
                _runtime_owner_id(after.id),
            )

    @commands.Cog.listener()
    async def on_guild_channel_delete(self, channel: discord.abc.GuildChannel) -> None:
        if isinstance(channel, discord.VoiceChannel) and _registry_row(channel.id):
            _delete_registry_row(channel.id)
            _forget_runtime_room(channel.id)

    @tasks.loop(seconds=SECURITY_MAINTENANCE_SECONDS)
    async def security_maintenance_loop(self) -> None:
        try:
            recovered = await asyncio.to_thread(_recover_stale_crediting_topups)
            if recovered:
                print(
                    f"[topup-recovery] returned {recovered} stale crediting row(s) to retry queue",
                    flush=True,
                )
        except Exception as exc:
            print(f"[topup-recovery] failed: {exc}", flush=True)

        for guild in list(self.bot.guilds):
            # Discover all runtime-created rooms while their in-memory IDs still exist.
            # Canonical-name fallback adopts pre-deployment rooms once.
            for channel in list(guild.voice_channels):
                try:
                    room_type = _managed_room_type(channel)
                    if room_type:
                        _upsert_voice_room(
                            channel,
                            room_type,
                            _runtime_owner_id(channel.id),
                        )
                except Exception as exc:
                    print(
                        f"[voice-guard] registry update failed channel={channel.id}: {exc}",
                        flush=True,
                    )

            # Persistence means renamed rooms remain recognizable after process restart.
            for row in _guild_registry_rows(guild.id):
                try:
                    channel_id = int(row["channel_id"])
                except (TypeError, ValueError):
                    continue

                channel = guild.get_channel(channel_id)
                if channel is None:
                    _delete_registry_row(channel_id)
                    _forget_runtime_room(channel_id)
                    continue

                if not isinstance(channel, discord.VoiceChannel):
                    _delete_registry_row(channel_id)
                    _forget_runtime_room(channel_id)
                    continue

                # Give a just-created room enough time for the creator move operation.
                # If move_to fails (Discord 40032), the orphan is removed on this sweep.
                if (
                    str(row.get("room_type") or "") != "vip"
                    and not channel.members
                    and _registry_age_seconds(row) >= 15
                ):
                    await self._delete_managed_voice_room(
                        channel,
                        reason="Temporary voice room orphan/empty sweeper",
                    )

    @security_maintenance_loop.before_loop
    async def before_security_maintenance_loop(self) -> None:
        await self.bot.wait_until_ready()

    @tasks.loop(minutes=DEFAULT_SYNC_INTERVAL_MINUTES)
    async def sync_staff_members_loop(self) -> None:
        try:
            result = await self._sync_once()
            now_text = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")
            print(
                "Discord staff auto sync complete "
                f"at {now_text}: "
                f"total_seen={result['total_seen']}, "
                f"synced_count={result['synced_count']}, "
                f"disabled_count={result['disabled_count']}"
            )
        except Exception as exc:
            print(f"Discord staff auto sync failed: {exc}")

    @sync_staff_members_loop.before_loop
    async def before_sync_staff_members_loop(self) -> None:
        await self.bot.wait_until_ready()

    @staff.command(
        name="sync_members",
        description="手動同步網站後台的客服 / 打手 / 陪玩下拉選單名單",
    )
    @app_commands.default_permissions(manage_messages=True)
    async def sync_staff_members_command(self, interaction: discord.Interaction) -> None:
        if not isinstance(interaction.user, discord.Member):
            await interaction.response.send_message("無法確認你的身分組。", ephemeral=True)
            return

        if not _is_admin_member(interaction.user):
            await interaction.response.send_message("只有總管 / 客服可以同步網站人員名單。", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True, thinking=True)

        try:
            result = await self._sync_once()
        except Exception as exc:
            await interaction.followup.send(
                f"同步失敗：{exc}",
                ephemeral=True,
            )
            return

        await interaction.followup.send(
            "網站人員名單同步完成。\n"
            f"掃描人數：{result['total_seen']}\n"
            f"同步人數：{result['synced_count']}\n"
            f"停用人數：{result['disabled_count']}",
            ephemeral=True,
        )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(StaffSyncCog(bot))
