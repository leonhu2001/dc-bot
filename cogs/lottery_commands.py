from __future__ import annotations

import discord
from discord.ext import commands
from discord import app_commands

from core.permissions import has_role, is_customer_staff
from services.logging_service import send_order_log
from services.lottery import (
    LOTTERY_COST_PER_CHANCE_DEFAULT,
    LOTTERY_MAX_CHANCES_PER_USER_DEFAULT,
    get_default_lottery_period,
    get_lottery_settings,
    save_lottery_settings,
    get_lottery_entries,
    get_lottery_drawn_user_ids,
    get_lottery_entry,
    upsert_lottery_entry,
    clear_lottery_entries,
    record_lottery_draw,
    build_lottery_info_embed,
    build_lottery_status_embed,
    pick_weighted_lottery_winners,
    send_lottery_announcement,
)
from services.rewards import (
    get_customer_reward_data,
    get_current_reward_points,
    adjust_customer_points,
)


class LotteryCommands(commands.Cog):
    lottery = app_commands.Group(name="lottery", description="魔丸點數抽獎")

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    def is_lottery_admin(self, member: discord.Member) -> bool:
        manager_role_id = int(getattr(self.bot, "manager_role_id_value", 0) or 0)
        return is_customer_staff(member) or has_role(member, manager_role_id) or member.guild_permissions.administrator

    @lottery.command(
        name="info",
        description="查看目前魔丸點數抽獎活動",
    )
    async def lottery_info(self, interaction: discord.Interaction):
        settings = get_lottery_settings()
        await interaction.response.send_message(embed=build_lottery_info_embed(settings), ephemeral=True)

    @lottery.command(
        name="join",
        description="使用魔丸點數參加抽獎，5 點 = 1 次抽獎機會",
    )
    @app_commands.describe(chances="要參加幾次抽獎，每次會消耗 5 點")
    async def join_lottery(self, interaction: discord.Interaction, chances: int):
        if chances <= 0:
            await interaction.response.send_message("抽獎次數必須大於 0。", ephemeral=True)
            return

        settings = get_lottery_settings()
        if settings.get("status") != "open":
            await interaction.response.send_message("目前抽獎尚未開放報名。", ephemeral=True)
            return

        period = str(settings.get("period", get_default_lottery_period()))
        cost = int(settings.get("cost_per_chance", LOTTERY_COST_PER_CHANCE_DEFAULT))
        max_chances = int(settings.get("max_chances_per_user", LOTTERY_MAX_CHANCES_PER_USER_DEFAULT))
        current_entry = get_lottery_entry(period, interaction.user.id)
        current_chances = int(current_entry["chances"]) if current_entry else 0

        if current_chances + chances > max_chances:
            await interaction.response.send_message(
                f"本期每人最多 {max_chances} 次，你目前已有 {current_chances} 次，最多還能加 {max(0, max_chances - current_chances)} 次。",
                ephemeral=True,
            )
            return

        points_needed = chances * cost
        data = get_customer_reward_data(interaction.user.id)
        current_points = get_current_reward_points(data)

        if current_points < points_needed:
            await interaction.response.send_message(
                f"點數不足。你目前有 {current_points:,} 點，本次需要 {points_needed:,} 點。",
                ephemeral=True,
            )
            return

        ok, message = await adjust_customer_points(
            customer_id=interaction.user.id,
            delta_points=-points_needed,
            operator_id=interaction.user.id,
            reason=f"參加 {period} 點數抽獎 {chances} 次",
        )
        if not ok:
            await interaction.response.send_message(message, ephemeral=True)
            return

        upsert_lottery_entry(period, interaction.user.id, chances, points_needed)

        await send_order_log(
            interaction.guild,
            title="抽獎報名",
            fields=[
                ("顧客", interaction.user.mention, True),
                ("期別", period, True),
                ("抽獎次數", f"{chances} 次", True),
                ("消耗點數", f"{points_needed:,} 點", True),
            ],
            color=discord.Color.gold(),
        )

        await interaction.response.send_message(
            f"已成功參加 **{period}** 抽獎 {chances} 次，消耗 {points_needed:,} 點。\n"
            f"你本期目前共 {current_chances + chances} 次抽獎機會。",
            ephemeral=True,
        )

    @lottery.command(
        name="status",
        description="客服查看目前抽獎池狀態",
    )
    async def lottery_status(self, interaction: discord.Interaction):
        if not isinstance(interaction.user, discord.Member) or not self.is_lottery_admin(interaction.user):
            await interaction.response.send_message("只有客服、店長或管理員可以查看抽獎池。", ephemeral=True)
            return

        settings = get_lottery_settings()
        await interaction.response.send_message(embed=build_lottery_status_embed(settings), ephemeral=True)

    @lottery.command(
        name="open",
        description="管理層設定或開啟本期點數抽獎",
    )
    @app_commands.describe(
        period="期別，例如 2026-05；不填則使用本月",
        title="抽獎活動名稱，可不填",
        note="活動備註，可先寫：獎品內部討論中",
        max_chances_per_user="每人本期最多可投入幾次，預設 20",
        announce_channel="抽獎開始公告要發到哪個頻道；不填則用預設公告頻道",
    )
    @app_commands.default_permissions(manage_messages=True)
    async def lottery_open(
        self,
        interaction: discord.Interaction,
        period: str | None = None,
        title: str | None = None,
        note: str | None = None,
        max_chances_per_user: int | None = None,
        announce_channel: discord.TextChannel | None = None,
    ):
        if not isinstance(interaction.user, discord.Member) or not self.is_lottery_admin(interaction.user):
            await interaction.response.send_message("只有客服、店長或管理員可以設定抽獎。", ephemeral=True)
            return

        if max_chances_per_user is not None and max_chances_per_user <= 0:
            await interaction.response.send_message("每人上限必須大於 0。", ephemeral=True)
            return

        settings = get_lottery_settings()
        settings["period"] = (period or get_default_lottery_period()).strip()
        settings["title"] = (title or settings.get("title") or "魔丸點數抽獎").strip()
        settings["note"] = (note or settings.get("note") or "獎品由管理層討論後設定。").strip()
        settings["status"] = "open"
        settings["cost_per_chance"] = LOTTERY_COST_PER_CHANCE_DEFAULT
        settings["max_chances_per_user"] = int(max_chances_per_user or LOTTERY_MAX_CHANCES_PER_USER_DEFAULT)
        save_lottery_settings(settings)

        await send_order_log(
            interaction.guild,
            title="抽獎已開啟 / 設定",
            fields=[
                ("期別", settings["period"], True),
                ("名稱", settings["title"], True),
                ("每人上限", f"{settings['max_chances_per_user']} 次", True),
                ("設定人員", interaction.user.mention, True),
                ("備註", settings["note"], False),
            ],
            color=discord.Color.gold(),
        )

        announcement_embed = build_lottery_info_embed(settings)
        announcement_embed.title = f"🎁 {settings['title']} 開始報名"
        announced = await send_lottery_announcement(
            interaction.guild,
            content="@everyone 🎁 魔丸點數抽獎已開放報名！使用 `/lottery_info` 查看活動，使用 `/join_lottery` 參加抽獎。",
            embed=announcement_embed,
            channel=announce_channel,
        )

        announce_text = f"公告已送出到 {announce_channel.mention if announce_channel else '預設公告頻道'}。" if announced else "公告送出失敗，請確認 Bot 權限與公告頻道設定。"
        await interaction.response.send_message(f"抽獎已設定並開放報名，{announce_text}", embed=build_lottery_info_embed(settings), ephemeral=True)

    @lottery.command(
        name="set_prizes",
        description="管理層設定本期抽獎獎池內容",
    )
    @app_commands.describe(
        prizes="獎池內容，例如：一獎：500T折抵券 x1｜二獎：指定費免費 x2",
        announce="是否發公告，預設否",
        announce_channel="獎池公告要發到哪個頻道；不填則用預設公告頻道",
    )
    @app_commands.default_permissions(manage_messages=True)
    async def lottery_set_prizes(
        self,
        interaction: discord.Interaction,
        prizes: str,
        announce: bool = False,
        announce_channel: discord.TextChannel | None = None,
    ):
        if not isinstance(interaction.user, discord.Member) or not self.is_lottery_admin(interaction.user):
            await interaction.response.send_message("只有客服、店長或管理員可以設定獎池。", ephemeral=True)
            return

        prize_text = prizes.strip()
        if not prize_text:
            await interaction.response.send_message("獎池內容不能是空的。", ephemeral=True)
            return

        if len(prize_text) > 1000:
            await interaction.response.send_message("獎池內容太長，請控制在 1000 字以內。", ephemeral=True)
            return

        settings = get_lottery_settings()
        settings["prizes"] = prize_text
        save_lottery_settings(settings)

        await send_order_log(
            interaction.guild,
            title="抽獎獎池已設定",
            fields=[
                ("期別", str(settings.get("period", get_default_lottery_period())), True),
                ("設定人員", interaction.user.mention, True),
                ("獎池內容", prize_text, False),
            ],
            color=discord.Color.gold(),
        )

        embed = build_lottery_info_embed(settings)
        embed.title = f"🎁 {settings.get('title', '魔丸點數抽獎')} 獎池更新"

        if announce:
            announced = await send_lottery_announcement(
                interaction.guild,
                content="@everyone 🎁 魔丸點數抽獎獎池已更新！使用 `/lottery_info` 查看活動詳情。",
                embed=embed,
                channel=announce_channel,
            )
            announce_text = f"公告已送出到 {announce_channel.mention if announce_channel else '預設公告頻道'}。" if announced else "公告送出失敗，請確認 Bot 權限與公告頻道設定。"
            await interaction.response.send_message(f"獎池已設定，{announce_text}", embed=embed, ephemeral=True)
        else:
            await interaction.response.send_message("獎池已設定。", embed=embed, ephemeral=True)

    @lottery.command(
        name="close",
        description="管理層關閉本期抽獎報名",
    )
    @app_commands.default_permissions(manage_messages=True)
    async def lottery_close(self, interaction: discord.Interaction):
        if not isinstance(interaction.user, discord.Member) or not self.is_lottery_admin(interaction.user):
            await interaction.response.send_message("只有客服、店長或管理員可以關閉抽獎。", ephemeral=True)
            return

        settings = get_lottery_settings()
        settings["status"] = "closed"
        save_lottery_settings(settings)
        await interaction.response.send_message(f"已關閉 **{settings['period']}** 抽獎報名。", ephemeral=True)

    @lottery.command(
        name="draw",
        description="客服開獎；可依照已設定獎池輸入本次要抽的獎品",
    )
    @app_commands.describe(
        prize="本次要抽的獎品名稱，例如 一獎：500T折抵券",
        winners="要抽出幾位得主，預設 1",
        announce_channel="開獎公告要發到哪個頻道；不填則用預設公告頻道",
    )
    @app_commands.default_permissions(manage_messages=True)
    async def draw_lottery(
        self,
        interaction: discord.Interaction,
        prize: str,
        winners: int = 1,
        announce_channel: discord.TextChannel | None = None,
    ):
        if not isinstance(interaction.user, discord.Member) or not self.is_lottery_admin(interaction.user):
            await interaction.response.send_message("只有客服、店長或管理員可以開獎。", ephemeral=True)
            return

        if winners <= 0:
            await interaction.response.send_message("得獎人數必須大於 0。", ephemeral=True)
            return

        settings = get_lottery_settings()
        period = str(settings.get("period", get_default_lottery_period()))
        entries = get_lottery_entries(period)
        drawn_user_ids = get_lottery_drawn_user_ids(period)
        entries = [row for row in entries if int(row.get("user_id", 0) or 0) not in drawn_user_ids]

        if not entries:
            await interaction.response.send_message("目前抽獎池沒有可開獎名單，或本期所有參加者都已中過獎。", ephemeral=True)
            return

        if winners > len(entries):
            winners = len(entries)

        picked = pick_weighted_lottery_winners(entries, winners)
        for winner_id in picked:
            record_lottery_draw(period, prize, winner_id, interaction.user.id)

        result_lines = [f"{index}. <@{winner_id}>" for index, winner_id in enumerate(picked, start=1)]
        embed = discord.Embed(
            title="🎁 魔丸點數抽獎開獎",
            color=discord.Color.gold(),
        )
        embed.add_field(name="期別", value=period, inline=True)
        embed.add_field(name="獎品", value=prize, inline=True)
        embed.add_field(name="開獎人", value=interaction.user.mention, inline=True)
        embed.add_field(name="得獎者", value="\n".join(result_lines), inline=False)

        await send_order_log(
            interaction.guild,
            title="抽獎開獎",
            fields=[
                ("期別", period, True),
                ("獎品", prize, True),
                ("開獎人", interaction.user.mention, True),
                ("得獎者", "\n".join(result_lines), False),
            ],
            color=discord.Color.gold(),
        )

        announced = await send_lottery_announcement(
            interaction.guild,
            content="@everyone 🎉 魔丸點數抽獎開獎啦！恭喜得獎者！",
            embed=embed,
            channel=announce_channel,
        )

        announce_text = f"公告已送出到 {announce_channel.mention if announce_channel else '預設公告頻道'}。" if announced else "公告送出失敗，請確認 Bot 權限與公告頻道設定。"
        await interaction.response.send_message(f"開獎完成，{announce_text}", embed=embed, ephemeral=True)

    @lottery.command(
        name="cancel",
        description="客服取消顧客本期抽獎報名並退還點數",
    )
    @app_commands.describe(customer="要取消報名的顧客", reason="取消原因，可不填")
    async def cancel_lottery_entry(self, interaction: discord.Interaction, customer: discord.Member, reason: str | None = None):
        if not isinstance(interaction.user, discord.Member) or not self.is_lottery_admin(interaction.user):
            await interaction.response.send_message("只有客服、店長或管理員可以取消抽獎報名。", ephemeral=True)
            return

        settings = get_lottery_settings()
        period = str(settings.get("period", get_default_lottery_period()))
        entry = get_lottery_entry(period, customer.id)

        if entry is None or int(entry.get("chances", 0)) <= 0:
            await interaction.response.send_message(f"{customer.mention} 本期沒有抽獎報名紀錄。", ephemeral=True)
            return

        refund_points = int(entry["points_used"])
        upsert_lottery_entry(period, customer.id, -int(entry["chances"]), -refund_points)
        ok, message = await adjust_customer_points(
            customer_id=customer.id,
            delta_points=refund_points,
            operator_id=interaction.user.id,
            reason=f"取消 {period} 抽獎報名退點：{reason or '未填寫'}",
        )

        await send_order_log(
            interaction.guild,
            title="抽獎報名已取消",
            fields=[
                ("顧客", customer.mention, True),
                ("期別", period, True),
                ("退還點數", f"{refund_points:,} 點", True),
                ("操作人員", interaction.user.mention, True),
                ("原因", reason or "未填寫", False),
            ],
            color=discord.Color.orange(),
        )

        await interaction.response.send_message(message, ephemeral=True)

    @lottery.command(
        name="reset",
        description="清空本期抽獎池，不自動退點。需輸入確認文字",
    )
    @app_commands.describe(confirm_text="請輸入：確認清空", reason="清空原因，可不填")
    @app_commands.default_permissions(manage_messages=True)
    async def reset_lottery(self, interaction: discord.Interaction, confirm_text: str, reason: str | None = None):
        if not isinstance(interaction.user, discord.Member) or not self.is_lottery_admin(interaction.user):
            await interaction.response.send_message("只有客服、店長或管理員可以清空抽獎池。", ephemeral=True)
            return

        if confirm_text != "確認清空":
            await interaction.response.send_message("未清空。若確定要清空，confirm_text 請輸入：確認清空", ephemeral=True)
            return

        settings = get_lottery_settings()
        period = str(settings.get("period", get_default_lottery_period()))
        entries = get_lottery_entries(period)
        clear_lottery_entries(period)

        await send_order_log(
            interaction.guild,
            title="抽獎池已清空",
            fields=[
                ("期別", period, True),
                ("清空人員", interaction.user.mention, True),
                ("原參與人數", f"{len(entries)} 人", True),
                ("原因", reason or "未填寫", False),
            ],
            color=discord.Color.red(),
        )

        await interaction.response.send_message(f"已清空 **{period}** 抽獎池。注意：此操作不會自動退點。", ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(LotteryCommands(bot))
    guild_id = int(getattr(bot, "guild_id_value", 0) or 0)
    if guild_id:
        bot.tree.copy_global_to(guild=discord.Object(id=guild_id))
