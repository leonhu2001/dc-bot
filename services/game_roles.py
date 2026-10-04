from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class GameRole:
    key: str
    game: str
    role_id: str
    label: str
    kind: str = "identity"


# ============================================================
# 遊戲資格身分組
#
# identity = 遊戲 / 平台身分，例如 APEX、三角洲<端遊>
# rank     = 遊戲階級資格，例如 頂獵、輻能、菁英
#
# 店內服務職位（頂護 / 女護 / 男護 / 男陪 / 女陪）不屬於遊戲身分，
# 由 role_catalog / order_rules 的 allowed_roles 獨立處理。
# ============================================================

GAME_ROLES: tuple[GameRole, ...] = (
    # Delta Force identities
    GameRole(
        key="delta_desktop",
        game="delta_force",
        role_id="1555453406041088131",
        label="三角洲<端遊>",
        kind="identity",
    ),
    GameRole(
        key="delta_mobile",
        game="delta_force",
        role_id="1555453449066254417",
        label="三角洲<手遊>",
        kind="identity",
    ),

    # Steam identity
    GameRole(
        key="steam_game",
        game="steam",
        role_id="1555629210922516590",
        label="Steam",
        kind="identity",
    ),

    # League of Legends
    GameRole(
        key="lol_game",
        game="lol",
        role_id="1555629055553048627",
        label="英雄聯盟",
        kind="identity",
    ),
    GameRole(
        key="lol_elite",
        game="lol",
        role_id="1545362618649284669",
        label="魔丸♛菁英",
        kind="rank",
    ),
    GameRole(
        key="lol_grandmaster",
        game="lol",
        role_id="1545362642322071642",
        label="魔丸♜宗師",
        kind="rank",
    ),
    GameRole(
        key="lol_master",
        game="lol",
        role_id="1545362644607832065",
        label="魔丸♞大師",
        kind="rank",
    ),

    # APEX Legends
    GameRole(
        key="apex_game",
        game="apex",
        role_id="1555628951336910968",
        label="APEX",
        kind="identity",
    ),
    GameRole(
        key="apex_predator",
        game="apex",
        role_id="1545364166834135100",
        label="魔丸♛頂獵",
        kind="rank",
    ),
    GameRole(
        key="apex_master",
        game="apex",
        role_id="1545364180905885746",
        label="魔丸♜大師",
        kind="rank",
    ),
    GameRole(
        key="apex_diamond",
        game="apex",
        role_id="1545364182273105951",
        label="魔丸♞鑽石",
        kind="rank",
    ),

    # Valorant
    GameRole(
        key="valorant_game",
        game="valorant",
        role_id="1555629001102598224",
        label="特戰英豪",
        kind="identity",
    ),
    GameRole(
        key="valorant_radiant",
        game="valorant",
        role_id="1545357782906314782",
        label="魔丸♛輻能",
        kind="rank",
    ),
    GameRole(
        key="valorant_immortal",
        game="valorant",
        role_id="1545359591582470164",
        label="魔丸♜神話",
        kind="rank",
    ),
    GameRole(
        key="valorant_ascendant",
        game="valorant",
        role_id="1545359674549993573",
        label="魔丸♞超凡",
        kind="rank",
    ),
)


# 舊資料曾把三角洲服務職位誤當成 game role。
# 保留 key 查詢相容性，但不放入 GAME_ROLES，因此不會再顯示在
# 「遊戲身分」或「階級資格」清單，也不會被當成遊戲資格。
LEGACY_GAME_ROLE_ALIASES: tuple[GameRole, ...] = (
    GameRole(
        key="delta_top_protector",
        game="delta_force",
        role_id="1500234130871550004",
        label="魔丸♛頂護",
        kind="service_alias",
    ),
    GameRole(
        key="delta_female_protector",
        game="delta_force",
        role_id="1500234170943934544",
        label="魔丸♝女護",
        kind="service_alias",
    ),
    GameRole(
        key="delta_male_protector",
        game="delta_force",
        role_id="1500751039060643990",
        label="魔丸♜男護",
        kind="service_alias",
    ),
)


GAME_IDENTITY_ROLES: tuple[GameRole, ...] = tuple(
    role for role in GAME_ROLES if role.kind == "identity"
)
GAME_RANK_ROLES: tuple[GameRole, ...] = tuple(
    role for role in GAME_ROLES if role.kind == "rank"
)

GAME_ROLE_BY_ID: dict[str, GameRole] = {
    role.role_id: role
    for role in GAME_ROLES
}

GAME_ROLE_BY_KEY: dict[str, GameRole] = {
    role.key: role
    for role in (*GAME_ROLES, *LEGACY_GAME_ROLE_ALIASES)
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
    訂單指定哪些遊戲身分 / 階級可以接時使用。

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
    "GAME_IDENTITY_ROLES",
    "GAME_RANK_ROLES",
    "LEGACY_GAME_ROLE_ALIASES",
    "GAME_ROLE_BY_ID",
    "GAME_ROLE_BY_KEY",
    "GAME_ROLE_IDS",
    "GAME_ROLE_LABEL_BY_ID",
    "game_roles_from_role_ids",
    "game_role_labels_from_role_ids",
    "has_any_game_role",
    "has_any_allowed_game_role",
]
