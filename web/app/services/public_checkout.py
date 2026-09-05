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

    if (
        rule_key
        == "farm_season_3x3_normal"
    ):

        return replace(
            source_rule,

            pricing_type="fixed",

            price=
                SEASON_NORMAL_PRICE,

            min_quantity=1,

            max_quantity=1,

            staff_adjustments=
                dict(
                    SEASON_NORMAL_ADJUSTMENTS
                ),

            staff_adjustment_labels=
                dict(
                    SEASON_NORMAL_ADJUSTMENT_LABELS
                ),
        )


    if (
        rule_key
        == "farm_season_3x3_contract"
    ):

        return replace(
            source_rule,

            pricing_type="unit",

            price=
                SEASON_CONTRACT_UNIT_PRICE,

            unit_label="個",

            min_quantity=1,

            max_quantity=
                SEASON_CONTRACT_MAX,

            staff_adjustments={},

            staff_adjustment_labels={},
        )


    return source_rule


def build_public_quote(
    *,
    rule_key: str,
    quantity: int | None = None,
    player_count: int | None = None,
    customer_adjustments: Any = None,
    specified_staff_id: str | None = None,
) -> dict:

    rule_key = str(
        rule_key
        or ""
    ).strip()


    if not rule_key:

        raise ValueError(
            "請先選擇商品方案。"
        )


    if (
        rule_key
        in PUBLIC_DISABLED_RULE_KEYS
    ):

        raise ValueError(
            "這個舊方案已停止提供新訂單。"
        )


    rule = _get_public_rule(
        rule_key
    )


    quantity_value = _to_int(
        quantity,
        1,
    )


    if quantity_value <= 0:
        quantity_value = 1


    if (
        rule_key
        == "farm_season_3x3_contract"
        and quantity_value
        > SEASON_CONTRACT_MAX
    ):

        raise ValueError(
            "命運契約最多只能選 7 個。"
        )


    player_count_value = _to_int(
        player_count,
        1,
    )


    if player_count_value <= 0:
        player_count_value = 1


    if (
        rule.player_count_enabled
        and rule.max_player_count is None
        and player_count_value > 8
    ):

        raise ValueError(
            "網站單次最多選擇 8 位陪玩。"
        )


    adjustments = (
        _normalize_adjustments(
            customer_adjustments
        )
    )


    for key in adjustments:

        if (
            key
            in CUSTOMER_FORBIDDEN_ADJUSTMENTS
        ):

            raise ValueError(
                "這個優惠只能由客服套用。"
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

        staff_adjustments=
            adjustments,
    )


    base_amount = int(
        result.base_amount
    )


    adjustment_amount = int(
        result.staff_adjustment_amount
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
