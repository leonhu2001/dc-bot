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


