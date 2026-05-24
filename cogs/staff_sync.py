import asyncio
import os
from datetime import datetime

import discord
from discord import app_commands
from discord.ext import commands, tasks

from shared.db import SessionLocal, create_all_tables
from web.app.config import config
from web.app.services.staff_service import sync_staff_members_from_discord


DEFAULT_SYNC_INTERVAL_MINUTES = 30


def _get_sync_interval_minutes() -> int:
    raw_value = os.getenv("STAFF_SYNC_INTERVAL_MINUTES", "")

    try:
        value = int(raw_value)
    except (TypeError, ValueError):
        value = DEFAULT_SYNC_INTERVAL_MINUTES

    return max(5, value)


def _is_admin_member(member: discord.Member) -> bool:
    role_ids = {str(role.id) for role in getattr(member, "roles", [])}
    return bool(role_ids & config.ADMIN_ROLE_IDS)


class StaffSyncCog(commands.Cog):
    staff = app_commands.Group(name="staff", description="人員同步")

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.sync_staff_members_loop.change_interval(minutes=_get_sync_interval_minutes())
        self.sync_staff_members_loop.start()

    def cog_unload(self) -> None:
        self.sync_staff_members_loop.cancel()

    async def _sync_once(self) -> dict:
        def run_sync() -> dict:
            create_all_tables()
            db = SessionLocal()

            try:
                return sync_staff_members_from_discord(db)
            finally:
                db.close()

        return await asyncio.to_thread(run_sync)

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
            await interaction.response.send_message("只有總控 / 客服可以同步網站人員名單。", ephemeral=True)
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
