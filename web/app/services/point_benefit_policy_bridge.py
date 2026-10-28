from __future__ import annotations

from typing import Any


def _patch_entertainment_variants(order_groups) -> None:
    variants_by_key = {
        "entertain": [
            ("basic_entertain_single", "單陪（不限）"),
            ("basic_entertain_female_single", "女單陪"),
            ("basic_entertain_male_single", "男單陪"),
            ("basic_entertain_double", "雙陪（不限）"),
            ("basic_entertain_female_double", "女雙陪"),
            ("basic_entertain_male_double", "男雙陪"),
        ],
        "entertain_mobile": [
            ("basic_mobile_entertain_single", "單陪（不限）"),
            ("basic_mobile_entertain_female_single", "女單陪"),
            ("basic_mobile_entertain_male_single", "男單陪"),
            ("basic_mobile_entertain_double", "雙陪（不限）"),
            ("basic_mobile_entertain_female_double", "女雙陪"),
            ("basic_mobile_entertain_male_double", "男雙陪"),
        ],
    }

    for spec in order_groups.GROUP_SPECS:
        key = str(spec.get("key") or "")
        variants = variants_by_key.get(key)
        if variants is None:
            continue
        spec["selector_label"] = "陪玩規格"
        spec["variants"] = list(variants)


def install_shared_point_benefit_policy() -> None:
    """Keep Web checkout on the same manager, seat and funding policy as Discord."""

    from services import point_benefit_catalog as point_catalog
    from services.self_service_point_benefit_policy import (
        check_order_point_benefit_allowed,
    )
    from web.app.services import checkout_preview as checkout
    from web.app.services import order_groups

    if getattr(checkout, "_shared_point_benefit_policy_installed", False):
        return

    _patch_entertainment_variants(order_groups)

    def point_item_status(
        *,
        rule_key: str,
        point_item_key: str,
        point_balance: int,
        quantity: int,
        has_specified_staff: bool,
    ) -> dict:
        rule = checkout.ORDER_RULES.get(str(rule_key))
        item = checkout.POINT_ITEM_MAP.get(str(point_item_key))
        if rule is None or item is None:
            return {"allowed": False, "reason": "不支援這個點數福利。"}
        if int(point_balance or 0) < int(item["cost"]):
            return {"allowed": False, "reason": "點數不足。"}

        allowed, reason = check_order_point_benefit_allowed(
            rule,
            item,
            {
                "quantity": max(1, int(quantity or 1)),
                "specified_staff_ids": ["selected"] if has_specified_staff else [],
            },
        )
        if allowed:
            return {"allowed": True, "reason": ""}

        result = {"allowed": False, "reason": reason or "此點數福利目前不可使用。"}
        if (
            str(item.get("kind") or "") == "free_specify_fee"
            and not has_specified_staff
        ):
            result["requires_specified"] = True
        return result

    checkout.point_item_status = point_item_status

    original_build_options = checkout.build_checkout_options

    def build_checkout_options(*args, **kwargs):
        result = original_build_options(*args, **kwargs)
        quote = result.get("quote") if isinstance(result, dict) else {}
        if not isinstance(quote, dict):
            quote = {}
        selected_seats = max(
            1,
            int(
                quote.get("required_staff_count")
                or quote.get("player_count")
                or kwargs.get("player_count")
                or 1
            ),
        )

        for option in result.get("point_options", []) if isinstance(result, dict) else []:
            try:
                reward_seats = int(option.get("seat_count") or 0)
            except (TypeError, ValueError):
                reward_seats = 0
            if reward_seats > 0 and reward_seats != selected_seats:
                option["allowed"] = False
                option["reason"] = "這張服務加贈券不適用此單陪／雙陪規格。"
        return result

    checkout.build_checkout_options = build_checkout_options

    original_build_preview = checkout.build_checkout_preview

    def build_checkout_preview(*args, **kwargs):
        rule_key = str(kwargs.get("rule_key") or "").strip()
        point_item_key = str(kwargs.get("point_item_key") or "").strip()
        if rule_key and point_item_key:
            rule = checkout.ORDER_RULES.get(rule_key)
            item = checkout.POINT_ITEM_MAP.get(point_item_key)
            if rule is not None and item is not None and str(item.get("kind") or "") == "service_bonus":
                try:
                    selected_players = max(1, int(kwargs.get("player_count") or 1))
                except (TypeError, ValueError):
                    selected_players = 1
                if not point_catalog.is_service_bonus_allowed_for_rule(
                    rule,
                    item,
                    player_count=selected_players,
                ):
                    raise ValueError("這張服務加贈券不適用此單陪／雙陪規格。")
        return original_build_preview(*args, **kwargs)

    checkout.build_checkout_preview = build_checkout_preview

    original_service_value = checkout.calculate_point_service_value

    def calculate_point_service_value(
        *,
        quote: dict,
        vip_pay_rate: int,
        point_item: dict | None,
    ) -> int:
        one_seat_value = original_service_value(
            quote=quote,
            vip_pay_rate=vip_pay_rate,
            point_item=point_item,
        )
        if not point_item or one_seat_value <= 0:
            return max(0, int(one_seat_value or 0))

        try:
            funded_seats = max(1, int(point_item.get("seat_count") or 1))
        except (TypeError, ValueError):
            funded_seats = 1
        try:
            actual_seats = max(1, int((quote or {}).get("required_staff_count") or 1))
        except (TypeError, ValueError):
            actual_seats = 1
        funded_seats = min(funded_seats, actual_seats)
        return max(0, int(one_seat_value) * funded_seats)

    checkout.calculate_point_service_value = calculate_point_service_value

    original_financials = checkout.calculate_checkout_financials

    def calculate_checkout_financials(*args, **kwargs):
        result = original_financials(*args, **kwargs)
        point_item = kwargs.get("point_item")
        if not isinstance(point_item, dict):
            return result

        try:
            funded_seats = max(1, int(point_item.get("seat_count") or 1))
        except (TypeError, ValueError):
            funded_seats = 1
        if funded_seats <= 1:
            return result

        note = str(result.get("point_service_note") or "")
        if note:
            result["point_service_note"] = note.replace(
                "（1 位陪玩）",
                f"（{funded_seats} 位陪玩同步加贈）",
            )
        return result

    checkout.calculate_checkout_financials = calculate_checkout_financials
    checkout._shared_point_benefit_policy_installed = True
