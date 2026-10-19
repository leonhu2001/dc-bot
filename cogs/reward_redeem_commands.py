from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands

from core.database import save_bot_data
from core.permissions import is_customer_staff
from core.time_utils import get_taipei_now_iso
from services.rewards import get_current_reward_points, get_customer_reward_data


POINT_REDEEM_ITEMS = [
    {"key": "discount_20", "cost": 10, "name": "20T 折價券"},
    {"key": "discount_30", "cost": 15, "name": "30T 折價券"},
    {"key": "free_specify_fee", "cost": 30, "name": "免指定費 1 次"},
    {"key": "discount_100", "cost": 45, "name": "100T 折價券"},
    {"key": "extra_hour_30m", "cost": 60, "name": "加時 30 分鐘"},
    {"key": "extra_hour_1h", "cost": 110, "name": "加時 1 小時"},
    {"key": "extra_game_1", "cost": 40, "name": "加 1 局"},
    {"key": "extra_game_2", "cost": 70, "name": "加 2 局"},
]

POINT_REDEEM_ITEMS_BY_KEY = {item["key"]: item for item in POINT_REDEEM_ITEMS}
POINT_REDEEM_ITEMS_BY_KEY.setdefault(
    "free_play_1h",
    dict(
        key="free_play_1h",
        cost=80,
        name="免費陪玩 1 小時",
    ),
)

_REWARD_REDEEM_SELECTIONS: dict[tuple[int, int], str] = {}


def build_reward_redeem_embed() -> discord.Embed:
    lines = [
        f"**{item['cost']} 點**｜{item['name']}"
        for item in POINT_REDEEM_ITEMS
    ]

    embed = discord.Embed(
        title="🎁 魔丸點數兌換",
        description=(
            "請先使用下拉式清單選擇要兌換的項目，再按下「兌換」。\n\n"
            + "\n".join(lines)
        ),
        color=discord.Color.gold(),
    )
    embed.set_footer(text="兌換成功後會自動扣除點數，並寫入顧客備註。")
    return embed


def append_reward_redeem_customer_note(
    data: dict,
    *,
    user_id: int,
    cost: int,
    reward_name: str,
    before_points: int,
    after_points: int,
) -> None:
    now_text = get_taipei_now_iso()
    note_text = (
        f"點數兌換：{cost} 點，{reward_name} "
        f"｜兌換前 {before_points} 點，兌換後 {after_points} 點"
    )

    notes = data.setdefault("notes", [])
    if not isinstance(notes, list):
        notes = []
        data["notes"] = notes

    notes.append(
        {
            "created_at": now_text,
            "created_by": int(user_id),
            "author_id": int(user_id),
            "operator_id": int(user_id),
            "content": note_text,
            "note": note_text,
            "source": "point_redeem",
        }
    )


class RewardRedeemSelect(discord.ui.Select):
    def __init__(self):
        options = [
            discord.SelectOption(
                label=f"{item['cost']} 點｜{item['name']}",
                value=item["key"],
                description=f"兌換 {item['name']}",
            )
            for item in POINT_REDEEM_ITEMS
        ]

        super().__init__(
            placeholder="選擇要兌換的項目",
            min_values=1,
            max_values=1,
            options=options,
            custom_id="reward_redeem_select",
        )

    async def callback(self, interaction: discord.Interaction):
        selected_key = self.values[0]
        item = POINT_REDEEM_ITEMS_BY_KEY.get(selected_key)

        if item is None:
            await interaction.response.send_message(
                "找不到這個兌換項目，請重新選擇。",
                ephemeral=True,
            )
            return

        message_id = interaction.message.id if interaction.message else 0
        _REWARD_REDEEM_SELECTIONS[
            (int(message_id), int(interaction.user.id))
        ] = selected_key

        await interaction.response.send_message(
            f"已選擇：**{item['cost']} 點｜{item['name']}**\n確認後請按「兌換」。",
            ephemeral=True,
        )


class RewardRedeemView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(RewardRedeemSelect())

    @discord.ui.button(
        label="兌換",
        style=discord.ButtonStyle.success,
        custom_id="reward_redeem_confirm_button",
    )
    async def redeem_button(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ):
        if not isinstance(interaction.user, discord.Member):
            await interaction.response.send_message(
                "這個功能只能在伺服器內使用。",
                ephemeral=True,
            )
            return

        message_id = interaction.message.id if interaction.message else 0
        selection_key = (int(message_id), int(interaction.user.id))
        selected_key = _REWARD_REDEEM_SELECTIONS.get(selection_key)

        if not selected_key:
            await interaction.response.send_message(
                "請先用下拉式清單選擇要兌換的項目。",
                ephemeral=True,
            )
            return

        item = POINT_REDEEM_ITEMS_BY_KEY.get(selected_key)
        if item is None:
            await interaction.response.send_message(
                "找不到這個兌換項目，請重新選擇。",
                ephemeral=True,
            )
            return

        cost = int(item["cost"])
        reward_name = str(item["name"])
        data = get_customer_reward_data(interaction.user.id)
        before_points = int(get_current_reward_points(data))

        if before_points < cost:
            await interaction.response.send_message(
                f"你的點數不足。\n目前點數：**{before_points} 點**\n需要點數：**{cost} 點**",
                ephemeral=True,
            )
            return

        data["point_adjustment"] = int(data.get("point_adjustment", 0) or 0) - cost
        after_points = int(get_current_reward_points(data))
        data["points"] = after_points

        point_logs = data.setdefault("point_adjustment_logs", [])
        if not isinstance(point_logs, list):
            point_logs = []
            data["point_adjustment_logs"] = point_logs

        point_logs.append(
            {
                "created_at": get_taipei_now_iso(),
                "operator_id": int(interaction.user.id),
                "operator_name": str(interaction.user),
                "delta": -cost,
                "reason": f"點數兌換：{reward_name}",
                "before_points": before_points,
                "after_points": after_points,
            }
        )

        append_reward_redeem_customer_note(
            data,
            user_id=interaction.user.id,
            cost=cost,
            reward_name=reward_name,
            before_points=before_points,
            after_points=after_points,
        )

        save_bot_data()
        _REWARD_REDEEM_SELECTIONS.pop(selection_key, None)

        await interaction.response.send_message(
            (
                f"兌換成功：**{reward_name}**\n"
                f"已扣除：**{cost} 點**\n"
                f"剩餘點數：**{after_points} 點**\n"
                "兌換紀錄已寫入你的顧客備註。"
            ),
            ephemeral=True,
        )


class RewardRedeemCommands(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(
        name="reward_redeem_panel",
        description="發送會員點數兌換面板",
    )
    async def reward_redeem_panel(self, interaction: discord.Interaction):
        if (
            not isinstance(interaction.user, discord.Member)
            or not is_customer_staff(interaction.user)
        ):
            await interaction.response.send_message(
                "只有客服可以發送點數兌換面板。",
                ephemeral=True,
            )
            return

        if interaction.channel is None or not hasattr(interaction.channel, "send"):
            await interaction.response.send_message(
                "請在文字頻道使用這個指令。",
                ephemeral=True,
            )
            return

        await interaction.response.defer(ephemeral=True)
        await interaction.channel.send(
            embed=build_reward_redeem_embed(),
            view=RewardRedeemView(),
            allowed_mentions=discord.AllowedMentions(
                users=False,
                roles=False,
                everyone=False,
            ),
        )
        await interaction.followup.send("已發送點數兌換面板。", ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(RewardRedeemCommands(bot))
    guild_id = int(getattr(bot, "guild_id_value", 0) or 0)
    if guild_id:
        bot.tree.copy_global_to(guild=discord.Object(id=guild_id))
