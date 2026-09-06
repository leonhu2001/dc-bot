from __future__ import annotations

from dataclasses import replace
from typing import Any

from services.order_rules import (
    CATEGORY_LABELS,
    ORDER_RULES,
    ROLE_LABELS,
    calculate_price,
    get_allowed_role_labels,
)


PUBLIC_DISABLED_RULE_KEYS = {
    "farm_season_3x3_skin",
    "farm_season_3x3_dc_skin",
    "farm_season_3x3_dc_loss",
    "farm_season_3x3_dc_skin_loss",
    "valorant_entertain",
    "valorant_tech",
    "valorant_top_tech",
}


PUBLIC_ROLE_LABELS = {
    "top_protector": "頂護航",
    "female_protector": "女護航",
    "male_protector": "男護航",
    "male_companion": "男陪",
    "female_companion": "女陪",
}


SEASON_NORMAL_PRICE = 4000

SEASON_CONTRACT_UNIT_PRICE = 600

SEASON_CONTRACT_MAX = 7

APEX_RANKED_SURCHARGE_PER_HOUR_PER_PLAYER = 50



SEASON_NORMAL_ADJUSTMENTS = {
    "skin": 2500,
    "loss_cover": 500,
}


SEASON_NORMAL_ADJUSTMENT_LABELS = {
    "skin": "造型",
    "loss_cover": "包損耗",
}


CUSTOMER_FORBIDDEN_ADJUSTMENTS = {
    "early_booking",
}


def _to_int(
    value: Any,
    default: int = 0,
) -> int:
    try:
        if value is None or value == "":
            return default

        return int(value)

    except (
        TypeError,
        ValueError,
    ):
        return default


def _normalize_adjustments(
    value: Any,
) -> list[str]:

    if value is None:
        return []

    if not isinstance(
        value,
        list,
    ):
        raise ValueError(
            "附加需求格式錯誤。"
        )

    result = []

    for item in value:

        key = str(
            item
            or ""
        ).strip()

        if (
            key
            and key not in result
        ):
            result.append(
                key
            )

    return result


def _public_role_label(
    role: str,
) -> str:

    return (
        PUBLIC_ROLE_LABELS.get(
            role
        )
        or ROLE_LABELS.get(
            role
        )
        or str(role)
    )


def _get_public_rule(
    rule_key: str,
):
    source_rule = (
        ORDER_RULES.get(
            rule_key
        )
    )

    if source_rule is None:

        raise ValueError(
            "找不到這個商品方案。"
        )


    # --------------------------------------------------------
    # 賽季 3x3 公開網站新規格
    #
    # 用 dataclasses.replace 建立一次性副本。
    # 不修改全域 ORDER_RULES。
    # 不影響 Discord Bot runtime。
    # --------------------------------------------------------

    is_apex_base_rule = (
        str(rule.category) == "apex"
        and not rule_key.endswith("_ranked")
    )

    if (
        rule_key
        == "farm_season_3x3_normal"
    ):

        unknown = [
            key
            for key
            in adjustments
            if key not in
            SEASON_NORMAL_ADJUSTMENTS
        ]


        if unknown:

            raise ValueError(
                "這張訂單包含未開放的附加需求。"
            )

    elif is_apex_base_rule:

        unknown = [
            key
            for key
            in adjustments
            if key != "ranked"
        ]

        if unknown:

            raise ValueError(
                "這張 APEX 訂單包含未開放的附加需求。"
            )

    elif adjustments:

        raise ValueError(
            "這個方案沒有開放附加需求。"
        )


    result = calculate_price(
        rule,

        quantity=
            quantity_value,

        player_count=(
            player_count_value
            if rule.player_count_enabled
            else None
        ),

        specified_roles=[],

        staff_adjustments=(
            []
            if is_apex_base_rule
            else adjustments
        ),
    )

    base_amount = int(
        result.base_amount
    )


    adjustment_amount = int(
        result.staff_adjustment_amount
    )

    apex_ranked_surcharge = 0

    if (
        is_apex_base_rule
        and "ranked" in adjustments
    ):
        apex_ranked_surcharge = (
            APEX_RANKED_SURCHARGE_PER_HOUR_PER_PLAYER
            * int(quantity_value)
            * int(
                player_count_value
                if rule.player_count_enabled
                else 1
            )
        )
        adjustment_amount += int(
            apex_ranked_surcharge
        )


    special_price_applied = False


    # --------------------------------------------------------
    # 命運契約第 5 個封頂 3000T。
    # --------------------------------------------------------

    original_amount = (
        base_amount
        + adjustment_amount
    )


    specified_staff_id = str(
        specified_staff_id
        or ""
    ).strip() or None


    if (
        specified_staff_id
        and not rule.allow_specify
    ):

        raise ValueError(
            "這個方案不開放指定人員。"
        )


    adjustment_details = []


    for key in adjustments:

        if (
            is_apex_base_rule
            and key == "ranked"
        ):
            adjustment_details.append(
                {
                    "key":
                        key,

                    "label":
                        "積分場（每人每小時 +50T）",

                    "amount":
                        int(
                            apex_ranked_surcharge
                        ),
                }
            )
            continue

        adjustment_details.append(
            {
                "key":
                    key,

                "label":
                    rule.staff_adjustment_labels.get(
                        key,
                        key,
                    ),

                "amount":
                    int(
                        rule.staff_adjustments[
                            key
                        ]
                    ),
            }
        )

    return {
        "rule_key":
            rule_key,

        "category":
            str(
                rule.category
            ),

        "category_label":
            CATEGORY_LABELS.get(
                rule.category,
                str(
                    rule.category
                ),
            ),

        "item":
            str(
                rule.label
            ),

        "pricing_type":
            str(
                rule.pricing_type
            ),

        "unit_label":
            str(
                rule.unit_label
                or "單"
            ),

        "quantity":
            quantity_value,

        "player_count":
            (
                player_count_value
                if rule.player_count_enabled
                else 1
            ),

        "required_staff_count":
            int(
                result.required_staff_count
            ),

        "service_quantity":
            int(
                result.service_quantity
            ),

        "base_amount":
            base_amount,

        "adjustment_amount":
            adjustment_amount,

        "original_amount":
            original_amount,

        "customer_pay_amount":
            original_amount,

        "manual_quote":
            (
                str(
                    rule.pricing_type
                )
                == "manual"
            ),

        "special_price_applied":
            special_price_applied,

        "customer_adjustments":
            adjustment_details,

        "allowed_roles":
            get_allowed_role_labels(
                rule
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

        "specified_staff_id":
            specified_staff_id,

        "point_benefits_allowed":
            bool(
                rule.point_benefits_allowed
            ),

        "verified_by_server":
            True,

        "benefits_pending":
            True,
    }
