import discord

from services.game_roles import GAME_ROLES


GAME_VOICE_ROLE_IDS: list[int] = [
    int(role.role_id)
    for role in GAME_ROLES
]


PLAY_VOICE_CATEGORY_ID = 0
PLAY_VOICE_LOBBY_CATEGORY_ID = 1508550586696597604
VIP_VOICE_LOBBY_CATEGORY_ID = 1508550977169526784
PLAY_VOICE_CREATE_CHANNEL_NAME = "➕┃點我創建陪玩頻道"
OLD_PLAY_VOICE_CREATE_CHANNEL_NAMES: list[str] = []
VIP_VOICE_CREATE_CHANNEL_NAME = "➕┃點我創建VIP頻道"
OLD_VIP_VOICE_CREATE_CHANNEL_NAMES: list[str] = []
PUBLIC_VOICE_CREATE_CHANNEL_NAME = "➕┃點我創建公共頻道"
VIP_VOICE_LOBBY_ROLE_ID = 0
VIP_VOICE_LOBBY_ROLE_IDS: list[int] = []
PLAY_VOICE_ALLOWED_ROLE_IDS: list[int] = []
DEFAULT_PLAY_VOICE_ALLOWED_ROLE_IDS: list[int] = [
    1500751059239440575,
    1482080315798192210,
    1500234130871550004,
    1500234170943934544,
    1500751039060643990,
    *GAME_VOICE_ROLE_IDS,
    1482084782031638548,
    1507204925766242425,
]

DEFAULT_RECEIVER_ROLE_IDS: list[int] = [
    1500751059239440575,
    1482080315798192210,
    1500234130871550004,
    1500234170943934544,
    1500751039060643990,
    *GAME_VOICE_ROLE_IDS,
]
EMPLOYEE_FAMILY_ROLE_ID = 1507204925766242425
VOICE_ROOM_HIDDEN_VISIBLE_ROLE_IDS: list[int] = []
VOICE_VIEW_ONLY_ROLE_IDS = []
VOICE_MOVE_MEMBER_ROLE_IDS: list[int] = []
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
    vip_voice_lobby_role_ids: list[int] | None = None,
    play_voice_allowed_role_ids: list[int],
    voice_room_hidden_visible_role_ids: list[int],
    voice_move_member_role_ids: list[int] | None = None,
    temp_voice_control_panels: dict[int, dict],
) -> None:
    global PLAY_VOICE_CATEGORY_ID
    global PLAY_VOICE_CREATE_CHANNEL_NAME
    global OLD_PLAY_VOICE_CREATE_CHANNEL_NAMES
    global VIP_VOICE_CREATE_CHANNEL_NAME
    global OLD_VIP_VOICE_CREATE_CHANNEL_NAMES
    global PUBLIC_VOICE_CREATE_CHANNEL_NAME
    global VIP_VOICE_LOBBY_ROLE_ID
    global VIP_VOICE_LOBBY_ROLE_IDS
    global PLAY_VOICE_ALLOWED_ROLE_IDS
    global VOICE_ROOM_HIDDEN_VISIBLE_ROLE_IDS
    global VOICE_VIEW_ONLY_ROLE_IDS
    global VOICE_MOVE_MEMBER_ROLE_IDS
    global TEMP_VOICE_CONTROL_PANELS

    PLAY_VOICE_CATEGORY_ID = int(play_voice_category_id)
    PLAY_VOICE_CREATE_CHANNEL_NAME = str(play_voice_create_channel_name)
    OLD_PLAY_VOICE_CREATE_CHANNEL_NAMES = list(old_play_voice_create_channel_names or [])
    VIP_VOICE_CREATE_CHANNEL_NAME = str(vip_voice_create_channel_name)
    OLD_VIP_VOICE_CREATE_CHANNEL_NAMES = list(old_vip_voice_create_channel_names or [])
    PUBLIC_VOICE_CREATE_CHANNEL_NAME = str(public_voice_create_channel_name)
    VIP_VOICE_LOBBY_ROLE_ID = int(vip_voice_lobby_role_id)
    VIP_VOICE_LOBBY_ROLE_IDS = [int(role_id) for role_id in (vip_voice_lobby_role_ids or [VIP_VOICE_LOBBY_ROLE_ID]) if int(role_id)]
    PLAY_VOICE_ALLOWED_ROLE_IDS = [int(role_id) for role_id in (play_voice_allowed_role_ids or DEFAULT_PLAY_VOICE_ALLOWED_ROLE_IDS)]
    VOICE_ROOM_HIDDEN_VISIBLE_ROLE_IDS = [int(role_id) for role_id in (voice_room_hidden_visible_role_ids or [])]
    VOICE_MOVE_MEMBER_ROLE_IDS = [
        int(role_id)
        for role_id in (
            voice_move_member_role_ids
            or DEFAULT_RECEIVER_ROLE_IDS
        )
        if int(role_id)
    ]
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
    role_ids: list[int] = []

    for raw_role_id in [*PLAY_VOICE_ALLOWED_ROLE_IDS, *DEFAULT_PLAY_VOICE_ALLOWED_ROLE_IDS]:
        role_id = int(raw_role_id)

        if role_id and role_id not in role_ids:
            role_ids.append(role_id)

    return [
        role
        for role_id in role_ids
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
        if int(role_id) in PLAY_VOICE_ALLOWED_ROLE_IDS:
            continue
        role = guild.get_role(int(role_id))
        if role is None:
            continue

        overwrites[role] = discord.PermissionOverwrite(
            view_channel=True,
            connect=False,
            speak=True,
            stream=False,
            use_voice_activation=False,
            read_message_history=True,
            send_messages=True,
        )

    return overwrites



def get_employee_family_role(guild: discord.Guild) -> discord.Role | None:
    return guild.get_role(int(EMPLOYEE_FAMILY_ROLE_ID or 0))


def build_employee_family_play_overwrite(connect: bool = True) -> discord.PermissionOverwrite:
    return discord.PermissionOverwrite(
        view_channel=True,
        connect=connect,
        speak=True,
        stream=True,
        use_voice_activation=True,
        send_messages=True,
        read_message_history=True,
    )



def build_full_temp_voice_overwrite(
    *,
    connect: bool = True,
    move_members: bool = False,
    manage_channels: bool = False,
) -> discord.PermissionOverwrite:
    return discord.PermissionOverwrite(
        view_channel=True,
        connect=connect,
        speak=True,
        stream=True,
        use_voice_activation=True,
        send_messages=True,
        read_message_history=True,
        attach_files=True,
        add_reactions=True,
        use_external_emojis=True,
        use_external_stickers=True,
        move_members=move_members,
        manage_channels=manage_channels,
    )



def is_receiver_voice_role(role: discord.Role | None) -> bool:
    if role is None:
        return False

    allowed_ids = {
        int(role_id)
        for role_id in (
            VOICE_MOVE_MEMBER_ROLE_IDS
            or DEFAULT_RECEIVER_ROLE_IDS
        )
    }

    return int(role.id) in allowed_ids



def get_vip_voice_allowed_roles(guild: discord.Guild) -> list[discord.Role]:
    """VIP 臨時房固定放行：陪玩、打手、客服；不包含員工家屬。"""
    excluded_role_ids = {int(EMPLOYEE_FAMILY_ROLE_ID or 0)}
    return [
        role
        for role in get_play_voice_allowed_roles(guild)
        if int(role.id) not in excluded_role_ids
    ]


def build_play_lobby_overwrites(guild: discord.Guild) -> dict:
    """點我創建陪玩頻道：只有陪玩/打手身分組可見可加入。"""
    overwrites = {
        guild.default_role: discord.PermissionOverwrite(
            view_channel=False,
            connect=False,
        ),
        guild.me: discord.PermissionOverwrite(
            view_channel=True,
            connect=True,
            speak=True,
            move_members=True,
            manage_channels=True,
            send_messages=True,
            read_message_history=True,
        ),
    }

    for role in get_play_voice_allowed_roles(guild):
        overwrites[role] = discord.PermissionOverwrite(
            view_channel=True,
            connect=True,
            speak=True,
            stream=True,
            use_voice_activation=True,
            send_messages=True,
            read_message_history=True,
        )

    return overwrites



def build_play_voice_overwrites(guild: discord.Guild) -> dict:
    """陪玩臨時房：陪玩 / 打手 / 客服 / 員工家屬完整權限；其他人需被移入後才給個人權限。"""
    overwrites = {
        guild.default_role: discord.PermissionOverwrite(
            view_channel=True,
            connect=False,
            send_messages=False,
            read_message_history=False,
        ),
        guild.me: build_full_temp_voice_overwrite(
            connect=True,
            move_members=True,
            manage_channels=True,
        ),
    }

    for role in get_play_voice_allowed_roles(guild):
        overwrites[role] = build_full_temp_voice_overwrite(
            connect=True,
            move_members=is_receiver_voice_role(role),
        )

    employee_family_role = get_employee_family_role(guild)
    if employee_family_role is not None:
        overwrites[employee_family_role] = build_full_temp_voice_overwrite(connect=True)

    apply_voice_view_only_role_overwrites(guild, overwrites)
    return overwrites

def build_vip_lobby_overwrites(guild: discord.Guild) -> dict:
    """點我創建VIP頻道：6 階 VIP 身分組皆可見可加入。"""
    overwrites = {
        guild.default_role: discord.PermissionOverwrite(
            view_channel=False,
            connect=False,
        ),
        guild.me: discord.PermissionOverwrite(
            view_channel=True,
            connect=True,
            speak=True,
            move_members=True,
            manage_channels=True,
            send_messages=True,
            read_message_history=True,
        ),
    }

    vip_role_ids = VIP_VOICE_LOBBY_ROLE_IDS or [VIP_VOICE_LOBBY_ROLE_ID]

    for vip_role_id in vip_role_ids:
        vip_role = guild.get_role(int(vip_role_id))
        if vip_role is not None:
            overwrites[vip_role] = discord.PermissionOverwrite(
                view_channel=True,
                connect=True,
                speak=True,
                stream=True,
                use_voice_activation=True,
                send_messages=True,
                read_message_history=True,
            )

    return overwrites



def build_vip_room_overwrites(guild: discord.Guild, member: discord.Member) -> dict:
    """VIP 臨時房：陪玩 / 打手 / 客服 / 創建者完整權限；員工家屬不作為固定放行角色。"""
    overwrites = {
        guild.default_role: discord.PermissionOverwrite(
            view_channel=True,
            connect=False,
            send_messages=False,
            read_message_history=False,
        ),
        guild.me: build_full_temp_voice_overwrite(
            connect=True,
            move_members=True,
            manage_channels=True,
        ),
        member: build_full_temp_voice_overwrite(connect=True),
    }

    for role in get_vip_voice_allowed_roles(guild):
        overwrites[role] = build_full_temp_voice_overwrite(
            connect=True,
            move_members=is_receiver_voice_role(role),
        )

    apply_voice_view_only_role_overwrites(guild, overwrites)
    return overwrites


def build_public_lobby_overwrites(guild: discord.Guild) -> dict:
    """公共入口頻道：維持原本入口權限，不受公共臨時房完整文字權限影響。"""
    return {
        guild.default_role: discord.PermissionOverwrite(
            view_channel=True,
            connect=True,
            speak=True,
            stream=True,
            use_voice_activation=True,
            send_messages=False,
            read_message_history=False,
        ),
        guild.me: discord.PermissionOverwrite(
            view_channel=True,
            connect=True,
            speak=True,
            move_members=True,
            manage_channels=True,
            send_messages=True,
            read_message_history=True,
        ),
    }




def build_public_voice_overwrites(guild: discord.Guild) -> dict:
    """公共臨時房：所有人完整權限。"""
    return {
        guild.default_role: build_full_temp_voice_overwrite(connect=True),
        guild.me: build_full_temp_voice_overwrite(
            connect=True,
            move_members=True,
            manage_channels=True,
        ),
    }

async def get_or_create_play_voice_lobby(guild: discord.Guild) -> discord.VoiceChannel | None:
    category = guild.get_channel(PLAY_VOICE_LOBBY_CATEGORY_ID)

    if category is None or not isinstance(category, discord.CategoryChannel):
        print("找不到陪玩語音類別，請確認 PLAY_VOICE_LOBBY_CATEGORY_ID 是否正確。")
        return None

    for channel in category.voice_channels:
        if channel.name == PLAY_VOICE_CREATE_CHANNEL_NAME:
            await channel.edit(
                overwrites=build_play_lobby_overwrites(guild),
                reason="Update play voice lobby permissions",
            )
            return channel

        if channel.name in OLD_PLAY_VOICE_CREATE_CHANNEL_NAMES:
            await channel.edit(
                name=PLAY_VOICE_CREATE_CHANNEL_NAME,
                overwrites=build_play_lobby_overwrites(guild),
                reason="Rename old play voice lobby",
            )
            return channel

    return await guild.create_voice_channel(
        name=PLAY_VOICE_CREATE_CHANNEL_NAME,
        category=category,
        overwrites=build_play_lobby_overwrites(guild),
        reason="Create play voice lobby",
    )


async def get_or_create_vip_voice_lobby(guild: discord.Guild) -> discord.VoiceChannel | None:
    category = guild.get_channel(VIP_VOICE_LOBBY_CATEGORY_ID)

    if category is None or not isinstance(category, discord.CategoryChannel):
        print("找不到 VIP 語音類別，請確認 VIP_VOICE_LOBBY_CATEGORY_ID 是否正確。")
        return None

    for channel in category.voice_channels:
        if channel.name == VIP_VOICE_CREATE_CHANNEL_NAME:
            await channel.edit(
                overwrites=build_vip_lobby_overwrites(guild),
                reason="Update VIP voice lobby permissions",
            )
            return channel

        if channel.name in OLD_VIP_VOICE_CREATE_CHANNEL_NAMES:
            await channel.edit(
                name=VIP_VOICE_CREATE_CHANNEL_NAME,
                overwrites=build_vip_lobby_overwrites(guild),
                reason="Rename old VIP voice lobby",
            )
            return channel

    return await guild.create_voice_channel(
        name=VIP_VOICE_CREATE_CHANNEL_NAME,
        category=category,
        overwrites=build_vip_lobby_overwrites(guild),
        reason="Create VIP voice lobby",
    )


async def get_or_create_public_voice_lobby(guild: discord.Guild) -> discord.VoiceChannel | None:
    category = guild.get_channel(PLAY_VOICE_CATEGORY_ID)

    if category is None or not isinstance(category, discord.CategoryChannel):
        print("找不到公共語音類別，請確認 PLAY_VOICE_CATEGORY_ID 是否正確。")
        return None

    for channel in category.voice_channels:
        if channel.name == PUBLIC_VOICE_CREATE_CHANNEL_NAME:
            await channel.edit(
                overwrites=build_public_lobby_overwrites(guild),
                reason="Update public voice lobby permissions",
            )
            return channel

    return await guild.create_voice_channel(
        name=PUBLIC_VOICE_CREATE_CHANNEL_NAME,
        category=category,
        overwrites=build_public_lobby_overwrites(guild),
        reason="Create public voice lobby",
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



def is_temp_managed_voice_room(channel: discord.abc.GuildChannel | None) -> bool:
    if not isinstance(channel, discord.VoiceChannel):
        return False

    panel_data = TEMP_VOICE_CONTROL_PANELS.get(channel.id)
    if isinstance(panel_data, dict) and panel_data.get("room_type") in {"play", "vip", "public"}:
        return True

    return (
        is_temp_play_voice_room(channel)
        or (
            channel.name.startswith("👑┃")
            and channel.name.endswith("的𝙑𝙄𝙋頻道")
        )
        or (
            channel.name.startswith("➕┃")
            and channel.name.endswith("的公共房間")
        )
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
    if member.bot or not is_temp_managed_voice_room(voice_channel):
        return

    overwrite = voice_channel.overwrites_for(member)

    overwrite.view_channel = True
    overwrite.connect = True
    overwrite.speak = True
    overwrite.stream = True
    overwrite.use_voice_activation = True

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
            reason="Grant temporary voice room and chat access",
        )
    except discord.Forbidden:
        print("Bot 權限不足，無法給予語音房 / 聊天室臨時權限。")
    except discord.HTTPException as e:
        print(f"給予語音房 / 聊天室臨時權限失敗：{e}")


async def revoke_play_voice_room_chat_access(
    voice_channel: discord.VoiceChannel | None,
    member: discord.Member,
) -> None:
    if member.bot or not is_temp_managed_voice_room(voice_channel):
        return

    panel_data = TEMP_VOICE_CONTROL_PANELS.get(voice_channel.id, {})
    if isinstance(panel_data, dict) and int(panel_data.get("owner_id") or 0) == member.id:
        return

    if member in voice_channel.members:
        return

    overwrite = voice_channel.overwrites_for(member)

    overwrite.view_channel = None
    overwrite.connect = None
    overwrite.speak = None
    overwrite.stream = None
    overwrite.use_voice_activation = None

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
                reason="Revoke temporary voice room and chat access",
            )
        else:
            await voice_channel.set_permissions(
                member,
                overwrite=None,
                reason="Revoke temporary voice room and chat access",
            )
    except discord.Forbidden:
        print("Bot 權限不足，無法收回語音房 / 聊天室臨時權限。")
    except discord.HTTPException as e:
        print(f"收回語音房 / 聊天室臨時權限失敗：{e}")

def safe_voice_control_panel_name(member: discord.Member) -> str:
    display_name = member.display_name.strip() or member.name
    clean = "".join(c if c.isalnum() else "-" for c in display_name.lower())
    return f"遙控器-{clean}-{member.id}"[:90]


async def delete_voice_control_panel(guild: discord.Guild, voice_channel_id: int):
    # 控制面板現在直接發在語音房聊天室。
    # 語音房被刪除時，聊天室內容會一起消失，所以這裡只需要清掉暫存資料。
    TEMP_VOICE_CONTROL_PANELS.pop(voice_channel_id, None)



def get_room_targets_for_control(guild: discord.Guild, room_type: str) -> list[discord.abc.Snowflake]:
    normalized_room_type = str(room_type or "public")

    if normalized_room_type == "public":
        return [guild.default_role]

    if normalized_room_type == "vip":
        return get_vip_voice_allowed_roles(guild)

    if normalized_room_type == "play":
        return get_play_voice_allowed_roles(guild)

    return get_play_voice_allowed_roles(guild)



async def apply_voice_lock_state(
    voice_channel: discord.VoiceChannel,
    owner: discord.Member,
    *,
    locked: bool,
    room_type: str,
) -> None:
    """只切換 connect，不改 view_channel，避免鎖定時把隱藏狀態洗掉。"""
    guild = voice_channel.guild
    overwrites = dict(voice_channel.overwrites)
    normalized_room_type = str(room_type or "public")

    targets = get_room_targets_for_control(guild, normalized_room_type)

    for target in targets:
        overwrite = overwrites.get(target, discord.PermissionOverwrite())

        overwrite.connect = not locked
        overwrite.speak = True
        overwrite.stream = True
        overwrite.use_voice_activation = True
        overwrite.send_messages = True
        overwrite.read_message_history = True
        overwrite.attach_files = True
        overwrite.add_reactions = True
        overwrite.use_external_emojis = True
        overwrite.use_external_stickers = True

        if isinstance(target, discord.Role) and "is_receiver_voice_role" in globals() and is_receiver_voice_role(target):
            overwrite.move_members = True

        overwrites[target] = overwrite

    if normalized_room_type != "public":
        everyone_overwrite = overwrites.get(guild.default_role, discord.PermissionOverwrite())

        # 非公共房 @everyone 永遠不能連接；但不改 view_channel，避免影響隱藏/顯示。
        everyone_overwrite.connect = False
        everyone_overwrite.send_messages = False
        everyone_overwrite.read_message_history = False

        overwrites[guild.default_role] = everyone_overwrite

    # 上鎖時清掉之前因進房產生的個人 connect=True 權限；解鎖時不強制改 view_channel。
    for target, overwrite in list(overwrites.items()):
        if not isinstance(target, discord.Member):
            continue

        is_owner = target.id == owner.id
        is_bot = guild.me is not None and target.id == guild.me.id

        if is_owner or is_bot:
            continue

        if locked:
            overwrite.connect = False
            overwrites[target] = overwrite
        else:
            if overwrite.connect is False:
                overwrite.connect = None

            if not _overwrite_has_any_explicit_value(overwrite):
                overwrites.pop(target, None)
            else:
                overwrites[target] = overwrite

    owner_overwrite = overwrites.get(owner, discord.PermissionOverwrite())
    owner_overwrite.view_channel = True
    owner_overwrite.connect = True
    owner_overwrite.speak = True
    owner_overwrite.stream = True
    owner_overwrite.use_voice_activation = True
    owner_overwrite.send_messages = True
    owner_overwrite.read_message_history = True
    owner_overwrite.attach_files = True
    owner_overwrite.add_reactions = True
    owner_overwrite.use_external_emojis = True
    owner_overwrite.use_external_stickers = True
    overwrites[owner] = owner_overwrite

    bot_member = guild.me

    if bot_member is not None:
        bot_overwrite = overwrites.get(bot_member, discord.PermissionOverwrite())
        bot_overwrite.view_channel = True
        bot_overwrite.connect = True
        bot_overwrite.speak = True
        bot_overwrite.stream = True
        bot_overwrite.use_voice_activation = True
        bot_overwrite.move_members = True
        bot_overwrite.manage_channels = True
        bot_overwrite.send_messages = True
        bot_overwrite.read_message_history = True
        bot_overwrite.attach_files = True
        bot_overwrite.add_reactions = True
        bot_overwrite.use_external_emojis = True
        bot_overwrite.use_external_stickers = True
        overwrites[bot_member] = bot_overwrite

    await voice_channel.edit(
        overwrites=overwrites,
        reason=f"Voice room {'locked' if locked else 'unlocked'} by control panel",
    )


async def apply_voice_hidden_state(
    voice_channel: discord.VoiceChannel,
    owner: discord.Member,
    *,
    hidden: bool,
    room_type: str,
) -> None:
    """只切換 view_channel，不改 connect，避免隱藏時把鎖定狀態洗掉。"""
    guild = voice_channel.guild
    overwrites = dict(voice_channel.overwrites)
    normalized_room_type = str(room_type or "public")

    if normalized_room_type == "public":
        everyone_overwrite = overwrites.get(guild.default_role, discord.PermissionOverwrite())
        everyone_overwrite.view_channel = False if hidden else True

        # 公共房沒有鎖定時預設可進；這裡不強制解鎖，只在沒設定過 connect 時補預設值。
        if everyone_overwrite.connect is None:
            everyone_overwrite.connect = True

        everyone_overwrite.speak = True
        everyone_overwrite.stream = True
        everyone_overwrite.use_voice_activation = True
        everyone_overwrite.send_messages = True
        everyone_overwrite.read_message_history = True
        overwrites[guild.default_role] = everyone_overwrite

    else:
        everyone_overwrite = overwrites.get(guild.default_role, discord.PermissionOverwrite())
        everyone_overwrite.view_channel = False if hidden else True
        everyone_overwrite.connect = False
        everyone_overwrite.send_messages = False
        everyone_overwrite.read_message_history = False
        overwrites[guild.default_role] = everyone_overwrite

        targets = get_room_targets_for_control(guild, normalized_room_type)

        for target in targets:
            overwrite = overwrites.get(target, discord.PermissionOverwrite())

            overwrite.view_channel = False if hidden else True
            overwrite.speak = True
            overwrite.stream = True
            overwrite.use_voice_activation = True
            overwrite.send_messages = True
            overwrite.read_message_history = True
            overwrite.attach_files = True
            overwrite.add_reactions = True
            overwrite.use_external_emojis = True
            overwrite.use_external_stickers = True

            # 不改 connect，避免「隱藏」把已鎖定的房間打開。
            if overwrite.connect is None:
                overwrite.connect = True

            if isinstance(target, discord.Role) and "is_receiver_voice_role" in globals() and is_receiver_voice_role(target):
                overwrite.move_members = True

            overwrites[target] = overwrite

    owner_overwrite = overwrites.get(owner, discord.PermissionOverwrite())
    owner_overwrite.view_channel = True
    owner_overwrite.connect = True
    owner_overwrite.speak = True
    owner_overwrite.stream = True
    owner_overwrite.use_voice_activation = True
    owner_overwrite.send_messages = True
    owner_overwrite.read_message_history = True
    owner_overwrite.attach_files = True
    owner_overwrite.add_reactions = True
    owner_overwrite.use_external_emojis = True
    owner_overwrite.use_external_stickers = True
    overwrites[owner] = owner_overwrite

    bot_member = guild.me

    if bot_member is not None:
        bot_overwrite = overwrites.get(bot_member, discord.PermissionOverwrite())
        bot_overwrite.view_channel = True
        bot_overwrite.connect = True
        bot_overwrite.speak = True
        bot_overwrite.stream = True
        bot_overwrite.use_voice_activation = True
        bot_overwrite.move_members = True
        bot_overwrite.manage_channels = True
        bot_overwrite.send_messages = True
        bot_overwrite.read_message_history = True
        bot_overwrite.attach_files = True
        bot_overwrite.add_reactions = True
        bot_overwrite.use_external_emojis = True
        bot_overwrite.use_external_stickers = True
        overwrites[bot_member] = bot_overwrite

    await voice_channel.edit(
        overwrites=overwrites,
        reason=f"Voice room {'hidden' if hidden else 'shown'} by control panel",
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




def get_default_voice_room_locked(room_type: str) -> bool:
    """所有臨時語音房預設未鎖定；入口頻道權限不受影響。"""
    return False

def get_default_voice_room_hidden(room_type: str) -> bool:
    """所有臨時語音房剛建立都預設顯示。"""
    return False


def get_voice_channel_hidden_state(voice_channel: discord.VoiceChannel) -> bool:
    overwrite = voice_channel.overwrites_for(voice_channel.guild.default_role)
    return overwrite.view_channel is False


def get_voice_channel_locked_state(voice_channel: discord.VoiceChannel, room_type: str) -> bool:
    targets = get_room_targets_for_control(voice_channel.guild, room_type)

    if not targets:
        return get_default_voice_room_locked(room_type)

    for target in targets:
        overwrite = voice_channel.overwrites_for(target)
        if overwrite.connect is True:
            return False

    return True


def sync_voice_control_panel_state_from_channel(voice_channel: discord.VoiceChannel) -> dict:
    data = TEMP_VOICE_CONTROL_PANELS.setdefault(
        int(voice_channel.id),
        {
            "owner_id": None,
            "panel_channel_id": voice_channel.id,
            "panel_message_id": None,
            "room_type": "public",
            "locked": False,
            "hidden": False,
        },
    )

    room_type = str(data.get("room_type") or "public")
    data["hidden"] = get_voice_channel_hidden_state(voice_channel)
    data["locked"] = get_voice_channel_locked_state(voice_channel, room_type)

    return data


def get_voice_control_status_line(voice_channel_id: int) -> str:
    data = TEMP_VOICE_CONTROL_PANELS.get(int(voice_channel_id), {})

    locked = bool(data.get("locked", False))
    hidden = bool(data.get("hidden", False))

    lock_text = "🔒 已鎖定" if locked else "🔓 未鎖定"
    hidden_text = "🙈 已隱藏" if hidden else "👁️ 顯示中"

    return f"目前狀態：{lock_text}｜{hidden_text}"


def build_voice_control_base_lines(description: str | None) -> list[str]:
    lines: list[str] = []

    for raw_line in str(description or "").splitlines():
        line = raw_line.strip()

        if not line:
            continue
        if line.startswith("目前狀態："):
            continue
        if line.startswith("⚠"):
            continue
        if "當包廂內無人時" in line:
            continue

        lines.append(raw_line.rstrip())

    if len(lines) > 2:
        lines = lines[:2]

    return lines


def inject_voice_control_status_line(description: str | None, voice_channel_id: int) -> str:
    lines = build_voice_control_base_lines(description)

    if not lines:
        lines = ["歡迎來到您的專屬包廂！", "可以使用遙控器管理頻道。"]

    return chr(10).join([
        *lines,
        "",
        get_voice_control_status_line(voice_channel_id),
        "",
        "⚠️ 當包廂內無人時，將自動銷毀。",
    ])


def update_voice_control_embed_status(message: discord.Message | None, voice_channel_id: int) -> discord.Embed:
    if message and message.embeds:
        embed = message.embeds[0]
    else:
        embed = discord.Embed(title="專屬語音房")

    if message and isinstance(message.channel, discord.VoiceChannel):
        sync_voice_control_panel_state_from_channel(message.channel)

    embed.description = inject_voice_control_status_line(embed.description or "", voice_channel_id)
    return embed

class VoiceRoomControlView(discord.ui.View):
    def __init__(self, voice_channel_id: int, owner_id: int, room_type: str):
        super().__init__(timeout=None)
        self.voice_channel_id = int(voice_channel_id)
        self.owner_id = int(owner_id)
        self.room_type = room_type
        self.refresh_state_buttons()

    def refresh_state_buttons(self) -> None:
        data = TEMP_VOICE_CONTROL_PANELS.setdefault(
            int(self.voice_channel_id),
            {
                "owner_id": int(self.owner_id),
                "panel_channel_id": None,
                "room_type": self.room_type,
                "locked": get_default_voice_room_locked(self.room_type),
                "hidden": get_default_voice_room_hidden(self.room_type),
            },
        )

        locked = bool(data.get("locked", get_default_voice_room_locked(self.room_type)))
        hidden = bool(data.get("hidden", get_default_voice_room_hidden(self.room_type)))

        for child in self.children:
            if not isinstance(child, discord.ui.Button):
                continue

            custom_id = str(child.custom_id or "")

            if custom_id == "voice_room_lock_toggle":
                if locked:
                    child.label = "🔓 解鎖"
                    child.style = discord.ButtonStyle.danger
                else:
                    child.label = "🔒 鎖定"
                    child.style = discord.ButtonStyle.primary

            elif custom_id == "voice_room_visibility_toggle":
                if hidden:
                    child.label = "👁️ 顯示"
                    child.style = discord.ButtonStyle.success
                else:
                    child.label = "🙈 隱藏"
                    child.style = discord.ButtonStyle.secondary

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
        label="🔒 鎖定",
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
                "locked": get_default_voice_room_locked(self.room_type),
                "hidden": get_default_voice_room_hidden(self.room_type),
            }
        )
        sync_voice_control_panel_state_from_channel(voice_channel)
        data["locked"] = not data.get("locked", False)

        try:
            await apply_voice_lock_state(voice_channel, owner, locked=data["locked"], room_type=self.room_type)
        except discord.Forbidden:
            await interaction.response.send_message("Bot 權限不足，無法鎖定/解鎖語音房。", ephemeral=True)
            return
        except discord.HTTPException as e:
            await interaction.response.send_message(f"鎖定/解鎖失敗：{e}", ephemeral=True)
            return

        sync_voice_control_panel_state_from_channel(voice_channel)
        self.refresh_state_buttons()
        await interaction.response.edit_message(
            embed=update_voice_control_embed_status(interaction.message, self.voice_channel_id),
            view=self,
        )

    @discord.ui.button(
        label="🙈 隱藏",
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
                "locked": get_default_voice_room_locked(self.room_type),
                "hidden": get_default_voice_room_hidden(self.room_type),
            }
        )
        sync_voice_control_panel_state_from_channel(voice_channel)
        data["hidden"] = not data.get("hidden", False)

        try:
            await apply_voice_hidden_state(voice_channel, owner, hidden=data["hidden"], room_type=self.room_type)
        except discord.Forbidden:
            await interaction.response.send_message("Bot 權限不足，無法隱藏/顯示語音房。", ephemeral=True)
            return
        except discord.HTTPException as e:
            await interaction.response.send_message(f"隱藏/顯示失敗：{e}", ephemeral=True)
            return

        sync_voice_control_panel_state_from_channel(voice_channel)
        self.refresh_state_buttons()
        await interaction.response.edit_message(
            embed=update_voice_control_embed_status(interaction.message, self.voice_channel_id),
            view=self,
        )

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



async def sync_temp_voice_room_permissions_on_create(
    voice_channel: discord.VoiceChannel,
    owner: discord.Member,
    room_type: str,
) -> None:
    """建立臨時語音房後，強制寫入最新角色權限；不影響入口頻道。"""
    normalized_room_type = str(room_type or "public")

    if normalized_room_type == "public":
        overwrites = build_public_voice_overwrites(voice_channel.guild)
    elif normalized_room_type == "vip":
        overwrites = build_vip_room_overwrites(voice_channel.guild, owner)
    else:
        overwrites = build_play_voice_overwrites(voice_channel.guild)

    try:
        await voice_channel.edit(
            overwrites=overwrites,
            reason="Sync temporary voice room permissions on create",
        )
    except discord.Forbidden:
        print(f"Bot 權限不足，無法同步語音房權限：{voice_channel.name} ({voice_channel.id})")
    except discord.HTTPException as exc:
        print(f"同步語音房權限失敗：{voice_channel.name} ({voice_channel.id}) {exc}")

async def create_voice_control_panel(
    guild: discord.Guild,
    category: discord.CategoryChannel,
    member: discord.Member,
    voice_channel: discord.VoiceChannel,
    room_type: str,
):
    TEMP_VOICE_CONTROL_PANELS[voice_channel.id] = {
        "owner_id": member.id,
        "panel_channel_id": voice_channel.id,
        "panel_message_id": None,
        "room_type": room_type,
        "locked": get_default_voice_room_locked(room_type),
        "hidden": get_default_voice_room_hidden(room_type),
    }

    await sync_temp_voice_room_permissions_on_create(voice_channel, member, room_type)
    await grant_play_voice_room_chat_access(voice_channel, member)
    sync_voice_control_panel_state_from_channel(voice_channel)

    embed = discord.Embed(
        title="專屬語音房",
        description=(
            f"歡迎來到您的專屬包廂！{member.mention}\n"
            "可以使用遙控器管理頻道。\n\n"
            "⚠️ 當包廂內無人時，將自動銷毀。"
        ),
        color=discord.Color.purple(),
    )

    embed.description = inject_voice_control_status_line(embed.description or "", voice_channel.id)

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
        ),
    )

    TEMP_VOICE_CONTROL_PANELS[voice_channel.id]["panel_message_id"] = message.id

