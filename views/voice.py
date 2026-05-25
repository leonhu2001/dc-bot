import discord


PLAY_VOICE_CATEGORY_ID = 0
PLAY_VOICE_CREATE_CHANNEL_NAME = "➕┃點我創建陪玩頻道"
OLD_PLAY_VOICE_CREATE_CHANNEL_NAMES: list[str] = []
VIP_VOICE_CREATE_CHANNEL_NAME = "➕┃點我創建VIP頻道"
OLD_VIP_VOICE_CREATE_CHANNEL_NAMES: list[str] = []
PUBLIC_VOICE_CREATE_CHANNEL_NAME = "➕┃點我創建公共頻道"
VIP_VOICE_LOBBY_ROLE_ID = 0
PLAY_VOICE_ALLOWED_ROLE_IDS: list[int] = []
VOICE_ROOM_HIDDEN_VISIBLE_ROLE_IDS: list[int] = []
VOICE_VIEW_ONLY_ROLE_IDS = [1507204925766242425]
TEMP_VOICE_CONTROL_PANELS: dict[int, dict] = {}


def configure_voice_helpers(
    *,
    play_voice_category_id: int,
    play_voice_create_channel_name: str,
    old_play_voice_create_channel_names: list[str],
    vip_voice_create_channel_name: str,
    old_vip_voice_create_channel_names: list[str],
    public_voice_create_channel_name: str,
    vip_voice_lobby_role_id: int,
    play_voice_allowed_role_ids: list[int],
    voice_room_hidden_visible_role_ids: list[int],
    temp_voice_control_panels: dict[int, dict],
) -> None:
    global PLAY_VOICE_CATEGORY_ID
    global PLAY_VOICE_CREATE_CHANNEL_NAME
    global OLD_PLAY_VOICE_CREATE_CHANNEL_NAMES
    global VIP_VOICE_CREATE_CHANNEL_NAME
    global OLD_VIP_VOICE_CREATE_CHANNEL_NAMES
    global PUBLIC_VOICE_CREATE_CHANNEL_NAME
    global VIP_VOICE_LOBBY_ROLE_ID
    global PLAY_VOICE_ALLOWED_ROLE_IDS
    global VOICE_ROOM_HIDDEN_VISIBLE_ROLE_IDS
    global VOICE_VIEW_ONLY_ROLE_IDS
    global TEMP_VOICE_CONTROL_PANELS

    PLAY_VOICE_CATEGORY_ID = int(play_voice_category_id)
    PLAY_VOICE_CREATE_CHANNEL_NAME = str(play_voice_create_channel_name)
    OLD_PLAY_VOICE_CREATE_CHANNEL_NAMES = list(old_play_voice_create_channel_names or [])
    VIP_VOICE_CREATE_CHANNEL_NAME = str(vip_voice_create_channel_name)
    OLD_VIP_VOICE_CREATE_CHANNEL_NAMES = list(old_vip_voice_create_channel_names or [])
    PUBLIC_VOICE_CREATE_CHANNEL_NAME = str(public_voice_create_channel_name)
    VIP_VOICE_LOBBY_ROLE_ID = int(vip_voice_lobby_role_id)
    PLAY_VOICE_ALLOWED_ROLE_IDS = [int(role_id) for role_id in (play_voice_allowed_role_ids or [])]
    VOICE_ROOM_HIDDEN_VISIBLE_ROLE_IDS = [int(role_id) for role_id in (voice_room_hidden_visible_role_ids or [])]
    TEMP_VOICE_CONTROL_PANELS = temp_voice_control_panels


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



def apply_voice_view_only_role_overwrites(
    guild: discord.Guild,
    overwrites: dict,
) -> dict:
    """讓指定身分組可以看見創建後的語音房，但不能連接。"""
    for role_id in VOICE_VIEW_ONLY_ROLE_IDS:
        role = guild.get_role(int(role_id))
        if role is None:
            continue

        overwrites[role] = discord.PermissionOverwrite(
            view_channel=True,
            connect=False,
            speak=False,
            stream=False,
            use_voice_activation=False,
            read_message_history=True,
            send_messages=False,
        )

    return overwrites


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

    apply_voice_view_only_role_overwrites(guild, overwrites)
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

    apply_voice_view_only_role_overwrites(guild, overwrites)
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



def is_temp_play_voice_room(channel: discord.abc.GuildChannel | None) -> bool:
    if not isinstance(channel, discord.VoiceChannel):
        return False

    panel_data = TEMP_VOICE_CONTROL_PANELS.get(channel.id)
    if isinstance(panel_data, dict) and panel_data.get("room_type") == "play":
        return True

    return (
        channel.category_id == PLAY_VOICE_CATEGORY_ID
        and channel.name.startswith("🎮┃")
        and channel.name.endswith("的陪玩頻道")
        and channel.name != PLAY_VOICE_CREATE_CHANNEL_NAME
    )


def member_has_play_voice_role(member: discord.Member) -> bool:
    return any(role.id in PLAY_VOICE_ALLOWED_ROLE_IDS for role in member.roles)


def _overwrite_has_any_explicit_value(overwrite: discord.PermissionOverwrite) -> bool:
    values = getattr(overwrite, "_values", None)
    if isinstance(values, dict):
        return bool(values)

    for attr in (
        "view_channel",
        "connect",
        "speak",
        "stream",
        "use_voice_activation",
        "send_messages",
        "read_message_history",
        "attach_files",
        "add_reactions",
        "use_external_emojis",
        "use_external_stickers",
        "move_members",
        "manage_channels",
    ):
        if getattr(overwrite, attr, None) is not None:
            return True
    return False


async def grant_play_voice_room_chat_access(
    voice_channel: discord.VoiceChannel | None,
    member: discord.Member,
) -> None:
    if member.bot or not is_temp_play_voice_room(voice_channel):
        return

    overwrite = voice_channel.overwrites_for(member)

    # 語音頻道本體。缺 view_channel 或 connect 時，語音內建聊天室仍可能顯示鎖住。
    overwrite.view_channel = True
    overwrite.connect = True
    overwrite.speak = True
    overwrite.stream = True
    overwrite.use_voice_activation = True

    # 語音頻道內建聊天室。
    overwrite.send_messages = True
    overwrite.read_message_history = True
    overwrite.attach_files = True
    overwrite.add_reactions = True
    overwrite.use_external_emojis = True
    overwrite.use_external_stickers = True

    try:
        await voice_channel.set_permissions(
            member,
            overwrite=overwrite,
            reason="Grant temporary play voice room and chat access",
        )
    except discord.Forbidden:
        print("Bot 權限不足，無法給予陪玩房語音 / 聊天室臨時權限。")
    except discord.HTTPException as e:
        print(f"給予陪玩房語音 / 聊天室臨時權限失敗：{e}")


async def revoke_play_voice_room_chat_access(
    voice_channel: discord.VoiceChannel | None,
    member: discord.Member,
) -> None:
    if member.bot or not is_temp_play_voice_room(voice_channel):
        return

    panel_data = TEMP_VOICE_CONTROL_PANELS.get(voice_channel.id, {})
    if isinstance(panel_data, dict) and int(panel_data.get("owner_id") or 0) == member.id:
        return

    if member_has_play_voice_role(member):
        return

    if member in voice_channel.members:
        return

    overwrite = voice_channel.overwrites_for(member)

    # 收回進房時臨時補上的語音房本體權限。
    overwrite.view_channel = None
    overwrite.connect = None
    overwrite.speak = None
    overwrite.stream = None
    overwrite.use_voice_activation = None

    # 收回進房時臨時補上的語音內建聊天室權限。
    overwrite.send_messages = None
    overwrite.read_message_history = None
    overwrite.attach_files = None
    overwrite.add_reactions = None
    overwrite.use_external_emojis = None
    overwrite.use_external_stickers = None

    try:
        if _overwrite_has_any_explicit_value(overwrite):
            await voice_channel.set_permissions(
                member,
                overwrite=overwrite,
                reason="Revoke temporary play voice room and chat access",
            )
        else:
            await voice_channel.set_permissions(
                member,
                overwrite=None,
                reason="Revoke temporary play voice room and chat access",
            )
    except discord.Forbidden:
        print("Bot 權限不足，無法收回陪玩房語音 / 聊天室臨時權限。")
    except discord.HTTPException as e:
        print(f"收回陪玩房語音 / 聊天室臨時權限失敗：{e}")

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
