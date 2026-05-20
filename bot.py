import os
from dotenv import load_dotenv

load_dotenv()
import os
import json
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


def is_review_media_attachment(attachment: discord.Attachment) -> bool:
    """判斷好評附件是否為可轉發的圖片或影片。"""
    if attachment.content_type:
        return (
            attachment.content_type.startswith("image/")
            or attachment.content_type.startswith("video/")
        )

    media_exts = (
        ".png", ".jpg", ".jpeg", ".gif", ".webp",
        ".mp4", ".mov", ".webm", ".mkv", ".avi", ".m4v"
    )
    return attachment.filename.lower().endswith(media_exts)


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

        media_attachments = []

        async for message in channel.history(
            after=draft["started_at"],
            oldest_first=True,
            limit=None
        ):
            if message.author.id != self.customer_id:
                continue

            for attachment in message.attachments:
                if is_review_media_attachment(attachment):
                    media_attachments.append(attachment)

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
            name="圖片 / 影片數量",
            value=f"{len(media_attachments)} 個",
            inline=True
        )

        files = []

        for attachment in media_attachments:
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
                            "匿名闆闆 的好評附件續傳"
                            if is_anonymous
                            else f"{interaction.user.mention} 的好評附件續傳"
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
    companion_preference = data.get("companion_preference")
    payment_method = data.get("payment_method", "未紀錄")

    if item is None:
        return "未紀錄自助下單內容", payment_method

    parts = []

    if category is not None:
        parts.append(ORDER_CATEGORY_LABELS.get(category, category))

    parts.append(item)

    if companion_preference is not None:
        parts.append(companion_preference)

    return "｜".join(parts), payment_method


def get_taipei_now_text() -> str:
    taipei_tz = timezone(timedelta(hours=8))
    return datetime.now(taipei_tz).strftime("%Y/%m/%d %H:%M")


class ReceiptModal(discord.ui.Modal, title="已結單收據"):
    receipt_id = discord.ui.TextInput(
        label="編號",
        placeholder="日期+今天第幾單 ex.20260427001",
        required=True,
        max_length=100
    )

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

        receipt_text = (
            "```text\n"
            "收據\n"
            "\n"
            f"編號：{self.receipt_id.value}\n"
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

        await interaction.response.send_message(
            f"此單已由 {interaction.user.mention} 結單，收據已送出。\n\n"
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

        await interaction.response.send_message(
            "已確認取消訂單，這個頻道將在 3 秒後關閉。",
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

DATA_FILE = Path(__file__).parent / "bot_data.json"
CLOSED_ORDER_KEEP_DAYS = 60



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
            "payment_method": data.get("payment_method"),
            "source_channel_id": data.get("source_channel_id"),
            "companion_preference": data.get("companion_preference"),
            "dispatch_channel_id": data.get("dispatch_channel_id"),
        }

    return result


def save_bot_data() -> None:
    payload = {
        "orders": _serialize_orders(),
        "claims": _serialize_claims(),
    }

    tmp_path = DATA_FILE.with_suffix(".tmp")

    try:
        with tmp_path.open("w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
        tmp_path.replace(DATA_FILE)
    except OSError as e:
        print(f"保存 bot_data.json 失敗：{e}")


def load_bot_data() -> None:
    if not DATA_FILE.exists():
        return

    try:
        with DATA_FILE.open("r", encoding="utf-8") as f:
            payload = json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        print(f"讀取 bot_data.json 失敗：{e}")
        return

    SELF_SERVICE_ORDER_SELECTIONS.clear()
    ORDER_CLAIMS.clear()

    for channel_id_text, data in payload.get("orders", {}).items():
        channel_id = _to_int(channel_id_text)
        if channel_id is None or not isinstance(data, dict):
            continue
        SELF_SERVICE_ORDER_SELECTIONS[channel_id] = data

    for message_id_text, data in payload.get("claims", {}).items():
        message_id = _to_int(message_id_text)
        if message_id is None or not isinstance(data, dict):
            continue

        ORDER_CLAIMS[message_id] = {
            "companion": {uid for uid in (_to_int(x) for x in data.get("companion", [])) if uid is not None},
            "booster": {uid for uid in (_to_int(x) for x in data.get("booster", [])) if uid is not None},
            "locked": bool(data.get("locked", False)),
            "customer_id": data.get("customer_id"),
            "category_label": data.get("category_label"),
            "item": data.get("item"),
            "payment_method": data.get("payment_method"),
            "source_channel_id": data.get("source_channel_id"),
            "companion_preference": data.get("companion_preference"),
            "dispatch_channel_id": data.get("dispatch_channel_id"),
        }


def remember_order_data(channel_id: int, data: dict) -> None:
    SELF_SERVICE_ORDER_SELECTIONS[channel_id] = data
    save_bot_data()


def remember_claim_data(message_id: int, data: dict) -> None:
    ORDER_CLAIMS[message_id] = data
    save_bot_data()


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
        payment_method=str(data["payment_method"]),
        source_channel_id=int(data["source_channel_id"]),
        companion_preference=data.get("companion_preference"),
        locked=bool(data.get("locked", False)),
    )


def get_taipei_now() -> datetime:
    taipei_tz = timezone(timedelta(hours=8))
    return datetime.now(taipei_tz)


def get_taipei_now_iso() -> str:
    return get_taipei_now().isoformat(timespec="seconds")


def cleanup_old_closed_orders() -> None:
    """清理已結單超過 CLOSED_ORDER_KEEP_DAYS 天的訂單與對應接單資料。"""
    if CLOSED_ORDER_KEEP_DAYS <= 0:
        return

    now = get_taipei_now()
    cutoff = now - timedelta(days=CLOSED_ORDER_KEEP_DAYS)
    order_channel_ids_to_remove = []
    dispatch_message_ids_to_remove = set()

    for channel_id, data in list(SELF_SERVICE_ORDER_SELECTIONS.items()):
        if not isinstance(data, dict) or not data.get("closed"):
            continue

        closed_at_text = data.get("closed_at")
        if not closed_at_text:
            continue

        try:
            closed_at = datetime.fromisoformat(str(closed_at_text))
        except ValueError:
            continue

        if closed_at.tzinfo is None:
            closed_at = closed_at.replace(tzinfo=timezone(timedelta(hours=8)))

        if closed_at < cutoff:
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
            f"{CLOSED_ORDER_KEEP_DAYS} 天的已結單訂單資料。"
        )


load_bot_data()
cleanup_old_closed_orders()

ORDER_CATEGORY_LABELS = {
    "basic": "基礎單",
    "fun": "趣味單",
    "farm": "代解代肝",
    "season": "賽季限定活動",
    "valorant": "Valorant - 陪玩/代打",
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
    "valorant": [
        "Valorant 陪玩",
        "Valorant 代打",
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
    "Valorant 陪玩",
}

COMPANION_PREFERENCE_OPTIONS = [
    "不指定陪玩/打手",
    "指定陪玩/打手",
]

PAYMENT_METHOD_OPTIONS = [
    "LinePay",
    "街口",
    "轉帳",
    "8591",
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
            discord.SelectOption(
                label="Valorant - 陪玩/代打",
                value="valorant",
                description="Valorant 陪玩、Valorant 代打",
                default=selected_category == "valorant"
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

def has_role(member: discord.Member, role_id: int) -> bool:
    return any(role.id == role_id for role in member.roles)


def build_self_service_order_embed(
    customer_mention: str,
    category_label: str,
    item: str,
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
        payment_method: str,
        source_channel_id: int,
        companion_preference: str | None = None,
        locked: bool = False,
    ):
        super().__init__(timeout=None)
        self.customer_id = customer_id
        self.category_label = category_label
        self.item = item
        self.payment_method = payment_method
        self.source_channel_id = source_channel_id
        self.companion_preference = companion_preference
        self.locked = locked

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
        data.setdefault("payment_method", self.payment_method)
        data.setdefault("source_channel_id", self.source_channel_id)
        data.setdefault("companion_preference", self.companion_preference)
        data.setdefault("dispatch_channel_id", DISPATCH_CHANNEL_ID)

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
            payment_method=self.payment_method,
            source_channel=source_channel,
            companion_preference=self.companion_preference,
            receiver_text=receiver_text
        )

        if claim_data.get("locked"):
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
                payment_method=self.payment_method,
                source_channel_id=self.source_channel_id,
                companion_preference=self.companion_preference,
                locked=bool(claim_data.get("locked"))
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


async def lock_dispatch_claim_panel(guild: discord.Guild, order_channel_id: int):
    """客服結單後，鎖定派單頻道對應的陪玩 / 打手接單面板。"""
    data = SELF_SERVICE_ORDER_SELECTIONS.get(order_channel_id, {})
    dispatch_message_id = data.get("dispatch_message_id")
    dispatch_channel_id = data.get("dispatch_channel_id", DISPATCH_CHANNEL_ID)

    if dispatch_message_id is None:
        return

    dispatch_channel = guild.get_channel(dispatch_channel_id)

    if dispatch_channel is None or not isinstance(dispatch_channel, discord.TextChannel):
        return

    try:
        message = await dispatch_channel.fetch_message(dispatch_message_id)
    except (discord.NotFound, discord.Forbidden, discord.HTTPException):
        return

    source_channel = guild.get_channel(order_channel_id)

    if source_channel is None or not isinstance(source_channel, discord.TextChannel):
        return

    claim_data = ORDER_CLAIMS.setdefault(
        dispatch_message_id,
        {
            "companion": set(),
            "booster": set(),
            "locked": False,
        }
    )
    claim_data["customer_id"] = data.get("customer_id")
    claim_data["category_label"] = ORDER_CATEGORY_LABELS.get(data.get("category"), data.get("category") or "未紀錄")
    claim_data["item"] = data.get("item", "未紀錄")
    claim_data["payment_method"] = data.get("payment_method", "未紀錄")
    claim_data["source_channel_id"] = order_channel_id
    claim_data["companion_preference"] = data.get("companion_preference")
    claim_data["dispatch_channel_id"] = dispatch_channel_id
    claim_data["locked"] = True

    data["closed"] = True
    data["closed_at"] = get_taipei_now_iso()
    remember_order_data(order_channel_id, data)
    remember_claim_data(dispatch_message_id, claim_data)

    companion_ids = sorted(claim_data.get("companion", set()))
    booster_ids = sorted(claim_data.get("booster", set()))
    lines = []

    if companion_ids:
        lines.append("陪玩接單：" + " ".join(f"<@{user_id}>" for user_id in companion_ids))

    if booster_ids:
        lines.append("打手接單：" + " ".join(f"<@{user_id}>" for user_id in booster_ids))

    receiver_text = "\n".join(lines) if lines else None

    category = data.get("category")
    item = data.get("item", "未紀錄")
    payment_method = data.get("payment_method", "未紀錄")
    companion_preference = data.get("companion_preference")
    customer_id = data.get("customer_id")
    category_label = ORDER_CATEGORY_LABELS.get(category, category or "未紀錄")
    customer_mention = f"<@{customer_id}>" if customer_id is not None else "未紀錄"

    embed = build_self_service_order_embed(
        customer_mention=customer_mention,
        category_label=category_label,
        item=item,
        payment_method=payment_method,
        source_channel=source_channel,
        companion_preference=companion_preference,
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
                customer_id=customer_id or 0,
                category_label=category_label,
                item=item,
                payment_method=payment_method,
                source_channel_id=order_channel_id,
                companion_preference=companion_preference,
                locked=True
            ),
            allowed_mentions=discord.AllowedMentions(
                users=True,
                roles=False,
                everyone=False
            )
        )
    except (discord.NotFound, discord.Forbidden, discord.HTTPException):
        pass

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
        data["payment_method"] = self.values[0]
        remember_order_data(self.channel_id, data)

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
            "payment_method": payment_method,
            "source_channel_id": interaction.channel.id,
            "companion_preference": companion_preference,
            "dispatch_channel_id": dispatch_channel.id,
        }
        data["dispatch_message_id"] = dispatch_message.id
        data["dispatch_channel_id"] = dispatch_channel.id
        data["closed"] = False
        remember_order_data(interaction.channel.id, data)
        remember_claim_data(dispatch_message.id, ORDER_CLAIMS[dispatch_message.id])

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

        self.add_item(SelfServiceOrderCategorySelect(customer_id, channel_id, category))
        self.add_item(SelfServiceOrderItemSelect(customer_id, channel_id, category, selected_item))
        self.add_item(SelfServiceCompanionPreferenceSelect(customer_id, channel_id, selected_item, selected_preference))

    @discord.ui.button(
        label="前往付款",
        style=discord.ButtonStyle.success,
        custom_id="self_service_order_go_payment_button",
        row=3
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
                "如果選擇娛樂陪、技術陪、保底單、Valorant 陪玩，請額外選擇是否指定陪玩/打手。"
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

class ExamScheduleModal(discord.ui.Modal, title="已預約考核"):
    exam_time = discord.ui.TextInput(
        label="考核時間",
        placeholder="例如：2026/04/26 晚上 8:00",
        required=True,
        max_length=100
    )

    async def on_submit(self, interaction: discord.Interaction):
        if not isinstance(interaction.user, discord.Member):
            await interaction.response.send_message("無法確認你的身分組。", ephemeral=True)
            return

        if not is_exam_staff(interaction.user):
            await interaction.response.send_message("只有考官或店長可以操作。", ephemeral=True)
            return

        guild = interaction.guild

        if guild is None:
            await interaction.response.send_message("這個功能只能在伺服器內使用。", ephemeral=True)
            return

        notice_channel = guild.get_channel(EXAM_NOTICE_CHANNEL_ID)

        if notice_channel is None or not isinstance(notice_channel, discord.TextChannel):
            await interaction.response.send_message(
                "找不到考核通知頻道，請確認 EXAM_NOTICE_CHANNEL_ID 是否正確。",
                ephemeral=True
            )
            return

        channel = interaction.channel
        recruit_nickname = "未紀錄暱稱"
        recruit_position = "未紀錄職位"

        if isinstance(channel, discord.TextChannel):
            recruit_nickname, recruit_position = get_recruit_info_from_channel(channel)

        await notice_channel.send(
            f"有新的考核預約。\n\n"
            f"申請人暱稱：{recruit_nickname}\n"
            f"應徵職位：{recruit_position}\n"
            f"考核時間：{self.exam_time.value}"
        )

        await interaction.response.send_message(
            f"已送出考核預約通知到 {notice_channel.mention}。這個頻道將在 3 秒後關閉。",
            ephemeral=True
        )

        if isinstance(channel, discord.TextChannel):
            await channel.send(
                f"此入職申請已由 {interaction.user.mention} 預約考核。頻道將在 3 秒後關閉。"
            )

            await asyncio.sleep(3)

            await channel.delete(reason=f"Recruit exam scheduled by {interaction.user}")


class ConfirmCancelRecruitView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=60)

    @discord.ui.button(
        label="是，取消申請",
        style=discord.ButtonStyle.danger,
        custom_id="confirm_cancel_recruit_yes"
    )
    async def confirm_cancel_recruit(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not isinstance(interaction.user, discord.Member):
            await interaction.response.send_message("無法確認你的身分組。", ephemeral=True)
            return

        if not is_exam_staff(interaction.user):
            await interaction.response.send_message("只有考官或店長可以取消申請。", ephemeral=True)
            return

        channel = interaction.channel

        await interaction.response.send_message(
            "已確認取消入職申請，這個頻道將在 3 秒後關閉。",
            ephemeral=False
        )

        await asyncio.sleep(3)

        if isinstance(channel, discord.TextChannel):
            await channel.delete(reason=f"Recruit application cancelled by {interaction.user}")

    @discord.ui.button(
        label="否，保留申請",
        style=discord.ButtonStyle.secondary,
        custom_id="confirm_cancel_recruit_no"
    )
    async def keep_recruit(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not isinstance(interaction.user, discord.Member):
            await interaction.response.send_message("無法確認你的身分組。", ephemeral=True)
            return

        if not is_exam_staff(interaction.user):
            await interaction.response.send_message("只有考官或店長可以操作。", ephemeral=True)
            return

        await interaction.response.send_message("已保留入職申請。", ephemeral=True)


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
            topic=f"recruit_nickname={self.nickname.value};recruit_position={self.position.value}"
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
    bot.add_view(MainPanelView())
    bot.add_view(OrderControlView())
    bot.add_view(StaffOrderOperationView())
    bot.add_view(RecruitControlView())
    bot.add_view(ComplaintPanelView())
    bot.add_view(FeedbackPanelView())
    bot.add_view(ComplaintResolveView())

    guild_for_voice = bot.get_guild(GUILD_ID)
    if guild_for_voice is not None:
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