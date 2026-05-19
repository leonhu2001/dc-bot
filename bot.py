import os
from dotenv import load_dotenv

load_dotenv()
import os
import json
import re
import random
import shutil
import sqlite3
import asyncio
from datetime import datetime, timezone, timedelta
from pathlib import Path

import discord
from discord.ext import commands
from discord import app_commands
from dotenv import load_dotenv


# ========= 讀取 .env =========

env_path = Path(__file__).parent / ".env"
load_dotenv(dotenv_path=env_path)

TOKEN = os.getenv("DISCORD_TOKEN")

if TOKEN is None:
    raise RuntimeError("讀不到 DISCORD_TOKEN，請確認 .env 檔案在 bot.py 同一個資料夾")


# ========= 固定 ID =========

GUILD_ID = 1129474191226306672

# 類別 ID
CUSTOMER_CATEGORY_ID = 1483895536938651809
EXAM_CATEGORY_ID = 1483873316702781471
PLAY_VOICE_CATEGORY_ID = 1482016208638447699

# 陪玩語音入口頻道名稱
PLAY_VOICE_CREATE_CHANNEL_NAME = "➕┃點我創建陪玩頻道"
OLD_PLAY_VOICE_CREATE_CHANNEL_NAMES = ["🎮┃陪玩點我創建頻道"]

# VIP 語音入口頻道名稱
VIP_VOICE_CREATE_CHANNEL_NAME = "➕┃點我創建VIP頻道"
OLD_VIP_VOICE_CREATE_CHANNEL_NAMES = ["👑┃𝙑𝙄𝙋專用點我創建頻道"]

# 公共語音入口頻道名稱
PUBLIC_VOICE_CREATE_CHANNEL_NAME = "➕┃點我創建公共頻道"

# VIP 語音入口可見 / 可進入身分組 ID
VIP_VOICE_LOBBY_ROLE_ID = 1482080566760177706

# 身分組 ID
CUSTOMER_ROLE_ID = 1482084782031638548
EXAMINER_ROLE_ID = 1497427024644411543
MANAGER_ROLE_ID = 1131128849443328030
RECRUIT_APPLICANT_ROLE_ID = 1498829171042943057  # 入職票口開啟期間身分組

# 會員制度 ID / 設定
SILVER_MEMBER_ROLE_ID = 1482080566760177706
PLATINUM_PRIVATE_CATEGORY_ID = 1483871504419520654
PLATINUM_CHAT_ROLE_IDS = [
    1503706721883783218,
    1503701170504339458,
]
REWARD_POINT_DIVISOR = 100
MEMBER_LEVELS = [
    {"name": "普通魔丸", "threshold": 0},
    {"name": "銀級魔丸", "threshold": 2500},
    {"name": "金級魔丸", "threshold": 7000},
    {"name": "白金魔丸", "threshold": 13000},
    {"name": "鑽石魔丸", "threshold": 30000},
    {"name": "頂級魔丸", "threshold": 77777},
]

# 訂單日誌 / 備份設定
ORDER_LOG_CATEGORY_ID = 1483895536938651809
ORDER_LOG_CHANNEL_NAME = "🤖┃機器人日誌"
LOTTERY_ANNOUNCE_CHANNEL_ID = 1482079302739693739
BACKUP_KEEP_DAYS = 30
ORDER_ID_PREFIX = "MO"

# 接單身分組 ID
COMPANION_RECEIVER_ROLE_ID = 1503706721883783218  # 陪玩接單
BOOSTER_RECEIVER_ROLE_ID = 1503701170504339458    # 打手接單

# 收據頻道 ID
RECEIPT_CHANNEL_ID = 1497623878619627682

# 考核通知頻道 ID
EXAM_NOTICE_CHANNEL_ID = 1482083066531942563

# 客訴面板頻道 ID
COMPLAINT_PANEL_CHANNEL_ID = 1497653883948765344

# 顧客意見箱面板頻道 ID
FEEDBACK_PANEL_CHANNEL_ID = 1504345505633927178

# 客訴送出頻道 ID
COMPLAINT_RECEIVE_CHANNEL_ID = 1502040302649872394

# 派單頻道 ID
DISPATCH_CHANNEL_ID = 1483868763446186036

# 評價頻道 ID
REVIEW_CHANNEL_ID = 1482998033091268691

# 歡迎頻道 ID
WELCOME_CHANNEL_ID = 1482080953353375752

# 新成員自動給予身分組 ID
NEW_MEMBER_ROLE_ID = 1483872591457550494

# 陪玩語音入口 / 陪玩語音房可見與可進入身分組 ID
# 目前只開放：陪玩接單、打手接單、客服
PLAY_VOICE_ALLOWED_ROLE_IDS = [
    1503706721883783218,
    1503701170504339458,
    1482084782031638548,
]

# 語音房按「隱藏」後，仍可看見房間的身分組 ID
VOICE_ROOM_HIDDEN_VISIBLE_ROLE_IDS = [
    1503706721883783218,
    1503701170504339458,
    1482084782031638548,
]

# 暫存由機器人建立的陪玩語音房 ID
TEMP_PLAY_VOICE_CHANNEL_IDS = set()

# 暫存由機器人建立的 VIP 語音房 ID
TEMP_VIP_VOICE_CHANNEL_IDS = set()

# 暫存由機器人建立的公共語音房 ID
TEMP_PUBLIC_VOICE_CHANNEL_IDS = set()

# 暫存語音房控制面板資料
# voice_channel_id -> {owner_id, panel_channel_id, room_type, locked, hidden}
TEMP_VOICE_CONTROL_PANELS = {}


# ========= Bot 設定 =========

intents = discord.Intents.default()
intents.guilds = True
intents.members = True
intents.voice_states = True
intents.message_content = True

bot = commands.Bot(command_prefix="!", intents=intents)


# ========= 工具函式 =========

def safe_channel_name(prefix: str, member: discord.Member) -> str:
    name = member.name.lower()
    clean = "".join(c if c.isalnum() else "-" for c in name)
    return f"{prefix}-{clean}-{member.id}"[:90]


def is_agree_answer(text: str) -> bool:
    answer = text.strip().lower()

    agree_words = {
        "是",
        "有",
        "已詳閱",
        "已詳讀",
        "已閱讀",
        "我已詳閱",
        "我已詳讀",
        "我已閱讀",
        "同意",
        "yes",
        "y",
        "ok",
        "okay",
    }

    return answer in agree_words


def is_customer_staff(member: discord.Member) -> bool:
    return any(role.id == CUSTOMER_ROLE_ID for role in member.roles)


def is_exam_staff(member: discord.Member) -> bool:
    return any(
        role.id in [EXAMINER_ROLE_ID, MANAGER_ROLE_ID]
        for role in member.roles
    )


def is_complaint_staff(member: discord.Member) -> bool:
    return any(
        role.id in [CUSTOMER_ROLE_ID, MANAGER_ROLE_ID]
        for role in member.roles
    )


def get_recruit_info_from_channel(channel: discord.TextChannel) -> tuple[str, str]:
    if not channel.topic:
        return "未紀錄暱稱", "未紀錄職位"

    data = {}

    for part in channel.topic.split(";"):
        if "=" in part:
            key, value = part.split("=", 1)
            data[key.strip()] = value.strip()

    nickname = data.get("recruit_nickname", "未紀錄暱稱")
    position = data.get("recruit_position", "未紀錄職位")

    return nickname, position


def get_recruit_member_id_from_channel(channel: discord.TextChannel) -> int | None:
    """從入職票口 topic 讀取申請人 ID。"""
    if not channel.topic:
        return None

    data = {}

    for part in channel.topic.split(";"):
        if "=" in part:
            key, value = part.split("=", 1)
            data[key.strip()] = value.strip()

    recruit_member_id = data.get("recruit_member_id")

    if recruit_member_id is None:
        return None

    try:
        return int(recruit_member_id)
    except ValueError:
        return None


async def remove_recruit_applicant_role(guild: discord.Guild | None, channel: discord.abc.GuildChannel | None):
    """入職票口關閉時收回申請人暫時身分組。"""
    if guild is None or not isinstance(channel, discord.TextChannel):
        return

    recruit_member_id = get_recruit_member_id_from_channel(channel)

    if recruit_member_id is None:
        return

    member = guild.get_member(recruit_member_id)
    role = guild.get_role(RECRUIT_APPLICANT_ROLE_ID)

    if member is None or role is None:
        return

    if role not in member.roles:
        return

    try:
        await member.remove_roles(role, reason="Recruit ticket closed")
    except discord.Forbidden:
        print("Bot 權限不足，無法收回入職申請暫時身分組。請確認 Bot 身分組位置高於該身分組。")
    except discord.HTTPException as e:
        print(f"收回入職申請暫時身分組失敗：{e}")


def get_order_customer_id_from_channel(channel: discord.TextChannel) -> int | None:
    """
    優先從頻道 topic 讀取點單顧客 ID。
    若是舊票口沒有 topic，會嘗試從頻道名稱最後一段讀取 ID。
    頻道名稱格式通常會是：下單-名字-使用者ID
    """
    if channel.topic:
        data = {}

        for part in channel.topic.split(";"):
            if "=" in part:
                key, value = part.split("=", 1)
                data[key.strip()] = value.strip()

        customer_id = data.get("order_customer_id")

        if customer_id is not None:
            try:
                return int(customer_id)
            except ValueError:
                pass

    try:
        possible_id = channel.name.rsplit("-", 1)[-1]
        return int(possible_id)
    except ValueError:
        return None


def rating_to_stars(rating_text: str) -> tuple[int | None, str | None]:
    try:
        rating = int(rating_text.strip())
    except ValueError:
        return None, None

    if rating < 1 or rating > 5:
        return None, None

    stars = "⭐" * rating
    return rating, stars


def is_anonymous_answer(text: str) -> bool:
    answer = text.strip().lower()
    return answer in {"是", "匿名", "要", "yes", "y", "true", "1"}


def is_image_attachment(attachment: discord.Attachment) -> bool:
    if attachment.content_type and attachment.content_type.startswith("image/"):
        return True

    image_exts = (".png", ".jpg", ".jpeg", ".gif", ".webp")
    return attachment.filename.lower().endswith(image_exts)


def chunk_list(items: list, size: int):
    for i in range(0, len(items), size):
        yield items[i:i + size]


def safe_voice_channel_name(member: discord.Member) -> str:
    display_name = member.display_name.strip() or member.name
    # Discord 語音頻道名稱最多 100 字，這裡留一點安全長度
    return f"🎮┃{display_name}的陪玩頻道"[:95]


def safe_vip_voice_channel_name(member: discord.Member) -> str:
    display_name = member.display_name.strip() or member.name
    # Discord 語音頻道名稱最多 100 字，這裡留一點安全長度
    return f"👑┃{display_name}的𝙑𝙄𝙋頻道"[:95]


def safe_public_voice_channel_name(member: discord.Member) -> str:
    display_name = member.display_name.strip() or member.name
    # Discord 語音頻道名稱最多 100 字，這裡留一點安全長度
    return f"➕┃{display_name}的公共房間"[:95]


def get_play_voice_allowed_roles(guild: discord.Guild) -> list[discord.Role]:
    return [
        role
        for role_id in PLAY_VOICE_ALLOWED_ROLE_IDS
        if (role := guild.get_role(role_id)) is not None
    ]


def get_voice_room_hidden_visible_roles(guild: discord.Guild) -> list[discord.Role]:
    return [
        role
        for role_id in VOICE_ROOM_HIDDEN_VISIBLE_ROLE_IDS
        if (role := guild.get_role(role_id)) is not None
    ]


def build_play_voice_overwrites(guild: discord.Guild) -> dict:
    overwrites = {
        guild.default_role: discord.PermissionOverwrite(
            view_channel=False,
            connect=False
        ),
        guild.me: discord.PermissionOverwrite(
            view_channel=True,
            connect=True,
            speak=True,
            move_members=True,
            manage_channels=True
        ),
    }

    for role in get_play_voice_allowed_roles(guild):
        overwrites[role] = discord.PermissionOverwrite(
            view_channel=True,
            connect=True,
            speak=True,
            stream=True,
            use_voice_activation=True
        )

    return overwrites


def build_vip_lobby_overwrites(guild: discord.Guild) -> dict:
    vip_role = guild.get_role(VIP_VOICE_LOBBY_ROLE_ID)

    overwrites = {
        guild.default_role: discord.PermissionOverwrite(
            view_channel=False,
            connect=False
        ),
        guild.me: discord.PermissionOverwrite(
            view_channel=True,
            connect=True,
            speak=True,
            move_members=True,
            manage_channels=True
        ),
    }

    if vip_role is not None:
        overwrites[vip_role] = discord.PermissionOverwrite(
            view_channel=True,
            connect=True,
            speak=True,
            stream=True,
            use_voice_activation=True
        )

    return overwrites


def build_vip_room_overwrites(guild: discord.Guild, member: discord.Member) -> dict:
    overwrites = {
        guild.default_role: discord.PermissionOverwrite(
            view_channel=False,
            connect=False
        ),
        guild.me: discord.PermissionOverwrite(
            view_channel=True,
            connect=True,
            speak=True,
            move_members=True,
            manage_channels=True
        ),
        member: discord.PermissionOverwrite(
            view_channel=True,
            connect=True,
            speak=True,
            stream=True,
            use_voice_activation=True
        ),
    }

    for role in get_play_voice_allowed_roles(guild):
        overwrites[role] = discord.PermissionOverwrite(
            view_channel=True,
            connect=True,
            speak=True,
            stream=True,
            use_voice_activation=True
        )

    return overwrites


def build_public_voice_overwrites(guild: discord.Guild) -> dict:
    return {
        guild.default_role: discord.PermissionOverwrite(
            view_channel=True,
            connect=True,
            speak=True,
            stream=True,
            use_voice_activation=True
        ),
        guild.me: discord.PermissionOverwrite(
            view_channel=True,
            connect=True,
            speak=True,
            move_members=True,
            manage_channels=True
        ),
    }


async def get_or_create_play_voice_lobby(guild: discord.Guild) -> discord.VoiceChannel | None:
    category = guild.get_channel(PLAY_VOICE_CATEGORY_ID)

    if category is None or not isinstance(category, discord.CategoryChannel):
        print("找不到陪玩語音類別，請確認 PLAY_VOICE_CATEGORY_ID 是否正確。")
        return None

    for channel in category.voice_channels:
        if channel.name == PLAY_VOICE_CREATE_CHANNEL_NAME:
            await channel.edit(overwrites=build_play_voice_overwrites(guild), reason="Update play voice lobby permissions")
            return channel

        if channel.name in OLD_PLAY_VOICE_CREATE_CHANNEL_NAMES:
            await channel.edit(
                name=PLAY_VOICE_CREATE_CHANNEL_NAME,
                overwrites=build_play_voice_overwrites(guild),
                reason="Rename old play voice lobby"
            )
            return channel

    return await guild.create_voice_channel(
        name=PLAY_VOICE_CREATE_CHANNEL_NAME,
        category=category,
        overwrites=build_play_voice_overwrites(guild),
        reason="Create play voice lobby"
    )


async def get_or_create_vip_voice_lobby(guild: discord.Guild) -> discord.VoiceChannel | None:
    category = guild.get_channel(PLAY_VOICE_CATEGORY_ID)

    if category is None or not isinstance(category, discord.CategoryChannel):
        print("找不到 VIP 語音類別，請確認 PLAY_VOICE_CATEGORY_ID 是否正確。")
        return None

    for channel in category.voice_channels:
        if channel.name == VIP_VOICE_CREATE_CHANNEL_NAME:
            await channel.edit(overwrites=build_vip_lobby_overwrites(guild), reason="Update VIP voice lobby permissions")
            return channel

        if channel.name in OLD_VIP_VOICE_CREATE_CHANNEL_NAMES:
            await channel.edit(
                name=VIP_VOICE_CREATE_CHANNEL_NAME,
                overwrites=build_vip_lobby_overwrites(guild),
                reason="Rename old VIP voice lobby"
            )
            return channel

    return await guild.create_voice_channel(
        name=VIP_VOICE_CREATE_CHANNEL_NAME,
        category=category,
        overwrites=build_vip_lobby_overwrites(guild),
        reason="Create VIP voice lobby"
    )


async def get_or_create_public_voice_lobby(guild: discord.Guild) -> discord.VoiceChannel | None:
    category = guild.get_channel(PLAY_VOICE_CATEGORY_ID)

    if category is None or not isinstance(category, discord.CategoryChannel):
        print("找不到公共語音類別，請確認 PLAY_VOICE_CATEGORY_ID 是否正確。")
        return None

    for channel in category.voice_channels:
        if channel.name == PUBLIC_VOICE_CREATE_CHANNEL_NAME:
            await channel.edit(overwrites=build_public_voice_overwrites(guild), reason="Update public voice lobby permissions")
            return channel

    return await guild.create_voice_channel(
        name=PUBLIC_VOICE_CREATE_CHANNEL_NAME,
        category=category,
        overwrites=build_public_voice_overwrites(guild),
        reason="Create public voice lobby"
    )


def build_creator_voice_overwrite() -> discord.PermissionOverwrite:
    return discord.PermissionOverwrite(
        view_channel=True,
        connect=True,
        speak=True,
        stream=True,
        use_voice_activation=True,
        move_members=True,
    )


def build_voice_control_panel_overwrites(
    guild: discord.Guild,
    member: discord.Member
) -> dict:
    return {
        guild.default_role: discord.PermissionOverwrite(
            view_channel=False,
            send_messages=False,
            read_message_history=False,
        ),
        guild.me: discord.PermissionOverwrite(
            view_channel=True,
            send_messages=True,
            manage_channels=True,
            read_message_history=True,
        ),
        member: discord.PermissionOverwrite(
            view_channel=True,
            send_messages=True,
            read_message_history=True,
        ),
    }


def safe_voice_control_panel_name(member: discord.Member) -> str:
    display_name = member.display_name.strip() or member.name
    clean = "".join(c if c.isalnum() else "-" for c in display_name.lower())
    return f"遙控器-{clean}-{member.id}"[:90]


async def delete_voice_control_panel(guild: discord.Guild, voice_channel_id: int):
    # 控制面板現在直接發在語音房聊天室。
    # 語音房被刪除時，聊天室內容會一起消失，所以這裡只需要清掉暫存資料。
    TEMP_VOICE_CONTROL_PANELS.pop(voice_channel_id, None)


def get_room_targets_for_control(
    guild: discord.Guild,
    room_type: str
) -> list[discord.abc.Snowflake]:
    if room_type == "public":
        return [guild.default_role]

    return get_play_voice_allowed_roles(guild)


async def apply_voice_lock_state(
    voice_channel: discord.VoiceChannel,
    owner: discord.Member,
    room_type: str,
    locked: bool,
):
    overwrites = dict(voice_channel.overwrites)

    for target in get_room_targets_for_control(voice_channel.guild, room_type):
        overwrite = overwrites.get(target, discord.PermissionOverwrite())
        overwrite.connect = not locked
        overwrites[target] = overwrite

    owner_overwrite = overwrites.get(owner, discord.PermissionOverwrite())
    owner_overwrite.view_channel = True
    owner_overwrite.connect = True
    owner_overwrite.speak = True
    owner_overwrite.stream = True
    owner_overwrite.use_voice_activation = True
    overwrites[owner] = owner_overwrite

    bot_member = voice_channel.guild.me
    if bot_member is not None:
        bot_overwrite = overwrites.get(bot_member, discord.PermissionOverwrite())
        bot_overwrite.view_channel = True
        bot_overwrite.connect = True
        bot_overwrite.manage_channels = True
        bot_overwrite.move_members = True
        overwrites[bot_member] = bot_overwrite

    await voice_channel.edit(
        overwrites=overwrites,
        reason="Voice room lock state changed by owner"
    )


async def apply_voice_hidden_state(
    voice_channel: discord.VoiceChannel,
    owner: discord.Member,
    room_type: str,
    hidden: bool,
):
    overwrites = dict(voice_channel.overwrites)
    guild = voice_channel.guild

    # 顯示：讓所有人都看得到。
    # 隱藏：只有創建者、Bot、指定三個身分組可以看得到。
    everyone_overwrite = overwrites.get(guild.default_role, discord.PermissionOverwrite())

    if hidden:
        everyone_overwrite.view_channel = False
        overwrites[guild.default_role] = everyone_overwrite

        for role in get_voice_room_hidden_visible_roles(guild):
            overwrite = overwrites.get(role, discord.PermissionOverwrite())
            overwrite.view_channel = True
            overwrite.connect = True
            overwrite.speak = True
            overwrite.stream = True
            overwrite.use_voice_activation = True
            overwrites[role] = overwrite
    else:
        everyone_overwrite.view_channel = True
        overwrites[guild.default_role] = everyone_overwrite

    owner_overwrite = overwrites.get(owner, discord.PermissionOverwrite())
    owner_overwrite.view_channel = True
    owner_overwrite.connect = True
    owner_overwrite.speak = True
    owner_overwrite.stream = True
    owner_overwrite.use_voice_activation = True
    overwrites[owner] = owner_overwrite

    bot_member = guild.me
    if bot_member is not None:
        bot_overwrite = overwrites.get(bot_member, discord.PermissionOverwrite())
        bot_overwrite.view_channel = True
        bot_overwrite.connect = True
        bot_overwrite.manage_channels = True
        bot_overwrite.move_members = True
        overwrites[bot_member] = bot_overwrite

    await voice_channel.edit(
        overwrites=overwrites,
        reason="Voice room visibility changed by owner"
    )


class VoiceRoomRenameModal(discord.ui.Modal, title="更改語音房名稱"):
    new_name = discord.ui.TextInput(
        label="新的頻道名稱",
        placeholder="請輸入新的語音房名稱",
        required=True,
        max_length=95,
    )

    def __init__(self, voice_channel_id: int, owner_id: int):
        super().__init__()
        self.voice_channel_id = voice_channel_id
        self.owner_id = owner_id

    async def on_submit(self, interaction: discord.Interaction):
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message("只有語音房創建者可以操作遙控器。", ephemeral=True)
            return

        guild = interaction.guild
        if guild is None:
            await interaction.response.send_message("這個功能只能在伺服器內使用。", ephemeral=True)
            return

        voice_channel = guild.get_channel(self.voice_channel_id)
        if not isinstance(voice_channel, discord.VoiceChannel):
            await interaction.response.send_message("找不到對應的語音房。", ephemeral=True)
            return

        try:
            await voice_channel.edit(
                name=self.new_name.value.strip()[:95],
                reason=f"Voice room renamed by {interaction.user}"
            )
        except discord.Forbidden:
            await interaction.response.send_message("Bot 權限不足，無法更改頻道名稱。", ephemeral=True)
            return
        except discord.HTTPException as e:
            await interaction.response.send_message(f"更改名稱失敗：{e}", ephemeral=True)
            return

        await interaction.response.defer()


class VoiceRoomLimitModal(discord.ui.Modal, title="設定語音房人數"):
    user_limit = discord.ui.TextInput(
        label="人數上限",
        placeholder="請輸入 0~99，0 代表不限人數",
        required=True,
        max_length=2,
    )

    def __init__(self, voice_channel_id: int, owner_id: int):
        super().__init__()
        self.voice_channel_id = voice_channel_id
        self.owner_id = owner_id

    async def on_submit(self, interaction: discord.Interaction):
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message("只有語音房創建者可以操作遙控器。", ephemeral=True)
            return

        guild = interaction.guild
        if guild is None:
            await interaction.response.send_message("這個功能只能在伺服器內使用。", ephemeral=True)
            return

        try:
            limit = int(self.user_limit.value.strip())
        except ValueError:
            await interaction.response.send_message("人數上限請輸入 0~99 的數字。", ephemeral=True)
            return

        if limit < 0 or limit > 99:
            await interaction.response.send_message("人數上限請輸入 0~99 的數字。", ephemeral=True)
            return

        voice_channel = guild.get_channel(self.voice_channel_id)
        if not isinstance(voice_channel, discord.VoiceChannel):
            await interaction.response.send_message("找不到對應的語音房。", ephemeral=True)
            return

        try:
            await voice_channel.edit(
                user_limit=limit,
                reason=f"Voice room user limit changed by {interaction.user}"
            )
        except discord.Forbidden:
            await interaction.response.send_message("Bot 權限不足，無法設定人數。", ephemeral=True)
            return
        except discord.HTTPException as e:
            await interaction.response.send_message(f"設定人數失敗：{e}", ephemeral=True)
            return

        await interaction.response.defer()


class VoiceRoomControlView(discord.ui.View):
    def __init__(self, voice_channel_id: int, owner_id: int, room_type: str):
        super().__init__(timeout=None)
        self.voice_channel_id = voice_channel_id
        self.owner_id = owner_id
        self.room_type = room_type

    async def get_voice_channel_and_owner(
        self,
        interaction: discord.Interaction
    ) -> tuple[discord.VoiceChannel | None, discord.Member | None]:
        guild = interaction.guild
        if guild is None:
            return None, None

        voice_channel = guild.get_channel(self.voice_channel_id)
        owner = guild.get_member(self.owner_id)

        if not isinstance(voice_channel, discord.VoiceChannel) or owner is None:
            return None, None

        return voice_channel, owner

    async def reject_if_not_owner(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message("只有語音房創建者可以操作遙控器。", ephemeral=True)
            return True
        return False

    @discord.ui.button(
        label="🔒 鎖定/解鎖",
        style=discord.ButtonStyle.primary,
        custom_id="voice_room_lock_toggle",
        row=0,
    )
    async def lock_toggle(self, interaction: discord.Interaction, button: discord.ui.Button):
        if await self.reject_if_not_owner(interaction):
            return

        voice_channel, owner = await self.get_voice_channel_and_owner(interaction)
        if voice_channel is None or owner is None:
            await interaction.response.send_message("找不到對應的語音房。", ephemeral=True)
            return

        data = TEMP_VOICE_CONTROL_PANELS.setdefault(
            self.voice_channel_id,
            {
                "owner_id": self.owner_id,
                "panel_channel_id": interaction.channel.id if interaction.channel else None,
                "room_type": self.room_type,
                "locked": False,
                "hidden": False,
            }
        )
        data["locked"] = not data.get("locked", False)

        try:
            await apply_voice_lock_state(voice_channel, owner, self.room_type, data["locked"])
        except discord.Forbidden:
            await interaction.response.send_message("Bot 權限不足，無法鎖定/解鎖語音房。", ephemeral=True)
            return
        except discord.HTTPException as e:
            await interaction.response.send_message(f"鎖定/解鎖失敗：{e}", ephemeral=True)
            return

        await interaction.response.defer()

    @discord.ui.button(
        label="👁️ 隱藏/顯示",
        style=discord.ButtonStyle.secondary,
        custom_id="voice_room_visibility_toggle",
        row=0,
    )
    async def visibility_toggle(self, interaction: discord.Interaction, button: discord.ui.Button):
        if await self.reject_if_not_owner(interaction):
            return

        voice_channel, owner = await self.get_voice_channel_and_owner(interaction)
        if voice_channel is None or owner is None:
            await interaction.response.send_message("找不到對應的語音房。", ephemeral=True)
            return

        data = TEMP_VOICE_CONTROL_PANELS.setdefault(
            self.voice_channel_id,
            {
                "owner_id": self.owner_id,
                "panel_channel_id": interaction.channel.id if interaction.channel else None,
                "room_type": self.room_type,
                "locked": False,
                "hidden": False,
            }
        )
        data["hidden"] = not data.get("hidden", False)

        try:
            await apply_voice_hidden_state(voice_channel, owner, self.room_type, data["hidden"])
        except discord.Forbidden:
            await interaction.response.send_message("Bot 權限不足，無法隱藏/顯示語音房。", ephemeral=True)
            return
        except discord.HTTPException as e:
            await interaction.response.send_message(f"隱藏/顯示失敗：{e}", ephemeral=True)
            return

        await interaction.response.defer()

    @discord.ui.button(
        label="✏️ 更改名稱",
        style=discord.ButtonStyle.success,
        custom_id="voice_room_rename",
        row=1,
    )
    async def rename_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if await self.reject_if_not_owner(interaction):
            return

        await interaction.response.send_modal(
            VoiceRoomRenameModal(
                voice_channel_id=self.voice_channel_id,
                owner_id=self.owner_id,
            )
        )

    @discord.ui.button(
        label="👥 設定人數",
        style=discord.ButtonStyle.danger,
        custom_id="voice_room_user_limit",
        row=1,
    )
    async def limit_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if await self.reject_if_not_owner(interaction):
            return

        await interaction.response.send_modal(
            VoiceRoomLimitModal(
                voice_channel_id=self.voice_channel_id,
                owner_id=self.owner_id,
            )
        )


async def create_voice_control_panel(
    guild: discord.Guild,
    category: discord.CategoryChannel,
    member: discord.Member,
    voice_channel: discord.VoiceChannel,
    room_type: str,
):
    # 不再額外建立文字頻道，控制面板直接發在語音房內建聊天室。
    TEMP_VOICE_CONTROL_PANELS[voice_channel.id] = {
        "owner_id": member.id,
        "panel_channel_id": voice_channel.id,
        "panel_message_id": None,
        "room_type": room_type,
        "locked": False,
        "hidden": False,
    }

    embed = discord.Embed(
        title="專屬語音房",
        description=(
            f"歡迎來到您的專屬包廂！{member.mention}\n"
            "可以使用遙控器管理頻道。\n\n"
            "⚠️ 當包廂內無人時，將自動銷毀。"
        ),
        color=discord.Color.purple()
    )

    message = await voice_channel.send(
        embed=embed,
        view=VoiceRoomControlView(
            voice_channel_id=voice_channel.id,
            owner_id=member.id,
            room_type=room_type,
        ),
        allowed_mentions=discord.AllowedMentions(
            users=True,
            roles=False,
            everyone=False,
        )
    )

    TEMP_VOICE_CONTROL_PANELS[voice_channel.id]["panel_message_id"] = message.id

async def create_private_channel(
    interaction: discord.Interaction,
    category_id: int,
    channel_name: str,
    allowed_roles: list[discord.Role],
    intro_message: str,
    view: discord.ui.View | None = None,
    topic: str | None = None,
):
    guild = interaction.guild
    member = interaction.user

    if guild is None:
        await interaction.response.send_message(
            "這個功能只能在伺服器內使用。",
            ephemeral=True
        )
        return

    category = guild.get_channel(category_id)

    if category is None or not isinstance(category, discord.CategoryChannel):
        await interaction.response.send_message(
            "找不到指定類別，請確認你填的是「類別 ID」，不是頻道 ID。",
            ephemeral=True
        )
        return

    if not interaction.response.is_done():
        await interaction.response.defer(ephemeral=True, thinking=True)

    overwrites = {
        guild.default_role: discord.PermissionOverwrite(
            view_channel=False,
            send_messages=False,
            read_message_history=False
        ),
        member: discord.PermissionOverwrite(
            view_channel=True,
            send_messages=True,
            read_message_history=True,
            attach_files=True
        ),
        guild.me: discord.PermissionOverwrite(
            view_channel=True,
            send_messages=True,
            manage_channels=True,
            read_message_history=True,
            attach_files=True
        ),
    }

    for role in allowed_roles:
        if role is not None:
            overwrites[role] = discord.PermissionOverwrite(
                view_channel=True,
                send_messages=True,
                read_message_history=True,
                attach_files=True
            )

    channel = await guild.create_text_channel(
        name=channel_name,
        category=category,
        overwrites=overwrites,
        topic=topic,
        reason=f"{member} opened a private channel"
    )

    role_mentions = " ".join(role.mention for role in allowed_roles if role is not None)

    await channel.send(
        content=f"{role_mentions}\n{intro_message}",
        view=view,
        allowed_mentions=discord.AllowedMentions(
            roles=True,
            users=True,
            everyone=False
        )
    )

    if topic and "order_customer_id=" in topic:
        await send_order_log(
            guild,
            title="新票口已建立",
            fields=[
                ("開單人", member.mention, True),
                ("票口", channel.mention, True),
                ("狀態", "已確認詳閱規章內容", False),
            ],
            color=discord.Color.purple(),
        )

    try:
        await interaction.delete_original_response()
    except discord.NotFound:
        pass
    except discord.HTTPException:
        pass


# ========= 評價暫存資料 =========

REVIEW_DRAFTS = {}


# ========= 評價 Modal / 按鈕 =========

class ReviewSubmitView(discord.ui.View):
    def __init__(self, customer_id: int, channel_id: int):
        super().__init__(timeout=86400)
        self.customer_id = customer_id
        self.channel_id = channel_id

    @discord.ui.button(
        label="送出好評",
        style=discord.ButtonStyle.success
    )
    async def submit_review(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.customer_id:
            await interaction.response.send_message(
                "只有這張票口的點單顧客可以送出評論。",
                ephemeral=True
            )
            return

        guild = interaction.guild

        if guild is None:
            await interaction.response.send_message(
                "這個功能只能在伺服器內使用。",
                ephemeral=True
            )
            return

        channel = interaction.channel

        if not isinstance(channel, discord.TextChannel):
            await interaction.response.send_message(
                "無法確認目前票口頻道。",
                ephemeral=True
            )
            return

        draft = REVIEW_DRAFTS.get(self.channel_id)

        if draft is None:
            await interaction.response.send_message(
                "找不到暫存的好評資料，請重新按「留下好評」。",
                ephemeral=True
            )
            return

        review_channel = guild.get_channel(REVIEW_CHANNEL_ID)

        if review_channel is None or not isinstance(review_channel, discord.TextChannel):
            await interaction.response.send_message(
                "找不到評價頻道，請確認 REVIEW_CHANNEL_ID 是否正確。",
                ephemeral=True
            )
            return

        await interaction.response.defer(ephemeral=True)

        image_attachments = []

        async for message in channel.history(
            after=draft["started_at"],
            oldest_first=True,
            limit=None
        ):
            if message.author.id != self.customer_id:
                continue

            for attachment in message.attachments:
                if is_image_attachment(attachment):
                    image_attachments.append(attachment)

        embed = discord.Embed(
            color=discord.Color.gold()
        )

        is_anonymous = draft.get("is_anonymous", False)
        review_customer_text = "匿名闆闆" if is_anonymous else interaction.user.mention

        embed.add_field(
            name="客戶",
            value=review_customer_text,
            inline=True
        )

        embed.add_field(
            name="評分",
            value=draft["stars"],
            inline=True
        )

        embed.add_field(
            name="評價內容",
            value=draft["content"],
            inline=False
        )

        embed.add_field(
            name="圖片數量",
            value=f"{len(image_attachments)} 張",
            inline=True
        )

        files = []

        for attachment in image_attachments:
            try:
                file = await attachment.to_file()
                files.append(file)
            except discord.HTTPException:
                pass
            except Exception:
                pass

        if files:
            first_batch = True

            for file_batch in chunk_list(files, 10):
                if first_batch:
                    await review_channel.send(
                        embed=embed,
                        files=file_batch,
                        allowed_mentions=discord.AllowedMentions(
                            users=not is_anonymous,
                            roles=False,
                            everyone=False
                        )
                    )
                    first_batch = False
                else:
                    await review_channel.send(
                        content=(
                            "匿名闆闆 的好評圖片續傳"
                            if is_anonymous
                            else f"{interaction.user.mention} 的好評圖片續傳"
                        ),
                        files=file_batch,
                        allowed_mentions=discord.AllowedMentions(
                            users=not is_anonymous,
                            roles=False,
                            everyone=False
                        )
                    )
        else:
            await review_channel.send(
                embed=embed,
                allowed_mentions=discord.AllowedMentions(
                    users=not is_anonymous,
                    roles=False,
                    everyone=False
                )
            )

        REVIEW_DRAFTS.pop(self.channel_id, None)

        await interaction.followup.send(
            "好評已送出，感謝闆闆支持！票口將在 3 秒後關閉。",
            ephemeral=True
        )

        await channel.send(
            f"{interaction.user.mention} 已完成評論，感謝闆闆支持！\n"
            f"票口將在 3 秒後關閉。"
        )

        await asyncio.sleep(3)

        await channel.delete(reason=f"Review completed by {interaction.user}")


class ReviewModal(discord.ui.Modal, title="留下好評"):
    rating = discord.ui.TextInput(
        label="評分",
        placeholder="請輸入 1~5",
        required=True,
        max_length=1
    )

    content = discord.ui.TextInput(
        label="評價內容",
        placeholder="請輸入你的評價內容",
        style=discord.TextStyle.paragraph,
        required=True,
        max_length=1000
    )

    anonymous = discord.ui.TextInput(
        label="是否匿名",
        placeholder="輸入：是 / 否",
        required=True,
        max_length=10
    )

    def __init__(self, customer_id: int):
        super().__init__()
        self.customer_id = customer_id

    async def on_submit(self, interaction: discord.Interaction):
        guild = interaction.guild

        if guild is None:
            await interaction.response.send_message("這個功能只能在伺服器內使用。", ephemeral=True)
            return

        if interaction.user.id != self.customer_id:
            await interaction.response.send_message("只有這張票口的點單顧客可以留下評論。", ephemeral=True)
            return

        if not isinstance(interaction.channel, discord.TextChannel):
            await interaction.response.send_message("無法確認目前票口頻道。", ephemeral=True)
            return

        rating_number, stars = rating_to_stars(self.rating.value)

        if rating_number is None or stars is None:
            await interaction.response.send_message("評分請輸入 1~5 的數字。", ephemeral=True)
            return

        REVIEW_DRAFTS[interaction.channel.id] = {
            "customer_id": self.customer_id,
            "rating_number": rating_number,
            "stars": stars,
            "content": self.content.value,
            "is_anonymous": is_anonymous_answer(self.anonymous.value),
            "started_at": interaction.created_at,
        }

        await interaction.response.send_message(
            "好評文字已填寫完成。\n\n"
            "如果有圖片，請直接傳到這個票口頻道。\n"
            "圖片可以傳很多張，也可以分很多則訊息傳。\n\n"
            "全部傳完後，請按下方的「送出好評」。",
            view=ReviewSubmitView(
                customer_id=self.customer_id,
                channel_id=interaction.channel.id
            ),
            ephemeral=False
        )


class ReviewButtonView(discord.ui.View):
    def __init__(self, customer_id: int):
        super().__init__(timeout=86400)
        self.customer_id = customer_id

    @discord.ui.button(
        label="留下好評",
        style=discord.ButtonStyle.success
    )
    async def leave_review(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.customer_id:
            await interaction.response.send_message("只有這張票口的點單顧客可以留下評論。", ephemeral=True)
            return

        await interaction.response.send_modal(
            ReviewModal(customer_id=self.customer_id)
        )


# ========= 派單 Modal =========

class DispatchModal(discord.ui.Modal, title="派單"):
    order_name = discord.ui.TextInput(
        label="單子名稱",
        placeholder="請輸入單子名稱",
        required=True,
        max_length=100
    )

    receiver = discord.ui.TextInput(
        label="接單打手/陪玩",
        placeholder="請輸入接單打手/陪玩名稱",
        required=True,
        max_length=100
    )

    async def on_submit(self, interaction: discord.Interaction):
        if not isinstance(interaction.user, discord.Member):
            await interaction.response.send_message("無法確認你的身分組。", ephemeral=True)
            return

        if not is_customer_staff(interaction.user):
            await interaction.response.send_message("只有客服可以派單。", ephemeral=True)
            return

        guild = interaction.guild

        if guild is None:
            await interaction.response.send_message("這個功能只能在伺服器內使用。", ephemeral=True)
            return

        dispatch_channel = guild.get_channel(DISPATCH_CHANNEL_ID)

        if dispatch_channel is None or not isinstance(dispatch_channel, discord.TextChannel):
            await interaction.response.send_message(
                "找不到派單頻道，請確認 DISPATCH_CHANNEL_ID 是否正確。",
                ephemeral=True
            )
            return

        source_channel = interaction.channel.mention if isinstance(interaction.channel, discord.TextChannel) else "未知頻道"

        embed = discord.Embed(
            title="新派單",
            color=discord.Color.blue()
        )

        embed.add_field(
            name="單子名稱",
            value=self.order_name.value,
            inline=False
        )

        embed.add_field(
            name="接單打手/陪玩",
            value=self.receiver.value,
            inline=False
        )

        embed.add_field(
            name="派單客服",
            value=interaction.user.mention,
            inline=False
        )

        embed.add_field(
            name="來源頻道",
            value=source_channel,
            inline=False
        )

        await dispatch_channel.send(
            embed=embed,
            allowed_mentions=discord.AllowedMentions(
                users=True,
                roles=False,
                everyone=False
            )
        )

        await interaction.response.send_message(
            f"已派單，派單資訊已送到 {dispatch_channel.mention}。",
            ephemeral=True
        )

        if isinstance(interaction.channel, discord.TextChannel):
            await interaction.channel.send(
                f"此單已由 {interaction.user.mention} 派單。\n"
                f"單子名稱：{self.order_name.value}\n"
                f"接單打手/陪玩：{self.receiver.value}"
            )


# ========= 收據 Modal =========

def get_order_summary_from_channel(channel_id: int) -> tuple[str, str]:
    """
    從自助下單暫存資料取得收據內容與付款方式。
    內容會沿用闆闆在自助下單面板選的類別、項目與指定選項。
    """
    data = SELF_SERVICE_ORDER_SELECTIONS.get(channel_id, {})

    category = data.get("category")
    item = data.get("item")
    quantity = _to_int(data.get("quantity"), 1) or 1
    companion_preference = data.get("companion_preference")
    payment_method = data.get("payment_method", "未紀錄")

    if item is None:
        return "未紀錄自助下單內容", payment_method

    parts = []

    if category is not None:
        parts.append(ORDER_CATEGORY_LABELS.get(category, category))

    parts.append(item)
    parts.append(f"數量：{quantity} 單")

    if companion_preference is not None:
        parts.append(companion_preference)

    return "｜".join(parts), payment_method


def get_taipei_now_text() -> str:
    taipei_tz = timezone(timedelta(hours=8))
    return datetime.now(taipei_tz).strftime("%Y/%m/%d %H:%M")


class ReceiptModal(discord.ui.Modal, title="已結單收據"):
    payee = discord.ui.TextInput(
        label="收款人",
        placeholder="例如：zYao或客服暱稱(代收)",
        required=True,
        max_length=100
    )

    amount = discord.ui.TextInput(
        label="金額",
        placeholder="例如：NT$ XXXX 中文字大寫",
        required=True,
        max_length=100
    )

    staff = discord.ui.TextInput(
        label="對接客服",
        placeholder="請輸入對接客服名稱",
        required=True,
        max_length=100
    )

    receiver = discord.ui.TextInput(
        label="接單打手/陪玩",
        placeholder="請輸入接單打手/陪玩名稱",
        required=True,
        max_length=100
    )

    async def on_submit(self, interaction: discord.Interaction):
        if not isinstance(interaction.user, discord.Member):
            await interaction.response.send_message("無法確認你的身分組。", ephemeral=True)
            return

        if not is_customer_staff(interaction.user):
            await interaction.response.send_message("只有客服可以操作已結單。", ephemeral=True)
            return

        guild = interaction.guild

        if guild is None:
            await interaction.response.send_message("這個功能只能在伺服器內使用。", ephemeral=True)
            return

        if not isinstance(interaction.channel, discord.TextChannel):
            await interaction.response.send_message("無法確認目前票口頻道。", ephemeral=True)
            return

        receipt_channel = guild.get_channel(RECEIPT_CHANNEL_ID)

        if receipt_channel is None or not isinstance(receipt_channel, discord.TextChannel):
            await interaction.response.send_message(
                "找不到收據頻道，請確認 RECEIPT_CHANNEL_ID 是否正確。",
                ephemeral=True
            )
            return

        order_channel = interaction.channel
        customer_id = get_order_customer_id_from_channel(order_channel)

        if customer_id is None:
            await interaction.response.send_message(
                "無法辨識這張票口的下單顧客，因此無法自動帶入付款人。",
                ephemeral=True
            )
            return

        customer_member = guild.get_member(customer_id)
        payer_text = f"@{customer_member.display_name}" if customer_member is not None else f"@{customer_id}"

        order_content, payment_method = get_order_summary_from_channel(order_channel.id)
        date_text = get_taipei_now_text()

        parsed_amount = parse_receipt_amount(self.amount.value)
        if parsed_amount is None or parsed_amount <= 0:
            await interaction.response.send_message(
                "金額欄位無法辨識，請輸入可辨識的數字，例如：1275、NT$1275、1275T。",
                ephemeral=True
            )
            return

        receipt_id = generate_order_receipt_id()
        closed_at_text = get_taipei_now_iso()

        order_data = SELF_SERVICE_ORDER_SELECTIONS.setdefault(order_channel.id, {})
        order_data["receipt_id"] = receipt_id
        order_data["order_no"] = receipt_id
        order_data["receipt_created_at"] = closed_at_text
        order_data["closed_at"] = closed_at_text
        order_data["closed"] = True
        order_data["status"] = "closed"
        order_data["amount"] = parsed_amount
        order_data["total_amount"] = parsed_amount
        order_data["payment_method"] = payment_method
        remember_order_data(order_channel.id, order_data)

        receipt_text = (
            "```text\n"
            "收據\n"
            "\n"
            f"編號：{receipt_id}\n"
            f"日期：{date_text}\n"
            "\n"
            f"收款人：{self.payee.value}\n"
            f"付款人：{payer_text}\n"
            "\n"
            f"內容：{order_content}\n"
            "\n"
            f"金額：{self.amount.value}\n"
            f"付款方式：{payment_method}\n"
            "```"
        )

        embed = discord.Embed(
            title="收據",
            description=receipt_text,
            color=discord.Color.green()
        )

        embed.add_field(
            name="付款人",
            value=payer_text,
            inline=False
        )

        embed.add_field(
            name="對接客服",
            value=self.staff.value,
            inline=False
        )

        embed.add_field(
            name="接單打手/陪玩",
            value=self.receiver.value,
            inline=False
        )

        await receipt_channel.send(
            embed=embed,
            allowed_mentions=discord.AllowedMentions(
                users=True,
                roles=False,
                everyone=False
            )
        )

        await lock_dispatch_claim_panel(guild, order_channel.id)

        reward_result = await add_customer_reward_from_order(
            guild=guild,
            order_channel_id=order_channel.id,
            customer_id=customer_id,
            amount_text=self.amount.value,
            notify_channel=interaction.channel,
        )

        await send_order_log(
            guild,
            title="訂單已結單",
            fields=[
                ("訂單編號", receipt_id, True),
                ("顧客", f"<@{customer_id}>", True),
                ("客服", interaction.user.mention, True),
                ("金額", self.amount.value, True),
                ("付款方式", payment_method, True),
                ("票口", order_channel.mention, False),
                ("內容", order_content, False),
            ],
            color=discord.Color.green(),
        )

        await interaction.response.send_message(
            f"此單已由 {interaction.user.mention} 結單，收據已送出。\n\n"
            f"{reward_result}\n\n"
            f"請闆闆留下評論",
            view=ReviewButtonView(customer_id=customer_id),
            allowed_mentions=discord.AllowedMentions(
                users=True,
                roles=False,
                everyone=False
            )
        )


# ========= 下單操作按鈕 =========

class ConfirmCancelOrderView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=60)

    @discord.ui.button(
        label="是，取消訂單",
        style=discord.ButtonStyle.danger,
        custom_id="confirm_cancel_order_yes"
    )
    async def confirm_cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not isinstance(interaction.user, discord.Member):
            await interaction.response.send_message("無法確認你的身分組。", ephemeral=True)
            return

        if not is_customer_staff(interaction.user):
            await interaction.response.send_message("只有客服可以取消訂單。", ephemeral=True)
            return

        channel = interaction.channel

        if interaction.guild is not None and isinstance(channel, discord.TextChannel):
            await delete_dispatch_claim_panel_for_order(
                guild=interaction.guild,
                order_channel_id=channel.id,
            )

        await interaction.response.send_message(
            "已確認取消訂單，這個頻道將在 3 秒後關閉，對應的派單訊息也會一併刪除。",
            ephemeral=False
        )

        await asyncio.sleep(3)

        if isinstance(channel, discord.TextChannel):
            await channel.delete(reason=f"Order cancelled by {interaction.user}")

    @discord.ui.button(
        label="否，保留訂單",
        style=discord.ButtonStyle.secondary,
        custom_id="confirm_cancel_order_no"
    )
    async def keep_order(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not isinstance(interaction.user, discord.Member):
            await interaction.response.send_message("無法確認你的身分組。", ephemeral=True)
            return

        if not is_customer_staff(interaction.user):
            await interaction.response.send_message("只有客服可以操作。", ephemeral=True)
            return

        await interaction.response.send_message("已保留訂單。", ephemeral=True)


# ========= 自助下單資料 =========

ORDER_CONTROL_SELECTIONS = {}
STAFF_ORDER_OPERATION_SELECTIONS = {}
SELF_SERVICE_ORDER_SELECTIONS = {}

# 派單頻道接單資料
# message_id 對應該派單訊息目前有哪些陪玩 / 打手接單。
# 重要訂單資料會保存到 bot_data.json，Bot 重啟後會自動讀回。
ORDER_CLAIMS = {}

# 顧客會員 / 獎勵資料
# user_id -> {total_spent, order_count, last_order_at, points, platinum_channel_id}
CUSTOMER_REWARDS = {}

# 訂單編號計數器：YYYYMMDD -> 當日最後流水號
ORDER_COUNTERS = {}

BACKUP_TASK_STARTED = False
STORED_REMINDER_TASK_STARTED = False
STORED_ORDER_REMINDER_DAYS = [3, 7]

DATA_FILE = Path(__file__).parent / "bot_data.json"  # 舊版 JSON 備援/遷移用
DB_FILE = Path(__file__).parent / "bot.db"
BACKUP_DIR = Path(__file__).parent / "backups"
CLOSED_ORDER_KEEP_DAYS = 0  # 已結單資料永久保留，不再自動刪除
CANCELLED_ORDER_KEEP_DAYS = 60  # 只清理超過 60 天的取消單暫存



def _to_int(value, default: int | None = None) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _serialize_orders() -> dict:
    return {
        str(channel_id): data
        for channel_id, data in SELF_SERVICE_ORDER_SELECTIONS.items()
    }


def _serialize_claims() -> dict:
    result = {}

    for message_id, data in ORDER_CLAIMS.items():
        result[str(message_id)] = {
            "companion": sorted(list(data.get("companion", set()))),
            "booster": sorted(list(data.get("booster", set()))),
            "locked": bool(data.get("locked", False)),
            "customer_id": data.get("customer_id"),
            "category_label": data.get("category_label"),
            "item": data.get("item"),
            "quantity": _to_int(data.get("quantity"), 1) or 1,
            "payment_method": data.get("payment_method"),
            "source_channel_id": data.get("source_channel_id"),
            "companion_preference": data.get("companion_preference"),
            "dispatch_channel_id": data.get("dispatch_channel_id"),
            "status": data.get("status", "active"),
            "stored_at": data.get("stored_at"),
            "stored_by": data.get("stored_by"),
            "stored_reason": data.get("stored_reason"),
            "stored_expected_time": data.get("stored_expected_time"),
            "stored_note": data.get("stored_note"),
        }

    return result


def _serialize_customer_rewards() -> dict:
    return {
        str(user_id): data
        for user_id, data in CUSTOMER_REWARDS.items()
    }


def _serialize_order_counters() -> dict:
    return {str(day): int(count) for day, count in ORDER_COUNTERS.items()}

def _json_default(value):
    if isinstance(value, set):
        return sorted(value)
    return str(value)


def _deserialize_claim_data(data: dict) -> dict:
    return {
        "companion": {uid for uid in (_to_int(x) for x in data.get("companion", [])) if uid is not None},
        "booster": {uid for uid in (_to_int(x) for x in data.get("booster", [])) if uid is not None},
        "locked": bool(data.get("locked", False)),
        "customer_id": data.get("customer_id"),
        "category_label": data.get("category_label"),
        "item": data.get("item"),
        "quantity": _to_int(data.get("quantity"), 1) or 1,
        "payment_method": data.get("payment_method"),
        "source_channel_id": data.get("source_channel_id"),
        "companion_preference": data.get("companion_preference"),
        "dispatch_channel_id": data.get("dispatch_channel_id"),
        "status": data.get("status", "active"),
        "stored_at": data.get("stored_at"),
        "stored_by": data.get("stored_by"),
        "stored_reason": data.get("stored_reason"),
        "stored_expected_time": data.get("stored_expected_time"),
        "stored_note": data.get("stored_note"),
    }


def _deserialize_customer_data(data: dict) -> dict:
    return {
        "total_spent": _to_int(data.get("total_spent"), 0) or 0,
        "order_count": _to_int(data.get("order_count"), 0) or 0,
        "last_order_at": data.get("last_order_at"),
        "points": _to_int(data.get("points"), 0) or 0,
        "point_adjustment": _to_int(data.get("point_adjustment"), 0) or 0,
        "point_adjustment_logs": list(data.get("point_adjustment_logs", [])) if isinstance(data.get("point_adjustment_logs", []), list) else [],
        "platinum_channel_id": _to_int(data.get("platinum_channel_id")),
        "manual_purchase_keys": list(data.get("manual_purchase_keys", [])) if isinstance(data.get("manual_purchase_keys", []), list) else [],
        "notes": list(data.get("notes", [])) if isinstance(data.get("notes", []), list) else [],
    }


def init_database() -> None:
    """建立 SQLite 資料表。第一階段先用 SQLite 保存 Bot 既有資料結構，避免大改造成風險。"""
    with sqlite3.connect(DB_FILE) as conn:
        cur = conn.cursor()
        cur.execute("""
        CREATE TABLE IF NOT EXISTS orders (
            channel_id INTEGER PRIMARY KEY,
            data TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """)
        cur.execute("""
        CREATE TABLE IF NOT EXISTS claims (
            message_id INTEGER PRIMARY KEY,
            data TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """)
        cur.execute("""
        CREATE TABLE IF NOT EXISTS customers (
            user_id INTEGER PRIMARY KEY,
            data TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """)
        cur.execute("""
        CREATE TABLE IF NOT EXISTS order_counters (
            day_key TEXT PRIMARY KEY,
            count INTEGER NOT NULL DEFAULT 0,
            updated_at TEXT NOT NULL
        )
        """)
        cur.execute("""
        CREATE TABLE IF NOT EXISTS lottery_settings (
            key TEXT PRIMARY KEY,
            data TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """)
        cur.execute("""
        CREATE TABLE IF NOT EXISTS lottery_entries (
            period TEXT NOT NULL,
            user_id INTEGER NOT NULL,
            chances INTEGER NOT NULL DEFAULT 0,
            points_used INTEGER NOT NULL DEFAULT 0,
            updated_at TEXT NOT NULL,
            PRIMARY KEY (period, user_id)
        )
        """)
        cur.execute("""
        CREATE TABLE IF NOT EXISTS lottery_draws (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            period TEXT NOT NULL,
            prize TEXT NOT NULL,
            winner_id INTEGER NOT NULL,
            drawn_by INTEGER NOT NULL,
            drawn_at TEXT NOT NULL
        )
        """)
        conn.commit()


def save_bot_data() -> None:
    """將資料寫入 SQLite。另保留一份 bot_data.json 快照，方便人工查看與緊急回復。"""
    init_database()
    now_text = get_taipei_now_iso()

    orders_payload = _serialize_orders()
    claims_payload = _serialize_claims()
    customers_payload = _serialize_customer_rewards()
    counters_payload = _serialize_order_counters()

    try:
        with sqlite3.connect(DB_FILE) as conn:
            cur = conn.cursor()

            cur.execute("DELETE FROM orders")
            cur.executemany(
                "INSERT OR REPLACE INTO orders (channel_id, data, updated_at) VALUES (?, ?, ?)",
                [
                    (int(channel_id), json.dumps(data, ensure_ascii=False, default=_json_default), now_text)
                    for channel_id, data in orders_payload.items()
                ]
            )

            cur.execute("DELETE FROM claims")
            cur.executemany(
                "INSERT OR REPLACE INTO claims (message_id, data, updated_at) VALUES (?, ?, ?)",
                [
                    (int(message_id), json.dumps(data, ensure_ascii=False, default=_json_default), now_text)
                    for message_id, data in claims_payload.items()
                ]
            )

            cur.execute("DELETE FROM customers")
            cur.executemany(
                "INSERT OR REPLACE INTO customers (user_id, data, updated_at) VALUES (?, ?, ?)",
                [
                    (int(user_id), json.dumps(data, ensure_ascii=False, default=_json_default), now_text)
                    for user_id, data in customers_payload.items()
                ]
            )

            cur.execute("DELETE FROM order_counters")
            cur.executemany(
                "INSERT OR REPLACE INTO order_counters (day_key, count, updated_at) VALUES (?, ?, ?)",
                [
                    (str(day), int(count), now_text)
                    for day, count in counters_payload.items()
                ]
            )

            conn.commit()
    except sqlite3.Error as e:
        print(f"保存 bot.db 失敗：{e}")
        return

    # 保留 JSON 快照，不再作為主要資料庫。這讓你緊急查資料比較方便。
    payload = {
        "orders": orders_payload,
        "claims": claims_payload,
        "customers": customers_payload,
        "order_counters": counters_payload,
    }
    tmp_path = DATA_FILE.with_suffix(".tmp")
    try:
        with tmp_path.open("w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
        tmp_path.replace(DATA_FILE)
    except OSError as e:
        print(f"保存 bot_data.json 快照失敗：{e}")


def load_bot_data_from_sqlite() -> bool:
    if not DB_FILE.exists():
        return False

    init_database()

    try:
        with sqlite3.connect(DB_FILE) as conn:
            conn.row_factory = sqlite3.Row
            cur = conn.cursor()

            orders_rows = cur.execute("SELECT channel_id, data FROM orders").fetchall()
            claims_rows = cur.execute("SELECT message_id, data FROM claims").fetchall()
            customers_rows = cur.execute("SELECT user_id, data FROM customers").fetchall()
            counter_rows = cur.execute("SELECT day_key, count FROM order_counters").fetchall()
    except sqlite3.Error as e:
        print(f"讀取 bot.db 失敗：{e}")
        return False

    # 如果 bot.db 存在但還沒有任何資料，就回頭讀舊 JSON。
    if not orders_rows and not claims_rows and not customers_rows and not counter_rows:
        return False

    SELF_SERVICE_ORDER_SELECTIONS.clear()
    ORDER_CLAIMS.clear()
    CUSTOMER_REWARDS.clear()
    ORDER_COUNTERS.clear()

    for row in orders_rows:
        try:
            data = json.loads(row["data"])
        except json.JSONDecodeError:
            continue
        SELF_SERVICE_ORDER_SELECTIONS[int(row["channel_id"])] = data

    for row in claims_rows:
        try:
            data = json.loads(row["data"])
        except json.JSONDecodeError:
            continue
        ORDER_CLAIMS[int(row["message_id"])] = _deserialize_claim_data(data)

    for row in customers_rows:
        try:
            data = json.loads(row["data"])
        except json.JSONDecodeError:
            continue
        CUSTOMER_REWARDS[int(row["user_id"])] = _deserialize_customer_data(data)

    for row in counter_rows:
        ORDER_COUNTERS[str(row["day_key"])] = int(row["count"] or 0)

    return True


def load_bot_data_from_json() -> bool:
    if not DATA_FILE.exists():
        return False

    try:
        with DATA_FILE.open("r", encoding="utf-8") as f:
            payload = json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        print(f"讀取 bot_data.json 失敗：{e}")
        return False

    SELF_SERVICE_ORDER_SELECTIONS.clear()
    ORDER_CLAIMS.clear()
    CUSTOMER_REWARDS.clear()
    ORDER_COUNTERS.clear()

    for channel_id_text, data in payload.get("orders", {}).items():
        channel_id = _to_int(channel_id_text)
        if channel_id is None or not isinstance(data, dict):
            continue
        SELF_SERVICE_ORDER_SELECTIONS[channel_id] = data

    for message_id_text, data in payload.get("claims", {}).items():
        message_id = _to_int(message_id_text)
        if message_id is None or not isinstance(data, dict):
            continue
        ORDER_CLAIMS[message_id] = _deserialize_claim_data(data)

    for user_id_text, data in payload.get("customers", {}).items():
        user_id = _to_int(user_id_text)
        if user_id is None or not isinstance(data, dict):
            continue
        CUSTOMER_REWARDS[user_id] = _deserialize_customer_data(data)

    for day_text, count in payload.get("order_counters", {}).items():
        if not isinstance(day_text, str):
            continue
        count_int = _to_int(count)
        if count_int is None:
            continue
        ORDER_COUNTERS[day_text] = count_int

    return True


def load_bot_data() -> None:
    # 先讀 SQLite；若還沒有資料，讀舊 JSON 並立即寫入 SQLite。
    if load_bot_data_from_sqlite():
        return

    if load_bot_data_from_json():
        save_bot_data()
        print("已從 bot_data.json 匯入資料並寫入 bot.db。")

def remember_order_data(channel_id: int, data: dict) -> None:
    SELF_SERVICE_ORDER_SELECTIONS[channel_id] = data
    save_bot_data()


def remember_claim_data(message_id: int, data: dict) -> None:
    ORDER_CLAIMS[message_id] = data
    save_bot_data()


def generate_order_receipt_id() -> str:
    """自動產生訂單編號，例如 MO20260519001。"""
    day_key = get_taipei_now().strftime("%Y%m%d")
    next_number = int(ORDER_COUNTERS.get(day_key, 0) or 0) + 1
    ORDER_COUNTERS[day_key] = next_number
    save_bot_data()
    return f"{ORDER_ID_PREFIX}{day_key}{next_number:03d}"


def get_or_create_order_log_channel_sync_hint() -> str:
    return f"{ORDER_LOG_CHANNEL_NAME}（類別 ID：{ORDER_LOG_CATEGORY_ID}）"


async def get_or_create_order_log_channel(guild: discord.Guild) -> discord.TextChannel | None:
    category = guild.get_channel(ORDER_LOG_CATEGORY_ID)
    if not isinstance(category, discord.CategoryChannel):
        return None

    for channel in category.text_channels:
        if channel.name == ORDER_LOG_CHANNEL_NAME:
            return channel

    try:
        return await guild.create_text_channel(
            name=ORDER_LOG_CHANNEL_NAME,
            category=category,
            reason="Create order log channel"
        )
    except (discord.Forbidden, discord.HTTPException) as e:
        print(f"建立機器人日誌頻道失敗：{e}")
        return None


async def send_order_log(
    guild: discord.Guild | None,
    title: str,
    description: str | None = None,
    fields: list[tuple[str, str, bool]] | None = None,
    color: discord.Color | None = None,
) -> None:
    if guild is None:
        return

    channel = await get_or_create_order_log_channel(guild)
    if channel is None:
        print(f"找不到或無法建立機器人日誌頻道：{get_or_create_order_log_channel_sync_hint()}")
        return

    embed = discord.Embed(
        title=title,
        description=description or "",
        color=color or discord.Color.blurple(),
        timestamp=get_taipei_now(),
    )

    for name, value, inline in fields or []:
        embed.add_field(name=name, value=value if value else "未紀錄", inline=inline)

    try:
        await channel.send(embed=embed, allowed_mentions=discord.AllowedMentions.none())
    except discord.HTTPException as e:
        print(f"送出機器人日誌失敗：{e}")


async def send_lottery_announcement(
    guild: discord.Guild | None,
    content: str,
    embed: discord.Embed | None = None,
    channel: discord.TextChannel | None = None,
) -> bool:
    if guild is None:
        return False

    target_channel = channel

    if target_channel is None:
        fetched_channel = guild.get_channel(LOTTERY_ANNOUNCE_CHANNEL_ID)
        if fetched_channel is None:
            try:
                fetched_channel = await guild.fetch_channel(LOTTERY_ANNOUNCE_CHANNEL_ID)
            except (discord.NotFound, discord.Forbidden, discord.HTTPException) as e:
                print(f"找不到抽獎公告頻道：{e}")
                return False

        if not isinstance(fetched_channel, discord.TextChannel):
            print("抽獎公告頻道不是文字頻道。")
            return False

        target_channel = fetched_channel

    try:
        await target_channel.send(
            content=content,
            embed=embed,
            allowed_mentions=discord.AllowedMentions(everyone=True, users=True, roles=False),
        )
        return True
    except discord.HTTPException as e:
        print(f"送出抽獎公告失敗：{e}")
        return False


def run_daily_backup_once() -> str | None:
    """若今天還沒有備份，複製 bot.db 到 backups/，並清掉過舊備份。"""
    if not DB_FILE.exists():
        return None

    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    day_key = get_taipei_now().strftime("%Y%m%d")
    backup_path = BACKUP_DIR / f"bot_{day_key}.db"

    if not backup_path.exists():
        shutil.copy2(DB_FILE, backup_path)

    cutoff = get_taipei_now() - timedelta(days=BACKUP_KEEP_DAYS)
    for old_file in BACKUP_DIR.glob("bot_*.db"):
        try:
            date_part = old_file.stem.replace("bot_", "")
            file_date = datetime.strptime(date_part, "%Y%m%d").replace(tzinfo=timezone(timedelta(hours=8)))
        except ValueError:
            continue
        if file_date < cutoff:
            try:
                old_file.unlink()
            except OSError:
                pass

    return str(backup_path)


async def daily_backup_loop():
    await bot.wait_until_ready()
    while not bot.is_closed():
        try:
            backup_path = run_daily_backup_once()
            if backup_path:
                print(f"bot.db backup checked: {backup_path}")
        except Exception as e:
            print(f"每日備份 bot.db 失敗：{e}")
        await asyncio.sleep(3600)


def _parse_datetime_safe(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(str(value))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone(timedelta(hours=8)))
    return dt


async def check_stored_order_reminders_once(guild: discord.Guild | None = None) -> None:
    guild = guild or bot.get_guild(GUILD_ID)
    if guild is None:
        return

    now = get_taipei_now()
    changed = False

    for channel_id, data in list(SELF_SERVICE_ORDER_SELECTIONS.items()):
        if not isinstance(data, dict) or str(data.get("status", "")).lower() != "stored":
            continue

        stored_at = _parse_datetime_safe(data.get("stored_at"))
        if stored_at is None:
            continue

        age_days = max(0, (now - stored_at).days)
        sent = data.setdefault("stored_reminders_sent", [])
        if not isinstance(sent, list):
            sent = []
            data["stored_reminders_sent"] = sent

        due_days = [day for day in STORED_ORDER_REMINDER_DAYS if age_days >= day and day not in sent]
        if not due_days:
            continue

        for day in due_days:
            sent.append(day)

            customer_id = data.get("customer_id") or get_order_customer_id_from_channel(guild.get_channel(channel_id)) if isinstance(guild.get_channel(channel_id), discord.TextChannel) else data.get("customer_id")
            item = data.get("item") or "未紀錄"
            quantity = _to_int(data.get("quantity"), 1) or 1
            amount = _to_int(data.get("amount"), 0) or 0
            order_no = data.get("order_no") or "未產生"
            ticket_channel = guild.get_channel(channel_id)
            ticket_text = ticket_channel.mention if isinstance(ticket_channel, discord.TextChannel) else f"票口 ID：{channel_id}"

            description = (
                f"有一筆存單已經超過 **{day} 天**，請客服確認是否需要恢復、取消或聯絡顧客。\n\n"
                f"顧客：{f'<@{customer_id}>' if customer_id else '未紀錄'}\n"
                f"票口：{ticket_text}\n"
                f"訂單編號：{order_no}\n"
                f"項目：{item} x{quantity}\n"
                f"金額：{format_t_amount(amount) if amount else '未紀錄'}\n"
                f"存單原因：{data.get('stored_reason') or '未填寫'}\n"
                f"預計恢復：{data.get('stored_expected_time') or '未填寫'}"
            )
            await send_order_log(
                guild,
                title=f"存單提醒｜已超過 {day} 天",
                description=description,
                color=discord.Color.orange(),
            )

        SELF_SERVICE_ORDER_SELECTIONS[channel_id] = data
        changed = True

    if changed:
        save_bot_data()


async def stored_order_reminder_loop():
    await bot.wait_until_ready()
    while not bot.is_closed():
        try:
            await check_stored_order_reminders_once()
        except Exception as e:
            print(f"存單提醒檢查失敗：{e}")
        await asyncio.sleep(21600)


def is_manager_or_admin(member: discord.Member) -> bool:
    return has_role(member, MANAGER_ROLE_ID) or member.guild_permissions.administrator

def parse_receipt_amount(amount_text: str) -> int | None:
    """從收據金額欄位擷取金額。
    支援：1275、NT$1,275、1275T、750+595。
    若有加號，會把所有數字相加；否則取第一組數字。
    """
    normalized = amount_text.replace(",", "").strip()
    numbers = [int(value) for value in re.findall(r"\d+", normalized)]

    if not numbers:
        return None

    if "+" in normalized and len(numbers) >= 2:
        return sum(numbers)

    return numbers[0]

def get_customer_reward_data(user_id: int) -> dict:
    data = CUSTOMER_REWARDS.setdefault(
        user_id,
        {
            "total_spent": 0,
            "order_count": 0,
            "last_order_at": None,
            "points": 0,
            "point_adjustment": 0,
            "point_adjustment_logs": [],
            "platinum_channel_id": None,
            "manual_purchase_keys": [],
        }
    )
    data.setdefault("total_spent", 0)
    data.setdefault("order_count", 0)
    data.setdefault("last_order_at", None)
    data.setdefault("points", 0)
    data.setdefault("point_adjustment", 0)
    data.setdefault("point_adjustment_logs", [])
    data.setdefault("platinum_channel_id", None)
    data.setdefault("manual_purchase_keys", [])
    data.setdefault("notes", [])
    if not isinstance(data["manual_purchase_keys"], list):
        data["manual_purchase_keys"] = []
    if not isinstance(data["point_adjustment_logs"], list):
        data["point_adjustment_logs"] = []
    if not isinstance(data["notes"], list):
        data["notes"] = []
    return data

def get_member_level(total_spent: int) -> dict:
    current = MEMBER_LEVELS[0]
    for level in MEMBER_LEVELS:
        if total_spent >= level["threshold"]:
            current = level
        else:
            break
    return current

def get_next_member_level(total_spent: int) -> dict | None:
    for level in MEMBER_LEVELS:
        if total_spent < level["threshold"]:
            return level
    return None

def format_t_amount(amount: int) -> str:
    return f"{amount:,}T"

def calculate_reward_points(total_spent: int) -> int:
    return total_spent // REWARD_POINT_DIVISOR


def get_current_reward_points(data: dict) -> int:
    total_spent = int(data.get("total_spent", 0) or 0)
    base_points = calculate_reward_points(total_spent)
    adjustment = int(data.get("point_adjustment", 0) or 0)
    return max(0, base_points + adjustment)

def build_member_info_embed(member: discord.abc.User, data: dict, show_points: bool = True) -> discord.Embed:
    total_spent = int(data.get("total_spent", 0) or 0)
    order_count = int(data.get("order_count", 0) or 0)
    points = get_current_reward_points(data)
    level = get_member_level(total_spent)
    next_level = get_next_member_level(total_spent)

    embed = discord.Embed(
        title="你的會員資料" if show_points else "顧客會員資料",
        color=discord.Color.purple()
    )
    embed.add_field(name="顧客", value=member.mention, inline=False)
    embed.add_field(name="累積消費", value=format_t_amount(total_spent), inline=True)
    if show_points:
        embed.add_field(name="目前點數", value=f"{points:,} 點", inline=True)
    embed.add_field(name="完成訂單", value=f"{order_count:,} 單", inline=True)
    embed.add_field(name="會員等級", value=level["name"], inline=True)

    if next_level is None:
        embed.add_field(name="距離下一級還差", value="已達最高等級", inline=False)
    else:
        gap = max(0, int(next_level["threshold"]) - total_spent)
        embed.add_field(
            name="距離下一級還差",
            value=f"{format_t_amount(gap)}（下一級：{next_level['name']}）",
            inline=False
        )

    return embed


def get_customer_notes(user_id: int) -> list[dict]:
    data = get_customer_reward_data(user_id)
    notes = data.setdefault("notes", [])
    if not isinstance(notes, list):
        data["notes"] = []
        notes = data["notes"]
    return notes


def format_customer_notes_for_staff(user_id: int, limit: int = 8) -> str:
    notes = get_customer_notes(user_id)
    if not notes:
        return "無備註"

    lines = []
    for index, note in enumerate(notes[:limit], start=1):
        tag = "🚫 黑名單" if note.get("is_blacklist") else "📝 備註"
        created_at = note.get("created_at") or "未紀錄時間"
        operator_id = note.get("operator_id")
        operator_text = f"<@{operator_id}>" if operator_id else "未紀錄"
        content = str(note.get("content") or "未填寫")
        lines.append(f"{index}. {tag}｜{content}\n　建立：{created_at}｜人員：{operator_text}")

    if len(notes) > limit:
        lines.append(f"…還有 {len(notes) - limit} 筆")

    return "\n".join(lines)


def format_customer_notes_for_ticket(user_id: int) -> str:
    notes = get_customer_notes(user_id)
    if not notes:
        return ""

    blacklist_notes = [n for n in notes if n.get("is_blacklist")]
    normal_notes = [n for n in notes if not n.get("is_blacklist")]
    picked = blacklist_notes[:3] + normal_notes[:3]

    lines = ["\n\n⚠️ 客服注意：此顧客有備註紀錄"]
    if blacklist_notes:
        lines.append("🚫 含黑名單 / 高風險備註")

    for index, note in enumerate(picked[:5], start=1):
        tag = "黑名單" if note.get("is_blacklist") else "備註"
        lines.append(f"{index}. [{tag}] {note.get('content') or '未填寫'}")

    return "\n".join(lines)

async def fetch_member_safely(guild: discord.Guild, user_id: int) -> discord.Member | None:
    member = guild.get_member(user_id)
    if member is not None:
        return member
    try:
        return await guild.fetch_member(user_id)
    except (discord.NotFound, discord.Forbidden, discord.HTTPException):
        return None

async def ensure_reward_member_benefits(guild: discord.Guild, member: discord.Member | None, data: dict) -> list[str]:
    if member is None:
        return []

    notices = []
    total_spent = int(data.get("total_spent", 0) or 0)

    if total_spent >= 2500:
        silver_role = guild.get_role(SILVER_MEMBER_ROLE_ID)
        if silver_role is not None and silver_role not in member.roles:
            try:
                await member.add_roles(silver_role, reason="累積消費達銀級魔丸門檻")
                notices.append("已給予銀級魔丸身分組")
            except discord.Forbidden:
                notices.append("銀級魔丸身分組給予失敗：Bot 權限不足或身分組位置不夠高")
            except discord.HTTPException:
                notices.append("銀級魔丸身分組給予失敗：Discord API 錯誤")

    if total_spent >= 13000:
        existing_channel_id = _to_int(data.get("platinum_channel_id"))
        if existing_channel_id is not None and guild.get_channel(existing_channel_id) is not None:
            return notices

        category = guild.get_channel(PLATINUM_PRIVATE_CATEGORY_ID)
        if not isinstance(category, discord.CategoryChannel):
            notices.append("白金專屬頻道建立失敗：找不到指定類別")
            return notices

        overwrites = {
            guild.default_role: discord.PermissionOverwrite(
                view_channel=False,
                send_messages=False,
                read_message_history=False,
            ),
            member: discord.PermissionOverwrite(
                view_channel=True,
                send_messages=True,
                read_message_history=True,
                attach_files=True,
            ),
        }

        if guild.me is not None:
            overwrites[guild.me] = discord.PermissionOverwrite(
                view_channel=True,
                send_messages=True,
                manage_channels=True,
                read_message_history=True,
                attach_files=True,
            )

        for role_id in PLATINUM_CHAT_ROLE_IDS:
            role = guild.get_role(role_id)
            if role is not None:
                overwrites[role] = discord.PermissionOverwrite(
                    view_channel=True,
                    send_messages=True,
                    read_message_history=True,
                    attach_files=True,
                )

        clean_name = "".join(c if c.isalnum() else "-" for c in member.display_name.lower())[:40]
        channel_name = f"白金魔丸-{clean_name}-{member.id}"[:90]

        try:
            channel = await guild.create_text_channel(
                name=channel_name,
                category=category,
                overwrites=overwrites,
                topic=f"platinum_customer_id={member.id}",
                reason="累積消費達白金魔丸門檻，自動建立專屬聊天頻道"
            )
            data["platinum_channel_id"] = channel.id
            notices.append(f"已建立白金專屬聊天頻道：{channel.mention}")

            await channel.send(
                f"{member.mention} 已達白金魔丸會員，這裡是你的專屬聊天頻道。",
                allowed_mentions=discord.AllowedMentions(users=True, roles=False, everyone=False)
            )
        except discord.Forbidden:
            notices.append("白金專屬頻道建立失敗：Bot 權限不足")
        except discord.HTTPException:
            notices.append("白金專屬頻道建立失敗：Discord API 錯誤")

    return notices

async def add_customer_reward_from_order(
    guild: discord.Guild,
    order_channel_id: int,
    customer_id: int,
    amount_text: str,
    notify_channel: discord.abc.Messageable | None = None,
) -> str:
    order_data = SELF_SERVICE_ORDER_SELECTIONS.get(order_channel_id, {})

    if order_data.get("reward_counted"):
        return "此訂單已累積過會員消費，未重複累積。"

    amount = parse_receipt_amount(amount_text)
    if amount is None or amount <= 0:
        return "會員消費未累積：收據金額欄位沒有可辨識的數字。"

    data = get_customer_reward_data(customer_id)
    old_total_spent = int(data.get("total_spent", 0) or 0)
    old_level = get_member_level(old_total_spent)
    data["total_spent"] = old_total_spent + amount
    data["order_count"] = int(data.get("order_count", 0) or 0) + 1
    data["last_order_at"] = get_taipei_now_iso()
    data["points"] = get_current_reward_points(data)

    order_data["reward_counted"] = True
    order_data["reward_amount"] = amount
    order_data["reward_counted_at"] = get_taipei_now_iso()
    SELF_SERVICE_ORDER_SELECTIONS[order_channel_id] = order_data

    member = await fetch_member_safely(guild, customer_id)
    benefit_notices = await ensure_reward_member_benefits(guild, member, data)

    level = get_member_level(int(data["total_spent"]))
    if level["threshold"] > old_level["threshold"]:
        upgrade_notice = f"恭喜 <@{customer_id}> 升級為 **{level['name']}**！目前累積消費：{format_t_amount(int(data['total_spent']))}"
        benefit_notices.insert(0, upgrade_notice)
        if notify_channel is not None:
            try:
                await notify_channel.send(
                    upgrade_notice,
                    allowed_mentions=discord.AllowedMentions(users=True, roles=False, everyone=False)
                )
            except discord.HTTPException:
                pass

    save_bot_data()

    result = (
        f"會員累積已更新：+{format_t_amount(amount)}，"
        f"目前累積 {format_t_amount(int(data['total_spent']))}，"
        f"完成訂單 {int(data['order_count'])} 單，"
        f"等級：{level['name']}。"
    )

    if benefit_notices:
        result += "\n" + "\n".join(f"- {notice}" for notice in benefit_notices)

    return result



def parse_manual_purchase_date(date_text: str) -> tuple[str, str] | tuple[None, None]:
    """支援 20260512、2026/05/12、2026-05-12，回傳 ISO 與顯示文字。"""
    text = date_text.strip()

    for fmt in ("%Y%m%d", "%Y/%m/%d", "%Y-%m-%d"):
        try:
            dt = datetime.strptime(text, fmt)
            taipei_tz = timezone(timedelta(hours=8))
            dt = dt.replace(tzinfo=taipei_tz)
            return dt.isoformat(timespec="seconds"), dt.strftime("%Y/%m/%d")
        except ValueError:
            pass

    return None, None


def build_manual_purchase_key(customer_id: int, amount: int, date_iso: str, note: str | None = None) -> str:
    clean_note = (note or "").strip()
    return f"manual:{customer_id}:{amount}:{date_iso}:{clean_note}"


async def add_manual_purchase(
    guild: discord.Guild,
    customer_id: int,
    amount: int,
    date_text: str,
    operator_id: int,
    note: str | None = None,
) -> tuple[bool, str]:
    if amount <= 0:
        return False, "金額必須大於 0。"

    date_iso, display_date = parse_manual_purchase_date(date_text)
    if date_iso is None or display_date is None:
        return False, "日期格式錯誤，請用 20260512、2026/05/12 或 2026-05-12。"

    data = get_customer_reward_data(customer_id)
    old_total_spent = int(data.get("total_spent", 0) or 0)
    old_level = get_member_level(old_total_spent)
    manual_keys = data.setdefault("manual_purchase_keys", [])
    purchase_key = build_manual_purchase_key(customer_id, amount, date_iso, note)

    if purchase_key in manual_keys:
        return False, f"已跳過重複補登：<@{customer_id}> {format_t_amount(amount)} {display_date}。"

    data["total_spent"] = int(data.get("total_spent", 0) or 0) + amount
    data["order_count"] = int(data.get("order_count", 0) or 0) + 1
    data["points"] = get_current_reward_points(data)

    old_last = data.get("last_order_at")
    if not old_last or str(date_iso) > str(old_last):
        data["last_order_at"] = date_iso

    manual_keys.append(purchase_key)
    data["last_manual_added_at"] = get_taipei_now_iso()
    data["last_manual_added_by"] = operator_id
    CUSTOMER_REWARDS[customer_id] = data

    member = await fetch_member_safely(guild, customer_id)
    benefit_notices = await ensure_reward_member_benefits(guild, member, data)
    save_bot_data()

    level = get_member_level(int(data["total_spent"]))
    if level["threshold"] > old_level["threshold"]:
        benefit_notices.insert(0, f"恭喜 <@{customer_id}> 升級為 **{level['name']}**！目前累積消費：{format_t_amount(int(data['total_spent']))}")

    msg = (
        f"已補登 <@{customer_id}>：+{format_t_amount(amount)}，日期 {display_date}。"
        f"目前累積 {format_t_amount(int(data['total_spent']))}，"
        f"完成訂單 {int(data['order_count'])} 單，等級：{level['name']}。"
    )
    if benefit_notices:
        msg += "\n" + "\n".join(f"- {notice}" for notice in benefit_notices)
    return True, msg


async def adjust_customer_points(
    customer_id: int,
    delta_points: int,
    operator_id: int,
    reason: str | None = None,
) -> tuple[bool, str]:
    if delta_points == 0:
        return False, "調整點數不能是 0。"

    data = get_customer_reward_data(customer_id)
    before_points = get_current_reward_points(data)

    if before_points + delta_points < 0:
        return False, f"扣點失敗：<@{customer_id}> 目前只有 {before_points:,} 點，不足扣除 {abs(delta_points):,} 點。"

    data["point_adjustment"] = int(data.get("point_adjustment", 0) or 0) + delta_points
    after_points = get_current_reward_points(data)
    data["points"] = after_points

    logs = data.setdefault("point_adjustment_logs", [])
    logs.append({
        "delta": delta_points,
        "before": before_points,
        "after": after_points,
        "operator_id": operator_id,
        "reason": (reason or "").strip(),
        "created_at": get_taipei_now_iso(),
    })
    # 避免 JSON 檔越來越肥，先保留最近 100 筆點數調整紀錄。
    if len(logs) > 100:
        data["point_adjustment_logs"] = logs[-100:]

    CUSTOMER_REWARDS[customer_id] = data
    save_bot_data()

    action = "增加" if delta_points > 0 else "扣除"
    reason_text = f"，原因：{reason}" if reason else ""
    return True, (
        f"已為 <@{customer_id}> {action} {abs(delta_points):,} 點{reason_text}。\n"
        f"調整前：{before_points:,} 點\n"
        f"調整後：{after_points:,} 點"
    )


def get_dispatch_claim_view_from_data(message_id: int) -> "DispatchClaimView | None":
    data = ORDER_CLAIMS.get(message_id)

    if not data:
        return None

    required_values = [
        data.get("customer_id"),
        data.get("category_label"),
        data.get("item"),
        data.get("payment_method"),
        data.get("source_channel_id"),
    ]

    if any(value is None for value in required_values):
        return None

    return DispatchClaimView(
        customer_id=int(data["customer_id"]),
        category_label=str(data["category_label"]),
        item=str(data["item"]),
        quantity=_to_int(data.get("quantity"), 1) or 1,
        payment_method=str(data["payment_method"]),
        source_channel_id=int(data["source_channel_id"]),
        companion_preference=data.get("companion_preference"),
        locked=bool(data.get("locked", False)),
        status=str(data.get("status", "active")),
    )


def get_taipei_now() -> datetime:
    taipei_tz = timezone(timedelta(hours=8))
    return datetime.now(taipei_tz)


def get_taipei_now_iso() -> str:
    return get_taipei_now().isoformat(timespec="seconds")


def cleanup_old_closed_orders() -> None:
    """
    清理過期的非必要暫存資料。

    重要規則：
    - 已結單 closed：永久保留，因為營收、會員累積、統計都會用到。
    - 存單 stored：永久保留，避免存單被誤刪。
    - 取消單 cancelled/canceled：超過 CANCELLED_ORDER_KEEP_DAYS 天後清理。
    - 備份檔：由 run_daily_backup_once() 依 BACKUP_KEEP_DAYS 清理。
    """
    if CANCELLED_ORDER_KEEP_DAYS <= 0:
        return

    now = get_taipei_now()
    cutoff = now - timedelta(days=CANCELLED_ORDER_KEEP_DAYS)
    order_channel_ids_to_remove = []
    dispatch_message_ids_to_remove = set()

    for channel_id, data in list(SELF_SERVICE_ORDER_SELECTIONS.items()):
        if not isinstance(data, dict):
            continue

        status = str(data.get("status", "")).lower()

        # closed / stored 都是營運重要紀錄，不自動刪。
        if status in {"closed", "stored"} or data.get("closed"):
            continue

        # 只清理取消單。
        if status not in {"cancelled", "canceled"}:
            continue

        time_text = (
            data.get("cancelled_at")
            or data.get("updated_at")
            or data.get("closed_at")
            or data.get("created_at")
        )
        if not time_text:
            continue

        try:
            order_time = datetime.fromisoformat(str(time_text))
        except ValueError:
            continue

        if order_time.tzinfo is None:
            order_time = order_time.replace(tzinfo=timezone(timedelta(hours=8)))

        if order_time < cutoff:
            order_channel_ids_to_remove.append(channel_id)
            dispatch_message_id = _to_int(data.get("dispatch_message_id"))
            if dispatch_message_id is not None:
                dispatch_message_ids_to_remove.add(dispatch_message_id)

    for channel_id in order_channel_ids_to_remove:
        SELF_SERVICE_ORDER_SELECTIONS.pop(channel_id, None)

    for message_id in dispatch_message_ids_to_remove:
        ORDER_CLAIMS.pop(message_id, None)

    if order_channel_ids_to_remove or dispatch_message_ids_to_remove:
        save_bot_data()
        print(
            f"已清理 {len(order_channel_ids_to_remove)} 筆超過 "
            f"{CANCELLED_ORDER_KEEP_DAYS} 天的取消單暫存資料。"
        )


load_bot_data()
cleanup_old_closed_orders()

ORDER_CATEGORY_LABELS = {
    "basic": "基礎單",
    "fun": "趣味單",
    "farm": "代解代肝",
    "season": "賽季限定活動",
}

ORDER_ITEMS_BY_CATEGORY = {
    # 使用者要求「由下到上」，所以下拉式顯示會從體驗單開始往上排到油鍋單
    "basic": [
        "體驗單",
        "娛樂陪",
        "技術陪",
        "保底單",
        "賭約單",
        "油鍋單",
    ],
    "fun": [
        "豪到你了嗎",
        "瘋狗嘶咬",
        "這什麼鳥槍",
        "想吃自己打",
    ],
    "farm": [
        "賽季3x3",
        "純綠代肝哈夫幣",
    ],
    "season": [
        "勇敢者行動",
        "S9炫彩勇敢者行動",
    ],
}

ORDER_ITEM_TO_CATEGORY = {
    item: category
    for category, items in ORDER_ITEMS_BY_CATEGORY.items()
    for item in items
}

SPECIAL_COMPANION_ITEMS = {
    "娛樂陪",
    "技術陪",
    "保底單",
}

QUANTITY_SELECT_ITEMS = {
    "娛樂陪",
    "技術陪",
}

QUANTITY_OPTIONS = list(range(1, 9))

COMPANION_PREFERENCE_OPTIONS = [
    "不指定陪玩/打手",
    "指定陪玩/打手",
]

PAYMENT_METHOD_OPTIONS = [
    "街口",
    "轉帳",
]


class OrderControlSelect(discord.ui.Select):
    def __init__(self):
        options = [
            discord.SelectOption(
                label="派單",
                value="dispatch",
                description="開啟自助下單面板給開單用戶填寫"
            ),
            discord.SelectOption(
                label="取消訂單",
                value="cancel",
                description="取消並關閉這張下單票口"
            ),
        ]

        super().__init__(
            placeholder="客服操作選項",
            min_values=1,
            max_values=1,
            options=options,
            custom_id="order_control_select",
            row=0
        )

    async def callback(self, interaction: discord.Interaction):
        if not isinstance(interaction.user, discord.Member):
            await interaction.response.send_message("無法確認你的身分組。", ephemeral=True)
            return

        if not is_customer_staff(interaction.user):
            await interaction.response.send_message("只有客服可以操作訂單。", ephemeral=True)
            return

        if not isinstance(interaction.channel, discord.TextChannel):
            await interaction.response.send_message("這個功能只能在下單票口內使用。", ephemeral=True)
            return

        ORDER_CONTROL_SELECTIONS[(interaction.channel.id, interaction.user.id)] = self.values[0]

        await interaction.response.defer()


class SelfServiceOrderCategorySelect(discord.ui.Select):
    def __init__(self, customer_id: int, channel_id: int, selected_category: str | None = None):
        self.customer_id = customer_id
        self.channel_id = channel_id

        options = [
            discord.SelectOption(
                label="基礎單",
                value="basic",
                description="油鍋單、賭約單、保底單、技術陪、娛樂陪、體驗單",
                default=selected_category == "basic"
            ),
            discord.SelectOption(
                label="趣味單",
                value="fun",
                description="豪到你了嗎、瘋狗嘶咬、這什麼鳥槍、想吃自己打",
                default=selected_category == "fun"
            ),
            discord.SelectOption(
                label="代解代肝",
                value="farm",
                description="賽季3x3、純綠代肝哈夫幣",
                default=selected_category == "farm"
            ),
            discord.SelectOption(
                label="賽季限定活動",
                value="season",
                description="勇敢者行動、S9炫彩勇敢者行動",
                default=selected_category == "season"
            ),
        ]

        super().__init__(
            placeholder="請選擇訂單類別",
            min_values=1,
            max_values=1,
            options=options,
            custom_id="self_service_order_category_select",
            row=0
        )

    async def callback(self, interaction: discord.Interaction):
        if interaction.user.id != self.customer_id:
            await interaction.response.send_message("只有開這張票口的用戶可以選擇訂單。", ephemeral=True)
            return

        selected_category = self.values[0]

        data = SELF_SERVICE_ORDER_SELECTIONS.setdefault(self.channel_id, {})
        data["customer_id"] = self.customer_id
        data["category"] = selected_category
        data.pop("item", None)
        data.pop("quantity", None)
        data.pop("companion_preference", None)
        data.pop("payment_method", None)
        remember_order_data(self.channel_id, data)

        await interaction.response.edit_message(
            view=SelfServiceOrderView(
                customer_id=self.customer_id,
                channel_id=self.channel_id,
                selected_category=selected_category
            )
        )


class SelfServiceOrderItemSelect(discord.ui.Select):
    def __init__(
        self,
        customer_id: int,
        channel_id: int,
        selected_category: str | None = None,
        selected_item: str | None = None,
    ):
        self.customer_id = customer_id
        self.channel_id = channel_id
        self.selected_category = selected_category

        if selected_category is None:
            options = [
                discord.SelectOption(
                    label="請先選擇訂單類別",
                    value="need_category",
                    description="選完上方類別後，這裡會自動更新項目"
                )
            ]
            disabled = True
            placeholder = "請先選擇訂單類別"
        else:
            options = [
                discord.SelectOption(
                    label=item,
                    value=item,
                    description=ORDER_CATEGORY_LABELS[selected_category],
                    default=item == selected_item
                )
                for item in ORDER_ITEMS_BY_CATEGORY[selected_category]
            ]
            disabled = False
            placeholder = "請選擇訂單項目"

        super().__init__(
            placeholder=placeholder,
            min_values=1,
            max_values=1,
            options=options,
            custom_id="self_service_order_item_select",
            row=1,
            disabled=disabled
        )

    async def callback(self, interaction: discord.Interaction):
        if interaction.user.id != self.customer_id:
            await interaction.response.send_message("只有開這張票口的用戶可以選擇訂單。", ephemeral=True)
            return

        selected_item = self.values[0]

        data = SELF_SERVICE_ORDER_SELECTIONS.setdefault(self.channel_id, {})
        data["customer_id"] = self.customer_id
        data["item"] = selected_item
        data["quantity"] = 1
        data.pop("payment_method", None)

        if selected_item in SPECIAL_COMPANION_ITEMS:
            data.pop("companion_preference", None)
        else:
            data["companion_preference"] = "不指定陪玩/打手"
        remember_order_data(self.channel_id, data)

        await interaction.response.edit_message(
            view=SelfServiceOrderView(
                customer_id=self.customer_id,
                channel_id=self.channel_id,
                selected_category=data.get("category")
            )
        )


class SelfServiceCompanionPreferenceSelect(discord.ui.Select):
    def __init__(
        self,
        customer_id: int,
        channel_id: int,
        selected_item: str | None = None,
        selected_preference: str | None = None,
    ):
        self.customer_id = customer_id
        self.channel_id = channel_id
        self.selected_item = selected_item

        if selected_item is None:
            options = [
                discord.SelectOption(
                    label="請先選擇訂單項目",
                    value="need_item",
                    description="選完上方項目後，這裡會自動更新"
                )
            ]
            disabled = True
            placeholder = "請先選擇訂單項目"
        elif selected_item in SPECIAL_COMPANION_ITEMS:
            options = [
                discord.SelectOption(
                    label="不指定陪玩/打手",
                    value="不指定陪玩/打手",
                    description="由客服安排合適人選",
                    default=selected_preference == "不指定陪玩/打手"
                ),
                discord.SelectOption(
                    label="指定陪玩/打手",
                    value="指定陪玩/打手",
                    description="由下單用戶指定人選",
                    default=selected_preference == "指定陪玩/打手"
                ),
            ]
            disabled = False
            placeholder = "請選擇是否指定陪玩/打手"
        else:
            options = [
                discord.SelectOption(
                    label="不指定陪玩/打手",
                    value="不指定陪玩/打手",
                    description="此項目不開放指定",
                    default=True
                )
            ]
            disabled = False
            placeholder = "不指定陪玩/打手"

        super().__init__(
            placeholder=placeholder,
            min_values=1,
            max_values=1,
            options=options,
            custom_id="self_service_companion_preference_select",
            row=2,
            disabled=disabled
        )

    async def callback(self, interaction: discord.Interaction):
        if interaction.user.id != self.customer_id:
            await interaction.response.send_message("只有開這張票口的用戶可以選擇訂單。", ephemeral=True)
            return

        if self.values[0] == "need_item":
            await interaction.response.defer()
            return

        data = SELF_SERVICE_ORDER_SELECTIONS.setdefault(self.channel_id, {})
        data["customer_id"] = self.customer_id
        data["companion_preference"] = self.values[0]
        data.pop("payment_method", None)
        remember_order_data(self.channel_id, data)

        await interaction.response.defer()

class SelfServiceOrderQuantitySelect(discord.ui.Select):
    def __init__(
        self,
        customer_id: int,
        channel_id: int,
        selected_item: str | None = None,
        selected_quantity: int | None = None,
    ):
        self.customer_id = customer_id
        self.channel_id = channel_id
        self.selected_item = selected_item
        quantity = selected_quantity or 1

        if selected_item is None:
            options = [
                discord.SelectOption(
                    label="請先選擇訂單項目",
                    value="need_item",
                    description="選完上方項目後，這裡會自動更新"
                )
            ]
            disabled = True
            placeholder = "請先選擇訂單項目"
        elif selected_item in QUANTITY_SELECT_ITEMS:
            options = [
                discord.SelectOption(
                    label=f"{num} 單",
                    value=str(num),
                    description=f"{num} 單 = 約 {num} 小時",
                    default=quantity == num
                )
                for num in QUANTITY_OPTIONS
            ]
            disabled = False
            placeholder = "請選擇數量"
        else:
            options = [
                discord.SelectOption(
                    label="1 單",
                    value="1",
                    description="此項目數量固定為 1 單",
                    default=True
                )
            ]
            disabled = False
            placeholder = "數量固定為 1 單"

        super().__init__(
            placeholder=placeholder,
            min_values=1,
            max_values=1,
            options=options,
            custom_id="self_service_order_quantity_select",
            row=3,
            disabled=disabled
        )

    async def callback(self, interaction: discord.Interaction):
        if interaction.user.id != self.customer_id:
            await interaction.response.send_message("只有開這張票口的用戶可以選擇訂單數量。", ephemeral=True)
            return

        if self.values[0] == "need_item":
            await interaction.response.defer()
            return

        data = SELF_SERVICE_ORDER_SELECTIONS.setdefault(self.channel_id, {})
        selected_item = data.get("item")

        try:
            quantity = int(self.values[0])
        except ValueError:
            await interaction.response.send_message("數量選擇異常，請重新選擇。", ephemeral=True)
            return

        if selected_item not in QUANTITY_SELECT_ITEMS:
            quantity = 1

        if quantity < 1 or quantity > max(QUANTITY_OPTIONS):
            await interaction.response.send_message("數量請選擇 1 到 8 單。", ephemeral=True)
            return

        data["customer_id"] = self.customer_id
        data["quantity"] = quantity
        data.pop("payment_method", None)
        remember_order_data(self.channel_id, data)

        await interaction.response.defer()

def has_role(member: discord.Member, role_id: int) -> bool:
    return any(role.id == role_id for role in member.roles)


def build_self_service_order_embed(
    customer_mention: str,
    category_label: str,
    item: str,
    quantity: int,
    payment_method: str,
    source_channel: discord.TextChannel,
    companion_preference: str | None = None,
    receiver_text: str | None = None,
) -> discord.Embed:
    embed = discord.Embed(
        title="新自助下單",
        color=discord.Color.blue()
    )

    embed.add_field(
        name="下單用戶",
        value=customer_mention,
        inline=False
    )

    embed.add_field(
        name="訂單類別",
        value=category_label,
        inline=True
    )

    embed.add_field(
        name="訂單項目",
        value=item,
        inline=True
    )

    embed.add_field(
        name="數量",
        value=f"{quantity} 單",
        inline=True
    )

    embed.add_field(
        name="付款方式",
        value=payment_method,
        inline=True
    )

    if companion_preference is not None:
        embed.add_field(
            name="指定選項",
            value=companion_preference,
            inline=False
        )

    if receiver_text is not None:
        embed.add_field(
            name="接單人員",
            value=receiver_text,
            inline=False
        )

    embed.add_field(
        name="來源票口",
        value=source_channel.mention,
        inline=False
    )

    return embed


class DispatchCancelClaimButton(discord.ui.Button):
    def __init__(self, disabled: bool = False):
        super().__init__(
            label="取消接單",
            style=discord.ButtonStyle.danger,
            custom_id="dispatch_cancel_claim",
            disabled=disabled
        )

    async def callback(self, interaction: discord.Interaction):
        view = self.view

        if not isinstance(view, DispatchClaimView):
            await interaction.response.send_message("接單面板狀態異常，請重新派單。", ephemeral=True)
            return

        await view.cancel_claim(interaction)


class DispatchClaimView(discord.ui.View):
    def __init__(
        self,
        customer_id: int,
        category_label: str,
        item: str,
        quantity: int,
        payment_method: str,
        source_channel_id: int,
        companion_preference: str | None = None,
        locked: bool = False,
        status: str = "active",
    ):
        super().__init__(timeout=None)
        self.customer_id = customer_id
        self.category_label = category_label
        self.item = item
        self.quantity = quantity
        self.payment_method = payment_method
        self.source_channel_id = source_channel_id
        self.companion_preference = companion_preference
        self.locked = locked
        self.status = status

        self.add_item(DispatchCancelClaimButton(disabled=locked))

        if locked:
            for item in self.children:
                item.disabled = True

    def get_receiver_label(self, claim_type: str) -> str:
        if claim_type == "companion":
            return "陪玩接單"
        return "打手接單"

    def get_required_role_id(self, claim_type: str) -> int:
        if claim_type == "companion":
            return COMPANION_RECEIVER_ROLE_ID
        return BOOSTER_RECEIVER_ROLE_ID

    def get_claim_data(self, message_id: int) -> dict:
        data = ORDER_CLAIMS.setdefault(
            message_id,
            {
                "companion": set(),
                "booster": set(),
                "locked": False,
            }
        )

        data.setdefault("customer_id", self.customer_id)
        data.setdefault("category_label", self.category_label)
        data.setdefault("item", self.item)
        data.setdefault("quantity", self.quantity)
        data.setdefault("payment_method", self.payment_method)
        data.setdefault("source_channel_id", self.source_channel_id)
        data.setdefault("companion_preference", self.companion_preference)
        data.setdefault("dispatch_channel_id", DISPATCH_CHANNEL_ID)
        data.setdefault("status", self.status)

        return data

    def build_receiver_text(self, claim_data: dict) -> str | None:
        companion_ids = sorted(claim_data.get("companion", set()))
        booster_ids = sorted(claim_data.get("booster", set()))

        lines = []

        if companion_ids:
            lines.append("陪玩接單：" + " ".join(f"<@{user_id}>" for user_id in companion_ids))

        if booster_ids:
            lines.append("打手接單：" + " ".join(f"<@{user_id}>" for user_id in booster_ids))

        if not lines:
            return None

        return "\n".join(lines)

    async def refresh_panel(self, interaction: discord.Interaction, locked: bool | None = None):
        guild = interaction.guild

        if guild is None:
            await interaction.response.send_message("這個功能只能在伺服器內使用。", ephemeral=True)
            return

        if not isinstance(interaction.channel, discord.TextChannel):
            await interaction.response.send_message("這個功能只能在派單文字頻道使用。", ephemeral=True)
            return

        source_channel = guild.get_channel(self.source_channel_id)

        if source_channel is None or not isinstance(source_channel, discord.TextChannel):
            await interaction.response.send_message("找不到來源票口。", ephemeral=True)
            return

        claim_data = self.get_claim_data(interaction.message.id)

        if locked is not None:
            claim_data["locked"] = locked

        remember_claim_data(interaction.message.id, claim_data)

        receiver_text = self.build_receiver_text(claim_data)

        new_embed = build_self_service_order_embed(
            customer_mention=f"<@{self.customer_id}>",
            category_label=self.category_label,
            item=self.item,
            quantity=_to_int(claim_data.get("quantity"), self.quantity) or 1,
            payment_method=self.payment_method,
            source_channel=source_channel,
            companion_preference=self.companion_preference,
            receiver_text=receiver_text
        )

        status = claim_data.get("status", "active")

        if status == "stored":
            new_embed.add_field(
                name="接單狀態",
                value=(
                    "已存單，接單面板已鎖定\n"
                    f"存單原因：{claim_data.get('stored_reason') or '未填寫'}\n"
                    f"預計恢復：{claim_data.get('stored_expected_time') or '未填寫'}"
                ),
                inline=False
            )
        elif claim_data.get("locked"):
            new_embed.add_field(
                name="接單狀態",
                value="已結單，接單面板已鎖定",
                inline=False
            )

        await interaction.response.edit_message(
            embed=new_embed,
            view=DispatchClaimView(
                customer_id=self.customer_id,
                category_label=self.category_label,
                item=self.item,
                quantity=_to_int(claim_data.get("quantity"), self.quantity) or 1,
                payment_method=self.payment_method,
                source_channel_id=self.source_channel_id,
                companion_preference=self.companion_preference,
                locked=bool(claim_data.get("locked")),
                status=str(claim_data.get("status", "active"))
            ),
            allowed_mentions=discord.AllowedMentions(
                users=True,
                roles=False,
                everyone=False
            )
        )

    async def claim_order(self, interaction: discord.Interaction, claim_type: str):
        if not isinstance(interaction.user, discord.Member):
            await interaction.response.send_message("無法確認你的身分組。", ephemeral=True)
            return

        if self.locked:
            await interaction.response.send_message("此單已結單，接單面板已鎖定。", ephemeral=True)
            return

        required_role_id = self.get_required_role_id(claim_type)
        receiver_label = self.get_receiver_label(claim_type)

        if not has_role(interaction.user, required_role_id):
            await interaction.response.send_message(
                f"你沒有「{receiver_label}」權限。",
                ephemeral=True
            )
            return

        claim_data = self.get_claim_data(interaction.message.id)

        if claim_data.get("locked"):
            await interaction.response.send_message("此單已結單，接單面板已鎖定。", ephemeral=True)
            return

        claim_data[claim_type].add(interaction.user.id)
        remember_claim_data(interaction.message.id, claim_data)

        await send_order_log(
            interaction.guild,
            title=f"{receiver_label}",
            fields=[
                ("接單人", interaction.user.mention, True),
                ("顧客", f"<@{self.customer_id}>", True),
                ("訂單", f"{self.category_label}｜{self.item} x{self.quantity}", False),
            ],
            color=discord.Color.green(),
        )

        await self.refresh_panel(interaction)

    async def cancel_claim(self, interaction: discord.Interaction):
        if not isinstance(interaction.user, discord.Member):
            await interaction.response.send_message("無法確認你的身分組。", ephemeral=True)
            return

        if self.locked:
            await interaction.response.send_message("此單已結單，接單面板已鎖定。", ephemeral=True)
            return

        claim_data = self.get_claim_data(interaction.message.id)

        if claim_data.get("locked"):
            await interaction.response.send_message("此單已結單，接單面板已鎖定。", ephemeral=True)
            return

        removed = False

        for key in ("companion", "booster"):
            if interaction.user.id in claim_data[key]:
                claim_data[key].remove(interaction.user.id)
                removed = True

        if not removed:
            await interaction.response.send_message("你目前沒有接這張單。", ephemeral=True)
            return

        remember_claim_data(interaction.message.id, claim_data)

        await send_order_log(
            interaction.guild,
            title="取消接單",
            fields=[
                ("操作人", interaction.user.mention, True),
                ("顧客", f"<@{self.customer_id}>", True),
                ("訂單", f"{self.category_label}｜{self.item} x{self.quantity}", False),
            ],
            color=discord.Color.orange(),
        )

        await self.refresh_panel(interaction)

    @discord.ui.button(
        label="陪玩接單",
        style=discord.ButtonStyle.success,
        custom_id="dispatch_claim_companion"
    )
    async def companion_claim(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.claim_order(interaction, "companion")

    @discord.ui.button(
        label="打手接單",
        style=discord.ButtonStyle.primary,
        custom_id="dispatch_claim_booster"
    )
    async def booster_claim(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.claim_order(interaction, "booster")


async def delete_dispatch_claim_panel_for_order(guild: discord.Guild, order_channel_id: int):
    """取消票口時，一併刪除派單頻道對應的接單面板，並清除保存資料。"""
    data = SELF_SERVICE_ORDER_SELECTIONS.get(order_channel_id, {})
    dispatch_message_id = _to_int(data.get("dispatch_message_id"))
    dispatch_channel_id = _to_int(data.get("dispatch_channel_id"), DISPATCH_CHANNEL_ID) or DISPATCH_CHANNEL_ID

    if dispatch_message_id is not None:
        dispatch_channel = guild.get_channel(dispatch_channel_id)

        if isinstance(dispatch_channel, discord.TextChannel):
            try:
                message = await dispatch_channel.fetch_message(dispatch_message_id)
                await message.delete()
            except discord.NotFound:
                pass
            except discord.Forbidden:
                print("Bot 權限不足，無法刪除派單接單面板。")
            except discord.HTTPException as e:
                print(f"刪除派單接單面板失敗：{e}")

        ORDER_CLAIMS.pop(dispatch_message_id, None)

    if order_channel_id in SELF_SERVICE_ORDER_SELECTIONS:
        SELF_SERVICE_ORDER_SELECTIONS.pop(order_channel_id, None)
        save_bot_data()
    elif dispatch_message_id is not None:
        save_bot_data()


async def lock_dispatch_claim_panel(guild: discord.Guild, order_channel_id: int):
    """客服結單後，鎖定派單頻道對應的陪玩 / 打手接單面板。

    這版會同時處理「恢復訂單後重新發派單面板」的情況：
    如果 orders 裡記到的是舊 dispatch_message_id，會再從 ORDER_CLAIMS 裡找同一張票口的派單訊息，
    並把找到的派單面板全部鎖定，避免最新那則恢復訂單面板還能繼續被按。
    """
    data = SELF_SERVICE_ORDER_SELECTIONS.get(order_channel_id, {})
    dispatch_channel_id = data.get("dispatch_channel_id", DISPATCH_CHANNEL_ID)

    source_channel = guild.get_channel(order_channel_id)

    if source_channel is None or not isinstance(source_channel, discord.TextChannel):
        return

    dispatch_channel = guild.get_channel(dispatch_channel_id)

    if dispatch_channel is None or not isinstance(dispatch_channel, discord.TextChannel):
        return

    # 優先鎖 orders 目前記錄的派單訊息，同時補抓所有 claims 裡來源票口相同的派單訊息。
    candidate_message_ids: list[int] = []

    first_dispatch_message_id = _to_int(data.get("dispatch_message_id"))
    if first_dispatch_message_id is not None:
        candidate_message_ids.append(first_dispatch_message_id)

    for message_id, claim in list(ORDER_CLAIMS.items()):
        claim_source_channel_id = _to_int(claim.get("source_channel_id"))
        if claim_source_channel_id == order_channel_id:
            parsed_message_id = _to_int(message_id)
            if parsed_message_id is not None and parsed_message_id not in candidate_message_ids:
                candidate_message_ids.append(parsed_message_id)

    if not candidate_message_ids:
        return

    customer_id = data.get("customer_id")
    category = data.get("category")
    item = data.get("item", "未紀錄")
    quantity = _to_int(data.get("quantity"), 1) or 1
    payment_method = data.get("payment_method", "未紀錄")
    companion_preference = data.get("companion_preference")
    category_label = ORDER_CATEGORY_LABELS.get(category, category or data.get("category_label") or "未紀錄")
    customer_mention = f"<@{customer_id}>" if customer_id is not None else "未紀錄"

    data["closed"] = True
    data["status"] = "closed"
    data["closed_at"] = get_taipei_now_iso()
    data["quantity"] = quantity
    data["dispatch_channel_id"] = dispatch_channel_id

    locked_any = False
    newest_existing_message_id: int | None = None

    for dispatch_message_id in candidate_message_ids:
        try:
            message = await dispatch_channel.fetch_message(dispatch_message_id)
        except (discord.NotFound, discord.Forbidden, discord.HTTPException):
            continue

        claim_data = ORDER_CLAIMS.setdefault(
            dispatch_message_id,
            {
                "companion": set(),
                "booster": set(),
                "locked": False,
            }
        )

        # 若是舊資料，補齊缺少欄位。
        claim_data["customer_id"] = claim_data.get("customer_id") or customer_id
        claim_data["category_label"] = claim_data.get("category_label") or category_label
        claim_data["item"] = claim_data.get("item") or item
        claim_data["quantity"] = _to_int(claim_data.get("quantity"), quantity) or quantity
        claim_data["payment_method"] = claim_data.get("payment_method") or payment_method
        claim_data["source_channel_id"] = order_channel_id
        claim_data["companion_preference"] = claim_data.get("companion_preference") or companion_preference
        claim_data["dispatch_channel_id"] = dispatch_channel_id
        claim_data["locked"] = True
        claim_data["status"] = "closed"

        companion_ids = sorted(claim_data.get("companion", set()))
        booster_ids = sorted(claim_data.get("booster", set()))
        lines = []

        if companion_ids:
            lines.append("陪玩接單：" + " ".join(f"<@{user_id}>" for user_id in companion_ids))

        if booster_ids:
            lines.append("打手接單：" + " ".join(f"<@{user_id}>" for user_id in booster_ids))

        receiver_text = "\n".join(lines) if lines else None

        embed = build_self_service_order_embed(
            customer_mention=customer_mention,
            category_label=str(claim_data.get("category_label") or category_label),
            item=str(claim_data.get("item") or item),
            quantity=_to_int(claim_data.get("quantity"), quantity) or quantity,
            payment_method=str(claim_data.get("payment_method") or payment_method),
            source_channel=source_channel,
            companion_preference=claim_data.get("companion_preference") or companion_preference,
            receiver_text=receiver_text
        )
        embed.add_field(
            name="接單狀態",
            value="已結單，接單面板已鎖定",
            inline=False
        )

        try:
            await message.edit(
                embed=embed,
                view=DispatchClaimView(
                    customer_id=_to_int(claim_data.get("customer_id"), _to_int(customer_id, 0) or 0) or 0,
                    category_label=str(claim_data.get("category_label") or category_label),
                    item=str(claim_data.get("item") or item),
                    quantity=_to_int(claim_data.get("quantity"), quantity) or quantity,
                    payment_method=str(claim_data.get("payment_method") or payment_method),
                    source_channel_id=order_channel_id,
                    companion_preference=claim_data.get("companion_preference") or companion_preference,
                    locked=True,
                    status="closed"
                ),
                allowed_mentions=discord.AllowedMentions(
                    users=True,
                    roles=False,
                    everyone=False
                )
            )
            locked_any = True
            newest_existing_message_id = dispatch_message_id
            remember_claim_data(dispatch_message_id, claim_data)
        except (discord.NotFound, discord.Forbidden, discord.HTTPException):
            continue

    if locked_any:
        # 用實際成功鎖定的最新派單訊息覆蓋，避免之後再找到舊面板。
        if newest_existing_message_id is not None:
            data["dispatch_message_id"] = newest_existing_message_id
        remember_order_data(order_channel_id, data)
        save_bot_data()

async def store_dispatch_claim_panel(
    guild: discord.Guild,
    order_channel: discord.TextChannel,
    staff_member: discord.Member,
    reason: str,
    expected_time: str | None = None,
    note: str | None = None,
):
    """將訂單標記為存單，鎖定派單接單面板但保留票口。"""
    data = SELF_SERVICE_ORDER_SELECTIONS.get(order_channel.id, {})
    dispatch_message_id = data.get("dispatch_message_id")
    dispatch_channel_id = data.get("dispatch_channel_id", DISPATCH_CHANNEL_ID)

    if dispatch_message_id is None:
        raise ValueError("找不到這張訂單對應的派單訊息，請確認顧客是否已完成付款方式並送出派單。")

    dispatch_channel = guild.get_channel(dispatch_channel_id)

    if dispatch_channel is None or not isinstance(dispatch_channel, discord.TextChannel):
        raise ValueError("找不到派單頻道，請確認 DISPATCH_CHANNEL_ID 是否正確。")

    try:
        message = await dispatch_channel.fetch_message(dispatch_message_id)
    except discord.NotFound as exc:
        raise ValueError("找不到派單訊息，可能已被刪除。") from exc
    except discord.Forbidden as exc:
        raise ValueError("Bot 權限不足，無法讀取派單訊息。") from exc
    except discord.HTTPException as exc:
        raise ValueError(f"讀取派單訊息失敗：{exc}") from exc

    customer_id = data.get("customer_id") or get_order_customer_id_from_channel(order_channel)
    category = data.get("category")
    item = data.get("item", "未紀錄")
    quantity = _to_int(data.get("quantity"), 1) or 1
    payment_method = data.get("payment_method", "未紀錄")
    companion_preference = data.get("companion_preference")
    category_label = ORDER_CATEGORY_LABELS.get(category, category or data.get("category_label") or "未紀錄")
    customer_mention = f"<@{customer_id}>" if customer_id is not None else "未紀錄"

    claim_data = ORDER_CLAIMS.setdefault(
        dispatch_message_id,
        {
            "companion": set(),
            "booster": set(),
            "locked": False,
        }
    )
    claim_data["customer_id"] = customer_id
    claim_data["category_label"] = category_label
    claim_data["item"] = item
    claim_data["quantity"] = quantity
    claim_data["payment_method"] = payment_method
    claim_data["source_channel_id"] = order_channel.id
    claim_data["companion_preference"] = companion_preference
    claim_data["dispatch_channel_id"] = dispatch_channel_id
    claim_data["locked"] = True
    claim_data["status"] = "stored"
    claim_data["stored_at"] = get_taipei_now_iso()
    claim_data["stored_by"] = staff_member.id
    claim_data["stored_reason"] = reason
    claim_data["stored_expected_time"] = expected_time or None
    claim_data["stored_note"] = note or None

    data["customer_id"] = customer_id
    data["quantity"] = quantity
    data["dispatch_message_id"] = dispatch_message_id
    data["dispatch_channel_id"] = dispatch_channel_id
    data["closed"] = False
    data["status"] = "stored"
    data["stored_at"] = claim_data["stored_at"]
    data["stored_by"] = staff_member.id
    data["stored_reason"] = reason
    data["stored_expected_time"] = expected_time or None
    data["stored_note"] = note or None
    data["stored_reminders_sent"] = []

    remember_order_data(order_channel.id, data)
    remember_claim_data(dispatch_message_id, claim_data)

    companion_ids = sorted(claim_data.get("companion", set()))
    booster_ids = sorted(claim_data.get("booster", set()))
    lines = []

    if companion_ids:
        lines.append("陪玩接單：" + " ".join(f"<@{user_id}>" for user_id in companion_ids))

    if booster_ids:
        lines.append("打手接單：" + " ".join(f"<@{user_id}>" for user_id in booster_ids))

    receiver_text = "\n".join(lines) if lines else None

    embed = build_self_service_order_embed(
        customer_mention=customer_mention,
        category_label=category_label,
        item=item,
        quantity=quantity,
        payment_method=payment_method,
        source_channel=order_channel,
        companion_preference=companion_preference,
        receiver_text=receiver_text
    )
    embed.add_field(
        name="接單狀態",
        value=(
            "已存單，接單面板已鎖定\n"
            f"存單原因：{reason}\n"
            f"預計恢復：{expected_time or '未填寫'}"
        ),
        inline=False
    )

    if note:
        embed.add_field(
            name="存單備註",
            value=note,
            inline=False
        )

    await message.edit(
        embed=embed,
        view=DispatchClaimView(
            customer_id=customer_id or 0,
            category_label=category_label,
            item=item,
            quantity=quantity,
            payment_method=payment_method,
            source_channel_id=order_channel.id,
            companion_preference=companion_preference,
            locked=True,
            status="stored"
        ),
        allowed_mentions=discord.AllowedMentions(
            users=True,
            roles=False,
            everyone=False
        )
    )


async def resume_stored_order(
    guild: discord.Guild,
    order_channel: discord.TextChannel,
    staff_member: discord.Member,
):
    """恢復已存單的訂單，保留原本接單人員，並把派單面板重新發到派單頻道最下面。"""
    data = SELF_SERVICE_ORDER_SELECTIONS.get(order_channel.id, {})
    old_dispatch_message_id = data.get("dispatch_message_id")
    dispatch_channel_id = data.get("dispatch_channel_id", DISPATCH_CHANNEL_ID)

    if old_dispatch_message_id is None:
        raise ValueError("找不到這張訂單對應的派單訊息，無法恢復。")

    dispatch_channel = guild.get_channel(dispatch_channel_id)

    if dispatch_channel is None or not isinstance(dispatch_channel, discord.TextChannel):
        raise ValueError("找不到派單頻道，請確認 DISPATCH_CHANNEL_ID 是否正確。")

    old_message = None

    try:
        old_message = await dispatch_channel.fetch_message(old_dispatch_message_id)
    except discord.NotFound:
        # 舊訊息不見時仍可用保存資料重新發一則，只要 bot_data.json 還有接單資料。
        old_message = None
    except discord.Forbidden as exc:
        raise ValueError("Bot 權限不足，無法讀取派單訊息。") from exc
    except discord.HTTPException as exc:
        raise ValueError(f"讀取派單訊息失敗：{exc}") from exc

    claim_data = ORDER_CLAIMS.get(old_dispatch_message_id)

    if not claim_data:
        raise ValueError("找不到已保存的接單資料，請重新派單。")

    customer_id = claim_data.get("customer_id") or data.get("customer_id") or get_order_customer_id_from_channel(order_channel)
    category_label = claim_data.get("category_label") or ORDER_CATEGORY_LABELS.get(data.get("category"), data.get("category") or "未紀錄")
    item = claim_data.get("item") or data.get("item", "未紀錄")
    quantity = _to_int(claim_data.get("quantity"), _to_int(data.get("quantity"), 1)) or 1
    payment_method = claim_data.get("payment_method") or data.get("payment_method", "未紀錄")
    companion_preference = claim_data.get("companion_preference") or data.get("companion_preference")
    customer_mention = f"<@{customer_id}>" if customer_id is not None else "未紀錄"

    claim_data["locked"] = False
    claim_data["status"] = "active"
    claim_data["customer_id"] = customer_id
    claim_data["category_label"] = str(category_label)
    claim_data["item"] = str(item)
    claim_data["quantity"] = quantity
    claim_data["payment_method"] = str(payment_method)
    claim_data["source_channel_id"] = order_channel.id
    claim_data["companion_preference"] = companion_preference
    claim_data["dispatch_channel_id"] = dispatch_channel.id

    # 存單相關資料保留在 bot_data.json 裡當紀錄，但不再顯示為已存單。
    data["closed"] = False
    data["status"] = "active"
    data["quantity"] = quantity
    data["dispatch_channel_id"] = dispatch_channel.id

    companion_ids = sorted(claim_data.get("companion", set()))
    booster_ids = sorted(claim_data.get("booster", set()))
    lines = []

    if companion_ids:
        lines.append("陪玩接單：" + " ".join(f"<@{user_id}>" for user_id in companion_ids))

    if booster_ids:
        lines.append("打手接單：" + " ".join(f"<@{user_id}>" for user_id in booster_ids))

    receiver_text = "\n".join(lines) if lines else None

    embed = build_self_service_order_embed(
        customer_mention=customer_mention,
        category_label=str(category_label),
        item=str(item),
        quantity=quantity,
        payment_method=str(payment_method),
        source_channel=order_channel,
        companion_preference=companion_preference,
        receiver_text=receiver_text
    )
    embed.add_field(
        name="接單狀態",
        value=f"已由 {staff_member.mention} 恢復訂單，接單面板已重新發到最新位置。",
        inline=False
    )

    new_message = await dispatch_channel.send(
        embed=embed,
        view=DispatchClaimView(
            customer_id=customer_id or 0,
            category_label=str(category_label),
            item=str(item),
            quantity=quantity,
            payment_method=str(payment_method),
            source_channel_id=order_channel.id,
            companion_preference=companion_preference,
            locked=False,
            status="active"
        ),
        allowed_mentions=discord.AllowedMentions(
            users=True,
            roles=False,
            everyone=False
        )
    )

    # 刪除舊的存單面板，避免同一張單在派單頻道出現兩個面板。
    if old_message is not None:
        try:
            await old_message.delete(reason=f"Stored order resumed by {staff_member}")
        except (discord.NotFound, discord.Forbidden, discord.HTTPException):
            pass

    # 把接單資料移到新的 message_id，保留原本陪玩/打手接單人員。
    ORDER_CLAIMS.pop(old_dispatch_message_id, None)
    ORDER_CLAIMS[new_message.id] = claim_data
    data["dispatch_message_id"] = new_message.id

    remember_order_data(order_channel.id, data)
    remember_claim_data(new_message.id, claim_data)
    save_bot_data()


class StoreOrderModal(discord.ui.Modal, title="存單"):
    reason = discord.ui.TextInput(
        label="存單原因",
        placeholder="例如：顧客暫時無法遊玩、改約時間、等待活動開啟",
        required=True,
        max_length=200
    )

    expected_time = discord.ui.TextInput(
        label="預計恢復時間",
        placeholder="例如：今晚 20:00、明天、未定",
        required=False,
        max_length=100
    )

    note = discord.ui.TextInput(
        label="備註",
        placeholder="可填寫付款狀態、注意事項或客服備註",
        style=discord.TextStyle.paragraph,
        required=False,
        max_length=800
    )

    async def on_submit(self, interaction: discord.Interaction):
        if not isinstance(interaction.user, discord.Member):
            await interaction.response.send_message("無法確認你的身分組。", ephemeral=True)
            return

        if not is_customer_staff(interaction.user):
            await interaction.response.send_message("只有客服可以存單。", ephemeral=True)
            return

        guild = interaction.guild

        if guild is None:
            await interaction.response.send_message("這個功能只能在伺服器內使用。", ephemeral=True)
            return

        if not isinstance(interaction.channel, discord.TextChannel):
            await interaction.response.send_message("這個功能只能在下單票口內使用。", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)

        try:
            await store_dispatch_claim_panel(
                guild=guild,
                order_channel=interaction.channel,
                staff_member=interaction.user,
                reason=self.reason.value.strip(),
                expected_time=self.expected_time.value.strip() or None,
                note=self.note.value.strip() or None,
            )
            await send_order_log(
                guild,
                title="訂單已存單",
                fields=[
                    ("票口", interaction.channel.mention, True),
                    ("操作人員", interaction.user.mention, True),
                    ("存單原因", self.reason.value.strip(), False),
                    ("預計恢復", self.expected_time.value.strip() or "未填寫", True),
                    ("備註", self.note.value.strip() or "未填寫", False),
                ],
                color=discord.Color.gold(),
            )
        except ValueError as e:
            await interaction.followup.send(str(e), ephemeral=True)
            return

        await interaction.channel.send(
            f"此訂單已由 {interaction.user.mention} 存單。\n\n"
            f"存單原因：{self.reason.value.strip()}\n"
            f"預計恢復：{self.expected_time.value.strip() or '未填寫'}\n"
            f"備註：{self.note.value.strip() or '無'}",
            allowed_mentions=discord.AllowedMentions(
                users=True,
                roles=False,
                everyone=False
            )
        )

        await interaction.followup.send("已存單，派單頻道接單面板已鎖定。", ephemeral=True)


class PaymentMethodSelect(discord.ui.Select):
    def __init__(self, customer_id: int, channel_id: int):
        self.customer_id = customer_id
        self.channel_id = channel_id

        options = [
            discord.SelectOption(label=method, value=method)
            for method in PAYMENT_METHOD_OPTIONS
        ]

        super().__init__(
            placeholder="請選擇付款方式",
            min_values=1,
            max_values=1,
            options=options,
            custom_id="payment_method_select",
            row=0
        )

    async def callback(self, interaction: discord.Interaction):
        if interaction.user.id != self.customer_id:
            await interaction.response.send_message("只有開這張票口的用戶可以選擇付款方式。", ephemeral=True)
            return

        data = SELF_SERVICE_ORDER_SELECTIONS.setdefault(self.channel_id, {})
        data["customer_id"] = self.customer_id
        selected_method = self.values[0]
        data["payment_method"] = selected_method
        remember_order_data(self.channel_id, data)

        payment_info = {
            "轉帳": (
                "銀行轉帳-國泰\n"
                "代碼：013\n"
                "帳號：135700021419"
            ),
            "街口": (
                "街口支付\n"
                "代碼：396\n"
                "帳號：900884222"
            ),
        }.get(selected_method)

        if payment_info is not None:
            await interaction.response.send_message(
                f"已選擇付款方式：{selected_method}\n\n"
                f"```text\n{payment_info}\n```",
                ephemeral=True
            )
        else:
            await interaction.response.defer()


class PaymentMethodView(discord.ui.View):
    def __init__(self, customer_id: int, channel_id: int):
        super().__init__(timeout=86400)
        self.customer_id = customer_id
        self.channel_id = channel_id
        self.add_item(PaymentMethodSelect(customer_id, channel_id))

    @discord.ui.button(
        label="送出",
        style=discord.ButtonStyle.success,
        custom_id="payment_method_submit_button",
        row=1
    )
    async def submit_payment(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.customer_id:
            await interaction.response.send_message("只有開這張票口的用戶可以送出付款方式。", ephemeral=True)
            return

        guild = interaction.guild

        if guild is None:
            await interaction.response.send_message("這個功能只能在伺服器內使用。", ephemeral=True)
            return

        if not isinstance(interaction.channel, discord.TextChannel):
            await interaction.response.send_message("無法確認目前票口頻道。", ephemeral=True)
            return

        data = SELF_SERVICE_ORDER_SELECTIONS.get(self.channel_id, {})
        category = data.get("category")
        item = data.get("item")
        quantity = _to_int(data.get("quantity"), 1) or 1
        companion_preference = data.get("companion_preference")
        payment_method = data.get("payment_method")

        if category is None or item is None:
            await interaction.response.send_message("找不到訂單資料，請回到自助下單面板重新選擇。", ephemeral=True)
            return

        if payment_method is None:
            await interaction.response.send_message("請先選擇付款方式，再按送出。", ephemeral=True)
            return

        item_category = ORDER_ITEM_TO_CATEGORY.get(item)

        if item_category != category:
            await interaction.response.send_message(
                "你選擇的訂單類別與訂單項目不一致，請回到自助下單面板重新選擇。",
                ephemeral=True
            )
            return

        if item in SPECIAL_COMPANION_ITEMS and companion_preference is None:
            await interaction.response.send_message(
                "這個項目請先回到自助下單面板選擇「不指定陪玩/打手」或「指定陪玩/打手」。",
                ephemeral=True
            )
            return

        if item not in QUANTITY_SELECT_ITEMS:
            quantity = 1
            data["quantity"] = 1
            remember_order_data(self.channel_id, data)
        elif quantity < 1 or quantity > max(QUANTITY_OPTIONS):
            await interaction.response.send_message("數量選擇異常，請回到自助下單面板重新選擇。", ephemeral=True)
            return

        if companion_preference is None:
            companion_preference = "不指定陪玩/打手"
            data["companion_preference"] = companion_preference
            remember_order_data(self.channel_id, data)

        dispatch_channel = guild.get_channel(DISPATCH_CHANNEL_ID)

        if dispatch_channel is None or not isinstance(dispatch_channel, discord.TextChannel):
            await interaction.response.send_message(
                "找不到派單頻道，請確認 DISPATCH_CHANNEL_ID 是否正確。",
                ephemeral=True
            )
            return

        category_label = ORDER_CATEGORY_LABELS[category]

        embed = build_self_service_order_embed(
            customer_mention=interaction.user.mention,
            category_label=category_label,
            item=item,
            quantity=quantity,
            payment_method=payment_method,
            source_channel=interaction.channel,
            companion_preference=companion_preference
        )

        dispatch_message = await dispatch_channel.send(
            embed=embed,
            view=DispatchClaimView(
                customer_id=interaction.user.id,
                category_label=category_label,
                item=item,
                quantity=quantity,
                payment_method=payment_method,
                source_channel_id=interaction.channel.id,
                companion_preference=companion_preference
            ),
            allowed_mentions=discord.AllowedMentions(
                users=True,
                roles=False,
                everyone=False
            )
        )

        ORDER_CLAIMS[dispatch_message.id] = {
            "companion": set(),
            "booster": set(),
            "locked": False,
            "customer_id": interaction.user.id,
            "category_label": category_label,
            "item": item,
            "quantity": quantity,
            "payment_method": payment_method,
            "source_channel_id": interaction.channel.id,
            "companion_preference": companion_preference,
            "dispatch_channel_id": dispatch_channel.id,
        }
        data["quantity"] = quantity
        data["dispatch_message_id"] = dispatch_message.id
        data["dispatch_channel_id"] = dispatch_channel.id
        data["closed"] = False
        remember_order_data(interaction.channel.id, data)
        remember_claim_data(dispatch_message.id, ORDER_CLAIMS[dispatch_message.id])

        await send_order_log(
            guild,
            title="新自助下單已派單",
            fields=[
                ("顧客", interaction.user.mention, True),
                ("訂單類別", category_label, True),
                ("訂單項目", item, True),
                ("數量", f"{quantity} 單", True),
                ("付款方式", payment_method, True),
                ("指定選項", companion_preference, True),
                ("票口", interaction.channel.mention, False),
                ("派單訊息", dispatch_message.jump_url, False),
            ],
            color=discord.Color.blue(),
        )

        await interaction.response.defer()

        operation_embed = discord.Embed(
            title="訂單操作",
            description="請客服從下拉式清單選擇後，按下確認。",
            color=discord.Color.green()
        )

        await interaction.channel.send(
            embed=operation_embed,
            view=StaffOrderOperationView()
        )


class SelfServiceOrderView(discord.ui.View):
    def __init__(self, customer_id: int, channel_id: int, selected_category: str | None = None):
        super().__init__(timeout=86400)
        self.customer_id = customer_id
        self.channel_id = channel_id

        data = SELF_SERVICE_ORDER_SELECTIONS.get(channel_id, {})
        category = selected_category or data.get("category")
        selected_item = data.get("item")
        selected_preference = data.get("companion_preference")
        selected_quantity = _to_int(data.get("quantity"), 1) or 1

        self.add_item(SelfServiceOrderCategorySelect(customer_id, channel_id, category))
        self.add_item(SelfServiceOrderItemSelect(customer_id, channel_id, category, selected_item))
        self.add_item(SelfServiceCompanionPreferenceSelect(customer_id, channel_id, selected_item, selected_preference))
        self.add_item(SelfServiceOrderQuantitySelect(customer_id, channel_id, selected_item, selected_quantity))

    @discord.ui.button(
        label="前往付款",
        style=discord.ButtonStyle.success,
        custom_id="self_service_order_go_payment_button",
        row=4
    )
    async def go_payment(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.customer_id:
            await interaction.response.send_message("只有開這張票口的用戶可以操作訂單。", ephemeral=True)
            return

        if not isinstance(interaction.channel, discord.TextChannel):
            await interaction.response.send_message("無法確認目前票口頻道。", ephemeral=True)
            return

        data = SELF_SERVICE_ORDER_SELECTIONS.get(self.channel_id, {})
        category = data.get("category")
        item = data.get("item")
        quantity = _to_int(data.get("quantity"), 1) or 1
        companion_preference = data.get("companion_preference")

        if category is None or item is None:
            await interaction.response.send_message("請先選擇訂單類別與訂單項目，再前往付款。", ephemeral=True)
            return

        item_category = ORDER_ITEM_TO_CATEGORY.get(item)

        if item_category != category:
            await interaction.response.send_message(
                "你選擇的訂單類別與訂單項目不一致，請重新選擇。",
                ephemeral=True
            )
            return

        if item in SPECIAL_COMPANION_ITEMS and companion_preference is None:
            await interaction.response.send_message(
                "這個項目請先選擇「不指定陪玩/打手」或「指定陪玩/打手」，再前往付款。",
                ephemeral=True
            )
            return

        if item not in QUANTITY_SELECT_ITEMS:
            quantity = 1
            data["quantity"] = 1
            remember_order_data(self.channel_id, data)
        elif quantity < 1 or quantity > max(QUANTITY_OPTIONS):
            await interaction.response.send_message("請重新選擇正確的數量。", ephemeral=True)
            return

        if companion_preference is None:
            companion_preference = "不指定陪玩/打手"
            data["companion_preference"] = companion_preference
            remember_order_data(self.channel_id, data)

        category_label = ORDER_CATEGORY_LABELS[category]
        payment_embed = discord.Embed(
            title="付款方式",
            description=(
                f"下單用戶：{interaction.user.mention}\n\n"
                f"訂單類別：{category_label}\n"
                f"訂單項目：{item}\n"
                f"數量：{quantity} 單\n"
                "請選擇付款方式，完成後按「送出」。"
            ),
            color=discord.Color.gold()
        )

        if data.get("companion_preference") is not None:
            payment_embed.add_field(
                name="指定選項",
                value=data["companion_preference"],
                inline=False
            )

        await interaction.response.defer()

        await interaction.channel.send(
            embed=payment_embed,
            view=PaymentMethodView(
                customer_id=self.customer_id,
                channel_id=self.channel_id
            ),
            allowed_mentions=discord.AllowedMentions(
                users=True,
                roles=False,
                everyone=False
            )
        )

class StaffOrderOperationSelect(discord.ui.Select):
    def __init__(self):
        options = [
            discord.SelectOption(
                label="已結單",
                value="done",
                description="填寫收據並送出評論按鈕"
            ),
            discord.SelectOption(
                label="存單",
                value="store",
                description="保留票口並鎖定派單接單面板"
            ),
            discord.SelectOption(
                label="恢復訂單",
                value="resume",
                description="恢復已存單訂單，重新開放接單面板"
            ),
            discord.SelectOption(
                label="取消訂單",
                value="cancel",
                description="取消並關閉這張下單票口"
            ),
        ]

        super().__init__(
            placeholder="訂單操作選項",
            min_values=1,
            max_values=1,
            options=options,
            custom_id="staff_order_operation_select",
            row=0
        )

    async def callback(self, interaction: discord.Interaction):
        if not isinstance(interaction.user, discord.Member):
            await interaction.response.send_message("無法確認你的身分組。", ephemeral=True)
            return

        if not is_customer_staff(interaction.user):
            await interaction.response.send_message("只有客服可以操作訂單。", ephemeral=True)
            return

        if not isinstance(interaction.channel, discord.TextChannel):
            await interaction.response.send_message("這個功能只能在下單票口內使用。", ephemeral=True)
            return

        STAFF_ORDER_OPERATION_SELECTIONS[(interaction.channel.id, interaction.user.id)] = self.values[0]

        await interaction.response.defer()


class StaffOrderOperationView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(StaffOrderOperationSelect())

    @discord.ui.button(
        label="確認",
        style=discord.ButtonStyle.success,
        custom_id="staff_order_operation_confirm",
        row=1
    )
    async def confirm_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not isinstance(interaction.user, discord.Member):
            await interaction.response.send_message("無法確認你的身分組。", ephemeral=True)
            return

        if not is_customer_staff(interaction.user):
            await interaction.response.send_message("只有客服可以操作訂單。", ephemeral=True)
            return

        if not isinstance(interaction.channel, discord.TextChannel):
            await interaction.response.send_message("這個功能只能在下單票口內使用。", ephemeral=True)
            return

        selected = STAFF_ORDER_OPERATION_SELECTIONS.get((interaction.channel.id, interaction.user.id))

        if selected is None:
            await interaction.response.send_message(
                "請先從下拉式清單選擇操作，再按確認。",
                ephemeral=True
            )
            return

        STAFF_ORDER_OPERATION_SELECTIONS.pop((interaction.channel.id, interaction.user.id), None)

        if selected == "done":
            await interaction.response.send_modal(ReceiptModal())
        elif selected == "store":
            await interaction.response.send_modal(StoreOrderModal())
        elif selected == "resume":
            guild = interaction.guild

            if guild is None:
                await interaction.response.send_message("這個功能只能在伺服器內使用。", ephemeral=True)
                return

            await interaction.response.defer(ephemeral=True)

            try:
                await resume_stored_order(
                    guild=guild,
                    order_channel=interaction.channel,
                    staff_member=interaction.user,
                )
                await send_order_log(
                    guild,
                    title="訂單已恢復",
                    fields=[
                        ("票口", interaction.channel.mention, True),
                        ("操作人員", interaction.user.mention, True),
                    ],
                    color=discord.Color.green(),
                )
            except ValueError as e:
                await interaction.followup.send(str(e), ephemeral=True)
                return

            await interaction.channel.send(
                f"此訂單已由 {interaction.user.mention} 恢復，派單頻道接單面板已重新開放。",
                allowed_mentions=discord.AllowedMentions(
                    users=True,
                    roles=False,
                    everyone=False
                )
            )
            await interaction.followup.send("已恢復訂單。", ephemeral=True)
        elif selected == "cancel":
            await interaction.response.send_message(
                "是否確定要取消這筆訂單？",
                view=ConfirmCancelOrderView(),
                ephemeral=True
            )
        else:
            await interaction.response.send_message(
                "選擇項目異常，請重新選擇一次。",
                ephemeral=True
            )


class OrderControlView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(OrderControlSelect())

    @discord.ui.button(
        label="確認",
        style=discord.ButtonStyle.success,
        custom_id="order_control_confirm",
        row=1
    )
    async def confirm_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not isinstance(interaction.user, discord.Member):
            await interaction.response.send_message("無法確認你的身分組。", ephemeral=True)
            return

        if not is_customer_staff(interaction.user):
            await interaction.response.send_message("只有客服可以操作訂單。", ephemeral=True)
            return

        if not isinstance(interaction.channel, discord.TextChannel):
            await interaction.response.send_message("這個功能只能在下單票口內使用。", ephemeral=True)
            return

        selected = ORDER_CONTROL_SELECTIONS.get((interaction.channel.id, interaction.user.id))

        if selected is None:
            await interaction.response.send_message(
                "請先從下拉式清單選擇操作，再按確認。",
                ephemeral=True
            )
            return

        ORDER_CONTROL_SELECTIONS.pop((interaction.channel.id, interaction.user.id), None)

        if selected == "cancel":
            await interaction.response.send_message(
                "是否確定要取消這筆訂單？",
                view=ConfirmCancelOrderView(),
                ephemeral=True
            )
            return

        if selected != "dispatch":
            await interaction.response.send_message(
                "選擇項目異常，請重新選擇一次。",
                ephemeral=True
            )
            return

        customer_id = get_order_customer_id_from_channel(interaction.channel)

        if customer_id is None:
            await interaction.response.send_message(
                "無法辨識開單用戶，請確認這張票口是不是由下單功能建立。",
                ephemeral=True
            )
            return

        customer = interaction.guild.get_member(customer_id) if interaction.guild else None
        customer_mention = customer.mention if customer is not None else f"<@{customer_id}>"

        embed = discord.Embed(
            title="自助下單",
            description=(
                f"下單用戶：{customer_mention}\n\n"
                "請下單用戶選擇訂單類別與訂單項目，完成後按「前往付款」。\n"
                "如果選擇娛樂陪、技術陪，數量欄位可選擇 1～8 單；1 單 = 1 小時，2 單 = 2 小時，依此類推。\n"
                "如果選擇娛樂陪、技術陪、保底單，請額外選擇是否指定陪玩/打手。"
            ),
            color=discord.Color.purple()
        )

        await interaction.response.defer()

        await interaction.channel.send(
            embed=embed,
            view=SelfServiceOrderView(
                customer_id=customer_id,
                channel_id=interaction.channel.id
            ),
            allowed_mentions=discord.AllowedMentions(
                users=True,
                roles=False,
                everyone=False
            )
        )

# ========= 入職操作 Modal / 按鈕 =========

class RecruitControlView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(
        label="已完成考核",
        style=discord.ButtonStyle.success,
        custom_id="recruit_exam_completed_button"
    )
    async def exam_completed(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not isinstance(interaction.user, discord.Member):
            await interaction.response.send_message("無法確認你的身分組。", ephemeral=True)
            return

        if not is_exam_staff(interaction.user):
            await interaction.response.send_message("只有考官或店長可以操作。", ephemeral=True)
            return

        channel = interaction.channel

        await interaction.response.send_message(
            f"此入職申請已由 {interaction.user.mention} 標記為已完成考核。\n"
            "頻道將在 3 秒後關閉。",
            ephemeral=False,
            allowed_mentions=discord.AllowedMentions(
                users=True,
                roles=False,
                everyone=False
            )
        )

        await asyncio.sleep(3)

        if isinstance(channel, discord.TextChannel):
            await remove_recruit_applicant_role(interaction.guild, channel)
            await channel.delete(reason=f"Recruit exam completed by {interaction.user}")


# ========= 客訴 Modal / 按鈕 =========

class ComplaintModal(discord.ui.Modal, title="客訴單"):
    complaint_content = discord.ui.TextInput(
        label="客訴內容",
        placeholder="請輸入你的客訴內容",
        style=discord.TextStyle.paragraph,
        required=True,
        max_length=1500
    )

    async def on_submit(self, interaction: discord.Interaction):
        guild = interaction.guild

        if guild is None:
            await interaction.response.send_message("這個功能只能在伺服器內使用。", ephemeral=True)
            return

        receive_channel = guild.get_channel(COMPLAINT_RECEIVE_CHANNEL_ID)

        if receive_channel is None or not isinstance(receive_channel, discord.TextChannel):
            await interaction.response.send_message(
                "找不到客訴接收頻道，請確認 COMPLAINT_RECEIVE_CHANNEL_ID 是否正確。",
                ephemeral=True
            )
            return

        boss_mention = interaction.user.mention
        boss_id = interaction.user.id

        embed = discord.Embed(
            title="客訴",
            description=(
                f"有一則來自 {boss_mention} 的客訴!\n"
                f"申請人 ID：{boss_id}\n\n"
                f"客訴內容：\n{self.complaint_content.value}"
            ),
            color=discord.Color.red()
        )

        await receive_channel.send(
            embed=embed,
            view=ComplaintResolveView(),
            allowed_mentions=discord.AllowedMentions(
                users=False,
                roles=False,
                everyone=False
            )
        )

        await interaction.response.send_message(
            "你的客訴已送出，會由相關人員處理。",
            ephemeral=True
        )


class ComplaintPanelView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(
        label="客訴單",
        style=discord.ButtonStyle.danger,
        custom_id="complaint_form_button"
    )
    async def complaint_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(ComplaintModal())


class ComplaintResolveView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(
        label="已解決",
        style=discord.ButtonStyle.success,
        custom_id="complaint_resolved_button"
    )
    async def resolved_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not isinstance(interaction.user, discord.Member):
            await interaction.response.send_message("無法確認你的身分組。", ephemeral=True)
            return

        if not is_complaint_staff(interaction.user):
            await interaction.response.send_message("只有客服或店長可以標記已解決。", ephemeral=True)
            return

        button.disabled = True
        button.label = "已解決"

        embed = interaction.message.embeds[0] if interaction.message.embeds else None

        if embed is not None:
            embed.color = discord.Color.green()
            embed.add_field(
                name="處理狀態",
                value=f"已由 {interaction.user.mention} 標記為已解決",
                inline=False
            )

            await interaction.response.edit_message(embed=embed, view=self)
        else:
            await interaction.response.edit_message(
                content=f"此客訴已由 {interaction.user.mention} 標記為已解決。",
                view=self
            )


# ========= 顧客意見箱 Modal / 按鈕 =========

class FeedbackModal(discord.ui.Modal, title="顧客意見箱"):
    feedback_content = discord.ui.TextInput(
        label="意見內容",
        placeholder="請輸入你的意見或建議",
        style=discord.TextStyle.paragraph,
        required=True,
        max_length=1500
    )

    async def on_submit(self, interaction: discord.Interaction):
        guild = interaction.guild

        if guild is None:
            await interaction.response.send_message("這個功能只能在伺服器內使用。", ephemeral=True)
            return

        receive_channel = guild.get_channel(COMPLAINT_RECEIVE_CHANNEL_ID)

        if receive_channel is None or not isinstance(receive_channel, discord.TextChannel):
            await interaction.response.send_message(
                "找不到意見接收頻道，請確認 COMPLAINT_RECEIVE_CHANNEL_ID 是否正確。",
                ephemeral=True
            )
            return

        boss_mention = interaction.user.mention
        boss_id = interaction.user.id

        embed = discord.Embed(
            title="顧客意見箱",
            description=(
                f"有一則來自 {boss_mention} 的顧客意見。\n"
                f"申請人 ID：{boss_id}\n\n"
                f"意見內容：\n{self.feedback_content.value}"
            ),
            color=discord.Color.blue()
        )

        await receive_channel.send(
            embed=embed,
            view=ComplaintResolveView(),
            allowed_mentions=discord.AllowedMentions(
                users=False,
                roles=False,
                everyone=False
            )
        )

        await interaction.response.send_message(
            "你的意見已送出，感謝闆闆回饋！",
            ephemeral=True
        )


class FeedbackPanelView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(
        label="填寫意見",
        style=discord.ButtonStyle.primary,
        custom_id="feedback_form_button"
    )
    async def feedback_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(FeedbackModal())


# ========= 下單 / 入職 Modal =========

class OrderModal(discord.ui.Modal, title="我要下單"):
    rule_confirm = discord.ui.TextInput(
        label="是否已詳閱規章內容",
        placeholder="請輸入：是",
        required=True,
        max_length=20
    )

    async def on_submit(self, interaction: discord.Interaction):
        if not is_agree_answer(self.rule_confirm.value):
            await interaction.response.send_message(
                "你尚未詳閱規章內容，暫時無法下單。請詳閱規章後再重新開單。",
                ephemeral=True
            )
            return

        guild = interaction.guild
        member = interaction.user

        if guild is None:
            await interaction.response.send_message("這個功能只能在伺服器內使用。", ephemeral=True)
            return

        customer_role = guild.get_role(CUSTOMER_ROLE_ID)

        intro = (
            f"這裡有闆闆開單。\n\n"
            f"開單人：{member.mention}\n"
            f"狀態：已確認詳閱規章內容"
            f"{format_customer_notes_for_ticket(member.id)}"
        )

        await create_private_channel(
            interaction=interaction,
            category_id=CUSTOMER_CATEGORY_ID,
            channel_name=safe_channel_name("下單", member),
            allowed_roles=[customer_role],
            intro_message=intro,
            view=OrderControlView(),
            topic=f"order_customer_id={member.id}"
        )


class RecruitModal(discord.ui.Modal, title="我要入職"):
    nickname = discord.ui.TextInput(
        label="暱稱",
        placeholder="請輸入你的暱稱",
        required=True,
        max_length=50
    )

    age = discord.ui.TextInput(
        label="年齡",
        placeholder="請輸入你的年齡",
        required=True,
        max_length=20
    )

    play_time = discord.ui.TextInput(
        label="可遊玩時段",
        placeholder="例如：平日晚上、假日整天",
        required=True,
        max_length=100
    )

    position = discord.ui.TextInput(
        label="應徵職位",
        placeholder="例如：陪玩、接待、客服、其他",
        required=True,
        max_length=100
    )

    async def on_submit(self, interaction: discord.Interaction):
        guild = interaction.guild
        member = interaction.user

        if guild is None:
            await interaction.response.send_message("這個功能只能在伺服器內使用。", ephemeral=True)
            return

        examiner_role = guild.get_role(EXAMINER_ROLE_ID)
        manager_role = guild.get_role(MANAGER_ROLE_ID)
        customer_role = guild.get_role(CUSTOMER_ROLE_ID)
        applicant_role = guild.get_role(RECRUIT_APPLICANT_ROLE_ID)

        if applicant_role is not None and isinstance(member, discord.Member):
            try:
                await member.add_roles(applicant_role, reason="Recruit ticket opened")
            except discord.Forbidden:
                print("Bot 權限不足，無法給予入職申請暫時身分組。請確認 Bot 身分組位置高於該身分組。")
            except discord.HTTPException as e:
                print(f"給予入職申請暫時身分組失敗：{e}")

        intro = (
            f"這裡有人想入職。\n\n"
            f"申請人：{member.mention}\n"
            f"暱稱：{self.nickname.value}\n"
            f"年齡：{self.age.value}\n"
            f"可遊玩時段：{self.play_time.value}\n"
            f"應徵職位：{self.position.value}"
        )

        await create_private_channel(
            interaction=interaction,
            category_id=EXAM_CATEGORY_ID,
            channel_name=safe_channel_name("入職", member),
            allowed_roles=[examiner_role, manager_role, customer_role],
            intro_message=intro,
            view=RecruitControlView(),
            topic=f"recruit_member_id={member.id};recruit_nickname={self.nickname.value};recruit_position={self.position.value}"
        )


# ========= 主面板下拉式清單 / 確認按鈕 =========

PANEL_SELECTIONS = {}


class MainPanelSelect(discord.ui.Select):
    def __init__(self):
        options = [
            discord.SelectOption(
                label="我要下單",
                value="order",
                description="開啟下單票口"
            ),
            discord.SelectOption(
                label="我要入職",
                value="recruit",
                description="開啟入職申請票口"
            ),
        ]

        super().__init__(
            placeholder="請選擇你要辦理的項目",
            min_values=1,
            max_values=1,
            options=options,
            custom_id="mawan_main_panel_select",
            row=0
        )

    async def callback(self, interaction: discord.Interaction):
        PANEL_SELECTIONS[interaction.user.id] = self.values[0]

        await interaction.response.defer()


class MainPanelView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(MainPanelSelect())

    @discord.ui.button(
        label="確認",
        style=discord.ButtonStyle.success,
        custom_id="mawan_main_panel_confirm",
        row=1
    )
    async def confirm_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        selected = PANEL_SELECTIONS.get(interaction.user.id)

        if selected is None:
            await interaction.response.send_message(
                "請先從下拉式清單選擇項目，再按確認。",
                ephemeral=True
            )
            return

        PANEL_SELECTIONS.pop(interaction.user.id, None)

        if selected == "order":
            await interaction.response.send_modal(OrderModal())
        elif selected == "recruit":
            await interaction.response.send_modal(RecruitModal())
        else:
            await interaction.response.send_message(
                "選擇項目異常，請重新選擇一次。",
                ephemeral=True
            )


# ========= Bot 事件 =========

@bot.event
async def on_member_join(member: discord.Member):
    role = member.guild.get_role(NEW_MEMBER_ROLE_ID)

    if role is not None:
        try:
            await member.add_roles(role, reason="新成員加入自動給予身分組")
        except discord.Forbidden:
            print("Bot 權限不足，無法給予新成員身分組。請確認 Bot 身分組位置高於要給的身分組。")
        except discord.HTTPException as e:
            print(f"給予新成員身分組失敗：{e}")
    else:
        print("找不到新成員身分組，請確認 NEW_MEMBER_ROLE_ID 是否正確")

    channel = member.guild.get_channel(WELCOME_CHANNEL_ID)

    if channel is None or not isinstance(channel, discord.TextChannel):
        print("找不到歡迎頻道，請確認 WELCOME_CHANNEL_ID 是否正確")
        return

    embed = discord.Embed(
        description=(
            f"**歡迎 {member.mention} 來到魔丸娛樂!**\n\n"
            f"歡迎闆闆光臨!\n"
            f"有任何問題都可以透過機器人開票口聯絡客服歐!"
        ),
        color=discord.Color.green()
    )

    embed.set_thumbnail(url=member.display_avatar.url)

    await channel.send(
        embed=embed,
        allowed_mentions=discord.AllowedMentions(
            users=True,
            roles=False,
            everyone=False
        )
    )


@bot.event
async def on_guild_channel_delete(channel: discord.abc.GuildChannel):
    # 如果入職票口被手動刪除，也嘗試收回申請人暫時身分組。
    await remove_recruit_applicant_role(channel.guild, channel)



@bot.event
async def on_voice_state_update(
    member: discord.Member,
    before: discord.VoiceState,
    after: discord.VoiceState
):
    guild = member.guild

    # 離開機器人建立的陪玩 / VIP / 公共語音房後，如果房間沒人就自動刪除
    # 這裡除了看暫存 ID，也會用頻道名稱判斷，避免 Bot 重開後忘記之前建立的臨時房。
    if before.channel is not None:
        is_temp_play_voice_room = (
            before.channel.id in TEMP_PLAY_VOICE_CHANNEL_IDS
            or (
                before.channel.category_id == PLAY_VOICE_CATEGORY_ID
                and before.channel.name.startswith("🎮┃")
                and before.channel.name.endswith("的陪玩頻道")
                and before.channel.name != PLAY_VOICE_CREATE_CHANNEL_NAME
            )
        )

        is_temp_vip_voice_room = (
            before.channel.id in TEMP_VIP_VOICE_CHANNEL_IDS
            or (
                before.channel.category_id == PLAY_VOICE_CATEGORY_ID
                and before.channel.name.startswith("👑┃")
                and before.channel.name.endswith("的𝙑𝙄𝙋頻道")
                and before.channel.name != VIP_VOICE_CREATE_CHANNEL_NAME
            )
        )

        is_temp_public_voice_room = (
            before.channel.id in TEMP_PUBLIC_VOICE_CHANNEL_IDS
            or (
                before.channel.category_id == PLAY_VOICE_CATEGORY_ID
                and before.channel.name.startswith("➕┃")
                and before.channel.name.endswith("的公共房間")
                and before.channel.name != PUBLIC_VOICE_CREATE_CHANNEL_NAME
            )
        )

        if is_temp_play_voice_room and len(before.channel.members) == 0:
            TEMP_PLAY_VOICE_CHANNEL_IDS.discard(before.channel.id)
            await delete_voice_control_panel(guild, before.channel.id)
            try:
                await before.channel.delete(reason="Temporary play voice room is empty")
            except discord.NotFound:
                pass
            except discord.Forbidden:
                print("Bot 權限不足，無法刪除陪玩語音房。")
            except discord.HTTPException as e:
                print(f"刪除陪玩語音房失敗：{e}")
            return

        if is_temp_vip_voice_room and len(before.channel.members) == 0:
            TEMP_VIP_VOICE_CHANNEL_IDS.discard(before.channel.id)
            await delete_voice_control_panel(guild, before.channel.id)
            try:
                await before.channel.delete(reason="Temporary VIP voice room is empty")
            except discord.NotFound:
                pass
            except discord.Forbidden:
                print("Bot 權限不足，無法刪除 VIP 語音房。")
            except discord.HTTPException as e:
                print(f"刪除 VIP 語音房失敗：{e}")
            return

        if is_temp_public_voice_room and len(before.channel.members) == 0:
            TEMP_PUBLIC_VOICE_CHANNEL_IDS.discard(before.channel.id)
            await delete_voice_control_panel(guild, before.channel.id)
            try:
                await before.channel.delete(reason="Temporary public voice room is empty")
            except discord.NotFound:
                pass
            except discord.Forbidden:
                print("Bot 權限不足，無法刪除公共語音房。")
            except discord.HTTPException as e:
                print(f"刪除公共語音房失敗：{e}")
            return

    # 沒有加入新語音頻道就不用處理
    if after.channel is None:
        return

    category = guild.get_channel(PLAY_VOICE_CATEGORY_ID)

    if category is None or not isinstance(category, discord.CategoryChannel):
        return

    # 取得或建立兩種入口語音頻道
    play_lobby_channel = await get_or_create_play_voice_lobby(guild)
    vip_lobby_channel = await get_or_create_vip_voice_lobby(guild)
    public_lobby_channel = await get_or_create_public_voice_lobby(guild)

    # 進入一般陪玩入口：建立一般陪玩語音房
    if play_lobby_channel is not None and after.channel.id == play_lobby_channel.id:
        try:
            overwrites = build_play_voice_overwrites(guild)
            overwrites[member] = build_creator_voice_overwrite()

            new_channel = await guild.create_voice_channel(
                name=safe_voice_channel_name(member),
                category=category,
                overwrites=overwrites,
                reason=f"Temporary play voice room created by {member}"
            )
            TEMP_PLAY_VOICE_CHANNEL_IDS.add(new_channel.id)

            await create_voice_control_panel(
                guild=guild,
                category=category,
                member=member,
                voice_channel=new_channel,
                room_type="play"
            )

            await member.move_to(
                new_channel,
                reason="Move member to created play voice room"
            )
        except discord.Forbidden:
            print("Bot 權限不足，無法建立或移動陪玩語音房。")
        except discord.HTTPException as e:
            print(f"建立或移動陪玩語音房失敗：{e}")

        return

    # 進入 VIP 入口：建立 VIP 專用語音房
    if vip_lobby_channel is not None and after.channel.id == vip_lobby_channel.id:
        try:
            new_channel = await guild.create_voice_channel(
                name=safe_vip_voice_channel_name(member),
                category=category,
                overwrites=build_vip_room_overwrites(guild, member),
                reason=f"Temporary VIP voice room created by {member}"
            )
            TEMP_VIP_VOICE_CHANNEL_IDS.add(new_channel.id)

            await create_voice_control_panel(
                guild=guild,
                category=category,
                member=member,
                voice_channel=new_channel,
                room_type="vip"
            )

            await member.move_to(
                new_channel,
                reason="Move member to created VIP voice room"
            )
        except discord.Forbidden:
            print("Bot 權限不足，無法建立或移動 VIP 語音房。")
        except discord.HTTPException as e:
            print(f"建立或移動 VIP 語音房失敗：{e}")

        return

    # 進入公共入口：建立所有人可見 / 可加入的公共語音房
    if public_lobby_channel is not None and after.channel.id == public_lobby_channel.id:
        try:
            overwrites = build_public_voice_overwrites(guild)
            overwrites[member] = build_creator_voice_overwrite()

            new_channel = await guild.create_voice_channel(
                name=safe_public_voice_channel_name(member),
                category=category,
                overwrites=overwrites,
                reason=f"Temporary public voice room created by {member}"
            )
            TEMP_PUBLIC_VOICE_CHANNEL_IDS.add(new_channel.id)

            await create_voice_control_panel(
                guild=guild,
                category=category,
                member=member,
                voice_channel=new_channel,
                room_type="public"
            )

            await member.move_to(
                new_channel,
                reason="Move member to created public voice room"
            )
        except discord.Forbidden:
            print("Bot 權限不足，無法建立或移動公共語音房。")
        except discord.HTTPException as e:
            print(f"建立或移動公共語音房失敗：{e}")

        return

@bot.event
async def on_ready():
    global BACKUP_TASK_STARTED, STORED_REMINDER_TASK_STARTED
    bot.add_view(MainPanelView())
    bot.add_view(OrderControlView())
    bot.add_view(StaffOrderOperationView())
    bot.add_view(RecruitControlView())
    bot.add_view(ComplaintPanelView())
    bot.add_view(FeedbackPanelView())
    bot.add_view(ComplaintResolveView())

    restored_dispatch_views = 0
    for message_id in list(ORDER_CLAIMS.keys()):
        view = get_dispatch_claim_view_from_data(message_id)
        if view is None:
            continue

        try:
            bot.add_view(view, message_id=message_id)
            restored_dispatch_views += 1
        except ValueError:
            pass

    if restored_dispatch_views:
        print(f"Restored dispatch claim views: {restored_dispatch_views}")

    guild_for_voice = bot.get_guild(GUILD_ID)
    if guild_for_voice is not None:
        await get_or_create_order_log_channel(guild_for_voice)
        if not BACKUP_TASK_STARTED:
            BACKUP_TASK_STARTED = True
            asyncio.create_task(daily_backup_loop())
        if not STORED_REMINDER_TASK_STARTED:
            STORED_REMINDER_TASK_STARTED = True
            asyncio.create_task(stored_order_reminder_loop())
        try:
            await get_or_create_play_voice_lobby(guild_for_voice)
            await get_or_create_vip_voice_lobby(guild_for_voice)
            await get_or_create_public_voice_lobby(guild_for_voice)
        except discord.Forbidden:
            print("Bot 權限不足，無法建立陪玩 / VIP / 公共語音入口。")
        except discord.HTTPException as e:
            print(f"建立陪玩 / VIP / 公共語音入口失敗：{e}")

    try:
        guild = discord.Object(id=GUILD_ID)
        synced = await bot.tree.sync(guild=guild)
        print(f"Slash commands synced: {len(synced)}")
    except Exception as e:
        print(f"Sync error: {e}")

    print(f"Logged in as {bot.user}")


# ========= Slash 指令 =========



# ========= 點數抽獎系統 =========

LOTTERY_COST_PER_CHANCE_DEFAULT = 5
LOTTERY_MAX_CHANCES_PER_USER_DEFAULT = 20


def get_default_lottery_period() -> str:
    return get_taipei_now().strftime("%Y-%m")


def get_lottery_settings() -> dict:
    init_database()
    default = {
        "period": get_default_lottery_period(),
        "title": "魔丸點數抽獎",
        "note": "獎品由管理層討論後設定。",
        "prizes": "獎池尚未設定，請等待管理層公告。",
        "status": "open",
        "cost_per_chance": LOTTERY_COST_PER_CHANCE_DEFAULT,
        "max_chances_per_user": LOTTERY_MAX_CHANCES_PER_USER_DEFAULT,
        "updated_at": get_taipei_now_iso(),
    }

    try:
        with sqlite3.connect(DB_FILE) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute("SELECT data FROM lottery_settings WHERE key='current'").fetchone()
    except sqlite3.Error as e:
        print(f"讀取抽獎設定失敗：{e}")
        return default

    if row is None:
        save_lottery_settings(default)
        return default

    try:
        data = json.loads(row["data"])
    except json.JSONDecodeError:
        return default

    for key, value in default.items():
        data.setdefault(key, value)

    return data


def save_lottery_settings(data: dict) -> None:
    init_database()
    data["updated_at"] = get_taipei_now_iso()
    try:
        with sqlite3.connect(DB_FILE) as conn:
            conn.execute(
                "INSERT OR REPLACE INTO lottery_settings (key, data, updated_at) VALUES (?, ?, ?)",
                ("current", json.dumps(data, ensure_ascii=False), data["updated_at"]),
            )
            conn.commit()
    except sqlite3.Error as e:
        print(f"保存抽獎設定失敗：{e}")


def get_lottery_entries(period: str) -> list[dict]:
    init_database()
    try:
        with sqlite3.connect(DB_FILE) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                """
                SELECT user_id, chances, points_used, updated_at
                FROM lottery_entries
                WHERE period=? AND chances > 0
                ORDER BY chances DESC, updated_at ASC
                """,
                (period,),
            ).fetchall()
    except sqlite3.Error as e:
        print(f"讀取抽獎池失敗：{e}")
        return []

    return [
        {
            "user_id": int(row["user_id"]),
            "chances": int(row["chances"]),
            "points_used": int(row["points_used"]),
            "updated_at": row["updated_at"],
        }
        for row in rows
    ]


def get_lottery_entry(period: str, user_id: int) -> dict | None:
    init_database()
    try:
        with sqlite3.connect(DB_FILE) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT user_id, chances, points_used, updated_at FROM lottery_entries WHERE period=? AND user_id=?",
                (period, user_id),
            ).fetchone()
    except sqlite3.Error as e:
        print(f"讀取抽獎報名資料失敗：{e}")
        return None

    if row is None:
        return None

    return {
        "user_id": int(row["user_id"]),
        "chances": int(row["chances"]),
        "points_used": int(row["points_used"]),
        "updated_at": row["updated_at"],
    }


def upsert_lottery_entry(period: str, user_id: int, chances_delta: int, points_delta: int) -> None:
    init_database()
    now_text = get_taipei_now_iso()
    current = get_lottery_entry(period, user_id)
    new_chances = chances_delta if current is None else int(current["chances"]) + chances_delta
    new_points_used = points_delta if current is None else int(current["points_used"]) + points_delta

    try:
        with sqlite3.connect(DB_FILE) as conn:
            if new_chances <= 0:
                conn.execute("DELETE FROM lottery_entries WHERE period=? AND user_id=?", (period, user_id))
            else:
                conn.execute(
                    """
                    INSERT OR REPLACE INTO lottery_entries (period, user_id, chances, points_used, updated_at)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (period, user_id, new_chances, max(new_points_used, 0), now_text),
                )
            conn.commit()
    except sqlite3.Error as e:
        print(f"更新抽獎報名資料失敗：{e}")


def clear_lottery_entries(period: str) -> None:
    init_database()
    try:
        with sqlite3.connect(DB_FILE) as conn:
            conn.execute("DELETE FROM lottery_entries WHERE period=?", (period,))
            conn.commit()
    except sqlite3.Error as e:
        print(f"清空抽獎池失敗：{e}")


def record_lottery_draw(period: str, prize: str, winner_id: int, drawn_by: int) -> None:
    init_database()
    try:
        with sqlite3.connect(DB_FILE) as conn:
            conn.execute(
                """
                INSERT INTO lottery_draws (period, prize, winner_id, drawn_by, drawn_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (period, prize, winner_id, drawn_by, get_taipei_now_iso()),
            )
            conn.commit()
    except sqlite3.Error as e:
        print(f"保存抽獎結果失敗：{e}")


def build_lottery_info_embed(settings: dict) -> discord.Embed:
    period = str(settings.get("period", get_default_lottery_period()))
    entries = get_lottery_entries(period)
    total_chances = sum(int(row["chances"]) for row in entries)
    participant_count = len(entries)
    cost = int(settings.get("cost_per_chance", LOTTERY_COST_PER_CHANCE_DEFAULT))
    max_chances = int(settings.get("max_chances_per_user", LOTTERY_MAX_CHANCES_PER_USER_DEFAULT))
    status_text = "開放報名" if settings.get("status") == "open" else "已關閉"

    embed = discord.Embed(
        title=str(settings.get("title") or "魔丸點數抽獎"),
        color=discord.Color.gold(),
    )
    embed.add_field(name="本期", value=period, inline=True)
    embed.add_field(name="狀態", value=status_text, inline=True)
    embed.add_field(name="規則", value=f"{cost} 點 = 1 次抽獎機會\n每人本期最多 {max_chances} 次", inline=False)
    embed.add_field(name="目前抽獎池", value=f"參與人數：{participant_count} 人\n總抽獎次數：{total_chances} 次", inline=False)
    prizes = str(settings.get("prizes") or "獎池尚未設定，請等待管理層公告。")
    embed.add_field(name="獎池內容", value=prizes[:1000], inline=False)

    note = str(settings.get("note") or "獎品由管理層討論後設定。")
    embed.add_field(name="活動備註", value=note[:1000], inline=False)
    return embed


def build_lottery_status_embed(settings: dict) -> discord.Embed:
    period = str(settings.get("period", get_default_lottery_period()))
    entries = get_lottery_entries(period)
    total_chances = sum(int(row["chances"]) for row in entries)

    embed = build_lottery_info_embed(settings)
    embed.title = f"抽獎池狀態｜{period}"

    if not entries:
        embed.add_field(name="參加名單", value="目前沒有人參加。", inline=False)
        return embed

    lines = []
    for index, row in enumerate(entries[:20], start=1):
        chance_rate = (int(row["chances"]) / total_chances * 100) if total_chances else 0
        lines.append(f"{index}. <@{row['user_id']}>｜{row['chances']} 次｜約 {chance_rate:.1f}%")

    if len(entries) > 20:
        lines.append(f"...另有 {len(entries) - 20} 人")

    embed.add_field(name="參加名單", value="\n".join(lines), inline=False)
    return embed


def pick_weighted_lottery_winners(entries: list[dict], winners: int) -> list[int]:
    pool = [dict(row) for row in entries if int(row.get("chances", 0)) > 0]
    picked: list[int] = []

    for _ in range(max(winners, 0)):
        if not pool:
            break

        total_weight = sum(int(row["chances"]) for row in pool)
        if total_weight <= 0:
            break

        ticket = random.randint(1, total_weight)
        running = 0
        chosen_index = 0

        for index, row in enumerate(pool):
            running += int(row["chances"])
            if ticket <= running:
                chosen_index = index
                break

        winner = pool.pop(chosen_index)
        picked.append(int(winner["user_id"]))

    return picked


def is_lottery_admin(member: discord.Member) -> bool:
    return is_customer_staff(member) or has_role(member, MANAGER_ROLE_ID) or member.guild_permissions.administrator


@bot.tree.command(
    name="lottery_info",
    description="查看目前魔丸點數抽獎活動",
    guild=discord.Object(id=GUILD_ID)
)
async def lottery_info(interaction: discord.Interaction):
    settings = get_lottery_settings()
    await interaction.response.send_message(embed=build_lottery_info_embed(settings), ephemeral=True)


@bot.tree.command(
    name="join_lottery",
    description="使用魔丸點數參加抽獎，5 點 = 1 次抽獎機會",
    guild=discord.Object(id=GUILD_ID)
)
@app_commands.describe(chances="要參加幾次抽獎，每次會消耗 5 點")
async def join_lottery(interaction: discord.Interaction, chances: int):
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


@bot.tree.command(
    name="lottery_status",
    description="客服查看目前抽獎池狀態",
    guild=discord.Object(id=GUILD_ID)
)
async def lottery_status(interaction: discord.Interaction):
    if not isinstance(interaction.user, discord.Member) or not is_lottery_admin(interaction.user):
        await interaction.response.send_message("只有客服、店長或管理員可以查看抽獎池。", ephemeral=True)
        return

    settings = get_lottery_settings()
    await interaction.response.send_message(embed=build_lottery_status_embed(settings), ephemeral=True)


@bot.tree.command(
    name="lottery_open",
    description="管理層設定或開啟本期點數抽獎",
    guild=discord.Object(id=GUILD_ID)
)
@app_commands.describe(
    period="期別，例如 2026-05；不填則使用本月",
    title="抽獎活動名稱，可不填",
    note="活動備註，可先寫：獎品內部討論中",
    max_chances_per_user="每人本期最多可投入幾次，預設 20",
    announce_channel="抽獎開始公告要發到哪個頻道；不填則用預設公告頻道"
)
async def lottery_open(
    interaction: discord.Interaction,
    period: str | None = None,
    title: str | None = None,
    note: str | None = None,
    max_chances_per_user: int | None = None,
    announce_channel: discord.TextChannel | None = None,
):
    if not isinstance(interaction.user, discord.Member) or not is_lottery_admin(interaction.user):
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


@bot.tree.command(
    name="lottery_set_prizes",
    description="管理層設定本期抽獎獎池內容",
    guild=discord.Object(id=GUILD_ID)
)
@app_commands.describe(
    prizes="獎池內容，例如：一獎：500T折抵券 x1｜二獎：指定費免費 x2",
    announce="是否發公告，預設否",
    announce_channel="獎池公告要發到哪個頻道；不填則用預設公告頻道"
)
async def lottery_set_prizes(
    interaction: discord.Interaction,
    prizes: str,
    announce: bool = False,
    announce_channel: discord.TextChannel | None = None,
):
    if not isinstance(interaction.user, discord.Member) or not is_lottery_admin(interaction.user):
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


@bot.tree.command(
    name="lottery_close",
    description="管理層關閉本期抽獎報名",
    guild=discord.Object(id=GUILD_ID)
)
async def lottery_close(interaction: discord.Interaction):
    if not isinstance(interaction.user, discord.Member) or not is_lottery_admin(interaction.user):
        await interaction.response.send_message("只有客服、店長或管理員可以關閉抽獎。", ephemeral=True)
        return

    settings = get_lottery_settings()
    settings["status"] = "closed"
    save_lottery_settings(settings)
    await interaction.response.send_message(f"已關閉 **{settings['period']}** 抽獎報名。", ephemeral=True)


@bot.tree.command(
    name="draw_lottery",
    description="客服開獎；可依照已設定獎池輸入本次要抽的獎品",
    guild=discord.Object(id=GUILD_ID)
)
@app_commands.describe(
    prize="本次要抽的獎品名稱，例如 一獎：500T折抵券",
    winners="要抽出幾位得主，預設 1",
    announce_channel="開獎公告要發到哪個頻道；不填則用預設公告頻道"
)
async def draw_lottery(
    interaction: discord.Interaction,
    prize: str,
    winners: int = 1,
    announce_channel: discord.TextChannel | None = None,
):
    if not isinstance(interaction.user, discord.Member) or not is_lottery_admin(interaction.user):
        await interaction.response.send_message("只有客服、店長或管理員可以開獎。", ephemeral=True)
        return

    if winners <= 0:
        await interaction.response.send_message("得獎人數必須大於 0。", ephemeral=True)
        return

    settings = get_lottery_settings()
    period = str(settings.get("period", get_default_lottery_period()))
    entries = get_lottery_entries(period)

    if not entries:
        await interaction.response.send_message("目前抽獎池沒有人參加，無法開獎。", ephemeral=True)
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


@bot.tree.command(
    name="cancel_lottery_entry",
    description="客服取消顧客本期抽獎報名並退還點數",
    guild=discord.Object(id=GUILD_ID)
)
@app_commands.describe(customer="要取消報名的顧客", reason="取消原因，可不填")
async def cancel_lottery_entry(interaction: discord.Interaction, customer: discord.Member, reason: str | None = None):
    if not isinstance(interaction.user, discord.Member) or not is_lottery_admin(interaction.user):
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


@bot.tree.command(
    name="reset_lottery",
    description="清空本期抽獎池，不自動退點。需輸入確認文字",
    guild=discord.Object(id=GUILD_ID)
)
@app_commands.describe(confirm_text="請輸入：確認清空", reason="清空原因，可不填")
async def reset_lottery(interaction: discord.Interaction, confirm_text: str, reason: str | None = None):
    if not isinstance(interaction.user, discord.Member) or not is_lottery_admin(interaction.user):
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


@bot.tree.command(
    name="my_points",
    description="查詢自己的魔丸會員資料",
    guild=discord.Object(id=GUILD_ID)
)
async def my_points(interaction: discord.Interaction):
    data = get_customer_reward_data(interaction.user.id)
    embed = build_member_info_embed(interaction.user, data, show_points=True)
    await interaction.response.send_message(embed=embed, ephemeral=True)


@bot.tree.command(
    name="customer_points",
    description="客服查詢指定顧客的魔丸會員資料",
    guild=discord.Object(id=GUILD_ID)
)
@app_commands.describe(customer="要查詢的顧客")
async def customer_points(interaction: discord.Interaction, customer: discord.Member):
    if not isinstance(interaction.user, discord.Member):
        await interaction.response.send_message("無法確認你的身分組。", ephemeral=True)
        return

    if not is_customer_staff(interaction.user) and not has_role(interaction.user, MANAGER_ROLE_ID):
        await interaction.response.send_message("只有客服或店長可以查詢顧客會員資料。", ephemeral=True)
        return

    data = get_customer_reward_data(customer.id)
    embed = build_member_info_embed(customer, data, show_points=True)
    embed.title = "顧客會員資料"
    await interaction.response.send_message(embed=embed, ephemeral=True)



@bot.tree.command(
    name="adjust_points",
    description="客服調整顧客魔丸點數，可輸入正數加點或負數扣點",
    guild=discord.Object(id=GUILD_ID)
)
@app_commands.describe(
    customer="要調整點數的顧客",
    points="調整點數，正數為加點，負數為扣點，例如 10 或 -10",
    reason="調整原因，可不填"
)
async def adjust_points(
    interaction: discord.Interaction,
    customer: discord.Member,
    points: int,
    reason: str | None = None,
):
    if not isinstance(interaction.user, discord.Member):
        await interaction.response.send_message("無法確認你的身分組。", ephemeral=True)
        return

    if not is_customer_staff(interaction.user) and not has_role(interaction.user, MANAGER_ROLE_ID):
        await interaction.response.send_message("只有客服或店長可以調整顧客點數。", ephemeral=True)
        return

    ok, message = await adjust_customer_points(
        customer_id=customer.id,
        delta_points=points,
        operator_id=interaction.user.id,
        reason=reason,
    )

    if ok:
        await send_order_log(
            interaction.guild,
            title="會員點數已調整",
            fields=[
                ("顧客", customer.mention, True),
                ("操作人員", interaction.user.mention, True),
                ("點數變動", f"{points:+,} 點", True),
                ("原因", reason or "未填寫", False),
            ],
            color=discord.Color.orange(),
        )

    await interaction.response.send_message(message, ephemeral=True)


@bot.tree.command(
    name="add_purchase",
    description="客服補登單筆顧客歷史消費",
    guild=discord.Object(id=GUILD_ID)
)
@app_commands.describe(
    customer="要補登的顧客",
    amount="消費金額，例如 900",
    date="完成日期，例如 20260512、2026/05/12 或 2026-05-12",
    note="備註，可不填"
)
async def add_purchase(
    interaction: discord.Interaction,
    customer: discord.Member,
    amount: int,
    date: str,
    note: str | None = None,
):
    if not isinstance(interaction.user, discord.Member):
        await interaction.response.send_message("無法確認你的身分組。", ephemeral=True)
        return

    if not is_customer_staff(interaction.user) and not has_role(interaction.user, MANAGER_ROLE_ID):
        await interaction.response.send_message("只有客服或店長可以補登會員消費。", ephemeral=True)
        return

    guild = interaction.guild
    if guild is None:
        await interaction.response.send_message("這個功能只能在伺服器內使用。", ephemeral=True)
        return

    ok, message = await add_manual_purchase(
        guild=guild,
        customer_id=customer.id,
        amount=amount,
        date_text=date,
        operator_id=interaction.user.id,
        note=note,
    )

    if ok:
        await send_order_log(
            guild,
            title="歷史消費已補登",
            fields=[
                ("顧客", customer.mention, True),
                ("操作人員", interaction.user.mention, True),
                ("金額", format_t_amount(amount), True),
                ("日期", date, True),
                ("備註", note or "未填寫", False),
            ],
            color=discord.Color.blue(),
        )

    await interaction.response.send_message(message, ephemeral=True)


@bot.tree.command(
    name="import_purchases",
    description="客服批量補登歷史消費，多行格式：顧客ID,金額,日期,備註",
    guild=discord.Object(id=GUILD_ID)
)
@app_commands.describe(
    records="每行一筆：顧客ID,金額,日期,備註；備註可省略"
)
async def import_purchases(interaction: discord.Interaction, records: str):
    if not isinstance(interaction.user, discord.Member):
        await interaction.response.send_message("無法確認你的身分組。", ephemeral=True)
        return

    if not is_customer_staff(interaction.user) and not has_role(interaction.user, MANAGER_ROLE_ID):
        await interaction.response.send_message("只有客服或店長可以批量補登會員消費。", ephemeral=True)
        return

    guild = interaction.guild
    if guild is None:
        await interaction.response.send_message("這個功能只能在伺服器內使用。", ephemeral=True)
        return

    await interaction.response.defer(ephemeral=True, thinking=True)

    success_count = 0
    skipped_count = 0
    result_lines = []

    for line_number, raw_line in enumerate(records.splitlines(), start=1):
        line = raw_line.strip()
        if not line:
            continue

        parts = [part.strip() for part in line.split(",")]
        if len(parts) < 3:
            skipped_count += 1
            result_lines.append(f"第 {line_number} 行失敗：格式不足，請用 顧客ID,金額,日期,備註")
            continue

        customer_text, amount_text, date_text = parts[0], parts[1], parts[2]
        note = ",".join(parts[3:]).strip() if len(parts) >= 4 else None
        customer_text = customer_text.replace("<@", "").replace(">", "").replace("!", "")

        try:
            customer_id = int(customer_text)
            amount = int(amount_text.replace("T", "").replace("t", "").replace(",", ""))
        except ValueError:
            skipped_count += 1
            result_lines.append(f"第 {line_number} 行失敗：顧客 ID 或金額不是數字。")
            continue

        ok, message = await add_manual_purchase(
            guild=guild,
            customer_id=customer_id,
            amount=amount,
            date_text=date_text,
            operator_id=interaction.user.id,
            note=note,
        )

        if ok:
            success_count += 1
        else:
            skipped_count += 1

        result_lines.append(message)

    summary = f"批量補登完成：成功 {success_count} 筆，跳過/失敗 {skipped_count} 筆。"
    detail = "\n".join(result_lines)
    if len(detail) > 1700:
        detail = detail[:1700] + "\n...（結果太長，已截斷）"

    await interaction.followup.send(f"{summary}\n\n{detail}", ephemeral=True)



@bot.tree.command(
    name="set_customer_rewards",
    description="管理員手動修正顧客會員資料",
    guild=discord.Object(id=GUILD_ID)
)
@app_commands.describe(
    customer="要修正的顧客",
    total_spent="累積消費總額，不填則不修改",
    order_count="完成訂單數，不填則不修改",
    last_order_date="最後下單日期，例如 20260512、2026/05/12；不填則不修改",
    point_adjustment="額外點數修正值，可正可負；不填則不修改",
    reason="修正原因，可不填"
)
async def set_customer_rewards(
    interaction: discord.Interaction,
    customer: discord.Member,
    total_spent: int | None = None,
    order_count: int | None = None,
    last_order_date: str | None = None,
    point_adjustment: int | None = None,
    reason: str | None = None,
):
    if not isinstance(interaction.user, discord.Member):
        await interaction.response.send_message("無法確認你的身分組。", ephemeral=True)
        return

    if not is_manager_or_admin(interaction.user):
        await interaction.response.send_message("只有管理員或店長可以手動修正顧客會員資料。", ephemeral=True)
        return

    if total_spent is None and order_count is None and last_order_date is None and point_adjustment is None:
        await interaction.response.send_message("請至少填一個要修正的欄位。", ephemeral=True)
        return

    if total_spent is not None and total_spent < 0:
        await interaction.response.send_message("累積消費不能小於 0。", ephemeral=True)
        return

    if order_count is not None and order_count < 0:
        await interaction.response.send_message("完成訂單數不能小於 0。", ephemeral=True)
        return

    date_iso = None
    display_date = None
    if last_order_date is not None:
        date_iso, display_date = parse_manual_purchase_date(last_order_date)
        if date_iso is None:
            await interaction.response.send_message("最後下單日期格式錯誤，請用 20260512、2026/05/12 或 2026-05-12。", ephemeral=True)
            return

    data = get_customer_reward_data(customer.id)
    before_embed = build_member_info_embed(customer, data, show_points=True)

    if total_spent is not None:
        data["total_spent"] = total_spent
    if order_count is not None:
        data["order_count"] = order_count
    if date_iso is not None:
        data["last_order_at"] = date_iso
    if point_adjustment is not None:
        data["point_adjustment"] = point_adjustment

    data["points"] = get_current_reward_points(data)
    data["last_manual_fixed_at"] = get_taipei_now_iso()
    data["last_manual_fixed_by"] = interaction.user.id
    data["last_manual_fixed_reason"] = (reason or "").strip()
    CUSTOMER_REWARDS[customer.id] = data

    benefit_notices = await ensure_reward_member_benefits(interaction.guild, customer, data) if interaction.guild else []
    save_bot_data()

    after_embed = build_member_info_embed(customer, data, show_points=True)
    after_embed.title = "顧客會員資料已修正"
    if reason:
        after_embed.add_field(name="修正原因", value=reason, inline=False)
    if benefit_notices:
        after_embed.add_field(name="會員權益處理", value="\n".join(benefit_notices), inline=False)

    await send_order_log(
        interaction.guild,
        title="顧客會員資料已手動修正",
        fields=[
            ("顧客", customer.mention, True),
            ("操作人員", interaction.user.mention, True),
            ("累積消費", format_t_amount(int(data.get("total_spent", 0) or 0)), True),
            ("完成訂單", f"{int(data.get('order_count', 0) or 0)} 單", True),
            ("目前點數", f"{get_current_reward_points(data):,} 點", True),
            ("原因", reason or "未填寫", False),
        ],
        color=discord.Color.orange(),
    )

    await interaction.response.send_message(embed=after_embed, ephemeral=True)



def _parse_iso_datetime_safely(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(str(value))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone(timedelta(hours=8)))
    return dt


def _get_order_closed_time(data: dict) -> datetime | None:
    return (
        _parse_iso_datetime_safely(data.get("closed_at"))
        or _parse_iso_datetime_safely(data.get("reward_counted_at"))
        or _parse_iso_datetime_safely(data.get("updated_at"))
    )


def _get_order_amount_for_stats(data: dict) -> int:
    for key in ("reward_amount", "amount", "total_amount"):
        value = data.get(key)
        if value is None:
            continue
        try:
            return int(value)
        except (TypeError, ValueError):
            parsed = parse_receipt_amount(str(value))
            if parsed is not None:
                return parsed
    return 0


def _is_closed_order_for_stats(data: dict) -> bool:
    return bool(data.get("closed")) or str(data.get("status", "")).lower() == "closed"


def _is_stored_order_for_stats(data: dict) -> bool:
    return str(data.get("status", "")).lower() == "stored"


def _is_cancelled_order_for_stats(data: dict) -> bool:
    return str(data.get("status", "")).lower() in {"cancelled", "canceled"}


def _normalize_stats_datetime_text(value: str | None) -> str | None:
    if not value:
        return None
    dt = _parse_iso_datetime_safely(str(value))
    if dt is None:
        # 支援 YYYYMMDD 這種舊補登日期
        text = str(value).strip()
        if len(text) == 8 and text.isdigit():
            return f"{text[0:4]}-{text[4:6]}-{text[6:8]}T00:00:00+08:00"
        return None
    return dt.isoformat(timespec="seconds")


def _get_sales_stats_from_sqlite(start_dt: datetime, end_dt: datetime) -> tuple[int, int, int, int]:
    """直接從 SQLite 統計營收，並相容兩種資料：
    1. 目前 Bot 使用的 JSON blob orders.data
    2. 舊營業額補登用的 relational/manual_revenue 資料
    回傳：完成訂單數、營收、目前存單數、目前取消單數
    """
    init_database()
    start_text = start_dt.isoformat(timespec="seconds")
    end_text = end_dt.isoformat(timespec="seconds")

    completed_count = 0
    total_revenue = 0
    stored_count = 0
    cancelled_count = 0

    try:
        with sqlite3.connect(DB_FILE) as conn:
            conn.row_factory = sqlite3.Row
            cur = conn.cursor()

            table_names = {
                row[0]
                for row in cur.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
            }

            if "orders" in table_names:
                order_columns = {
                    row[1]
                    for row in cur.execute("PRAGMA table_info(orders)").fetchall()
                }

                # 新版 SQLite 過渡資料表：orders(channel_id, data, updated_at)
                if "data" in order_columns:
                    for row in cur.execute("SELECT data FROM orders").fetchall():
                        try:
                            data = json.loads(row["data"])
                        except (TypeError, json.JSONDecodeError):
                            continue
                        if not isinstance(data, dict):
                            continue

                        if _is_stored_order_for_stats(data):
                            stored_count += 1
                        if _is_cancelled_order_for_stats(data):
                            cancelled_count += 1
                        if not _is_closed_order_for_stats(data):
                            continue

                        closed_text = _normalize_stats_datetime_text(
                            data.get("closed_at") or data.get("reward_counted_at") or data.get("updated_at")
                        )
                        if closed_text is None or not (start_text <= closed_text < end_text):
                            continue

                        completed_count += 1
                        total_revenue += _get_order_amount_for_stats(data)

                # 舊補登或正式 relational orders：orders(... amount/status/closed_at ...)
                if {"amount", "status"}.issubset(order_columns):
                    date_column = "closed_at" if "closed_at" in order_columns else "created_at"

                    if date_column in order_columns:
                        query = f"""
                            SELECT COUNT(*) AS count_value, COALESCE(SUM(amount), 0) AS revenue_value
                            FROM orders
                            WHERE status = 'closed'
                              AND {date_column} >= ?
                              AND {date_column} < ?
                        """
                        row = cur.execute(query, (start_text, end_text)).fetchone()
                        completed_count += int(row["count_value"] or 0)
                        total_revenue += int(row["revenue_value"] or 0)

                    stored_row = cur.execute("SELECT COUNT(*) AS c FROM orders WHERE status = 'stored'").fetchone()
                    cancelled_row = cur.execute("SELECT COUNT(*) AS c FROM orders WHERE status IN ('cancelled', 'canceled')").fetchone()
                    stored_count += int(stored_row["c"] or 0)
                    cancelled_count += int(cancelled_row["c"] or 0)

            # 建議之後舊營業額統一補進 manual_revenue，避免跟正式 orders 混在一起。
            if "manual_revenue" in table_names:
                manual_columns = {
                    row[1]
                    for row in cur.execute("PRAGMA table_info(manual_revenue)").fetchall()
                }
                if {"date_text", "amount", "status"}.issubset(manual_columns):
                    row = cur.execute(
                        """
                        SELECT COUNT(*) AS count_value, COALESCE(SUM(amount), 0) AS revenue_value
                        FROM manual_revenue
                        WHERE status = 'closed'
                          AND date_text >= ?
                          AND date_text < ?
                        """,
                        (start_text[:10], end_text[:10]),
                    ).fetchone()
                    completed_count += int(row["count_value"] or 0)
                    total_revenue += int(row["revenue_value"] or 0)

                    stored_row = cur.execute("SELECT COUNT(*) AS c FROM manual_revenue WHERE status = 'stored'").fetchone()
                    cancelled_row = cur.execute("SELECT COUNT(*) AS c FROM manual_revenue WHERE status IN ('cancelled', 'canceled')").fetchone()
                    stored_count += int(stored_row["c"] or 0)
                    cancelled_count += int(cancelled_row["c"] or 0)

    except sqlite3.Error as e:
        print(f"讀取 SQLite 統計失敗：{e}")

    return completed_count, total_revenue, stored_count, cancelled_count


def build_sales_stats_embed(title: str, start_dt: datetime, end_dt: datetime) -> discord.Embed:
    completed_count, total_revenue, stored_count, cancelled_count = _get_sales_stats_from_sqlite(start_dt, end_dt)
    avg_order = total_revenue // completed_count if completed_count else 0

    embed = discord.Embed(
        title=title,
        color=discord.Color.green(),
        timestamp=get_taipei_now(),
    )
    embed.add_field(name="完成訂單數", value=f"{completed_count:,} 單", inline=True)
    embed.add_field(name="營收", value=format_t_amount(total_revenue), inline=True)
    embed.add_field(name="平均客單價", value=format_t_amount(avg_order), inline=True)
    embed.add_field(name="目前存單數", value=f"{stored_count:,} 單", inline=True)
    embed.add_field(name="目前取消單數", value=f"{cancelled_count:,} 單", inline=True)
    embed.set_footer(text=f"統計區間：{start_dt.strftime('%Y/%m/%d %H:%M')} ～ {end_dt.strftime('%Y/%m/%d %H:%M')}")
    return embed

def _require_customer_staff_or_manager(interaction: discord.Interaction) -> bool:
    return (
        isinstance(interaction.user, discord.Member)
        and (is_customer_staff(interaction.user) or has_role(interaction.user, MANAGER_ROLE_ID) or interaction.user.guild_permissions.administrator)
    )


@bot.tree.command(
    name="stats_today",
    description="客服查詢今日營運統計",
    guild=discord.Object(id=GUILD_ID)
)
async def stats_today(interaction: discord.Interaction):
    if not _require_customer_staff_or_manager(interaction):
        await interaction.response.send_message("只有客服、店長或管理員可以查詢營運統計。", ephemeral=True)
        return

    now = get_taipei_now()
    start_dt = now.replace(hour=0, minute=0, second=0, microsecond=0)
    end_dt = start_dt + timedelta(days=1)
    embed = build_sales_stats_embed("今日營運統計", start_dt, end_dt)
    await interaction.response.send_message(embed=embed, ephemeral=True)


@bot.tree.command(
    name="stats_month",
    description="客服查詢本月營運統計",
    guild=discord.Object(id=GUILD_ID)
)
async def stats_month(interaction: discord.Interaction):
    if not _require_customer_staff_or_manager(interaction):
        await interaction.response.send_message("只有客服、店長或管理員可以查詢營運統計。", ephemeral=True)
        return

    now = get_taipei_now()
    start_dt = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    if start_dt.month == 12:
        end_dt = start_dt.replace(year=start_dt.year + 1, month=1)
    else:
        end_dt = start_dt.replace(month=start_dt.month + 1)
    embed = build_sales_stats_embed("本月營運統計", start_dt, end_dt)
    await interaction.response.send_message(embed=embed, ephemeral=True)


@bot.tree.command(
    name="top_customers",
    description="客服查詢顧客累積消費排行前 10 名",
    guild=discord.Object(id=GUILD_ID)
)
async def top_customers(interaction: discord.Interaction):
    if not _require_customer_staff_or_manager(interaction):
        await interaction.response.send_message("只有客服、店長或管理員可以查詢顧客排行。", ephemeral=True)
        return

    ranked = []
    for user_id, data in CUSTOMER_REWARDS.items():
        if not isinstance(data, dict):
            continue
        total_spent = int(data.get("total_spent", 0) or 0)
        if total_spent <= 0:
            continue
        ranked.append((user_id, total_spent, int(data.get("order_count", 0) or 0), get_member_level(total_spent)["name"]))

    ranked.sort(key=lambda row: row[1], reverse=True)
    top_rows = ranked[:10]

    embed = discord.Embed(
        title="顧客消費排行 TOP 10",
        color=discord.Color.gold(),
        timestamp=get_taipei_now(),
    )

    if not top_rows:
        embed.description = "目前還沒有可排行的顧客消費資料。"
    else:
        lines = []
        medals = ["🥇", "🥈", "🥉"]
        for index, (user_id, total_spent, order_count, level_name) in enumerate(top_rows, start=1):
            prefix = medals[index - 1] if index <= 3 else f"#{index}"
            lines.append(
                f"{prefix} <@{user_id}>｜{format_t_amount(total_spent)}｜{order_count:,} 單｜{level_name}"
            )
        embed.description = "\n".join(lines)

    await interaction.response.send_message(embed=embed, ephemeral=True)



@bot.tree.command(
    name="order_search",
    description="客服搜尋訂單，可用訂單編號、顧客 ID、項目或狀態查詢",
    guild=discord.Object(id=GUILD_ID)
)
@app_commands.describe(
    keyword="關鍵字：訂單編號、顧客ID、項目名稱，可不填",
    status="狀態：active / stored / closed / cancelled，可不填",
    limit="最多顯示幾筆，預設 10，最多 20"
)
async def order_search(
    interaction: discord.Interaction,
    keyword: str | None = None,
    status: str | None = None,
    limit: int = 10,
):
    if not _require_customer_staff_or_manager(interaction):
        await interaction.response.send_message("只有客服、店長或管理員可以搜尋訂單。", ephemeral=True)
        return

    limit = max(1, min(int(limit or 10), 20))
    keyword_text = (keyword or "").strip().lower()
    status_text = (status or "").strip().lower()

    matches = []
    for channel_id, data in SELF_SERVICE_ORDER_SELECTIONS.items():
        if not isinstance(data, dict):
            continue

        order_status = str(data.get("status") or ("closed" if data.get("closed") else "active")).lower()
        if status_text and order_status != status_text:
            continue

        customer_id = data.get("customer_id") or ""
        haystack = " ".join([
            str(data.get("order_no") or ""),
            str(customer_id),
            str(data.get("category") or ""),
            str(data.get("item") or ""),
            str(data.get("payment_method") or ""),
            str(channel_id),
            order_status,
        ]).lower()

        if keyword_text and keyword_text not in haystack:
            continue

        matches.append((channel_id, data))

    def sort_key(row):
        _, data = row
        return str(data.get("closed_at") or data.get("stored_at") or data.get("created_at") or data.get("updated_at") or "")

    matches.sort(key=sort_key, reverse=True)
    shown = matches[:limit]

    embed = discord.Embed(
        title="訂單搜尋結果",
        color=discord.Color.blurple(),
        timestamp=get_taipei_now(),
    )

    if not shown:
        embed.description = "沒有找到符合條件的訂單。"
    else:
        lines = []
        for channel_id, data in shown:
            order_no = data.get("order_no") or "未產生"
            customer_id = data.get("customer_id")
            customer_text = f"<@{customer_id}>" if customer_id else "未紀錄"
            item = data.get("item") or "未紀錄"
            quantity = _to_int(data.get("quantity"), 1) or 1
            amount = _to_int(data.get("amount"), 0) or 0
            order_status = str(data.get("status") or ("closed" if data.get("closed") else "active"))
            ticket_text = f"<#{channel_id}>" if int(channel_id) > 0 else f"歷史資料 {channel_id}"
            lines.append(
                f"**{order_no}**｜{order_status}\n"
                f"顧客：{customer_text}｜項目：{item} x{quantity}｜金額：{format_t_amount(amount) if amount else '未紀錄'}\n"
                f"票口：{ticket_text}"
            )
        embed.description = "\n\n".join(lines)
        if len(matches) > limit:
            embed.set_footer(text=f"只顯示前 {limit} 筆，共找到 {len(matches)} 筆")

    await interaction.response.send_message(embed=embed, ephemeral=True)


@bot.tree.command(
    name="check_stored_orders",
    description="客服手動檢查是否有超過 3/7 天的存單提醒",
    guild=discord.Object(id=GUILD_ID)
)
async def check_stored_orders(interaction: discord.Interaction):
    if not _require_customer_staff_or_manager(interaction):
        await interaction.response.send_message("只有客服、店長或管理員可以檢查存單提醒。", ephemeral=True)
        return

    await interaction.response.defer(ephemeral=True)
    await check_stored_order_reminders_once(interaction.guild)
    await interaction.followup.send("已檢查存單提醒，若有逾期存單會發到機器人日誌。", ephemeral=True)


@bot.tree.command(
    name="add_customer_note",
    description="客服新增顧客備註或黑名單紀錄",
    guild=discord.Object(id=GUILD_ID)
)
@app_commands.describe(
    customer="要新增備註的顧客",
    note="備註內容",
    blacklist="是否標記為黑名單 / 高風險備註"
)
async def add_customer_note(
    interaction: discord.Interaction,
    customer: discord.Member,
    note: str,
    blacklist: bool = False,
):
    if not _require_customer_staff_or_manager(interaction):
        await interaction.response.send_message("只有客服、店長或管理員可以新增顧客備註。", ephemeral=True)
        return

    content = note.strip()[:500]
    if not content:
        await interaction.response.send_message("備註內容不能空白。", ephemeral=True)
        return

    data = get_customer_reward_data(customer.id)
    notes = data.setdefault("notes", [])
    notes.append({
        "content": content,
        "is_blacklist": bool(blacklist),
        "operator_id": interaction.user.id,
        "created_at": get_taipei_now_iso(),
    })
    CUSTOMER_REWARDS[customer.id] = data
    save_bot_data()

    await send_order_log(
        interaction.guild,
        title="新增顧客備註",
        fields=[
            ("顧客", customer.mention, True),
            ("類型", "黑名單 / 高風險" if blacklist else "一般備註", True),
            ("操作人員", interaction.user.mention, True),
            ("內容", content, False),
        ],
        color=discord.Color.red() if blacklist else discord.Color.blue(),
    )

    await interaction.response.send_message(
        f"已新增 {'黑名單 / 高風險' if blacklist else '一般'}備註給 {customer.mention}。",
        ephemeral=True,
        allowed_mentions=discord.AllowedMentions(users=True, roles=False, everyone=False),
    )


@bot.tree.command(
    name="customer_notes",
    description="客服查詢顧客備註 / 黑名單紀錄",
    guild=discord.Object(id=GUILD_ID)
)
@app_commands.describe(customer="要查詢備註的顧客")
async def customer_notes(interaction: discord.Interaction, customer: discord.Member):
    if not _require_customer_staff_or_manager(interaction):
        await interaction.response.send_message("只有客服、店長或管理員可以查詢顧客備註。", ephemeral=True)
        return

    embed = discord.Embed(
        title="顧客備註 / 黑名單紀錄",
        description=format_customer_notes_for_staff(customer.id, limit=15),
        color=discord.Color.red() if any(n.get("is_blacklist") for n in get_customer_notes(customer.id)) else discord.Color.blue(),
        timestamp=get_taipei_now(),
    )
    embed.add_field(name="顧客", value=customer.mention, inline=False)
    await interaction.response.send_message(embed=embed, ephemeral=True)


@bot.tree.command(
    name="remove_customer_note",
    description="客服刪除顧客備註，index 請看 /customer_notes 的編號",
    guild=discord.Object(id=GUILD_ID)
)
@app_commands.describe(
    customer="要刪除備註的顧客",
    index="要刪除第幾筆備註，從 1 開始"
)
async def remove_customer_note(interaction: discord.Interaction, customer: discord.Member, index: int):
    if not _require_customer_staff_or_manager(interaction):
        await interaction.response.send_message("只有客服、店長或管理員可以刪除顧客備註。", ephemeral=True)
        return

    data = get_customer_reward_data(customer.id)
    notes = data.setdefault("notes", [])
    if index < 1 or index > len(notes):
        await interaction.response.send_message("找不到這個備註編號，請先用 /customer_notes 查看。", ephemeral=True)
        return

    removed = notes.pop(index - 1)
    CUSTOMER_REWARDS[customer.id] = data
    save_bot_data()

    await send_order_log(
        interaction.guild,
        title="刪除顧客備註",
        fields=[
            ("顧客", customer.mention, True),
            ("操作人員", interaction.user.mention, True),
            ("刪除內容", str(removed.get("content") or "未填寫"), False),
        ],
        color=discord.Color.dark_grey(),
    )

    await interaction.response.send_message(f"已刪除 {customer.mention} 的第 {index} 筆備註。", ephemeral=True)


@bot.tree.command(
    name="setup_panel",
    description="建立魔丸娛樂客服面板",
    guild=discord.Object(id=GUILD_ID)
)
@app_commands.checks.has_permissions(administrator=True)
async def setup_panel(interaction: discord.Interaction):
    embed = discord.Embed(
        title="魔丸娛樂客服中心",
        description="歡迎來到魔丸娛樂，點擊下方按鈕聯絡客服",
        color=discord.Color.purple()
    )

    await interaction.channel.send(
        embed=embed,
        view=MainPanelView()
    )

    await interaction.response.send_message(
        "客服面板已建立。",
        ephemeral=True
    )


@bot.tree.command(
    name="setup_complaint_panel",
    description="建立客訴表單面板",
    guild=discord.Object(id=GUILD_ID)
)
@app_commands.checks.has_permissions(administrator=True)
async def setup_complaint_panel(interaction: discord.Interaction):
    guild = interaction.guild

    if guild is None:
        await interaction.response.send_message("這個功能只能在伺服器內使用。", ephemeral=True)
        return

    panel_channel = guild.get_channel(COMPLAINT_PANEL_CHANNEL_ID)

    if panel_channel is None or not isinstance(panel_channel, discord.TextChannel):
        await interaction.response.send_message(
            "找不到客訴面板頻道，請確認 COMPLAINT_PANEL_CHANNEL_ID 是否正確。",
            ephemeral=True
        )
        return

    embed = discord.Embed(
        title="我要客訴!!",
        description="如有任何客訴內容，請點擊下方按鈕填寫客訴單。",
        color=discord.Color.red()
    )

    embed.set_footer(text="魔丸娛樂｜客訴表單")

    await panel_channel.send(
        embed=embed,
        view=ComplaintPanelView()
    )

    await interaction.response.send_message(
        f"客訴表單面板已建立在 {panel_channel.mention}。",
        ephemeral=True
    )


@bot.tree.command(
    name="setup_feedback_panel",
    description="建立顧客意見箱面板",
    guild=discord.Object(id=GUILD_ID)
)
@app_commands.checks.has_permissions(administrator=True)
async def setup_feedback_panel(interaction: discord.Interaction):
    guild = interaction.guild

    if guild is None:
        await interaction.response.send_message("這個功能只能在伺服器內使用。", ephemeral=True)
        return

    panel_channel = guild.get_channel(FEEDBACK_PANEL_CHANNEL_ID)

    if panel_channel is None or not isinstance(panel_channel, discord.TextChannel):
        await interaction.response.send_message(
            "找不到顧客意見箱面板頻道，請確認 FEEDBACK_PANEL_CHANNEL_ID 是否正確。",
            ephemeral=True
        )
        return

    embed = discord.Embed(
        title="顧客意見箱",
        description="如有任何意見或建議，請點擊下方按鈕填寫。",
        color=discord.Color.blue()
    )

    embed.set_footer(text="魔丸娛樂｜顧客意見箱")

    await panel_channel.send(
        embed=embed,
        view=FeedbackPanelView()
    )

    await interaction.response.send_message(
        f"顧客意見箱面板已建立在 {panel_channel.mention}。",
        ephemeral=True
    )


@bot.tree.command(
    name="setup_play_voice",
    description="建立陪玩語音入口頻道",
    guild=discord.Object(id=GUILD_ID)
)
@app_commands.checks.has_permissions(administrator=True)
async def setup_play_voice(interaction: discord.Interaction):
    guild = interaction.guild

    if guild is None:
        await interaction.response.send_message("這個功能只能在伺服器內使用。", ephemeral=True)
        return

    lobby_channel = await get_or_create_play_voice_lobby(guild)

    if lobby_channel is None:
        await interaction.response.send_message(
            "建立失敗，請確認 PLAY_VOICE_CATEGORY_ID 是否正確。",
            ephemeral=True
        )
        return

    await interaction.response.send_message(
        f"陪玩語音入口已建立 / 確認存在：{lobby_channel.mention}",
        ephemeral=True
    )




@bot.tree.command(
    name="setup_vip_voice",
    description="建立 VIP 語音入口頻道",
    guild=discord.Object(id=GUILD_ID)
)
@app_commands.checks.has_permissions(administrator=True)
async def setup_vip_voice(interaction: discord.Interaction):
    guild = interaction.guild

    if guild is None:
        await interaction.response.send_message("這個功能只能在伺服器內使用。", ephemeral=True)
        return

    lobby_channel = await get_or_create_vip_voice_lobby(guild)

    if lobby_channel is None:
        await interaction.response.send_message(
            "建立失敗，請確認 PLAY_VOICE_CATEGORY_ID 是否正確。",
            ephemeral=True
        )
        return

    await interaction.response.send_message(
        f"VIP 語音入口已建立 / 確認存在：{lobby_channel.mention}",
        ephemeral=True
    )



@bot.tree.command(
    name="setup_public_voice",
    description="建立公共語音入口頻道",
    guild=discord.Object(id=GUILD_ID)
)
@app_commands.checks.has_permissions(administrator=True)
async def setup_public_voice(interaction: discord.Interaction):
    guild = interaction.guild

    if guild is None:
        await interaction.response.send_message("這個功能只能在伺服器內使用。", ephemeral=True)
        return

    lobby_channel = await get_or_create_public_voice_lobby(guild)

    if lobby_channel is None:
        await interaction.response.send_message(
            "建立失敗，請確認 PLAY_VOICE_CATEGORY_ID 是否正確。",
            ephemeral=True
        )
        return

    await interaction.response.send_message(
        f"公共語音入口已建立 / 確認存在：{lobby_channel.mention}",
        ephemeral=True
    )



@bot.tree.command(
    name="delete_dispatch_panel",
    description="刪除派單頻道中已取消訂單的接單面板",
    guild=discord.Object(id=GUILD_ID)
)
@app_commands.describe(
    message_id="要刪除的派單訊息 ID",
    channel="派單訊息所在頻道；不填則使用目前頻道"
)
async def delete_dispatch_panel(
    interaction: discord.Interaction,
    message_id: str,
    channel: discord.TextChannel | None = None,
):
    if not isinstance(interaction.user, discord.Member):
        await interaction.response.send_message("無法確認你的身分組。", ephemeral=True)
        return

    if not is_customer_staff(interaction.user) and not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message("只有客服或管理員可以刪除派單面板。", ephemeral=True)
        return

    target_channel = channel or interaction.channel

    if not isinstance(target_channel, discord.TextChannel):
        await interaction.response.send_message("請在文字頻道使用，或指定派單訊息所在頻道。", ephemeral=True)
        return

    try:
        target_message_id = int(message_id.strip())
    except ValueError:
        await interaction.response.send_message("訊息 ID 格式錯誤，請貼純數字訊息 ID。", ephemeral=True)
        return

    try:
        message = await target_channel.fetch_message(target_message_id)
    except discord.NotFound:
        await interaction.response.send_message("找不到這則派單訊息，可能已經被刪除了。", ephemeral=True)
        return
    except discord.Forbidden:
        await interaction.response.send_message("Bot 權限不足，無法讀取該頻道訊息。", ephemeral=True)
        return
    except discord.HTTPException as e:
        await interaction.response.send_message(f"讀取派單訊息失敗：{e}", ephemeral=True)
        return

    try:
        await message.delete()
    except discord.Forbidden:
        await interaction.response.send_message("Bot 權限不足，無法刪除該派單訊息。", ephemeral=True)
        return
    except discord.HTTPException as e:
        await interaction.response.send_message(f"刪除派單訊息失敗：{e}", ephemeral=True)
        return

    ORDER_CLAIMS.pop(target_message_id, None)

    removed_order_links = 0
    for order_channel_id, data in list(SELF_SERVICE_ORDER_SELECTIONS.items()):
        if _to_int(data.get("dispatch_message_id")) == target_message_id:
            data["status"] = "cancelled"
            data["cancelled"] = True
            data["cancelled_at"] = get_taipei_now_iso()
            data["dispatch_message_id"] = None
            SELF_SERVICE_ORDER_SELECTIONS[order_channel_id] = data
            removed_order_links += 1

    save_bot_data()

    await interaction.response.send_message(
        f"已刪除派單面板，並清理相關接單暫存資料。關聯訂單：{removed_order_links} 筆。",
        ephemeral=True
    )

    await send_order_log(
        interaction.guild,
        "刪除派單面板",
        (
            f"操作人員：{interaction.user.mention}\n"
            f"派單頻道：{target_channel.mention}\n"
            f"訊息 ID：{target_message_id}\n"
            f"關聯訂單：{removed_order_links} 筆"
        ),
        color=discord.Color.red()
    )

@setup_panel.error
@setup_complaint_panel.error
@setup_feedback_panel.error
@setup_play_voice.error
@setup_vip_voice.error
@setup_public_voice.error
async def command_error(
    interaction: discord.Interaction,
    error: app_commands.AppCommandError
):
    if interaction.response.is_done():
        send = interaction.followup.send
    else:
        send = interaction.response.send_message

    if isinstance(error, app_commands.MissingPermissions):
        await send(
            "你需要管理員權限才能使用這個指令。",
            ephemeral=True
        )
    elif isinstance(error, discord.Forbidden):
        await send(
            "Bot 權限不足。請確認 Bot 有檢視頻道、傳送訊息、嵌入連結、管理頻道、管理身分組等必要權限。",
            ephemeral=True
        )
    else:
        await send(
            f"發生錯誤：{error}",
            ephemeral=True
        )


bot.run(TOKEN)