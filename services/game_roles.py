from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class GameRole:
    key: str
    game: str
    role_id: str
    label: str


# ============================================================
# 遊戲身分組
#
# 注意：
# 1. 這裡只負責「辨識身分組」
# 2. 不代表任何階級高低
# 3. 不會自動取得任何接單權限
# 4. 哪張單能由哪些身分組接，之後由訂單規則另外指定
# ============================================================

GAME_ROLES: tuple[GameRole, ...] = (
    # League of Legends
    GameRole(
        key="lol_elite",
        game="lol",
        role_id="1545362618649284669",
        label="魔丸♛菁英",
    ),
    GameRole(
        key="lol_grandmaster",
        game="lol",
        role_id="1545362642322071642",
        label="魔丸♜宗師",
    ),
    GameRole(
        key="lol_master",
        game="lol",
        role_id="1545362644607832065",
        label="魔丸♞大師",
    ),

    # APEX Legends
    GameRole(
        key="apex_predator",
        game="apex",
        role_id="1545364166834135100",
        label="魔丸♛頂獵",
    ),
    GameRole(
        key="apex_master",
        game="apex",
        role_id="1545364180905885746",
        label="魔丸♜大師",
    ),
    GameRole(
        key="apex_diamond",
        game="apex",
        role_id="1545364182273105951",
        label="魔丸♞鑽石",
    ),

    # 特戰英豪
    GameRole(
        key="valorant_radiant",
        game="valorant",
        role_id="1545357782906314782",
        label="魔丸♛輻能",
    ),
    GameRole(
        key="valorant_immortal",
        game="valorant",
        role_id="1545359591582470164",
        label="魔丸♜神話",
    ),
    GameRole(
        key="valorant_ascendant",
        game="valorant",
        role_id="1545359674549993573",
        label="魔丸♞超凡",
    ),
)


GAME_ROLE_BY_ID: dict[str, GameRole] = {
    role.role_id: role
    for role in GAME_ROLES
}

GAME_ROLE_BY_KEY: dict[str, GameRole] = {
    role.key: role
    for role in GAME_ROLES
}

GAME_ROLE_IDS: set[str] = set(GAME_ROLE_BY_ID)

GAME_ROLE_LABEL_BY_ID: dict[str, str] = {
    role.role_id: role.label
    for role in GAME_ROLES
}


def normalize_role_ids(value) -> set[str]:
    if not value:
        return set()

    if isinstance(value, (list, tuple, set)):
        return {
            str(item).strip()
            for item in value
            if str(item).strip()
        }

    return {
        item.strip()
        for item in str(value).split(",")
        if item.strip()
    }


def game_roles_from_role_ids(role_ids) -> list[GameRole]:
    role_set = normalize_role_ids(role_ids)

    return [
        role
        for role in GAME_ROLES
        if role.role_id in role_set
    ]


def game_role_labels_from_role_ids(role_ids) -> list[str]:
    return [
        role.label
        for role in game_roles_from_role_ids(role_ids)
    ]


def has_any_game_role(role_ids) -> bool:
    return bool(
        normalize_role_ids(role_ids)
        & GAME_ROLE_IDS
    )


def has_any_allowed_game_role(
    role_ids,
    allowed_role_ids,
) -> bool:
    """
    之後訂單指定哪些遊戲身分組可以接時使用。

    例如：
        has_any_allowed_game_role(
            member_role_ids,
            {
                "1545357782906314782",
                "1545359591582470164",
            },
        )

    只有使用者實際持有指定 Role ID 才會回傳 True。
    不存在任何階級繼承或自動放行。
    """

    member_roles = normalize_role_ids(role_ids)
    allowed_roles = normalize_role_ids(allowed_role_ids)

    if not allowed_roles:
        return True

    return bool(member_roles & allowed_roles)


__all__ = [
    "GameRole",
    "GAME_ROLES",
    "GAME_ROLE_BY_ID",
    "GAME_ROLE_BY_KEY",
    "GAME_ROLE_IDS",
    "GAME_ROLE_LABEL_BY_ID",
    "game_roles_from_role_ids",
    "game_role_labels_from_role_ids",
    "has_any_game_role",
    "has_any_allowed_game_role",
]
