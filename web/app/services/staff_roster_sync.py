# -*- coding: utf-8 -*-

from __future__ import annotations

import json
import sqlite3
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


ROOT = (
    Path(
        __file__
    )
    .resolve()
    .parents[3]
)

WEB_DB = (
    ROOT
    / "web_dashboard.db"
)


SERVICE_ROLE_PRIORITY = (
    "top_protector",
    "female_protector",
    "male_protector",
    "female_companion",
    "male_companion",
    "lol_elite",
    "lol_grandmaster",
    "lol_master",
    "apex_predator",
    "apex_master",
    "apex_diamond",
    "valorant_radiant",
    "valorant_immortal",
    "valorant_ascendant",
)


FALLBACK_ROLE_TITLE = {
    "top_protector":
        "頂護",

    "female_protector":
        "女護",

    "male_protector":
        "男護",

    "female_companion":
        "女陪",

    "male_companion":
        "男陪",

    "lol_elite":
        "菁英",

    "lol_grandmaster":
        "宗師",

    "lol_master":
        "LOL 大師",

    "apex_predator":
        "頂獵",

    "apex_master":
        "APEX 大師",

    "apex_diamond":
        "鑽石",

    "valorant_radiant":
        "輻能",

    "valorant_immortal":
        "神話",

    "valorant_ascendant":
        "超凡",
}


FALLBACK_PROFILE_TYPE = {
    "top_protector":
        "protector",

    "female_protector":
        "protector",

    "male_protector":
        "protector",

    "female_companion":
        "companion",

    "male_companion":
        "companion",

    "lol_elite":
        "game",

    "lol_grandmaster":
        "game",

    "lol_master":
        "game",

    "apex_predator":
        "game",

    "apex_master":
        "game",

    "apex_diamond":
        "game",

    "valorant_radiant":
        "game",

    "valorant_immortal":
        "game",

    "valorant_ascendant":
        "game",
}


def _json_list(
    value: Any,
) -> list[str]:

    if value is None:

        return []


    if isinstance(
        value,
        list,
    ):

        return [
            str(x)

            for x
            in value

            if str(
                x
            ).strip()
        ]


    try:

        parsed = json.loads(
            str(
                value
            )
        )

    except Exception:

        return []


    if not isinstance(
        parsed,
        list,
    ):

        return []


    return [
        str(x)

        for x
        in parsed

        if str(
            x
        ).strip()
    ]


def _columns(
    conn: sqlite3.Connection,
    table: str,
):

    return {
        str(
            row[1]
        ):
            {
                "type":
                    str(
                        row[2]
                        or ""
                    ),

                "notnull":
                    bool(
                        row[3]
                    ),

                "default":
                    row[4],

                "pk":
                    bool(
                        row[5]
                    ),
            }

        for row
        in conn.execute(
            f"PRAGMA table_info({table})"
        ).fetchall()
    }


def _table_exists(
    conn: sqlite3.Connection,
    table: str,
) -> bool:

    row = conn.execute(
        "SELECT 1 "
        "FROM sqlite_master "
        "WHERE type='table' "
        "AND name=? "
        "LIMIT 1",
        (
            table,
        ),
    ).fetchone()


    return (
        row
        is not None
    )


def _choose_service_role(
    role_ids,
    *,
    role_ids_by_key,
):

    role_ids = {
        str(x)

        for x
        in (
            role_ids
            or []
        )
    }


    for role_key in (
        SERVICE_ROLE_PRIORITY
    ):

        role_id = str(
            role_ids_by_key.get(
                role_key
            )
            or ""
        )


        if (
            role_id
            and role_id
            in role_ids
        ):

            return role_key


    return None


def _display_name_from_row(
    row,
    columns,
    staff_id,
):

    for field in (
        "display_name",
        "global_name",
        "username",
    ):

        if field not in columns:

            continue


        value = str(
            row[
                field
            ]
            or ""
        ).strip()


        if value:

            return value


    return str(
        staff_id
    )


def _required_fallback(
    column_name,
    column_meta,
):

    column_type = str(
        column_meta.get(
            "type"
        )
        or ""
    ).upper()


    if (
        "INT"
        in column_type
        or "REAL"
        in column_type
        or "NUM"
        in column_type
    ):

        return 0


    if column_name.startswith(
        "is_"
    ):

        return 0


    return ""


def _infer_profile_defaults(
    conn,
    *,
    role_ids_by_key,
):

    result = {
        role_key: {
            "profile_type":
                None,

            "role_title":
                None,
        }

        for role_key
        in SERVICE_ROLE_PRIORITY
    }


    if (
        not _table_exists(
            conn,
            "staff_profiles",
        )
        or not _table_exists(
            conn,
            "web_staff_members",
        )
    ):

        return result


    profile_cols = (
        _columns(
            conn,
            "staff_profiles",
        )
    )


    member_cols = (
        _columns(
            conn,
            "web_staff_members",
        )
    )


    if (
        "staff_discord_id"
        not in profile_cols
        or "discord_id"
        not in member_cols
        or "roles_json"
        not in member_cols
    ):

        return result


    select_parts = [
        "p.staff_discord_id",
        "m.roles_json",
    ]


    if (
        "profile_type"
        in profile_cols
    ):

        select_parts.append(
            "p.profile_type"
        )


    if (
        "role_title"
        in profile_cols
    ):

        select_parts.append(
            "p.role_title"
        )


    rows = conn.execute(
        "SELECT "
        + ", ".join(
            select_parts
        )
        + " FROM staff_profiles p "
        + "JOIN web_staff_members m "
        + "ON CAST(m.discord_id AS TEXT)="
        + "CAST(p.staff_discord_id AS TEXT)"
    ).fetchall()


    profile_types = defaultdict(
        Counter
    )


    role_titles = defaultdict(
        Counter
    )


    for row in rows:

        role_key = (
            _choose_service_role(
                _json_list(
                    row[
                        "roles_json"
                    ]
                ),
                role_ids_by_key=
                    role_ids_by_key,
            )
        )


        if not role_key:

            continue


        if (
            "profile_type"
            in profile_cols
        ):

            value = str(
                row[
                    "profile_type"
                ]
                or ""
            ).strip()


            if value:

                profile_types[
                    role_key
                ][
                    value
                ] += 1


        if (
            "role_title"
            in profile_cols
        ):

            value = str(
                row[
                    "role_title"
                ]
                or ""
            ).strip()


            if value:

                role_titles[
                    role_key
                ][
                    value
                ] += 1


    for role_key in (
        SERVICE_ROLE_PRIORITY
    ):

        if profile_types[
            role_key
        ]:

            result[
                role_key
            ][
                "profile_type"
            ] = (
                profile_types[
                    role_key
                ].most_common(
                    1
                )[0][0]
            )


        if role_titles[
            role_key
        ]:

            result[
                role_key
            ][
                "role_title"
            ] = (
                role_titles[
                    role_key
                ].most_common(
                    1
                )[0][0]
            )


    return result


def ensure_staff_roster_profiles(
) -> dict:

    if not WEB_DB.exists():

        return {
            "created":
                0,

            "expected":
                0,

            "existing":
                0,

            "hidden":
                0,

            "created_staff":
                [],
        }


    from services.order_rules import (
        ROLE_IDS,
    )
    from services.game_roles import (
        GAME_ROLE_BY_KEY,
    )


    role_ids_by_key = {
        key:
            str(
                ROLE_IDS[
                    key
                ]
            )

        for key
        in SERVICE_ROLE_PRIORITY

        if key
        in ROLE_IDS
    }

    for key in (
        SERVICE_ROLE_PRIORITY
    ):
        game_role = (
            GAME_ROLE_BY_KEY.get(
                key
            )
        )

        if game_role is not None:
            role_ids_by_key[
                key
            ] = str(
                game_role.role_id
            )


    if not role_ids_by_key:

        raise RuntimeError(
            "找不到服務身分組設定。"
        )


    conn = sqlite3.connect(
        WEB_DB
    )

    conn.row_factory = (
        sqlite3.Row
    )


    try:

        if (
            not _table_exists(
                conn,
                "web_staff_members",
            )
            or not _table_exists(
                conn,
                "staff_profiles",
            )
        ):

            raise RuntimeError(
                "陪玩陣容資料表不存在。"
            )


        member_cols = (
            _columns(
                conn,
                "web_staff_members",
            )
        )


        profile_cols = (
            _columns(
                conn,
                "staff_profiles",
            )
        )


        required_member_cols = {
            "discord_id",
            "roles_json",
        }


        if not required_member_cols.issubset(
            member_cols
        ):

            raise RuntimeError(
                "web_staff_members "
                "缺少 discord_id / roles_json。"
            )


        if (
            "staff_discord_id"
            not in profile_cols
        ):

            raise RuntimeError(
                "staff_profiles "
                "缺少 staff_discord_id。"
            )


        select_fields = [
            "discord_id",
            "roles_json",
        ]


        for optional in (
            "display_name",
            "global_name",
            "username",
        ):

            if optional in member_cols:

                select_fields.append(
                    optional
                )


        where_sql = ""


        if (
            "is_active"
            in member_cols
        ):

            where_sql = (
                " WHERE "
                "COALESCE(is_active,1)=1"
            )


        member_rows = conn.execute(
            "SELECT "
            + ", ".join(
                select_fields
            )
            + " FROM web_staff_members"
            + where_sql
        ).fetchall()


        expected = []


        for row in member_rows:

            role_key = (
                _choose_service_role(
                    _json_list(
                        row[
                            "roles_json"
                        ]
                    ),
                    role_ids_by_key=
                        role_ids_by_key,
                )
            )


            if not role_key:

                continue


            staff_id = str(
                row[
                    "discord_id"
                ]
            )


            expected.append(
                {
                    "staff_id":
                        staff_id,

                    "display_name":
                        _display_name_from_row(
                            row,
                            member_cols,
                            staff_id,
                        ),

                    "role_key":
                        role_key,
                }
            )


        existing_rows = conn.execute(
            "SELECT staff_discord_id"
            + (
                ", is_public"
                if "is_public"
                in profile_cols
                else ""
            )
            + " FROM staff_profiles"
        ).fetchall()


        existing_ids = {
            str(
                row[
                    "staff_discord_id"
                ]
            )

            for row
            in existing_rows
        }


        hidden_ids = set()


        if (
            "is_public"
            in profile_cols
        ):

            for row in existing_rows:

                if (
                    int(
                        row[
                            "is_public"
                        ]
                        or 0
                    )
                    == 0
                ):

                    hidden_ids.add(
                        str(
                            row[
                                "staff_discord_id"
                            ]
                        )
                    )


        inferred = (
            _infer_profile_defaults(
                conn,
                role_ids_by_key=
                    role_ids_by_key,
            )
        )


        created_staff = []


        for item in expected:

            staff_id = item[
                "staff_id"
            ]


            if staff_id in existing_ids:

                continue


            role_key = item[
                "role_key"
            ]


            values = {
                "staff_discord_id":
                    staff_id,
            }


            if (
                "display_name"
                in profile_cols
            ):

                values[
                    "display_name"
                ] = item[
                    "display_name"
                ]


            if (
                "profile_type"
                in profile_cols
            ):

                values[
                    "profile_type"
                ] = (
                    inferred[
                        role_key
                    ][
                        "profile_type"
                    ]
                    or FALLBACK_PROFILE_TYPE[
                        role_key
                    ]
                )


            if (
                "role_title"
                in profile_cols
            ):

                values[
                    "role_title"
                ] = (
                    inferred[
                        role_key
                    ][
                        "role_title"
                    ]
                    or FALLBACK_ROLE_TITLE[
                        role_key
                    ]
                )


            if (
                "is_public"
                in profile_cols
            ):

                values[
                    "is_public"
                ] = 1


            if (
                "sort_score"
                in profile_cols
            ):

                values[
                    "sort_score"
                ] = 0


            for field in (
                "main_games",
                "service_tags",
                "bio",
                "card_image_url",
                "forum",
            ):

                if field in profile_cols:

                    values[
                        field
                    ] = ""


            # Fill any schema-specific mandatory field
            # we don't know about, without touching PKs.
            for (
                column_name,
                meta
            ) in profile_cols.items():

                if (
                    column_name
                    in values
                    or meta[
                        "pk"
                    ]
                    or not meta[
                        "notnull"
                    ]
                    or meta[
                        "default"
                    ]
                    is not None
                ):

                    continue


                values[
                    column_name
                ] = (
                    _required_fallback(
                        column_name,
                        meta,
                    )
                )


            columns_sql = (
                ", ".join(
                    values.keys()
                )
            )


            placeholders = (
                ", ".join(
                    "?"

                    for _
                    in values
                )
            )


            conn.execute(
                "INSERT INTO staff_profiles "
                f"({columns_sql}) "
                f"VALUES ({placeholders})",
                tuple(
                    values.values()
                ),
            )


            existing_ids.add(
                staff_id
            )


            created_staff.append(
                {
                    "staff_id":
                        staff_id,

                    "display_name":
                        item[
                            "display_name"
                        ],

                    "role_key":
                        role_key,

                    "role_title":
                        FALLBACK_ROLE_TITLE[
                            role_key
                        ],
                }
            )


        conn.commit()


        return {
            "created":
                len(
                    created_staff
                ),

            "expected":
                len(
                    expected
                ),

            "existing":
                len(
                    existing_ids
                ),

            "hidden":
                len(
                    hidden_ids
                    & {
                        item[
                            "staff_id"
                        ]

                        for item
                        in expected
                    }
                ),

            "created_staff":
                created_staff,
        }


    finally:

        conn.close()
