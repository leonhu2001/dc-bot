from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

from core.vip_levels import has_active_vip_progress_reset


ROOT_DIR = Path(__file__).resolve().parents[3]

BOT_DB = ROOT_DIR / "bot.db"
WEB_DB = ROOT_DIR / "web_dashboard.db"


VIP_LEVELS_PUBLIC = [
    {
        "key": "silver",
        "name": "銀級魔丸",
        "threshold": 2000,
        "benefits": [
            "專屬 VIP 身分組，可使用 VIP 專屬包廂",
        ],
    },
    {
        "key": "gold",
        "name": "金級魔丸",
        "threshold": 6000,
        "benefits": [
            "享有銀級魔丸所有福利",
            "優先客服回覆",
            "體驗單、趣味單外全館 98 折",
            "可根據闆闆要求製作「自訂單」",
        ],
    },
    {
        "key": "platinum",
        "name": "白金魔丸",
        "threshold": 12000,
        "benefits": [
            "享有金級魔丸所有福利",
            "可建立 VIP 專屬私人文字頻道",
            "儲值返利 2%",
            "每月一張折現券 200T",
            "優先排單",
        ],
    },
    {
        "key": "diamond",
        "name": "鑽石魔丸",
        "threshold": 25000,
        "benefits": [
            "享有白金魔丸所有福利",
            "優先安排熟悉打手",
            "儲值返利 3%",
            "體驗單、趣味單外全館 96 折",
        ],
    },
    {
        "key": "white_diamond",
        "name": "白鑽魔丸",
        "threshold": 50000,
        "benefits": [
            "享有鑽石魔丸所有福利",
            "儲值返利 4%",
            "每月額外一張折現券 500T",
        ],
    },
    {
        "key": "black_diamond",
        "name": "黑鑽魔丸",
        "threshold": 88888,
        "benefits": [
            "享有白鑽魔丸所有福利",
            "每月一次免費「機密航天保底 1000w」",
            "儲值返利 5%",
            "體驗單、趣味單外全館 94 折",
        ],
    },
]


VIP_CUSTOM_ORDER_RULES = [
    "闆闆自由開發。",
    "須提供規則、內容、機制、玩法、方案。",
]


VIP_REBATE_RULES = [
    "儲值後如需退款，僅能退錢包總金額的 95%。",
    "儲值達 VIP 標準也可使用返利，但若後續取出致使額度未到仍會降級。",
]


VIP_PRIVATE_CHANNEL_RULES = [
    "白金以上 VIP 可申請一間能與指定打手們聊天的專屬文字頻道。",
    "頻道成員包含：VIP 客人、指定打手、客服。",
    "付款、改單、退款、售後皆須由客服確認。",
    "禁止私下交易、私下收款、私自改價，違者將取消相關福利。",
]


VIP_GENERAL_RULES = [
    "高等級 VIP 可享有所有低等級福利。",
    "VIP 等級依累積有效消費金額計算。",
    "每月消費可維持當前 VIP 等級。",
    "若當月未消費，次月將下降一階。",
    "鑽石以上會員每 3 個月享有一次保級寬限。",
    "體驗單、趣味單不適用 VIP 折扣。",
    "VIP 折扣不可與其他優惠、折扣碼併用。",
    "所有 VIP 福利不得轉讓、折現或累積至下月。",
    "本店保有活動內容調整與最終解釋權。",
]


ALL_MEMBER_LEVEL_NAMES = [
    "普通魔丸",
    *[
        level["name"]
        for level in VIP_LEVELS_PUBLIC
    ],
]


def normalize_public_text(
    value: Any,
) -> str:
    text = str(
        value or ""
    ).strip()

    # Public website terminology.
    # Do not expose the old wording.
    text = text.replace(
        "\u8b77\u7d1a",
        "\u8b77\u822a",
    )

    return text


def format_t(
    value: Any,
) -> str:
    try:
        amount = int(
            value or 0
        )
    except (
        TypeError,
        ValueError,
    ):
        amount = 0

    return f"{amount:,}T"


def format_date(
    value: Any,
) -> str:
    text = str(
        value or ""
    ).strip()

    if not text:
        return "\u2014"

    text = text.replace(
        "T",
        " ",
    )

    if "+" in text:
        text = text.split(
            "+",
            1,
        )[0]

    return (
        text[:16]
        .replace(
            "-",
            "/",
        )
    )


def _connect(
    path: Path,
) -> sqlite3.Connection:
    conn = sqlite3.connect(
        path,
        timeout=15,
    )

    conn.row_factory = sqlite3.Row

    return conn


def _table_exists(
    conn: sqlite3.Connection,
    table: str,
) -> bool:
    row = conn.execute(
        """
        SELECT name
        FROM sqlite_master
        WHERE type = 'table'
          AND name = ?
        """,
        (
            str(table),
        ),
    ).fetchone()

    return row is not None


def _columns(
    conn: sqlite3.Connection,
    table: str,
) -> set[str]:
    if not _table_exists(
        conn,
        table,
    ):
        return set()

    return {
        str(row["name"])
        for row
        in conn.execute(
            f"PRAGMA table_info({table})"
        ).fetchall()
    }


def _json_dict(
    value: Any,
) -> dict:
    if isinstance(
        value,
        dict,
    ):
        return dict(value)

    text = str(
        value or ""
    ).strip()

    if not text:
        return {}

    try:
        data = json.loads(
            text
        )
    except Exception:
        return {}

    if isinstance(
        data,
        dict,
    ):
        return data

    return {}


def _safe_int(
    value: Any,
    default: int = 0,
) -> int:
    try:
        return int(
            value
            if value is not None
            else default
        )
    except (
        TypeError,
        ValueError,
    ):
        return default


def _derive_vip_name(
    total_spent: int,
) -> str:
    name = "普通魔丸"

    for level in VIP_LEVELS_PUBLIC:
        if total_spent >= int(
            level["threshold"]
        ):
            name = str(
                level["name"]
            )

    return name


def _vip_index_from_total(
    total_spent: int,
) -> int:
    index = 0

    for level_index, level in enumerate(
        VIP_LEVELS_PUBLIC,
        start=1,
    ):
        if total_spent >= int(
            level["threshold"]
        ):
            index = level_index
        else:
            break

    return index


def _stored_vip_index(
    customer_data: dict,
    total_spent: int,
) -> int:
    index = _safe_int(
        customer_data.get(
            "vip_level_index"
        ),
        None,
    )

    if index is None:
        level_name = normalize_public_text(
            customer_data.get(
                "level"
            )
        )

        if level_name in ALL_MEMBER_LEVEL_NAMES:
            index = ALL_MEMBER_LEVEL_NAMES.index(
                level_name
            )
        elif level_name in {
            "無會員",
            "無",
        }:
            index = 0
        else:
            index = _vip_index_from_total(
                total_spent
            )

    return max(
        0,
        min(
            int(index),
            len(ALL_MEMBER_LEVEL_NAMES) - 1,
        ),
    )


def _effective_vip_index(
    customer_data: dict,
) -> int:
    total_spent = max(
        0,
        _safe_int(
            customer_data.get(
                "total_spent"
            )
        ),
    )

    cumulative_index = _vip_index_from_total(
        total_spent
    )
    stored_index = _stored_vip_index(
        customer_data,
        total_spent,
    )

    if stored_index >= cumulative_index:
        return stored_index

    base_total = _safe_int(
        customer_data.get(
            "vip_progress_base_total_spent"
        ),
        None,
    )

    # 舊版正常升級也可能殘留 base_total；只有真正 reset 才重算進度。
    if not has_active_vip_progress_reset(customer_data):
        return cumulative_index

    earned_after_reset = max(
        0,
        total_spent - int(base_total or 0),
    )

    if stored_index <= 0:
        current_threshold = 0
    else:
        current_threshold = int(
            VIP_LEVELS_PUBLIC[
                stored_index - 1
            ]["threshold"]
        )

    virtual_total = (
        current_threshold
        + earned_after_reset
    )

    progressed_index = _vip_index_from_total(
        virtual_total
    )

    return max(
        stored_index,
        min(
            progressed_index,
            len(ALL_MEMBER_LEVEL_NAMES) - 1,
        ),
    )


def _resolve_vip_name(
    customer_data: dict,
) -> str:
    return ALL_MEMBER_LEVEL_NAMES[
        _effective_vip_index(
            customer_data
        )
    ]


def _vip_progress(
    customer_data: dict,
) -> dict:
    total_spent = max(
        0,
        _safe_int(
            customer_data.get(
                "total_spent"
            )
        ),
    )

    current_index = _effective_vip_index(
        customer_data
    )

    if current_index >= len(
        VIP_LEVELS_PUBLIC
    ):
        return {
            "next_name": None,
            "next_threshold": None,
            "remaining": 0,
            "percent": 100,
        }

    next_level = VIP_LEVELS_PUBLIC[
        current_index
    ]
    next_threshold = int(
        next_level["threshold"]
    )

    if current_index <= 0:
        current_threshold = 0
    else:
        current_threshold = int(
            VIP_LEVELS_PUBLIC[
                current_index - 1
            ]["threshold"]
        )

    span = max(
        1,
        next_threshold
        - current_threshold,
    )

    stored_index = _stored_vip_index(
        customer_data,
        total_spent,
    )
    cumulative_index = _vip_index_from_total(
        total_spent
    )
    base_total = _safe_int(
        customer_data.get(
            "vip_progress_base_total_spent"
        ),
        None,
    )

    active_reset = (
        has_active_vip_progress_reset(
            customer_data
        )
    )

    if active_reset:
        progress_value = max(
            0,
            total_spent - int(base_total),
        )
        remaining = max(
            0,
            span - progress_value,
        )
    else:
        progress_value = max(
            0,
            total_spent
            - current_threshold,
        )
        remaining = max(
            0,
            next_threshold
            - total_spent,
        )

    percent = min(
        100,
        max(
            0,
            int(
                progress_value
                * 100
                / span
            ),
        ),
    )

    return {
        "next_name": str(
            next_level["name"]
        ),
        "next_threshold": (
            next_threshold
        ),
        "remaining": remaining,
        "percent": percent,
    }


def _load_customer_data(
    customer_id: str,
) -> dict:
    data: dict = {}

    if not BOT_DB.exists():
        return data

    with _connect(
        BOT_DB
    ) as conn:

        if not _table_exists(
            conn,
            "customers",
        ):
            return data

        cols = _columns(
            conn,
            "customers",
        )

        key_col = None

        for candidate in (
            "customer_id",
            "user_id",
        ):
            if candidate in cols:
                key_col = candidate
                break

        if key_col is None:
            return data

        row = conn.execute(
            f"""
            SELECT *
            FROM customers
            WHERE CAST({key_col} AS TEXT) = ?
            LIMIT 1
            """,
            (
                str(customer_id),
            ),
        ).fetchone()

        if row is None:
            return data

        row_data = dict(
            row
        )

        for json_col in (
            "data",
            "data_json",
        ):
            if json_col in row_data:
                data.update(
                    _json_dict(
                        row_data.get(
                            json_col
                        )
                    )
                )

        for key, value in (
            row_data.items()
        ):
            if value is not None:
                data[key] = value

    return data


def _wallet_balance(
    customer_id: str,
) -> int:
    if not BOT_DB.exists():
        return 0

    with _connect(
        BOT_DB
    ) as conn:

        if not _table_exists(
            conn,
            "customer_wallets",
        ):
            return 0

        cols = _columns(
            conn,
            "customer_wallets",
        )

        if not {
            "customer_discord_id",
            "balance",
        }.issubset(
            cols
        ):
            return 0

        row = conn.execute(
            """
            SELECT balance
            FROM customer_wallets
            WHERE CAST(
                customer_discord_id
                AS TEXT
            ) = ?
            LIMIT 1
            """,
            (
                str(customer_id),
            ),
        ).fetchone()

        if row is None:
            return 0

        return _safe_int(
            row["balance"]
        )


def _favorite_count(
    customer_id: str,
) -> int:
    if not WEB_DB.exists():
        return 0

    with _connect(
        WEB_DB
    ) as conn:

        if not _table_exists(
            conn,
            "staff_favorites",
        ):
            return 0

        row = conn.execute(
            """
            SELECT COUNT(*) AS c
            FROM staff_favorites
            WHERE customer_discord_id = ?
            """,
            (
                str(customer_id),
            ),
        ).fetchone()

        return _safe_int(
            row["c"]
            if row
            else 0
        )


def _recent_orders(
    customer_id: str,
    limit: int = 6,
) -> list[dict]:
    if not WEB_DB.exists():
        return []

    with _connect(
        WEB_DB
    ) as conn:

        if not _table_exists(
            conn,
            "web_orders",
        ):
            return []

        cols = _columns(
            conn,
            "web_orders",
        )

        if (
            "customer_discord_id"
            not in cols
        ):
            return []

        order_by = (
            "id DESC"
            if "id" in cols
            else "rowid DESC"
        )

        rows = conn.execute(
            f"""
            SELECT *
            FROM web_orders
            WHERE CAST(
                customer_discord_id
                AS TEXT
            ) = ?
            ORDER BY {order_by}
            LIMIT ?
            """,
            (
                str(customer_id),
                max(
                    1,
                    min(
                        int(limit),
                        20,
                    ),
                ),
            ),
        ).fetchall()

    status_labels = {
        "active": "進行中",
        "stored": "暫存",
        "closed": "已完成",
        "cancelled": "已取消",
        "canceled": "已取消",
    }

    result = []

    for row in rows:
        item = dict(
            row
        )

        status = str(
            item.get(
                "status"
            )
            or ""
        ).lower()

        amount = item.get(
            "customer_pay_amount"
        )

        if amount is None:
            amount = item.get(
                "amount"
            )

        order_no = (
            item.get(
                "bot_order_no"
            )
            or item.get(
                "order_no"
            )
            or (
                f"WEB-{item.get('id')}"
                if item.get("id")
                else "\u2014"
            )
        )

        result.append(
            {
                "id": item.get(
                    "id"
                ),
                "order_no": str(
                    order_no
                ),
                "category": normalize_public_text(
                    item.get(
                        "category"
                    )
                ),
                "item": normalize_public_text(
                    item.get(
                        "item"
                    )
                    or "\u8a02\u55ae"
                ),
                "amount": _safe_int(
                    amount
                ),
                "amount_text": format_t(
                    amount
                ),
                "status": status,
                "status_label": (
                    status_labels.get(
                        status,
                        normalize_public_text(
                            status
                        )
                        or "\u672a\u77e5",
                    )
                ),
                "created_at": (
                    format_date(
                        item.get(
                            "created_at"
                        )
                    )
                ),
            }
        )

    return result


def _closed_order_count(
    customer_id: str,
) -> int:
    if not WEB_DB.exists():
        return 0

    with _connect(
        WEB_DB
    ) as conn:

        if not _table_exists(
            conn,
            "web_orders",
        ):
            return 0

        cols = _columns(
            conn,
            "web_orders",
        )

        if not {
            "customer_discord_id",
            "status",
        }.issubset(
            cols
        ):
            return 0

        row = conn.execute(
            """
            SELECT COUNT(*) AS c
            FROM web_orders
            WHERE CAST(
                customer_discord_id
                AS TEXT
            ) = ?
              AND status = 'closed'
            """,
            (
                str(customer_id),
            ),
        ).fetchone()

        return _safe_int(
            row["c"]
            if row
            else 0
        )


def _favorite_profiles(
    customer_id: str,
    limit: int = 6,
) -> list[dict]:
    if not WEB_DB.exists():
        return []

    with _connect(
        WEB_DB
    ) as conn:

        if not _table_exists(
            conn,
            "staff_favorites",
        ):
            return []

        has_profiles = (
            _table_exists(
                conn,
                "staff_profiles",
            )
        )

        favorites = conn.execute(
            """
            SELECT *
            FROM staff_favorites
            WHERE customer_discord_id = ?
            ORDER BY id DESC
            LIMIT ?
            """,
            (
                str(customer_id),
                max(
                    1,
                    min(
                        int(limit),
                        20,
                    ),
                ),
            ),
        ).fetchall()

        result = []

        for favorite in favorites:
            favorite_data = dict(
                favorite
            )

            staff_id = str(
                favorite_data.get(
                    "staff_discord_id"
                )
                or ""
            )

            profile = {}

            if (
                has_profiles
                and staff_id
            ):
                row = conn.execute(
                    """
                    SELECT *
                    FROM staff_profiles
                    WHERE staff_discord_id = ?
                      AND COALESCE(
                          is_public,
                          1
                      ) = 1
                    LIMIT 1
                    """,
                    (
                        staff_id,
                    ),
                ).fetchone()

                if row:
                    profile = dict(
                        row
                    )

            display_name = (
                profile.get(
                    "display_name"
                )
                or favorite_data.get(
                    "staff_display_name"
                )
                or staff_id
            )

            result.append(
                {
                    "staff_id": staff_id,
                    "display_name": (
                        normalize_public_text(
                            display_name
                        )
                    ),
                    "role_title": (
                        normalize_public_text(
                            profile.get(
                                "role_title"
                            )
                            or profile.get(
                                "profile_type"
                            )
                            or "\u966a\u73a9"
                        )
                    ),
                    "avatar_url": (
                        f"/discord-avatar/"
                        f"{staff_id}"
                        f"?size=128"
                    ),
                }
            )

    return result


def get_member_summary(
    customer_id: str,
) -> dict:
    customer_id = str(
        customer_id
        or ""
    ).strip()

    customer_data = (
        _load_customer_data(
            customer_id
        )
    )

    total_spent = _safe_int(
        customer_data.get(
            "total_spent"
        )
    )

    points = _safe_int(
        customer_data.get(
            "points"
        )
    )

    completed_orders = _safe_int(
        customer_data.get(
            "completed_orders"
        )
        or customer_data.get(
            "order_count"
        )
    )

    if completed_orders <= 0:
        completed_orders = (
            _closed_order_count(
                customer_id
            )
        )

    vip_name = _resolve_vip_name(
        customer_data
    )

    vip_progress = _vip_progress(
        customer_data
    )

    return {
        "customer_id": customer_id,
        "total_spent": total_spent,
        "total_spent_text": format_t(
            total_spent
        ),
        "points": points,
        "wallet_balance": (
            _wallet_balance(
                customer_id
            )
        ),
        "wallet_balance_text": (
            format_t(
                _wallet_balance(
                    customer_id
                )
            )
        ),
        "completed_orders": (
            completed_orders
        ),
        "favorite_count": (
            _favorite_count(
                customer_id
            )
        ),
        "vip_name": vip_name,
        "vip_progress": vip_progress,
        "recent_orders": (
            _recent_orders(
                customer_id
            )
        ),
        "favorite_profiles": (
            _favorite_profiles(
                customer_id
            )
        ),
        "last_order_at": (
            format_date(
                customer_data.get(
                    "last_order_at"
                )
            )
        ),
    }


def _staff_role_group(
    profile: dict,
) -> str:
    text = (
        normalize_public_text(
            profile.get(
                "profile_type"
            )
        )
        + " "
        + normalize_public_text(
            profile.get(
                "role_title"
            )
        )
    )

    if "\u5973\u966a" in text:
        return "female_companion"

    if "\u7537\u966a" in text:
        return "male_companion"

    if (
        "\u9802\u8b77" in text
        or "\u5973\u8b77" in text
        or "\u7537\u8b77" in text
        or "\u8b77\u822a" in text
    ):
        return "protector"

    return "other"



STAFF_ROLE_FILTER_DEFS = (
    ("female_companion", "女陪"),
    ("male_companion", "男陪"),
    ("female_protector", "女護"),
    ("male_protector", "男護"),
    ("top_protector", "頂護"),
    ("lol_master", "LOL大師"),
    ("lol_grandmaster", "宗師"),
    ("lol_elite", "菁英"),
    ("apex_diamond", "鑽石"),
    ("apex_master", "APEX大師"),
    ("apex_predator", "頂獵"),
    ("valorant_ascendant", "超凡"),
    ("valorant_immortal", "神話"),
    ("valorant_radiant", "輻能"),
)


HOMEPAGE_STAFF_FILTER_KEYS = {
    "entertainment_female",
    "entertainment_male",
    "strong_player",
}


STRONG_PLAYER_ROLE_KEYS = {
    "top_protector",
    "lol_elite",
    "apex_predator",
    "valorant_radiant",
}


def get_public_staff_role_filters() -> list[dict]:
    return [
        {
            "key": key,
            "label": label,
        }
        for key, label
        in STAFF_ROLE_FILTER_DEFS
    ]


def _staff_role_keys(
    conn: sqlite3.Connection,
    staff_id: str,
    profile: dict,
) -> list[str]:
    role_ids: set[str] = set()
    member_found = False

    if (
        _table_exists(
            conn,
            "web_staff_members",
        )
    ):
        member_cols = _columns(
            conn,
            "web_staff_members",
        )

        if {
            "discord_id",
            "roles_json",
        }.issubset(
            member_cols
        ):
            row = conn.execute(
                """
                SELECT roles_json
                FROM web_staff_members
                WHERE CAST(discord_id AS TEXT) = ?
                LIMIT 1
                """,
                (
                    str(staff_id),
                ),
            ).fetchone()

            if row is not None:
                member_found = True

                raw_roles = row[
                    "roles_json"
                ]

                if isinstance(
                    raw_roles,
                    (
                        list,
                        tuple,
                        set,
                    ),
                ):
                    role_ids = {
                        str(item).strip()
                        for item in raw_roles
                        if str(item).strip()
                    }
                else:
                    text = str(
                        raw_roles
                        or ""
                    ).strip()

                    if text:
                        try:
                            parsed = json.loads(
                                text
                            )
                        except Exception:
                            parsed = [
                                part.strip()
                                for part
                                in text.split(",")
                                if part.strip()
                            ]

                        if isinstance(
                            parsed,
                            (
                                list,
                                tuple,
                                set,
                            ),
                        ):
                            role_ids = {
                                str(item).strip()
                                for item in parsed
                                if str(item).strip()
                            }

    from services.order_rules import (
        ROLE_IDS,
    )
    from services.game_roles import (
        GAME_ROLE_BY_KEY,
    )

    role_id_by_key = {
        key: str(
            ROLE_IDS.get(
                key
            )
            or ""
        )
        for key, _label
        in STAFF_ROLE_FILTER_DEFS
        if key in ROLE_IDS
    }

    for key, _label in (
        STAFF_ROLE_FILTER_DEFS
    ):
        game_role = (
            GAME_ROLE_BY_KEY.get(
                key
            )
        )

        if game_role is not None:
            role_id_by_key[
                key
            ] = str(
                game_role.role_id
            )

    keys = [
        key
        for key, _label
        in STAFF_ROLE_FILTER_DEFS
        if (
            role_id_by_key.get(
                key
            )
            and role_id_by_key[
                key
            ] in role_ids
        )
    ]

    # 舊資料只有個人牆文字時，仍保留服務身分組篩選。
    text = (
        normalize_public_text(
            profile.get(
                "profile_type"
            )
        )
        + " "
        + normalize_public_text(
            profile.get(
                "role_title"
            )
        )
    )

    legacy_checks = (
        (
            "top_protector",
            "頂護",
        ),
        (
            "female_protector",
            "女護",
        ),
        (
            "male_protector",
            "男護",
        ),
        (
            "female_companion",
            "女陪",
        ),
        (
            "male_companion",
            "男陪",
        ),
    )

    if not member_found:
        for key, marker in (
            legacy_checks
        ):
            if (
                marker in text
                and key not in keys
            ):
                keys.append(
                    key
                )

    return keys

def _stats_for_staff(
    conn: sqlite3.Connection,
    staff_id: str,
) -> dict:
    favorite_count = 0
    completed_count = 0
    review_count = 0
    average_rating = None

    if _table_exists(
        conn,
        "staff_favorites",
    ):
        row = conn.execute(
            """
            SELECT COUNT(*) AS c
            FROM staff_favorites
            WHERE staff_discord_id = ?
            """,
            (
                staff_id,
            ),
        ).fetchone()

        favorite_count = _safe_int(
            row["c"]
            if row
            else 0
        )

    if _table_exists(
        conn,
        "order_reviews",
    ):
        cols = _columns(
            conn,
            "order_reviews",
        )

        conditions = [
            "staff_discord_id = ?",
        ]

        if "is_public" in cols:
            conditions.append(
                "COALESCE(is_public, 1) = 1"
            )

        if "is_hidden" in cols:
            conditions.append(
                "COALESCE(is_hidden, 0) = 0"
            )

        row = conn.execute(
            f"""
            SELECT
                COUNT(*) AS c,
                AVG(rating) AS avg_rating
            FROM order_reviews
            WHERE {' AND '.join(conditions)}
            """,
            (
                staff_id,
            ),
        ).fetchone()

        if row:
            review_count = _safe_int(
                row["c"]
            )

            if (
                row["avg_rating"]
                is not None
            ):
                try:
                    average_rating = float(
                        row["avg_rating"]
                    )
                except Exception:
                    average_rating = None

    if (
        _table_exists(
            conn,
            "web_orders",
        )
        and _table_exists(
            conn,
            "order_assignments",
        )
    ):
        order_cols = _columns(
            conn,
            "web_orders",
        )

        assign_cols = _columns(
            conn,
            "order_assignments",
        )

        if {
            "id",
            "status",
        }.issubset(
            order_cols
        ) and {
            "order_id",
            "worker_discord_id",
        }.issubset(
            assign_cols
        ):

            active_condition = ""

            if (
                "is_active"
                in assign_cols
            ):
                active_condition = (
                    "AND COALESCE("
                    "oa.is_active, 1"
                    ") = 1"
                )

            row = conn.execute(
                f"""
                SELECT
                    COUNT(
                        DISTINCT wo.id
                    ) AS c
                FROM web_orders wo
                JOIN order_assignments oa
                  ON oa.order_id = wo.id
                WHERE
                    oa.worker_discord_id = ?
                  AND wo.status = 'closed'
                  {active_condition}
                """,
                (
                    staff_id,
                ),
            ).fetchone()

            completed_count = (
                _safe_int(
                    row["c"]
                    if row
                    else 0
                )
            )

    return {
        "favorite_count": (
            favorite_count
        ),
        "completed_count": (
            completed_count
        ),
        "review_count": (
            review_count
        ),
        "average_rating": (
            average_rating
        ),
        "average_rating_text": (
            f"{average_rating:.1f}"
            if average_rating
            is not None
            else "\u2014"
        ),
    }


def _is_favorite(
    conn: sqlite3.Connection,
    customer_id: str | None,
    staff_id: str,
) -> bool:
    if not customer_id:
        return False

    if not _table_exists(
        conn,
        "staff_favorites",
    ):
        return False

    row = conn.execute(
        """
        SELECT id
        FROM staff_favorites
        WHERE customer_discord_id = ?
          AND staff_discord_id = ?
        LIMIT 1
        """,
        (
            str(customer_id),
            str(staff_id),
        ),
    ).fetchone()

    return row is not None


def _profile_to_public(
    conn: sqlite3.Connection,
    profile: dict,
    customer_id: str | None = None,
) -> dict:
    staff_id = str(
        profile.get(
            "staff_discord_id"
        )
        or ""
    )

    result = {
        "staff_id": staff_id,
        "display_name": (
            normalize_public_text(
                profile.get(
                    "display_name"
                )
                or staff_id
                or "\u6210\u54e1"
            )
        ),
        "profile_type": (
            normalize_public_text(
                profile.get(
                    "profile_type"
                )
                or "\u966a\u73a9"
            )
        ),
        "role_title": (
            normalize_public_text(
                profile.get(
                    "role_title"
                )
                or profile.get(
                    "profile_type"
                )
                or "\u966a\u73a9"
            )
        ),
        "main_games": (
            normalize_public_text(
                profile.get(
                    "main_games"
                )
            )
        ),
        "service_tags": (
            normalize_public_text(
                profile.get(
                    "service_tags"
                )
            )
        ),
        "bio": (
            normalize_public_text(
                profile.get(
                    "bio"
                )
            )
        ),
        # Old promotional/card image is intentionally
        # not exposed on the redesigned website.
        "avatar_url": (
            f"/discord-avatar/"
            f"{staff_id}"
            f"?size=512"
        ),
    }

    result["role_keys"] = (
        _staff_role_keys(
            conn,
            staff_id,
            result,
        )
    )

    result["role_group"] = (
        _staff_role_group(
            result
        )
    )

    result.update(
        _stats_for_staff(
            conn,
            staff_id,
        )
    )

    result["is_favorite"] = (
        _is_favorite(
            conn,
            customer_id,
            staff_id,
        )
    )

    return result


def list_public_staff(
    *,
    customer_id: str | None = None,
    role_filter: str | None = None,
) -> list[dict]:
    if not WEB_DB.exists():
        return []

    with _connect(
        WEB_DB
    ) as conn:

        if not _table_exists(
            conn,
            "staff_profiles",
        ):
            return []

        cols = _columns(
            conn,
            "staff_profiles",
        )

        conditions = []

        if "is_public" in cols:
            conditions.append(
                "COALESCE(is_public, 1) = 1"
            )

        where_sql = (
            "WHERE "
            + " AND ".join(
                conditions
            )
            if conditions
            else ""
        )

        order_parts = []

        if "sort_score" in cols:
            order_parts.append(
                "sort_score DESC"
            )

        if "updated_at" in cols:
            order_parts.append(
                "updated_at DESC"
            )

        if "id" in cols:
            order_parts.append(
                "id DESC"
            )
        else:
            order_parts.append(
                "rowid DESC"
            )

        rows = conn.execute(
            f"""
            SELECT *
            FROM staff_profiles
            {where_sql}
            ORDER BY {', '.join(order_parts)}
            """
        ).fetchall()

        profiles = [
            _profile_to_public(
                conn,
                dict(row),
                customer_id,
            )
            for row
            in rows
        ]

        # Keep the profile record for history, but do not show
        # people who no longer have any eligible live Discord role.
        profiles = [
            profile
            for profile
            in profiles
            if profile.get(
                "role_keys"
            )
        ]

    role_filter = str(
        role_filter
        or ""
    ).strip()

    if (
        role_filter
        and role_filter != "all"
    ):
        if (
            role_filter
            == "entertainment_female"
        ):
            profiles = [
                profile
                for profile
                in profiles
                if set(
                    profile.get(
                        "role_keys"
                    )
                    or []
                )
                == {
                    "female_companion",
                }
            ]

        elif (
            role_filter
            == "entertainment_male"
        ):
            profiles = [
                profile
                for profile
                in profiles
                if set(
                    profile.get(
                        "role_keys"
                    )
                    or []
                )
                == {
                    "male_companion",
                }
            ]

        elif (
            role_filter
            == "strong_player"
        ):
            profiles = [
                profile
                for profile
                in profiles
                if bool(
                    STRONG_PLAYER_ROLE_KEYS
                    & set(
                        profile.get(
                            "role_keys"
                        )
                        or []
                    )
                )
            ]

        else:
            protector_keys = {
                "top_protector",
                "female_protector",
                "male_protector",
            }

            profiles = [
                profile
                for profile
                in profiles
                if (
                    (
                        role_filter
                        == "protector"
                        and bool(
                            protector_keys
                            & set(
                                profile.get(
                                    "role_keys"
                                )
                                or []
                            )
                        )
                    )
                    or (
                        role_filter
                        in (
                            profile.get(
                                "role_keys"
                            )
                            or []
                        )
                    )
                    or (
                        profile.get(
                            "role_group"
                        )
                        == role_filter
                    )
                )
            ]

    return profiles


def _public_reviews(
    conn: sqlite3.Connection,
    staff_id: str,
    limit: int = 8,
) -> list[dict]:
    if not _table_exists(
        conn,
        "order_reviews",
    ):
        return []

    cols = _columns(
        conn,
        "order_reviews",
    )

    conditions = [
        "staff_discord_id = ?",
    ]

    if "is_public" in cols:
        conditions.append(
            "COALESCE(is_public, 1) = 1"
        )

    if "is_hidden" in cols:
        conditions.append(
            "COALESCE(is_hidden, 0) = 0"
        )

    order_by = (
        "id DESC"
        if "id" in cols
        else "rowid DESC"
    )

    rows = conn.execute(
        f"""
        SELECT *
        FROM order_reviews
        WHERE {' AND '.join(conditions)}
        ORDER BY {order_by}
        LIMIT ?
        """,
        (
            staff_id,
            max(
                1,
                min(
                    int(limit),
                    20,
                ),
            ),
        ),
    ).fetchall()

    result = []

    for row in rows:
        data = dict(
            row
        )

        result.append(
            {
                "rating": max(
                    0,
                    min(
                        5,
                        _safe_int(
                            data.get(
                                "rating"
                            )
                        ),
                    ),
                ),
                "comment": (
                    normalize_public_text(
                        data.get(
                            "comment"
                        )
                    )
                    or "\u672a\u7559\u8a55\u8ad6"
                ),
                "service_item": (
                    normalize_public_text(
                        data.get(
                            "service_item"
                        )
                        or data.get(
                            "service_category"
                        )
                    )
                ),
                "created_at": (
                    format_date(
                        data.get(
                            "created_at"
                        )
                    )
                ),
            }
        )

    return result


def get_public_staff(
    staff_id: str,
    *,
    customer_id: str | None = None,
) -> dict | None:
    if not WEB_DB.exists():
        return None

    with _connect(
        WEB_DB
    ) as conn:

        if not _table_exists(
            conn,
            "staff_profiles",
        ):
            return None

        cols = _columns(
            conn,
            "staff_profiles",
        )

        public_condition = ""

        if "is_public" in cols:
            public_condition = (
                "AND COALESCE("
                "is_public, 1"
                ") = 1"
            )

        row = conn.execute(
            f"""
            SELECT *
            FROM staff_profiles
            WHERE staff_discord_id = ?
            {public_condition}
            LIMIT 1
            """,
            (
                str(staff_id),
            ),
        ).fetchone()

        if row is None:
            return None

        profile = _profile_to_public(
            conn,
            dict(row),
            customer_id,
        )

        profile["reviews"] = (
            _public_reviews(
                conn,
                str(staff_id),
            )
        )

        return profile


def toggle_favorite(
    *,
    customer_id: str,
    staff_id: str,
) -> bool:
    customer_id = str(
        customer_id
        or ""
    ).strip()

    staff_id = str(
        staff_id
        or ""
    ).strip()

    if (
        not customer_id
        or not staff_id
    ):
        raise ValueError(
            "\u7f3a\u5c11\u6536\u85cf\u8cc7\u6599"
        )

    if not WEB_DB.exists():
        raise ValueError(
            "\u500b\u4eba\u7246\u8cc7\u6599\u5eab\u4e0d\u5b58\u5728"
        )

    with _connect(
        WEB_DB
    ) as conn:

        if not _table_exists(
            conn,
            "staff_profiles",
        ):
            raise ValueError(
                "\u500b\u4eba\u7246\u5c1a\u672a\u555f\u7528"
            )

        profile = conn.execute(
            """
            SELECT *
            FROM staff_profiles
            WHERE staff_discord_id = ?
              AND COALESCE(
                    is_public,
                    1
                  ) = 1
            LIMIT 1
            """,
            (
                staff_id,
            ),
        ).fetchone()

        if profile is None:
            raise ValueError(
                "\u627e\u4e0d\u5230\u9019\u4f4d\u516c\u958b\u966a\u73a9"
            )

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS
            staff_favorites (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                customer_discord_id TEXT NOT NULL,
                staff_discord_id TEXT NOT NULL,
                staff_display_name TEXT,
                source TEXT NOT NULL DEFAULT 'profile',
                created_at TEXT NOT NULL
            )
            """
        )

        conn.execute(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS
            idx_staff_favorites_unique
            ON staff_favorites(
                customer_discord_id,
                staff_discord_id
            )
            """
        )

        existing = conn.execute(
            """
            SELECT id
            FROM staff_favorites
            WHERE customer_discord_id = ?
              AND staff_discord_id = ?
            LIMIT 1
            """,
            (
                customer_id,
                staff_id,
            ),
        ).fetchone()

        if existing is not None:
            conn.execute(
                """
                DELETE FROM staff_favorites
                WHERE customer_discord_id = ?
                  AND staff_discord_id = ?
                """,
                (
                    customer_id,
                    staff_id,
                ),
            )

            conn.commit()

            return False

        profile_data = dict(
            profile
        )

        conn.execute(
            """
            INSERT OR IGNORE INTO staff_favorites (
                customer_discord_id,
                staff_discord_id,
                staff_display_name,
                source,
                created_at
            )
            VALUES (
                ?,
                ?,
                ?,
                'website',
                datetime('now')
            )
            """,
            (
                customer_id,
                staff_id,
                str(
                    profile_data.get(
                        "display_name"
                    )
                    or staff_id
                ),
            ),
        )

        conn.commit()

        return True


# ============================================================
# Homepage popular services
# ============================================================

def get_popular_order_groups(
    limit: int = 3,
) -> list[dict]:
    """
    Rank current public order groups by actual placed-order count.

    Cancelled / failed orders are ignored.  Old rows without
    order_rule_key are matched by their stored item label when possible.
    """
    from collections import Counter

    from web.app.services.order_groups import (
        GROUP_SPECS,
        get_grouped_order_catalog,
    )

    groups = get_grouped_order_catalog(
        "all"
    )

    if not groups:
        return []

    group_by_key = {
        str(
            group.get(
                "key"
            )
            or ""
        ):
            group
        for group
        in groups
    }

    rule_to_group: dict[str, str] = {}
    item_to_group: dict[str, str] = {}

    for spec in GROUP_SPECS:
        group_key = str(
            spec.get(
                "key"
            )
            or ""
        )

        if group_key not in group_by_key:
            continue

        group_label = str(
            spec.get(
                "label"
            )
            or ""
        ).strip()

        if group_label:
            item_to_group[
                group_label
            ] = group_key

        for (
            rule_key,
            public_label,
        ) in spec.get(
            "variants",
            []
        ):
            rule_key = str(
                rule_key
            )

            rule_to_group[
                rule_key
            ] = group_key

            public_label = str(
                public_label
                or ""
            ).strip()

            if public_label:
                item_to_group[
                    public_label
                ] = group_key

            rule = ORDER_RULES.get(
                rule_key
            )

            if rule is not None:
                rule_label = str(
                    getattr(
                        rule,
                        "label",
                        "",
                    )
                    or ""
                ).strip()

                if rule_label:
                    item_to_group[
                        rule_label
                    ] = group_key

    counts: Counter[str] = Counter()

    if (
        WEB_DB.exists()
    ):
        try:
            with _connect(
                WEB_DB
            ) as conn:
                if _table_exists(
                    conn,
                    "web_orders",
                ):
                    cols = _columns(
                        conn,
                        "web_orders",
                    )

                    select_cols = []

                    if (
                        "order_rule_key"
                        in cols
                    ):
                        select_cols.append(
                            "order_rule_key"
                        )

                    if "item" in cols:
                        select_cols.append(
                            "item"
                        )

                    if "status" in cols:
                        select_cols.append(
                            "status"
                        )

                    if select_cols:
                        rows = conn.execute(
                            "SELECT "
                            + ", ".join(
                                select_cols
                            )
                            + " FROM web_orders"
                        ).fetchall()

                        ignored_statuses = {
                            "cancelled",
                            "canceled",
                            "failed",
                            "rejected",
                            "void",
                        }

                        for row in rows:
                            status = str(
                                (
                                    row["status"]
                                    if "status"
                                    in cols
                                    else ""
                                )
                                or ""
                            ).strip().lower()

                            if (
                                status
                                in ignored_statuses
                            ):
                                continue

                            group_key = ""

                            if (
                                "order_rule_key"
                                in cols
                            ):
                                rule_key = str(
                                    row[
                                        "order_rule_key"
                                    ]
                                    or ""
                                ).strip()

                                group_key = (
                                    rule_to_group.get(
                                        rule_key,
                                        "",
                                    )
                                )

                            if (
                                not group_key
                                and "item"
                                in cols
                            ):
                                item = str(
                                    row[
                                        "item"
                                    ]
                                    or ""
                                ).strip()

                                group_key = (
                                    item_to_group.get(
                                        item,
                                        "",
                                    )
                                )

                            if (
                                group_key
                                in group_by_key
                            ):
                                counts[
                                    group_key
                                ] += 1

        except Exception as exc:
            print(
                "[popular_services]",
                repr(
                    exc
                ),
            )

    ordered = sorted(
        groups,
        key=lambda group: (
            -int(
                counts.get(
                    str(
                        group.get(
                            "key"
                        )
                        or ""
                    ),
                    0,
                )
            ),
            groups.index(
                group
            ),
        ),
    )

    requested = max(
        1,
        min(
            int(
                limit
                or 3
            ),
            4,
        ),
    )

    selected = ordered[
        :requested
    ]

    result = []

    for rank, group in enumerate(
        selected,
        start=1,
    ):
        item = dict(
            group
        )

        item[
            "popularity_rank"
        ] = rank

        item[
            "popularity_count"
        ] = int(
            counts.get(
                str(
                    group.get(
                        "key"
                    )
                    or ""
                ),
                0,
            )
        )

        result.append(
            item
        )

    return result


# ============================================================
# Public order catalog
# ============================================================

from services.order_rules import (
    CATEGORY_LABELS,
    ORDER_RULES,
    ROLE_LABELS,
)


PUBLIC_ORDER_CATEGORY_ORDER = [
    "basic",
    "fun",
    "farm",
    "title",
    "steam",
    "valorant",
]


PUBLIC_ORDER_CATEGORY_DESCRIPTIONS = {
    "basic":
        "三角洲主要服務，從娛樂陪玩到技術需求。",

    "fun":
        "魔丸限定趣味玩法與特色企劃。",

    "farm":
        "代解、代肝與指定進度服務。",

    "title":
        "高難度挑戰與稱號相關方案。",

    "steam":
        "Steam 遊戲陪玩服務。",

    "valorant":
        "Valorant 陪玩與開黑服務。",
}


def _public_role_name(
    role,
) -> str:
    text = normalize_public_text(
        ROLE_LABELS.get(
            role,
            role,
        )
    )

    for prefix in (
        "魔丸♛",
        "魔丸♝",
        "魔丸♜",
        "魔丸♞",
        "魔丸♟",
    ):
        if text.startswith(
            prefix
        ):
            text = text[
                len(prefix):
            ]

    return text


def _public_price_text(
    rule,
) -> str:
    pricing_type = str(
        rule.pricing_type
        or ""
    )

    price = _safe_int(
        rule.price
    )

    if (
        pricing_type == "manual"
        or price <= 0
    ):
        return "客服報價"

    if pricing_type == "fixed":
        return f"{price:,}T"

    unit = normalize_public_text(
        rule.unit_label
        or "單"
    )

    return (
        f"{price:,}T"
        f" / {unit}"
    )


def get_order_categories() -> list[dict]:
    existing = {
        str(rule.category)
        for rule
        in ORDER_RULES.values()
    }

    result = [
        {
            "key": "all",
            "label": "全部",
        }
    ]

    for key in (
        PUBLIC_ORDER_CATEGORY_ORDER
    ):

        if key not in existing:
            continue

        result.append(
            {
                "key": key,
                "label": normalize_public_text(
                    CATEGORY_LABELS.get(
                        key,
                        key,
                    )
                ),
            }
        )

    return result


def list_order_catalog(
    category: str = "all",
) -> list[dict]:
    category = str(
        category
        or "all"
    ).strip()

    valid_categories = {
        item["key"]
        for item
        in get_order_categories()
    }

    if category not in valid_categories:
        category = "all"

    result = []

    for rule in (
        ORDER_RULES.values()
    ):

        rule_category = str(
            rule.category
        )

        if (
            category != "all"
            and rule_category
            != category
        ):
            continue

        required_staff = (
            "依點選人數"
            if rule.required_staff_count
            == "player_count"
            else (
                f"{int(rule.required_staff_count)} 位"
            )
        )

        roles = [
            _public_role_name(
                role
            )
            for role
            in rule.allowed_roles
        ]

        badges = []

        if rule.allow_specify:
            badges.append(
                "可指定"
            )

        if (
            rule.service_bonus_buy
            and rule.service_bonus_gift
        ):
            badges.append(
                f"買{int(rule.service_bonus_buy)}"
                f"送{int(rule.service_bonus_gift)}"
            )

        if not rule.point_benefits_allowed:
            badges.append(
                "不適用點數福利"
            )

        if rule.player_count_enabled:
            badges.append(
                "可選人數"
            )

        note = normalize_public_text(
            rule.note
        )

        description = (
            note
            or PUBLIC_ORDER_CATEGORY_DESCRIPTIONS.get(
                rule_category,
                "依方案提供服務。",
            )
        )

        result.append(
            {
                "key": str(
                    rule.key
                ),
                "category": (
                    rule_category
                ),
                "category_label":
                    normalize_public_text(
                        CATEGORY_LABELS.get(
                            rule_category,
                            rule_category,
                        )
                    ),
                "label":
                    normalize_public_text(
                        rule.label
                    ),
                "price":
                    _safe_int(
                        rule.price
                    ),
                "price_text":
                    _public_price_text(
                        rule
                    ),
                "unit_label":
                    normalize_public_text(
                        rule.unit_label
                    ),
                "required_staff":
                    required_staff,
                "allowed_roles":
                    roles,
                "allow_specify":
                    bool(
                        rule.allow_specify
                    ),
                "badges":
                    badges,
                "description":
                    description,
                "min_quantity":
                    int(
                        rule.min_quantity
                    ),
                "max_quantity":
                    (
                        int(
                            rule.max_quantity
                        )
                        if rule.max_quantity
                        is not None
                        else None
                    ),
                "player_count_enabled":
                    bool(
                        rule.player_count_enabled
                    ),
            }
        )

    return result
