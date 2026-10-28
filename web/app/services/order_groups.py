from __future__ import annotations

from typing import Any

from services.order_rule_store import (
    get_active_override,
    get_custom_rule_definition,
)
from services.order_rules import (
    CATEGORY_LABELS,
    ORDER_RULES,
    SOURCE_AUTHORITY_RULE_KEYS,
    get_allowed_role_labels,
)


PUBLIC_ROLE_LABELS = {
    "top_protector": "頂護航",
    "female_protector": "女護航",
    "male_protector": "男護航",
    "male_companion": "男陪",
    "female_companion": "女陪",
}


CATEGORY_ORDER = [
    "delta_desktop_basic",
    "delta_mobile_basic",
    "delta_desktop_fun",
    "farm",
    "steam",
    "valorant",
    "lol",
    "apex",
]


HIDDEN_PUBLIC_RULE_KEYS = {
    # 造型不再作為獨立商品。
    # 前台改成賽季 3x3｜普通底下 +3000T 的附加選項。
    "farm_season_3x3_skin",
    "farm_season_3x3_dc_skin",
    "farm_season_3x3_dc_loss",
    "farm_season_3x3_dc_skin_loss",
    "valorant_entertain",
    "valorant_tech",
    "valorant_top_tech",
}


GROUP_SPECS = [
    {
        "key": "exbar_gamble",
        "category": "delta_desktop_basic",
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
        "category": "delta_desktop_basic",
        "label": "絕巴技術陪",
        "variants": [
            ("basic_exbar_tech", "絕巴技術陪"),
        ],
    },

    {
        "key": "tech_play",
        "category": "delta_desktop_basic",
        "label": "技術陪",
        "selector_label": "難度",
        "description": "三角洲端遊技術陪；難度與陪玩人數分開選擇。",
        "variants": [
            ("basic_tech_secret_single", "機密"),
            ("basic_tech_topsecret_single", "絕密"),
        ],
    },

    {
        "key": "tech_play_mobile",
        "category": "delta_mobile_basic",
        "label": "技術陪",
        "selector_label": "難度",
        "description": "三角洲手遊技術陪；難度與陪玩人數分開選擇。",
        "variants": [
            ("basic_mobile_tech_secret_single", "機密"),
            ("basic_mobile_tech_topsecret_single", "絕密"),
        ],
    },

    {
        "key": "entertain",
        "category": "delta_desktop_basic",
        "label": "娛樂陪",
        "selector_label": "陪玩類型",
        "description": "娛樂陪類型與陪玩人數分開選擇；福利累積 10 個服務小時回饋 1 小時。",
        "variants": [
            ("basic_entertain_single", "不限"),
            ("basic_entertain_female_single", "女陪"),
            ("basic_entertain_male_single", "男陪"),
        ],
    },

    {
        "key": "entertain_mobile",
        "category": "delta_mobile_basic",
        "label": "娛樂陪",
        "selector_label": "陪玩類型",
        "description": "娛樂陪類型與陪玩人數分開選擇；價格與端遊相同。",
        "variants": [
            ("basic_mobile_entertain_single", "不限"),
            ("basic_mobile_entertain_female_single", "女陪"),
            ("basic_mobile_entertain_male_single", "男陪"),
        ],
    },

    {
        "key": "oil",
        "category": "delta_desktop_basic",
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
        "category": "delta_desktop_basic",
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
        "category": "delta_desktop_basic",
        "label": "體驗單",
        "selector_label": "方案",
        "variants": [
            ("basic_trial_500", "500T"),
            ("basic_trial_1000", "1000T"),
        ],
    },

    {
        "key": "lovebirds",
        "category": "delta_desktop_fun",
        "label": "比翼雙飛",
        "variants": [
            ("fun_lovebirds", "比翼雙飛"),
        ],
    },

    {
        "key": "read_no_reply",
        "category": "delta_desktop_fun",
        "label": "已讀亂回",
        "variants": [
            ("fun_read_no_reply", "已讀亂回"),
        ],
    },

    {
        "key": "rich_enough",
        "category": "delta_desktop_fun",
        "label": "豪到你了嗎",
        "variants": [
            ("fun_rich_enough", "豪到你了嗎"),
        ],
    },

    {
        "key": "eat_yourself",
        "category": "delta_desktop_fun",
        "label": "想吃自己打",
        "variants": [
            ("fun_eat_yourself", "想吃自己打"),
        ],
    },

    {
        "key": "galagame",
        "category": "delta_desktop_fun",
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
        "description": "娛樂陪福利累積 10 個服務小時回饋 1 小時，可於達標當單直接折抵。",
        "variants": [
            ("steam_play", "Steam 陪玩"),
        ],
    },

    {"key":"valorant_entertain","category":"valorant","label":"特戰英豪｜娛樂陪","selector_label":"模式","description":"娛樂陪福利：NG 累積 10 個服務小時回饋 1 小時、積分累積 10 個服務局回饋 1 局，達標當單可直接折抵；指定每位 +100T，NG 2 小時 / 積分 2 局以上免指定費。","variants":[("valorant_entertain_ng","NG"),("valorant_entertain_ranked","積分")]},
    {"key":"valorant_ascendant","category":"valorant","label":"特戰英豪｜超凡陪","selector_label":"模式","description":"指定每位 +100T，NG 2 小時 / 積分 2 局以上免指定費。","variants":[("valorant_ascendant_ng","NG"),("valorant_ascendant_ranked","積分")]},
    {"key":"valorant_immortal","category":"valorant","label":"特戰英豪｜神話陪","selector_label":"模式","description":"指定每位 +100T，NG 2 小時 / 積分 2 局以上免指定費。","variants":[("valorant_immortal_ng","NG"),("valorant_immortal_ranked","積分")]},
    {"key":"valorant_radiant","category":"valorant","label":"特戰英豪｜輻能陪","selector_label":"模式","description":"指定每位 +100T，NG 2 小時 / 積分 2 局以上免指定費。","variants":[("valorant_radiant_ng","NG"),("valorant_radiant_ranked","積分")]},
    {"key":"lol_entertain","category":"lol","label":"英雄聯盟｜娛樂陪","selector_label":"模式","description":"娛樂陪福利：ARAM / NG 累積 10 個服務小時回饋 1 小時、積分累積 10 個服務局回饋 1 局，達標當單可直接折抵；指定每位 +100T，ARAM / NG 2 小時、積分 2 局以上免指定費。","variants":[("lol_entertain_aram","ARAM"),("lol_entertain_ng","NG"),("lol_entertain_ranked","積分")]},
    {"key":"lol_master","category":"lol","label":"英雄聯盟｜大師陪","selector_label":"模式","description":"指定每位 +100T，NG 2 小時 / 積分 2 局以上免指定費。","variants":[("lol_master_ng","NG"),("lol_master_ranked","積分")]},
    {"key":"lol_grandmaster","category":"lol","label":"英雄聯盟｜宗師陪","selector_label":"模式","description":"指定每位 +100T，NG 2 小時 / 積分 2 局以上免指定費。","variants":[("lol_grandmaster_ng","NG"),("lol_grandmaster_ranked","積分")]},
    {"key":"lol_elite","category":"lol","label":"英雄聯盟｜菁英陪","selector_label":"模式","description":"指定每位 +100T，NG 2 小時 / 積分 2 局以上免指定費。","variants":[("lol_elite_ng","NG"),("lol_elite_ranked","積分")]},

    {
        "key": "apex_entertain",
        "category": "apex",
        "label": "APEX｜娛樂陪",
        "selector_label": "模式",
        "description": "NG 300T/人/H、積分 350T/人/H；指定每位 +100T，2H 以上免指定費；娛樂陪福利累積 10 個服務小時回饋 1 小時，可於達標當單直接折抵。",
        "variants": [
            ("apex_entertain_ng", "NG"),
            ("apex_entertain_ranked", "積分"),
        ],
    },
    {
        "key": "apex_diamond",
        "category": "apex",
        "label": "APEX｜鑽石陪",
        "selector_label": "模式",
        "description": "NG 400T/人/H、積分 450T/人/H；指定每位 +100T，2H 以上免指定費。",
        "variants": [
            ("apex_diamond_ng", "NG"),
            ("apex_diamond_ranked", "積分"),
        ],
    },
    {
        "key": "apex_master",
        "category": "apex",
        "label": "APEX｜大師陪",
        "selector_label": "模式",
        "description": "NG 500T/人/H、積分 550T/人/H；指定每位 +100T，2H 以上免指定費。",
        "variants": [
            ("apex_master_ng", "NG"),
            ("apex_master_ranked", "積分"),
        ],
    },
    {
        "key": "apex_predator",
        "category": "apex",
        "label": "APEX｜頂獵陪",
        "selector_label": "模式",
        "description": "NG 600T/人/H、積分 650T/人/H；指定每位 +100T，2H 以上免指定費。",
        "variants": [
            ("apex_predator_ng", "NG"),
            ("apex_predator_ranked", "積分"),
        ],
    },

]


# 甜蜜單與教學單依遊戲分組；接單資格與智慧派單條件只留在內部規則。
_GAME_SHARED_GROUPS = (
    ("delta_desktop", "delta_desktop_basic", "三角洲<端遊>"),
    ("delta_mobile", "delta_mobile_basic", "三角洲<手遊>"),
    ("steam", "steam", "Steam"),
    ("valorant", "valorant", "特戰英豪"),
    ("lol", "lol", "英雄聯盟"),
    ("apex", "apex", "APEX"),
)

for _prefix, _category, _game_label in _GAME_SHARED_GROUPS:
    GROUP_SPECS.append({
        "key": f"{_prefix}_sweet",
        "category": _category,
        "label": "甜蜜單",
        "selector_label": "陪玩類型",
        "description": f"{_game_label}限定甜蜜單；陪玩類型與人數分開選擇。",
        "variants": [
            (f"{_prefix}_sweet_female", "女陪"),
            (f"{_prefix}_sweet_male", "男陪"),
            (f"{_prefix}_sweet_any", "不限"),
        ],
    })

_GAME_TEACHING_GROUPS = (
    ("delta_desktop", "delta_desktop_basic", "三角洲<端遊>"),
    ("delta_mobile", "delta_mobile_basic", "三角洲<手遊>"),
    ("valorant", "valorant", "特戰英豪"),
    ("lol", "lol", "英雄聯盟"),
    ("apex", "apex", "APEX"),
)

for _prefix, _category, _game_label in _GAME_TEACHING_GROUPS:
    GROUP_SPECS.append({
        "key": f"{_prefix}_teaching",
        "category": _category,
        "label": "教學單",
        "description": f"{_game_label}限定教學服務。",
        "variants": [
            (f"{_prefix}_teaching_one", "1 對 1 教學"),
        ],
    })


def _presentation_intro(rule_key: str) -> str:
    """Read customer-facing intro copy without mixing it into pricing rules."""
    key = str(rule_key or "").strip()
    if not key:
        return ""

    try:
        active = get_active_override(key)
        payload = (active or {}).get("payload") or {}
        if isinstance(payload, dict) and "intro" in payload:
            return str(payload.get("intro") or "").strip()
    except Exception:
        pass

    try:
        custom = get_custom_rule_definition(key)
        payload = (custom or {}).get("payload") or {}
        if isinstance(payload, dict):
            return str(payload.get("intro") or "").strip()
    except Exception:
        pass

    return ""


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

    roles = get_allowed_role_labels(rule)

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
        "intro": _presentation_intro(rule_key),
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
                "",
            ),
        "starting_price":
            starting_price,
        "starting_price_text":
            starting_price_text,
        "variants":
            variants,
    }


DYNAMIC_ADMIN_GROUP_LABEL = "後台新增商品"


def _current_group_specs() -> list[dict]:
    """Return storefront groups using the effective manager-controlled names.

    Built-in products used to keep the hard-coded GROUP_SPECS name forever, so
    changing a product's second/third-level name in the manager page only changed
    the rule itself while the public card still showed the old text.  A non-empty
    catalog_group_label now means the manager intentionally moved/renamed that
    built-in variant, so resolve both its group name and variant name live.

    Custom rules still live in SQLite and can be created without a Git deploy, so
    the final catalog is always rebuilt at request time.
    """
    specs: list[dict] = []

    for source_spec in GROUP_SPECS:
        base_variants: list[tuple[str, str]] = []
        moved_variants: dict[str, list[tuple[str, str]]] = {}

        for rule_key, public_label in source_spec.get("variants", []):
            rule = ORDER_RULES.get(str(rule_key))
            manager_group_label = (
                ""
                if str(rule_key) in SOURCE_AUTHORITY_RULE_KEYS
                else (
                    str(getattr(rule, "catalog_group_label", "") or "").strip()
                    if rule is not None
                    else ""
                )
            )

            if not manager_group_label:
                base_variants.append((str(rule_key), str(public_label)))
                continue

            effective_label = str(
                getattr(rule, "label", "")
                or public_label
            )
            moved_variants.setdefault(manager_group_label, []).append(
                (str(rule_key), effective_label)
            )

        if base_variants:
            specs.append({
                **source_spec,
                "variants": base_variants,
            })

        for manager_group_label, variants in moved_variants.items():
            specs.append({
                **source_spec,
                "label": manager_group_label,
                "variants": variants,
            })

    grouped = {
        (
            str(spec.get("category") or ""),
            str(spec.get("label") or ""),
        ): spec
        for spec in specs
    }

    is_custom = getattr(
        ORDER_RULES,
        "is_custom",
        None,
    )
    if not callable(is_custom):
        return specs

    for rule_key, rule in ORDER_RULES.items():
        key = str(rule_key or "").strip()
        if not key:
            continue

        try:
            if not bool(is_custom(key)):
                continue
        except Exception:
            continue

        category = str(
            getattr(rule, "category", "")
            or ""
        ).strip()
        if not category:
            continue

        group_label = (
            str(
                getattr(
                    rule,
                    "catalog_group_label",
                    "",
                )
                or ""
            ).strip()
            or DYNAMIC_ADMIN_GROUP_LABEL
        )

        group_key = (category, group_label)
        spec = grouped.get(group_key)

        if spec is None:
            intro = _presentation_intro(key)
            spec = {
                "key": f"admin_{key}",
                "category": category,
                "label": group_label,
                "selector_label": "方案",
                "description": intro,
                "variants": [],
            }
            specs.append(spec)
            grouped[group_key] = spec

        if not any(
            str(existing_key) == key
            for existing_key, _label
            in spec.get("variants", [])
        ):
            spec["variants"].append(
                (
                    key,
                    str(
                        getattr(rule, "label", key)
                        or key
                    ),
                )
            )

    return specs


def get_public_order_categories() -> list[dict]:
    result = [
        {
            "key": "all",
            "label": "全部",
        }
    ]

    current_specs = _current_group_specs()
    available = {
        spec["category"]
        for spec
        in current_specs
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

    current_specs = _current_group_specs()
    valid = {
        "all",
        *[
            str(spec.get("category") or "")
            for spec in current_specs
            if str(spec.get("category") or "")
        ],
    }

    if category not in valid:
        category = "all"

    groups = []

    for spec in current_specs:

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
