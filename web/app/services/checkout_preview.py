from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

from services.order_flow import (
    get_payment_method_info,
)

from services.order_rules import (
    ALL_ROLE_IDS,
    ALL_ROLE_LABELS,
    ORDER_RULES,
    ROLE_IDS,
    calculate_price,
    get_allowed_role_keys,
    get_required_staff_count,
)

from web.app.services.public_checkout import (
    build_public_quote,
)


ROOT = Path(
    __file__
).resolve().parents[3]

BOT_DB = (
    ROOT
    / "bot.db"
)

WEB_DB = (
    ROOT
    / "web_dashboard.db"
)


PUBLIC_ROLE_LABELS = {
    "top_protector": "頂護航",
    "female_protector": "女護航",
    "male_protector": "男護航",
    "male_companion": "男陪",
    "female_companion": "女陪",
}


# ============================================================
# VIP
#
# Pay rate:
# Gold / Platinum 98%
# Diamond / White Diamond 96%
# Black Diamond 94%
# ============================================================

VIP_PAY_RATES = {
    "普通魔丸": 100,
    "銀級魔丸": 100,
    "金級魔丸": 98,
    "白金魔丸": 98,
    "鑽石魔丸": 96,
    "白鑽魔丸": 96,
    "黑鑽魔丸": 94,
}


VIP_THRESHOLDS = [
    (88888, "黑鑽魔丸"),
    (50000, "白鑽魔丸"),
    (25000, "鑽石魔丸"),
    (12000, "白金魔丸"),
    (6000, "金級魔丸"),
    (2000, "銀級魔丸"),
]


# 因目前公開 VIP 條款的兩處排除文字並不完全一致，
# 結帳先採保守模式，避免錯誤多給折扣。
VIP_EXCLUDED_CATEGORIES = {
    "fun",
    "title",
}


VIP_EXCLUDED_RULE_KEYS = {
    "basic_trial_500",
    "basic_trial_1000",
    "farm_season_3x3_normal",
    "farm_season_3x3_contract",
    "farm_season_3x3_dc_skin",
    "farm_season_3x3_dc_loss",
    "farm_season_3x3_dc_skin_loss",
}


# ============================================================
# Points
#
# 80-point free hour is intentionally NOT in this list.
# ============================================================

POINT_ITEMS = [
    {
        "key": "discount_20",
        "cost": 5,
        "name": "20T 折價券",
        "kind": "cash_discount",
        "amount": 20,
    },
    {
        "key": "discount_30",
        "cost": 10,
        "name": "30T 折價券",
        "kind": "cash_discount",
        "amount": 30,
    },
    {
        "key": "extra_10",
        "cost": 15,
        "name": "加時 30 分鐘",
        "kind": "extra_hours",
        "hours": 0.5,
    },
    {
        "key": "extra_15",
        "cost": 20,
        "name": "加場一場保撤",
        "kind": "extra_game",
        "games": 1,
    },
    {
        "key": "free_specify_fee",
        "cost": 25,
        "name": "免指定費 1 次",
        "kind": "free_specify_fee",
    },
    {
        "key": "discount_100",
        "cost": 30,
        "name": "100T 折價券",
        "kind": "cash_discount",
        "amount": 100,
    },
    {
        "key": "extra_30",
        "cost": 40,
        "name": "加時 1 小時",
        "kind": "extra_hours",
        "hours": 1,
    },
]


POINT_ITEM_MAP = {
    item["key"]:
        item
    for item
    in POINT_ITEMS
}


PAYMENT_METHODS = [
    "轉帳",
    "街口",
]


# ============================================================
# Generic helpers
# ============================================================

def _to_int(
    value: Any,
    default: int = 0,
) -> int:

    try:

        if (
            value is None
            or value == ""
        ):
            return default

        return int(value)

    except (
        TypeError,
        ValueError,
    ):

        return default


def _table_exists(
    conn: sqlite3.Connection,
    table: str,
) -> bool:

    row = conn.execute(
        "SELECT name "
        "FROM sqlite_master "
        "WHERE type='table' "
        "AND name=?",
        (
            table,
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

    try:

        return {
            str(
                row[1]
            )
            for row
            in conn.execute(
                f"PRAGMA table_info({table})"
            ).fetchall()
        }

    except sqlite3.Error:

        return set()


def _json_dict(
    value,
) -> dict:

    if isinstance(
        value,
        dict,
    ):
        return value

    if value is None:
        return {}

    try:

        parsed = json.loads(
            str(
                value
            )
        )

    except Exception:

        return {}

    return (
        parsed
        if isinstance(
            parsed,
            dict,
        )
        else {}
    )


def _json_list(
    value,
) -> list[str]:

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

    if value is None:
        return []

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


# ============================================================
# Customer / VIP / points
# ============================================================

def _vip_from_total_spent(
    total_spent: int,
) -> str:

    for threshold, name in (
        VIP_THRESHOLDS
    ):

        if (
            total_spent
            >= threshold
        ):
            return name

    return "普通魔丸"


def load_customer_state(
    customer_id: str,
) -> dict:

    customer_id = str(
        customer_id
        or ""
    ).strip()

    result = {
        "customer_id":
            customer_id,

        "total_spent":
            0,

        "points":
            0,

        "vip_name":
            "普通魔丸",

        "wallet_balance":
            0,
    }


    if BOT_DB.exists():

        try:

            conn = sqlite3.connect(
                BOT_DB
            )

            conn.row_factory = (
                sqlite3.Row
            )


            try:

                customer_cols = (
                    _columns(
                        conn,
                        "customers",
                    )
                )


                if customer_cols:

                    if (
                        "customer_id"
                        in customer_cols
                    ):
                        id_col = (
                            "customer_id"
                        )

                    elif (
                        "user_id"
                        in customer_cols
                    ):
                        id_col = (
                            "user_id"
                        )

                    else:
                        id_col = None


                    if id_col:

                        row = conn.execute(
                            "SELECT * "
                            "FROM customers "
                            f"WHERE CAST({id_col} AS TEXT)=? "
                            "LIMIT 1",
                            (
                                customer_id,
                            ),
                        ).fetchone()


                        if row is not None:

                            row_data = dict(
                                row
                            )


                            json_data = {}


                            for candidate in (
                                "data_json",
                                "data",
                            ):

                                if (
                                    candidate
                                    in row_data
                                ):

                                    json_data = (
                                        _json_dict(
                                            row_data.get(
                                                candidate
                                            )
                                        )
                                    )

                                    if json_data:
                                        break


                            total_spent = (
                                _to_int(
                                    row_data.get(
                                        "total_spent"
                                    ),
                                    _to_int(
                                        json_data.get(
                                            "total_spent"
                                        ),
                                        0,
                                    ),
                                )
                            )


                            result[
                                "total_spent"
                            ] = max(
                                0,
                                total_spent,
                            )


                            if (
                                "point_adjustment"
                                in json_data
                            ):

                                adjustment = (
                                    _to_int(
                                        json_data.get(
                                            "point_adjustment"
                                        ),
                                        0,
                                    )
                                )

                                points = max(
                                    0,
                                    (
                                        total_spent
                                        // 100
                                    )
                                    + adjustment,
                                )

                            else:

                                points = (
                                    _to_int(
                                        row_data.get(
                                            "points"
                                        ),
                                        _to_int(
                                            json_data.get(
                                                "points"
                                            ),
                                            0,
                                        ),
                                    )
                                )


                            result[
                                "points"
                            ] = max(
                                0,
                                points,
                            )


                            level = str(
                                row_data.get(
                                    "level"
                                )
                                or ""
                            ).strip()


                            if level:

                                result[
                                    "vip_name"
                                ] = level

                            else:

                                result[
                                    "vip_name"
                                ] = (
                                    _vip_from_total_spent(
                                        total_spent
                                    )
                                )


                wallet_cols = (
                    _columns(
                        conn,
                        "customer_wallets",
                    )
                )


                if (
                    "customer_discord_id"
                    in wallet_cols
                    and "balance"
                    in wallet_cols
                ):

                    wallet = conn.execute(
                        "SELECT balance "
                        "FROM customer_wallets "
                        "WHERE CAST(customer_discord_id AS TEXT)=? "
                        "LIMIT 1",
                        (
                            customer_id,
                        ),
                    ).fetchone()


                    if wallet is not None:

                        result[
                            "wallet_balance"
                        ] = max(
                            0,
                            _to_int(
                                wallet[
                                    "balance"
                                ],
                                0,
                            ),
                        )


            finally:

                conn.close()


        except sqlite3.Error:

            pass


    return result


def vip_discount_policy(
    *,
    vip_name: str,
    rule_key: str,
) -> dict:

    rule = (
        ORDER_RULES.get(
            str(
                rule_key
            )
        )
    )


    pay_rate = (
        VIP_PAY_RATES.get(
            str(
                vip_name
            ),
            100,
        )
    )


    if (
        pay_rate >= 100
    ):

        return {
            "eligible":
                False,

            "pay_rate":
                100,

            "reason":
                "目前會員等級沒有全館折扣。",
        }


    if (
        rule is None
    ):

        return {
            "eligible":
                False,

            "pay_rate":
                100,

            "reason":
                "無法確認商品規則。",
        }


    if (
        str(
            rule_key
        )
        in VIP_EXCLUDED_RULE_KEYS
    ):

        return {
            "eligible":
                False,

            "pay_rate":
                100,

            "reason":
                "此方案目前列入 VIP 折扣排除。",
        }


    if (
        str(
            rule.category
        )
        in VIP_EXCLUDED_CATEGORIES
    ):

        return {
            "eligible":
                False,

            "pay_rate":
                100,

            "reason":
                "此分類目前列入 VIP 折扣排除。",
        }


    return {
        "eligible":
            True,

        "pay_rate":
            pay_rate,

        "reason":
            f"自動套用 {pay_rate} 折後比例。",
    }


# ============================================================
# Staff
# ============================================================

def _choose_role_key(
    rule,
    role_ids: set[str],
) -> str | None:

    matched = [
        role_key
        for role_key
        in get_allowed_role_keys(rule)
        if str(
            ALL_ROLE_IDS.get(
                role_key
            )
        )
        in role_ids
    ]


    if not matched:
        return None


    fee_map = {
        **(rule.specify_fee_by_role or {}),
        **(getattr(rule, "specify_fee_by_game_role", {}) or {}),
    }


    # Match current Discord self-service logic:
    # if a member owns multiple matching roles,
    # use the highest applicable specify fee role.
    matched.sort(
        key=lambda role_key:
            int(
                fee_map.get(
                    role_key,
                    rule.specify_fee_default
                    or 0,
                )
            ),
        reverse=True,
    )


    return matched[0]


def list_eligible_staff(
    *,
    rule_key: str,
) -> list[dict]:

    rule = (
        ORDER_RULES.get(
            str(
                rule_key
            )
        )
    )


    if (
        rule is None
        or not rule.allow_specify
        or not WEB_DB.exists()
    ):
        return []


    try:

        conn = sqlite3.connect(
            WEB_DB
        )

        conn.row_factory = (
            sqlite3.Row
        )


        try:

            member_columns = (
                _columns(
                    conn,
                    "web_staff_members",
                )
            )


            if (
                "discord_id"
                not in member_columns
                or "roles_json"
                not in member_columns
            ):
                return []


            active_where = (
                "WHERE COALESCE(m.is_active, 1) = 1 "
                if "is_active"
                in member_columns
                else ""
            )


            # ------------------------------------------------
            # 指定名單以 Discord 同步身分為準。
            #
            # staff_profiles 只拿來補漂亮顯示名稱與排序，
            # 不再是出現在指定名單的必要條件。
            #
            # 所以：
            # - 有個人牆 -> 優先個人牆名稱
            # - 沒個人牆 -> Discord 暱稱
            # - 個人牆隱藏 -> 仍可指定
            # - 是否能指定 -> 只看目前 Discord 身分
            # ------------------------------------------------

            if _table_exists(
                conn,
                "staff_profiles",
            ):

                rows = conn.execute(
                    "SELECT "
                    "m.discord_id AS staff_discord_id, "
                    "COALESCE("
                    "NULLIF(p.display_name, ''), "
                    "NULLIF(m.display_name, ''), "
                    "NULLIF(m.global_name, ''), "
                    "NULLIF(m.username, ''), "
                    "m.discord_id"
                    ") AS display_name, "
                    "m.roles_json, "
                    "COALESCE(p.sort_score, 0) "
                    "AS profile_sort_score "
                    "FROM web_staff_members m "
                    "LEFT JOIN staff_profiles p "
                    "ON p.staff_discord_id = m.discord_id "
                    f"{active_where}"
                    "ORDER BY "
                    "COALESCE(p.sort_score, 0) DESC, "
                    "display_name ASC"
                ).fetchall()


            else:

                rows = conn.execute(
                    "SELECT "
                    "m.discord_id AS staff_discord_id, "
                    "COALESCE("
                    "NULLIF(m.display_name, ''), "
                    "NULLIF(m.global_name, ''), "
                    "NULLIF(m.username, ''), "
                    "m.discord_id"
                    ") AS display_name, "
                    "m.roles_json, "
                    "0 AS profile_sort_score "
                    "FROM web_staff_members m "
                    f"{active_where}"
                    "ORDER BY display_name ASC"
                ).fetchall()


        finally:

            conn.close()


    except sqlite3.Error:

        return []


    result = []


    seen = set()


    for row in rows:

        staff_id = str(
            row[
                "staff_discord_id"
            ]
            or ""
        ).strip()


        if (
            not staff_id
            or staff_id in seen
        ):
            continue


        role_ids = set(
            _json_list(
                row[
                    "roles_json"
                ]
            )
        )


        role_key = (
            _choose_role_key(
                rule,
                role_ids,
            )
        )


        if role_key is None:
            continue


        seen.add(
            staff_id
        )


        result.append(
            {
                "staff_id":
                    staff_id,

                "display_name":
                    str(
                        row[
                            "display_name"
                        ]
                        or staff_id
                    ),

                "role_key":
                    role_key,

                "role_label":
                    PUBLIC_ROLE_LABELS.get(
                        role_key
                    )
                    or ALL_ROLE_LABELS.get(
                        role_key,
                        role_key,
                    ),

                "avatar_url":
                    (
                        "/discord-avatar/"
                        f"{staff_id}"
                        "?size=256"
                    ),

                "source":
                    "discord_role",
            }
        )


    return result



def resolve_selected_staff(
    *,
    rule_key: str,
    selected_ids: Any,
) -> tuple[
    list[dict],
    list[str],
]:

    rule = (
        ORDER_RULES.get(
            str(
                rule_key
            )
        )
    )


    if rule is None:

        raise ValueError(
            "找不到商品規則。"
        )


    if selected_ids is None:
        selected_ids = []


    if not isinstance(
        selected_ids,
        list,
    ):

        raise ValueError(
            "指定人員格式錯誤。"
        )


    clean_ids = []


    for value in selected_ids:

        text = str(
            value
            or ""
        ).strip()

        if (
            text
            and text not in clean_ids
        ):
            clean_ids.append(
                text
            )


    if not clean_ids:

        return [], []


    if not rule.allow_specify:

        raise ValueError(
            "這個方案不開放指定人員。"
        )


    required_staff = (
        get_required_staff_count(
            rule,
            1,
        )
    )


    max_specified = (
        int(
            rule.max_specified_count
        )
        if rule.max_specified_count
        is not None
        else required_staff
    )


    if (
        len(
            clean_ids
        )
        > max_specified
    ):

        raise ValueError(
            f"這個方案最多只能指定 {max_specified} 位。"
        )


    available = {
        item["staff_id"]:
            item
        for item
        in list_eligible_staff(
            rule_key=
                rule_key
        )
    }


    selected = []

    role_keys = []


    for staff_id in clean_ids:

        item = (
            available.get(
                staff_id
            )
        )


        if item is None:

            raise ValueError(
                "指定的人員目前不在可指定名單，"
                "可能已停用個人牆或職位不符合。"
            )


        selected.append(
            item
        )


        role_keys.append(
            item[
                "role_key"
            ]
        )


    return (
        selected,
        role_keys,
    )


# ============================================================
# Point benefit rules
# ============================================================

def _point_item_for_rule(rule, item: dict) -> dict:
    data = dict(item or {})
    pricing_type = str(getattr(rule, "pricing_type", "") or "")

    if pricing_type == "game":
        key = str(data.get("key") or "")

        if key == "extra_10":
            data.update({
                "name": "加一局",
                "kind": "extra_games",
                "games": 1,
            })
            data.pop("hours", None)

        elif key == "extra_30":
            data.update({
                "name": "加兩局",
                "kind": "extra_games",
                "games": 2,
            })
            data.pop("hours", None)

    return data


def point_item_status(
    *,
    rule_key: str,
    point_item_key: str,
    point_balance: int,
    quantity: int,
    has_specified_staff: bool,
) -> dict:

    rule = (
        ORDER_RULES.get(
            str(
                rule_key
            )
        )
    )


    item = (
        POINT_ITEM_MAP.get(
            str(
                point_item_key
            )
        )
    )


    if (
        rule is None
        or item is None
    ):

        return {
            "allowed":
                False,

            "reason":
                "不支援這個點數福利。",
        }


    if (
        point_balance
        < int(
            item[
                "cost"
            ]
        )
    ):

        return {
            "allowed":
                False,

            "reason":
                "點數不足。",
        }


    if not bool(
        rule.point_benefits_allowed
    ):

        return {
            "allowed":
                False,

            "reason":
                "此方案不可使用點數福利。",
        }


    category = str(
        rule.category
    )


    if category == "steam":

        return {
            "allowed":
                False,

            "reason":
                "Steam遊戲目前不可使用點數福利。",
        }


    if category in {
        "fun",
        "title",
    }:

        return {
            "allowed":
                False,

            "reason":
                "趣味單不可使用點數福利。",
        }


    if str(
        rule_key
    ).startswith(
        "basic_trial_"
    ):

        return {
            "allowed":
                False,

            "reason":
                "體驗單不可使用點數福利。",
        }


    kind = str(
        item[
            "kind"
        ]
    )


    if (
        kind
        == "free_specify_fee"
    ):

        if not rule.allow_specify:

            return {
                "allowed":
                    False,

                "reason":
                    "此方案不開放指定。",
            }


        if (
            str(
                rule.pricing_type
            )
            == "hourly"
            and int(
                quantity
            ) >= 2
        ):

            return {
                "allowed":
                    False,

                "reason":
                    "2 小時以上本來就免指定費。",
            }


        if not has_specified_staff:

            return {
                "allowed":
                    False,

                "requires_specified":
                    True,

                "reason":
                    "需先指定人員。",
            }


    if (
        kind
        == "extra_game"
        and category
        in {
            "valorant",
            "lol",
        }
    ):

        return {
            "allowed":
                False,

            "reason":
                "特戰英豪 / 英雄聯盟不可使用加場一場保撤。",
        }


    if (
        kind
        == "extra_hours"
        and str(
            rule.pricing_type
        )
        not in {
            "hourly",
            "game",
        }
    ):

        return {
            "allowed":
                False,

            "reason":
                "加時只適用小時計價方案。",
        }


    if (
        kind
        == "extra_game"
        and str(
            rule.pricing_type
        )
        != "game"
    ):

        return {
            "allowed":
                False,

            "reason":
                "加場只適用局數計價方案。",
        }


    return {
        "allowed":
            True,

        "reason":
            "",
    }


def list_point_options(
    *,
    rule_key: str,
    point_balance: int,
    quantity: int,
    has_specified_staff: bool = False,
) -> list[dict]:

    rule = (
        ORDER_RULES.get(
            str(
                rule_key
            )
        )
    )

    if rule is None:

        return []


    result = []


    for item in POINT_ITEMS:

        status = (
            point_item_status(
                rule_key=
                    rule_key,

                point_item_key=
                    item[
                        "key"
                    ],

                point_balance=
                    point_balance,

                quantity=
                    quantity,

                has_specified_staff=
                    has_specified_staff,
            )
        )


        data = _point_item_for_rule(
            rule,
            item,
        )


        data.update(
            status
        )


        result.append(
            data
        )


    return result


# ============================================================
# Financial calculation
# ============================================================

def calculate_checkout_financials(
    *,
    service_amount: int,
    vip_pay_rate: int,
    specify_fee: int,
    point_item: dict | None,
    wallet_balance: int,
    use_wallet: bool,
) -> dict:

    service_amount = max(
        0,
        int(
            service_amount
            or 0
        ),
    )


    vip_pay_rate = max(
        0,
        min(
            100,
            int(
                vip_pay_rate
                or 100
            ),
        ),
    )


    specify_fee = max(
        0,
        int(
            specify_fee
            or 0
        ),
    )


    wallet_balance = max(
        0,
        int(
            wallet_balance
            or 0
        ),
    )


    after_vip = int(
        round(
            service_amount
            * vip_pay_rate
            / 100
        )
    )


    vip_discount_amount = max(
        0,
        service_amount
        - after_vip,
    )


    point_cash_discount = 0

    point_waived_specify = 0

    point_service_note = ""


    if point_item:

        kind = str(
            point_item.get(
                "kind"
            )
            or ""
        )


        if (
            kind
            == "cash_discount"
        ):

            point_cash_discount = min(
                after_vip,
                max(
                    0,
                    int(
                        point_item.get(
                            "amount"
                        )
                        or 0
                    ),
                ),
            )


        elif (
            kind
            == "free_specify_fee"
        ):

            point_waived_specify = (
                specify_fee
            )


        elif (
            kind
            == "extra_hours"
        ):

            hours = float(
                point_item.get(
                    "hours"
                )
                or 0
            )


            if hours == 0.5:

                point_service_note = (
                    "服務時間 +30 分鐘"
                )

            else:

                point_service_note = (
                    f"服務時間 +{hours:g} 小時"
                )


        elif (
            kind
            == "extra_games"
        ):

            games = int(
                point_item.get(
                    "games"
                )
                or 0
            )


            point_service_note = (
                f"服務局數 +{games} 局"
            )


        elif (
            kind
            == "extra_game"
        ):

            games = int(
                point_item.get(
                    "games"
                )
                or 0
            )


            point_service_note = (
                f"加場 {games} 場保撤"
            )


    effective_specify_fee = max(
        0,
        specify_fee
        - point_waived_specify,
    )


    after_point = max(
        0,
        after_vip
        - point_cash_discount,
    )


    subtotal = max(
        0,
        after_point
        + effective_specify_fee,
    )


    wallet_use = (
        min(
            wallet_balance,
            subtotal,
        )
        if use_wallet
        else 0
    )


    remaining = max(
        0,
        subtotal
        - wallet_use,
    )


    return {
        "service_amount":
            service_amount,

        "vip_pay_rate":
            vip_pay_rate,

        "vip_discount_amount":
            vip_discount_amount,

        "service_after_vip":
            after_vip,

        "specify_fee":
            specify_fee,

        "point_cash_discount":
            point_cash_discount,

        "point_waived_specify_fee":
            point_waived_specify,

        "effective_specify_fee":
            effective_specify_fee,

        "point_service_note":
            point_service_note,

        "subtotal_before_wallet":
            subtotal,

        "wallet_use_amount":
            wallet_use,

        "remaining_pay_amount":
            remaining,

        # For later final order snapshot.
        # Percentage discounts affect payout base;
        # point cash discount is store-absorbed.
        "payout_base_preview":
            max(
                0,
                after_vip
                + effective_specify_fee,
            ),

        "store_absorbed_preview":
            point_cash_discount,
    }


# ============================================================
# Checkout endpoints data
# ============================================================

def build_checkout_options(
    *,
    customer_id: str,
    rule_key: str,
    quantity: int = 1,
    player_count: int = 1,
    customer_adjustments: Any = None,
    preselected_staff_id: str | None = None,
) -> dict:

    quote = build_public_quote(
        rule_key=
            rule_key,

        quantity=
            quantity,

        player_count=
            player_count,

        customer_adjustments=
            customer_adjustments,

        specified_staff_id=
            None,
    )


    customer = load_customer_state(
        customer_id
    )


    rule = (
        ORDER_RULES.get(
            str(
                rule_key
            )
        )
    )


    if rule is None:

        raise ValueError(
            "找不到商品規則。"
        )


    required_staff = int(
        quote.get(
            "required_staff_count"
        )
        or 1
    )


    max_specified = (
        int(
            rule.max_specified_count
        )
        if rule.max_specified_count
        is not None
        else required_staff
    )


    max_specified = min(
        max_specified,
        required_staff,
    )


    eligible_staff = (
        list_eligible_staff(
            rule_key=
                rule_key
        )
    )


    preselected_staff_id = str(
        preselected_staff_id
        or ""
    ).strip() or None


    preselected_staff = None


    if preselected_staff_id:

        if not rule.allow_specify:

            raise ValueError(
                "你從陪玩陣容選擇的人員"
                "無法指定到這個方案。"
            )


        for item in eligible_staff:

            if (
                str(
                    item[
                        "staff_id"
                    ]
                )
                == preselected_staff_id
            ):

                preselected_staff = (
                    item
                )

                break


        if preselected_staff is None:

            raise ValueError(
                "你從陪玩陣容指定的人員"
                "目前無法接這個方案，"
                "請重新選擇適用方案。"
            )


    vip = (
        vip_discount_policy(
            vip_name=
                customer[
                    "vip_name"
                ],

            rule_key=
                rule_key,
        )
    )


    point_options = (
        list_point_options(
            rule_key=
                rule_key,

            point_balance=
                customer[
                    "points"
                ],

            quantity=
                int(
                    quote[
                        "quantity"
                    ]
                ),

            has_specified_staff=
                bool(
                    preselected_staff
                ),
        )
    )


    payment_methods = []


    for method in PAYMENT_METHODS:

        payment_methods.append(
            {
                "key":
                    method,

                "label":
                    method,

                "info":
                    get_payment_method_info(
                        method
                    )
                    or "",
            }
        )


    return {
        "quote":
            quote,

        "customer":
            customer,

        "vip":
            vip,

        "staff": {
            "allow_specify":
                bool(
                    rule.allow_specify
                ),

            "max_specified_count":
                max_specified,

            "items":
                eligible_staff,

            "preselected_staff_id":
                preselected_staff_id,

            "preselected_staff":
                preselected_staff,

            # From roster/profile means this staff
            # is already the user's explicit choice.
            "preselected_locked":
                bool(
                    preselected_staff
                ),
        },

        "point_options":
            point_options,

        "payment_methods":
            payment_methods,

        "read_only_preview":
            True,
    }



def build_checkout_preview(
    *,
    customer_id: str,
    rule_key: str,
    quantity: int = 1,
    player_count: int = 1,
    customer_adjustments: Any = None,
    specified_staff_ids: Any = None,
    point_item_key: str | None = None,
    use_wallet: bool = False,
    payment_method: str | None = None,
) -> dict:

    quote = build_public_quote(
        rule_key=
            rule_key,

        quantity=
            quantity,

        player_count=
            player_count,

        customer_adjustments=
            customer_adjustments,

        specified_staff_id=
            None,
    )


    customer = load_customer_state(
        customer_id
    )


    rule = (
        ORDER_RULES.get(
            str(
                rule_key
            )
        )
    )


    if rule is None:

        raise ValueError(
            "找不到商品規則。"
        )


    selected_staff, role_keys = (
        resolve_selected_staff(
            rule_key=
                rule_key,

            selected_ids=
                specified_staff_ids,
        )
    )


    specify_fee = 0

    free_specify_by_rule = False


    if role_keys:

        # Season 3x3 does not allow specify,
        # so its website-only quantity override never reaches here.
        price = calculate_price(
            rule,

            quantity=
                int(
                    quote[
                        "quantity"
                    ]
                ),

            player_count=(
                int(
                    quote[
                        "player_count"
                    ]
                )
                if rule.player_count_enabled
                else None
            ),

            specified_roles=
                role_keys,

            staff_adjustments=[],
        )


        specify_fee = max(
            0,
            int(
                price.specify_fee
            ),
        )


        free_specify_by_rule = bool(
            price.free_specify_fee
        )


    vip = (
        vip_discount_policy(
            vip_name=
                customer[
                    "vip_name"
                ],

            rule_key=
                rule_key,
        )
    )


    vip_rate = (
        int(
            vip[
                "pay_rate"
            ]
        )
        if vip[
            "eligible"
        ]
        else 100
    )


    selected_point_item = None


    point_item_key = str(
        point_item_key
        or ""
    ).strip()


    if point_item_key:

        item = (
            POINT_ITEM_MAP.get(
                point_item_key
            )
        )


        if item is None:

            raise ValueError(
                "找不到這個點數福利。"
            )


        status = (
            point_item_status(
                rule_key=
                    rule_key,

                point_item_key=
                    point_item_key,

                point_balance=
                    customer[
                        "points"
                    ],

                quantity=
                    int(
                        quote[
                            "quantity"
                        ]
                    ),

                has_specified_staff=
                    bool(
                        selected_staff
                    ),
            )
        )


        if not status.get(
            "allowed"
        ):

            raise ValueError(
                str(
                    status.get(
                        "reason"
                    )
                    or "目前不能使用這個點數福利。"
                )
            )


        selected_point_item = (
            _point_item_for_rule(
                rule,
                item,
            )
        )


    finance = (
        calculate_checkout_financials(
            service_amount=
                int(
                    quote.get(
                        "customer_pay_amount"
                    )
                    or 0
                ),

            vip_pay_rate=
                vip_rate,

            specify_fee=
                specify_fee,

            point_item=
                selected_point_item,

            wallet_balance=
                customer[
                    "wallet_balance"
                ],

            use_wallet=
                bool(
                    use_wallet
                ),
        )
    )


    remaining = int(
        finance[
            "remaining_pay_amount"
        ]
    )


    payment_method = str(
        payment_method
        or ""
    ).strip()


    if remaining > 0:

        # 官網建立訂單時不選付款方式。
        # 接單人數滿後才由 Discord PaymentMethodView 讓顧客選擇。
        if (
            payment_method
            and payment_method
            not in PAYMENT_METHODS
        ):

            raise ValueError(
                "付款方式格式錯誤。"
            )


        if payment_method:

            payment_display = (
                payment_method
            )


            payment_info = (
                get_payment_method_info(
                    payment_method
                )
                or ""
            )


        else:

            payment_display = (
                "接單滿人後於 Discord 選擇"
            )


            payment_info = ""


    else:

        if (
            finance[
                "wallet_use_amount"
            ] > 0
        ):

            payment_display = (
                "錢包全額"
            )

        else:

            payment_display = (
                "無需額外付款"
            )


        payment_info = ""


    point_cost = (
        int(
            selected_point_item[
                "cost"
            ]
        )
        if selected_point_item
        else 0
    )


    point_name = (
        str(
            selected_point_item[
                "name"
            ]
        )
        if selected_point_item
        else ""
    )


    return {
        "quote":
            quote,

        "customer":
            customer,

        "vip":
            vip,

        "selected_staff":
            selected_staff,

        "selected_staff_ids": [
            item[
                "staff_id"
            ]
            for item
            in selected_staff
        ],

        "selected_role_keys":
            role_keys,

        "free_specify_by_rule":
            free_specify_by_rule,

        "point": {
            "key":
                (
                    selected_point_item[
                        "key"
                    ]
                    if selected_point_item
                    else None
                ),

            "name":
                point_name,

            "cost":
                point_cost,

            "balance_before":
                customer[
                    "points"
                ],

            # preview only, no DB mutation
            "balance_after_preview":
                max(
                    0,
                    customer[
                        "points"
                    ]
                    - point_cost,
                ),
        },

        "finance":
            finance,

        "payment": {
            "method":
                payment_display,

            "external_method":
                (
                    payment_method
                    if remaining > 0
                    else None
                ),

            "info":
                payment_info,
        },

        "wallet_after_preview":
            max(
                0,
                customer[
                    "wallet_balance"
                ]
                - int(
                    finance[
                        "wallet_use_amount"
                    ]
                ),
            ),

        "read_only_preview":
            True,

        "server_verified":
            True,
    }

# === PHASE 3B-2.4 STAFF ORDER FILTER ===

PUBLIC_DIRECT_ORDER_EXCLUDED_RULE_KEYS = {
    "farm_season_3x3_skin",
    "custom_custom_order",
    "farm_season_3x3_dc_skin",
    "farm_season_3x3_dc_loss",
    "farm_season_3x3_dc_skin_loss",
    "valorant_entertain",
    "valorant_tech",
    "valorant_top_tech",
}


def _role_keys_from_discord_ids(
    role_ids,
) -> tuple[str, ...]:

    role_id_set = {
        str(
            role_id
        ).strip()

        for role_id
        in (
            role_ids
            or []
        )

        if str(
            role_id
        ).strip()
    }


    result = []


    for role_key, role_id in (
        ALL_ROLE_IDS.items()
    ):

        if (
            str(
                role_id
            )
            in role_id_set
        ):

            result.append(
                role_key
            )


    return tuple(
        result
    )


def _load_cached_staff_role_keys(
    staff_id: str,
) -> tuple[str, ...]:

    staff_id = str(
        staff_id
        or ""
    ).strip()


    if (
        not staff_id
        or not WEB_DB.exists()
    ):

        return ()


    try:

        conn = sqlite3.connect(
            WEB_DB
        )

        conn.row_factory = (
            sqlite3.Row
        )


        try:

            cols = (
                _columns(
                    conn,
                    "web_staff_members",
                )
            )


            if (
                "discord_id"
                not in cols
                or "roles_json"
                not in cols
            ):

                return ()


            active_sql = (
                " AND COALESCE(is_active,1)=1"
                if "is_active"
                in cols
                else ""
            )


            row = conn.execute(
                "SELECT roles_json "
                "FROM web_staff_members "
                "WHERE CAST(discord_id AS TEXT)=?"
                + active_sql
                + " LIMIT 1",
                (
                    staff_id,
                ),
            ).fetchone()


        finally:

            conn.close()


    except sqlite3.Error:

        return ()


    if row is None:

        return ()


    return _role_keys_from_discord_ids(
        _json_list(
            row[
                "roles_json"
            ]
        )
    )


def _load_live_staff_role_keys(
    staff_id: str,
) -> tuple[
    tuple[str, ...],
    str,
]:

    staff_id = str(
        staff_id
        or ""
    ).strip()


    if not staff_id:

        return (
            (),
            "none",
        )


    try:

        from web.app.services.discord_service import (
            get_member_role_ids,
        )


        live_role_ids = (
            get_member_role_ids(
                staff_id
            )
        )


        return (
            _role_keys_from_discord_ids(
                live_role_ids
            ),
            "discord_live",
        )


    except Exception:

        cached = (
            _load_cached_staff_role_keys(
                staff_id
            )
        )


        if cached:

            return (
                cached,
                "web_staff_members_cache",
            )


        return (
            (),
            "unavailable",
        )


def eligible_rule_keys_for_role_keys(
    role_keys,
) -> list[str]:

    role_set = {
        str(
            role_key
        ).strip()

        for role_key
        in (
            role_keys
            or []
        )

        if str(
            role_key
        ).strip()
    }


    result = []


    for rule_key, rule in (
        ORDER_RULES.items()
    ):

        if (
            rule_key
            in PUBLIC_DIRECT_ORDER_EXCLUDED_RULE_KEYS
        ):

            continue


        if not rule.allow_specify:

            continue


        if (
            role_set
            & set(
                get_allowed_role_keys(rule)
            )
        ):

            result.append(
                rule_key
            )


    return sorted(
        result
    )


def _safe_group_mapping(
    value,
):

    if isinstance(
        value,
        dict,
    ):

        return value


    try:

        from dataclasses import (
            asdict,
            is_dataclass,
        )


        if is_dataclass(
            value
        ):

            return asdict(
                value
            )


    except Exception:

        pass


    if (
        hasattr(
            value,
            "__dict__",
        )
        and str(
            getattr(
                value.__class__,
                "__module__",
                "",
            )
        )
        == "web.app.services.order_groups"
    ):

        try:

            return dict(
                vars(
                    value
                )
            )

        except Exception:

            return None


    return None


def discover_order_group_rule_map(
) -> dict[str, list[str]]:

    try:

        from web.app.services import (
            order_groups as order_groups_module,
        )


    except Exception:

        return {}


    result: dict[
        str,
        set[str],
    ] = {}


    visited = set()


    def walk(
        value,
        depth: int = 0,
    ) -> set[str]:

        if depth > 14:

            return set()


        if isinstance(
            value,
            str,
        ):

            if value in ORDER_RULES:

                return {
                    value
                }

            return set()


        if (
            value is None
            or isinstance(
                value,
                (
                    int,
                    float,
                    bool,
                    bytes,
                ),
            )
        ):

            return set()


        object_id = id(
            value
        )


        if object_id in visited:

            return set()


        mapping = (
            _safe_group_mapping(
                value
            )
        )


        if (
            isinstance(
                value,
                (
                    dict,
                    list,
                    tuple,
                    set,
                ),
            )
            or mapping is not None
        ):

            visited.add(
                object_id
            )


        if isinstance(
            value,
            (
                list,
                tuple,
                set,
            ),
        ):

            found = set()


            for item in value:

                found.update(
                    walk(
                        item,
                        depth + 1,
                    )
                )


            return found


        if mapping is None:

            return set()


        found = set()


        for child in (
            mapping.values()
        ):

            found.update(
                walk(
                    child,
                    depth + 1,
                )
            )


        key = str(
            mapping.get(
                "key"
            )
            or ""
        ).strip()


        if (
            key
            and key
            not in ORDER_RULES
            and found
        ):

            result.setdefault(
                key,
                set(),
            ).update(
                found
            )


        return found


    for name, value in (
        vars(
            order_groups_module
        ).items()
    ):

        if name.startswith(
            "__"
        ):

            continue


        if callable(
            value
        ):

            continue


        if isinstance(
            value,
            type,
        ):

            continue


        walk(
            value
        )


    return {
        key:
            sorted(
                rules
            )

        for key, rules
        in result.items()
    }


def build_staff_order_filter(
    staff_id: str,
) -> dict:

    staff_id = str(
        staff_id
        or ""
    ).strip()


    role_keys, role_source = (
        _load_live_staff_role_keys(
            staff_id
        )
    )


    if not role_keys:

        raise ValueError(
            "目前無法確認這位陪玩的有效接單身分。"
        )


    eligible_rule_keys = (
        eligible_rule_keys_for_role_keys(
            role_keys
        )
    )


    eligible_set = set(
        eligible_rule_keys
    )


    group_rule_map = (
        discover_order_group_rule_map()
    )


    eligible_group_keys = []


    for group_key, rule_keys in (
        group_rule_map.items()
    ):

        if (
            set(
                rule_keys
            )
            & eligible_set
        ):

            eligible_group_keys.append(
                group_key
            )


    public_rules = {
        rule_key:
            {
                "key":
                    rule_key,

                "label":
                    str(
                        rule.label
                    ),

                "category":
                    str(
                        rule.category
                    ),

                "allowed_roles":
                    list(
                        get_allowed_role_keys(rule)
                    ),

                "allow_specify":
                    bool(
                        rule.allow_specify
                    ),
            }

        for rule_key, rule
        in ORDER_RULES.items()

        if rule_key
        not in PUBLIC_DIRECT_ORDER_EXCLUDED_RULE_KEYS
    }


    return {
        "staff_id":
            staff_id,

        "staff_role_keys":
            list(
                role_keys
            ),

        "role_source":
            role_source,

        "eligible_rule_keys":
            eligible_rule_keys,

        "eligible_group_keys":
            sorted(
                eligible_group_keys
            ),

        "group_rule_map":
            group_rule_map,

        "rules":
            public_rules,

        "excluded_rule_keys":
            sorted(
                PUBLIC_DIRECT_ORDER_EXCLUDED_RULE_KEYS
            ),

        "filter_active":
            True,
    }

# === /PHASE 3B-2.4 STAFF ORDER FILTER ===

# === PHASE 3B-2.5 STRICT STAFF CATALOG ===

MW_DIRECT_ORDER_EXCLUDED_RULE_KEYS = {
    "farm_season_3x3_skin",
    "custom_custom_order",
    "farm_season_3x3_dc_skin",
    "farm_season_3x3_dc_loss",
    "farm_season_3x3_dc_skin_loss",
    "valorant_entertain",
    "valorant_tech",
    "valorant_top_tech",
}


# Public card names.
#
# These are only a fallback for the visual catalog grouping.
# Actual eligibility ALWAYS comes from ORDER_RULES.allowed_roles.
MW_ORDER_GROUP_FALLBACKS = {
    "絕巴四幻神賭單": [
        "basic_exbar_gamble_zongheng",
        "basic_exbar_gamble_leiguan",
        "basic_exbar_gamble_tianyuan",
        "basic_exbar_gamble_rangefinder",
    ],

    "絕巴技術陪": [
        "basic_exbar_tech",
    ],

    "技術陪": [
        "basic_tech_secret_single",
        "basic_tech_secret_double",
        "basic_tech_topsecret_single",
        "basic_tech_topsecret_double",
    ],

    "教學單": [
        "basic_teaching_one",
        "basic_teaching_two",
    ],

    "娛樂陪": [
        "basic_entertain_single",
        "basic_entertain_double",
    ],

    "甜蜜單": [
        "basic_sweet_single",
    ],

    "油鍋": [
        "basic_oil_fuel",
        "basic_oil_satellite",
        "basic_oil_all",
    ],

    "賭約": [
        "basic_bet_1000",
        "basic_bet_1500",
        "basic_bet_2500",
    ],

    "體驗": [
        "basic_trial_500",
        "basic_trial_1000",
    ],

    "比翼雙飛": [
        "fun_lovebirds",
    ],

    "已讀亂回": [
        "fun_read_no_reply",
    ],

    "富得流油": [
        "fun_rich_enough",
    ],

    "吃自己": [
        "fun_eat_yourself",
    ],

    "Galagame": [
        "fun_mawan_galagame_basic",
        "fun_mawan_galagame_standard",
        "fun_mawan_galagame_hard",
        "fun_mawan_galagame_hell",
    ],

    "部門任務": [
        "farm_department_task",
    ],

    "半幣": [
        "farm_halfcoin_120m",
        "farm_halfcoin_360m",
    ],

    "Steam": [
        "steam_play",
    ],

    "特戰英豪 娛樂陪": [
        "valorant_entertain_ng",
        "valorant_entertain_ranked",
    ],
    "特戰英豪 超凡陪": [
        "valorant_ascendant_ng",
        "valorant_ascendant_ranked",
    ],
    "特戰英豪 神話陪": [
        "valorant_immortal_ng",
        "valorant_immortal_ranked",
    ],
    "特戰英豪 輻能陪": [
        "valorant_radiant_ng",
        "valorant_radiant_ranked",
    ],
    "英雄聯盟 娛樂陪": [
        "lol_entertain_aram",
        "lol_entertain_ng",
        "lol_entertain_ranked",
    ],
    "英雄聯盟 大師陪": [
        "lol_master_ng",
        "lol_master_ranked",
    ],
    "英雄聯盟 宗師陪": [
        "lol_grandmaster_ng",
        "lol_grandmaster_ranked",
    ],
    "英雄聯盟 菁英陪": [
        "lol_elite_ng",
        "lol_elite_ranked",
    ],
}


def _mw25_role_keys_from_ids(
    role_ids,
) -> tuple[str, ...]:

    role_id_set = {
        str(
            value
        ).strip()

        for value
        in (
            role_ids
            or []
        )

        if str(
            value
        ).strip()
    }


    result = []


    for role_key, role_id in (
        ALL_ROLE_IDS.items()
    ):

        if (
            str(
                role_id
            )
            in role_id_set
        ):

            result.append(
                role_key
            )


    return tuple(
        result
    )


def _mw25_load_staff_role_keys(
    staff_id: str,
) -> tuple[str, ...]:

    staff_id = str(
        staff_id
        or ""
    ).strip()


    if (
        not staff_id
        or not WEB_DB.exists()
    ):

        return ()


    try:

        conn = sqlite3.connect(
            WEB_DB
        )

        conn.row_factory = (
            sqlite3.Row
        )


        try:

            columns = {
                str(
                    row[1]
                )

                for row
                in conn.execute(
                    "PRAGMA table_info(web_staff_members)"
                ).fetchall()
            }


            if (
                "discord_id"
                not in columns
                or "roles_json"
                not in columns
            ):

                return ()


            active_sql = (
                " AND COALESCE(is_active,1)=1"
                if "is_active"
                in columns
                else ""
            )


            row = conn.execute(
                "SELECT roles_json "
                "FROM web_staff_members "
                "WHERE CAST(discord_id AS TEXT)=?"
                + active_sql
                + " LIMIT 1",
                (
                    staff_id,
                ),
            ).fetchone()


        finally:

            conn.close()


    except sqlite3.Error:

        return ()


    if row is None:

        return ()


    return _mw25_role_keys_from_ids(
        _json_list(
            row[
                "roles_json"
            ]
        )
    )


def mw25_eligible_rule_keys_for_roles(
    role_keys,
) -> list[str]:

    role_set = {
        str(
            role_key
        ).strip()

        for role_key
        in (
            role_keys
            or []
        )

        if str(
            role_key
        ).strip()
    }


    result = []


    for rule_key, rule in (
        ORDER_RULES.items()
    ):

        if (
            rule_key
            in MW_DIRECT_ORDER_EXCLUDED_RULE_KEYS
        ):

            continue


        # From staff roster means that employee is being specified.
        if not rule.allow_specify:

            continue


        if (
            role_set
            & set(
                get_allowed_role_keys(rule)
            )
        ):

            result.append(
                rule_key
            )


    return sorted(
        result
    )


def _mw25_discover_dynamic_groups(
) -> dict[str, list[str]]:

    try:

        from dataclasses import (
            asdict,
            is_dataclass,
        )

        from web.app.services import (
            order_groups as order_groups_module,
        )

    except Exception:

        return {}


    result = {}


    visited = set()


    def convert(
        value,
    ):

        if isinstance(
            value,
            dict,
        ):

            return value


        if is_dataclass(
            value
        ):

            try:

                return asdict(
                    value
                )

            except Exception:

                return None


        if (
            hasattr(
                value,
                "__dict__",
            )
            and str(
                getattr(
                    value.__class__,
                    "__module__",
                    "",
                )
            )
            == "web.app.services.order_groups"
        ):

            try:

                return dict(
                    vars(
                        value
                    )
                )

            except Exception:

                return None


        return None


    def walk(
        value,
        depth=0,
    ):

        if depth > 14:

            return set()


        if isinstance(
            value,
            str,
        ):

            if value in ORDER_RULES:

                return {
                    value
                }

            return set()


        if (
            value is None
            or isinstance(
                value,
                (
                    int,
                    float,
                    bool,
                    bytes,
                ),
            )
        ):

            return set()


        object_id = id(
            value
        )


        if object_id in visited:

            return set()


        mapping = convert(
            value
        )


        if (
            isinstance(
                value,
                (
                    dict,
                    list,
                    tuple,
                    set,
                ),
            )
            or mapping is not None
        ):

            visited.add(
                object_id
            )


        if isinstance(
            value,
            (
                list,
                tuple,
                set,
            ),
        ):

            found = set()


            for item in value:

                found.update(
                    walk(
                        item,
                        depth + 1,
                    )
                )


            return found


        if mapping is None:

            return set()


        found = set()


        for child in mapping.values():

            found.update(
                walk(
                    child,
                    depth + 1,
                )
            )


        if found:

            label = str(
                mapping.get(
                    "title"
                )
                or mapping.get(
                    "label"
                )
                or mapping.get(
                    "name"
                )
                or mapping.get(
                    "display_name"
                )
                or ""
            ).strip()


            if label:

                result.setdefault(
                    label,
                    set(),
                ).update(
                    found
                )


        return found


    for name, value in (
        vars(
            order_groups_module
        ).items()
    ):

        if name.startswith(
            "__"
        ):

            continue


        if callable(
            value
        ):

            continue


        if isinstance(
            value,
            type,
        ):

            continue


        walk(
            value
        )


    return {
        label:
            sorted(
                values
            )

        for label, values
        in result.items()
    }


def mw25_order_group_meta(
) -> dict[str, list[str]]:

    result = {
        label:
            [
                rule_key

                for rule_key
                in rule_keys

                if rule_key
                in ORDER_RULES
            ]

        for label, rule_keys
        in MW_ORDER_GROUP_FALLBACKS.items()
    }


    dynamic = (
        _mw25_discover_dynamic_groups()
    )


    for label, rule_keys in (
        dynamic.items()
    ):

        valid = [
            key

            for key
            in rule_keys

            if key
            in ORDER_RULES
        ]


        if valid:

            result[
                label
            ] = sorted(
                set(
                    valid
                )
            )


    return result


def build_staff_order_filter(
    staff_id: str,
) -> dict:

    staff_id = str(
        staff_id
        or ""
    ).strip()


    role_keys = (
        _mw25_load_staff_role_keys(
            staff_id
        )
    )


    if not role_keys:

        raise ValueError(
            "目前無法確認這位陪玩的有效接單身分。"
        )


    eligible_rule_keys = (
        mw25_eligible_rule_keys_for_roles(
            role_keys
        )
    )


    rules = {}


    for rule_key, rule in (
        ORDER_RULES.items()
    ):

        if (
            rule_key
            in MW_DIRECT_ORDER_EXCLUDED_RULE_KEYS
        ):

            continue


        rules[
            rule_key
        ] = {
            "key":
                rule_key,

            "label":
                str(
                    rule.label
                ),

            "category":
                str(
                    rule.category
                ),

            "allowed_roles":
                list(
                    get_allowed_role_keys(rule)
                ),

            "allow_specify":
                bool(
                    rule.allow_specify
                ),
        }


    group_meta = (
        mw25_order_group_meta()
    )


    eligible_set = set(
        eligible_rule_keys
    )


    eligible_group_labels = [
        label

        for label, rule_keys
        in group_meta.items()

        if (
            set(
                rule_keys
            )
            & eligible_set
        )
    ]


    return {
        "staff_id":
            staff_id,

        "staff_role_keys":
            list(
                role_keys
            ),

        "role_source":
            "web_staff_members",

        "eligible_rule_keys":
            eligible_rule_keys,

        "eligible_group_labels":
            sorted(
                eligible_group_labels
            ),

        "group_meta":
            group_meta,

        "rules":
            rules,

        "excluded_rule_keys":
            sorted(
                MW_DIRECT_ORDER_EXCLUDED_RULE_KEYS
            ),

        "filter_active":
            True,
    }

# === /PHASE 3B-2.5 STRICT STAFF CATALOG ===
