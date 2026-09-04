from __future__ import annotations

from typing import Any

from services.order_rules import (
    CATEGORY_LABELS,
    ORDER_RULES,
)


PUBLIC_ROLE_LABELS = {
    "top_protector": "頂護航",
    "female_protector": "女護航",
    "male_protector": "男護航",
    "male_companion": "男陪",
    "female_companion": "女陪",
}


CATEGORY_ORDER = [
    "basic",
    "fun",
    "farm",
    "steam",
    "valorant",
]


HIDDEN_PUBLIC_RULE_KEYS = {
    # 造型不再作為獨立商品。
    # 前台改成賽季 3x3｜普通底下 +3000T 的附加選項。
    "farm_season_3x3_skin",
    "farm_season_3x3_dc_skin",
    "farm_season_3x3_dc_loss",
    "farm_season_3x3_dc_skin_loss",
}


GROUP_SPECS = [
    {
        "key": "exbar_gamble",
        "category": "basic",
        "label": "絕巴四幻神賭單",
        "selector_label": "賭注目標",
        "description": "選擇本次四幻神賭單的目標。",
        "variants": [
            ("basic_exbar_gamble_zongheng", "縱橫"),
            ("basic_exbar_gamble_leiguan", "淚冠"),
            ("basic_exbar_gamble_tianyuan", "天圓地方"),
            ("basic_exbar_gamble_rangefinder", "測距儀"),
        ],
    },

    {
        "key": "exbar_tech",
        "category": "basic",
        "label": "絕巴技術陪",
        "description": "絕巴技術陪服務。",
        "variants": [
            ("basic_exbar_tech", "絕巴技術陪"),
        ],
    },

    {
        "key": "tech_play",
        "category": "basic",
        "label": "技術陪",
        "selector_label": "難度 / 護航人數",
        "description": "依難度與護航人數選擇方案。",
        "variants": [
            ("basic_tech_secret_single", "機密｜1 位護航"),
            ("basic_tech_secret_double", "機密｜2 位護航"),
            ("basic_tech_topsecret_single", "絕密｜1 位護航"),
            ("basic_tech_topsecret_double", "絕密｜2 位護航"),
        ],
    },

    {
        "key": "teaching",
        "category": "basic",
        "label": "教學單",
        "selector_label": "導師人數",
        "description": "由頂護航提供教學服務。",
        "variants": [
            ("basic_teaching_one", "1 名導師"),
            ("basic_teaching_two", "2 名導師"),
        ],
    },

    {
        "key": "entertain",
        "category": "basic",
        "label": "娛樂陪",
        "selector_label": "陪玩人數",
        "description": "以聊天、娛樂與遊戲體驗為主。",
        "variants": [
            ("basic_entertain_single", "單陪"),
            ("basic_entertain_double", "雙陪"),
        ],
    },

    {
        "key": "sweet",
        "category": "basic",
        "label": "甜蜜單",
        "variants": [
            ("basic_sweet_single", "單陪"),
        ],
    },

    {
        "key": "oil",
        "category": "basic",
        "label": "油鍋單",
        "selector_label": "方案",
        "variants": [
            ("basic_oil_fuel", "火箭燃油"),
            ("basic_oil_satellite", "GTI 衛星通訊天線"),
            ("basic_oil_all", "全包"),
        ],
    },

    {
        "key": "bet",
        "category": "basic",
        "label": "賭約單",
        "selector_label": "賭約金額",
        "variants": [
            ("basic_bet_1000", "1000T"),
            ("basic_bet_1500", "1500T"),
            ("basic_bet_2500", "2500T"),
        ],
    },

    {
        "key": "trial",
        "category": "basic",
        "label": "體驗單",
        "selector_label": "方案",
        "variants": [
            ("basic_trial_500", "500T"),
            ("basic_trial_1000", "1000T"),
        ],
    },

    {
        "key": "lovebirds",
        "category": "fun",
        "label": "比翼雙飛",
        "variants": [
            ("fun_lovebirds", "比翼雙飛"),
        ],
    },

    {
        "key": "read_no_reply",
        "category": "fun",
        "label": "已讀亂回",
        "variants": [
            ("fun_read_no_reply", "已讀亂回"),
        ],
    },

    {
        "key": "rich_enough",
        "category": "fun",
        "label": "豪到你了嗎",
        "variants": [
            ("fun_rich_enough", "豪到你了嗎"),
        ],
    },

    {
        "key": "eat_yourself",
        "category": "fun",
        "label": "想吃自己打",
        "variants": [
            ("fun_eat_yourself", "想吃自己打"),
        ],
    },

    {
        "key": "galagame",
        "category": "fun",
        "label": "魔丸娛樂嘎拉給木",
        "selector_label": "難度",
        "description": "依好感度難度選擇本次趣味方案。",
        "variants": [
            ("fun_mawan_galagame_basic", "基礎"),
            ("fun_mawan_galagame_standard", "標準"),
            ("fun_mawan_galagame_hard", "困難"),
            ("fun_mawan_galagame_hell", "地獄"),
        ],
    },

    {
        "key": "season_3x3",
        "category": "farm",
        "label": "賽季 3×3",
        "selector_label": "方案",
        "description": "賽季3x3可加購造型或包損耗；命運契約依數量計價。",
        "variants": [
            ("farm_season_3x3_normal", "賽季3x3"),
            ("farm_season_3x3_contract", "命運契約"),
        ],
    },

    {
        "key": "department_task",
        "category": "farm",
        "label": "代解部門任務",
        "variants": [
            ("farm_department_task", "客服報價"),
        ],
    },

    {
        "key": "halfcoin",
        "category": "farm",
        "label": "哈夫幣代洗",
        "selector_label": "數量",
        "variants": [
            ("farm_halfcoin_120m", "120M"),
            ("farm_halfcoin_360m", "360M"),
        ],
    },



    {
        "key": "steam",
        "category": "steam",
        "label": "Steam 陪玩",
        "variants": [
            ("steam_play", "Steam 陪玩"),
        ],
    },

    {
        "key": "valorant",
        "category": "valorant",
        "label": "Valorant 陪玩",
        "selector_label": "陪玩類型",
        "description": "選擇娛樂陪、技術陪或頂級技術陪。",
        "variants": [
            ("valorant_entertain", "娛樂陪"),
            ("valorant_tech", "技術陪"),
            ("valorant_top_tech", "頂級技術陪"),
        ],
    },
]


def _to_int(
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


def _price_text(
    price: int,
    pricing_type: str,
    unit_label: str,
) -> str:
    if (
        pricing_type == "manual"
        or price <= 0
    ):
        return "客服報價"

    if pricing_type == "fixed":
        return f"{price:,}T"

    return (
        f"{price:,}T"
        f" / {unit_label}"
    )


def _variant_data(
    rule_key: str,
    public_label: str,
    group_key: str,
) -> dict:
    rule = ORDER_RULES[
        rule_key
    ]

    price = _to_int(
        rule.price
    )

    pricing_type = str(
        rule.pricing_type
    )

    unit_label = str(
        rule.unit_label
        or "單"
    )

    quantity_enabled = (
        pricing_type
        in {
            "hourly",
            "game",
            "unit",
        }
    )

    min_quantity = int(
        rule.min_quantity
    )

    max_quantity = (
        int(rule.max_quantity)
        if rule.max_quantity
        is not None
        else 24
    )

    quantity_price_overrides = {}

    customer_adjustments = []

    # --------------------------------------------------------
    # 賽季 3x3 特殊規格
    # --------------------------------------------------------

    if (
        group_key == "season_3x3"
        and rule_key
        == "farm_season_3x3_normal"
    ):
        quantity_enabled = False
        min_quantity = 1
        max_quantity = 1

        customer_adjustments = [
            {
                "key": "skin",
                "label": "造型",
                "amount": 2500,
            },
            {
                "key": "loss_cover",
                "label": "包損耗",
                "amount": 500,
            },
        ]

    elif (
        group_key == "season_3x3"
        and rule_key
        == "farm_season_3x3_contract"
    ):
        quantity_enabled = True
        min_quantity = 1
        max_quantity = 7

    roles = [
        PUBLIC_ROLE_LABELS.get(
            role,
            str(role),
        )
        for role
        in rule.allowed_roles
    ]

    if (
        rule.required_staff_count
        == "player_count"
    ):
        required_staff = "依選擇人數"
    else:
        required_staff = (
            f"{int(rule.required_staff_count)} 位"
        )

    return {
        "rule_key": rule_key,
        "label": public_label,
        "price": price,
        "price_text": _price_text(
            price,
            pricing_type,
            unit_label,
        ),
        "pricing_type": pricing_type,
        "unit_label": unit_label,
        "quantity_enabled":
            quantity_enabled,
        "min_quantity":
            min_quantity,
        "max_quantity":
            max_quantity,
        "quantity_price_overrides":
            quantity_price_overrides,
        "player_count_enabled":
            bool(
                rule.player_count_enabled
            ),
        "min_player_count":
            int(
                rule.min_player_count
            ),
        "max_player_count":
            (
                int(
                    rule.max_player_count
                )
                if rule.max_player_count
                is not None
                else 8
            ),
        "price_multiply_player_count":
            bool(
                rule.price_multiply_player_count
            ),
        "allow_specify":
            bool(
                rule.allow_specify
            ),
        "max_specified_count":
            (
                int(
                    rule.max_specified_count
                )
                if rule.max_specified_count
                is not None
                else None
            ),
        "required_staff":
            required_staff,
        "allowed_roles":
            roles,
        "point_benefits_allowed":
            bool(
                rule.point_benefits_allowed
            ),
        "service_bonus_buy":
            (
                int(
                    rule.service_bonus_buy
                )
                if rule.service_bonus_buy
                else None
            ),
        "service_bonus_gift":
            int(
                rule.service_bonus_gift
                or 0
            ),
        "customer_adjustments":
            customer_adjustments,
        "note":
            str(
                rule.note
                or ""
            ),
    }


def _group_data(
    spec: dict,
) -> dict | None:
    variants = []

    for (
        rule_key,
        public_label,
    ) in spec["variants"]:

        if (
            rule_key
            in HIDDEN_PUBLIC_RULE_KEYS
        ):
            continue

        if rule_key not in ORDER_RULES:
            continue

        variants.append(
            _variant_data(
                rule_key,
                public_label,
                spec["key"],
            )
        )

    if not variants:
        return None

    numeric_prices = [
        int(
            variant["price"]
        )
        for variant
        in variants
        if int(
            variant["price"]
        ) > 0
    ]

    starting_price = (
        min(numeric_prices)
        if numeric_prices
        else 0
    )

    manual_only = all(
        variant[
            "pricing_type"
        ] == "manual"
        for variant
        in variants
    )

    if manual_only:
        starting_price_text = (
            "客服報價"
        )

    elif len(variants) == 1:
        starting_price_text = (
            variants[0][
                "price_text"
            ]
        )

    else:
        starting_price_text = (
            f"{starting_price:,}T 起"
        )

    return {
        "key": spec["key"],
        "category":
            spec["category"],
        "category_label":
            CATEGORY_LABELS.get(
                spec["category"],
                spec["category"],
            ),
        "label":
            spec["label"],
        "selector_label":
            spec.get(
                "selector_label",
                "方案",
            ),
        "description":
            spec.get(
                "description",
                "選擇適合你的方案。",
            ),
        "starting_price":
            starting_price,
        "starting_price_text":
            starting_price_text,
        "variants":
            variants,
    }


def get_public_order_categories() -> list[dict]:
    result = [
        {
            "key": "all",
            "label": "全部",
        }
    ]

    available = {
        spec["category"]
        for spec
        in GROUP_SPECS
    }

    for category in CATEGORY_ORDER:

        if category not in available:
            continue

        result.append(
            {
                "key": category,
                "label":
                    CATEGORY_LABELS.get(
                        category,
                        category,
                    ),
            }
        )

    return result


def get_grouped_order_catalog(
    category: str = "all",
) -> list[dict]:
    category = str(
        category
        or "all"
    ).strip()

    valid = {
        item["key"]
        for item
        in get_public_order_categories()
    }

    if category not in valid:
        category = "all"

    groups = []

    for spec in GROUP_SPECS:

        if (
            category != "all"
            and spec["category"]
            != category
        ):
            continue

        group = _group_data(
            spec
        )

        if group:
            groups.append(
                group
            )

    return groups
