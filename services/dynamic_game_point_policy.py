from __future__ import annotations


_INSTALLED = False


def install_dynamic_game_point_policy() -> None:
    """Keep Discord point-service UI and payout on the shared authoritative policy."""

    global _INSTALLED
    if _INSTALLED:
        return

    from services import self_service_financials as financials
    from services import self_service_selection_runtime as selection
    from services.multi_seat_order_policy_20261028 import (
        SERVICE_POINT_BENEFIT_RULE_OVERRIDES,
    )
    from services.order_rules import ORDER_RULES
    from services.point_benefit_catalog import (
        DYNAMIC_GAME_POINT_CATEGORIES,
        get_point_benefit_item,
        resolve_rule_staff_count,
    )

    # The 2026-10-28 migration intentionally paused seat-aware service rewards for
    # these game catalogs while their pricing model was undecided. The dynamic
    # rule-price policy is now confirmed, so explicitly lift that pause for every
    # current LoL / VALORANT / APEX rule (including LoL ARAM variants).
    for key, rule in ORDER_RULES.items():
        if str(getattr(rule, "category", "") or "").strip().lower() in DYNAMIC_GAME_POINT_CATEGORIES:
            SERVICE_POINT_BENEFIT_RULE_OVERRIDES[str(key)] = True

    # Discord's older seat-funding wrapper reads point_benefit_key only from the
    # financial result. Some self-service flows keep the selected key only on order
    # data, which made that wrapper silently fall back to one worker. Fund current
    # seat-aware rewards here using BOTH sources, then mark the old wrapper as
    # superseded so startup cannot multiply the amount a second time.
    if not hasattr(financials, "_dynamic_point_original_financials"):
        original_financials = financials.calculate_self_service_financials
        financials._dynamic_point_original_financials = original_financials
        financials._seat_split_20261028_original_calculate = original_financials

        def calculate_self_service_financials(rule, price_result, data: dict) -> dict:
            result = original_financials(rule, price_result, data)
            if not isinstance(result, dict):
                return result

            key = str(
                result.get("point_benefit_key")
                or (data or {}).get("point_benefit_key")
                or (data or {}).get("selected_point_benefit_key")
                or ""
            ).strip()
            benefit = get_point_benefit_item(key)
            if not benefit:
                return result

            try:
                funded_seats = max(1, int(benefit.get("seat_count") or 1))
            except (TypeError, ValueError):
                funded_seats = 1
            actual_seats = resolve_rule_staff_count(rule, (data or {}).get("player_count", 1))
            funded_seats = min(funded_seats, max(1, int(actual_seats or 1)))
            if funded_seats <= 1:
                return result

            one_seat_value = max(0, int(result.get("point_service_value") or 0))
            if one_seat_value > 0:
                additional = one_seat_value * (funded_seats - 1)
                result["point_service_value"] = one_seat_value + additional
                result["payout_base_amount"] = max(
                    0,
                    int(result.get("payout_base_amount") or 0) + additional,
                )
                result["store_absorbed_amount"] = max(
                    0,
                    int(result.get("store_absorbed_amount") or 0) + additional,
                )

            note = str(result.get("service_bonus_text") or "")
            if note:
                result["service_bonus_text"] = note.replace(
                    "（1 位陪玩）",
                    f"（{funded_seats} 位陪玩同步加贈）",
                )
            return result

        financials.calculate_self_service_financials = calculate_self_service_financials

    # Discord used the raw fixed catalog cost to hide unaffordable options before
    # adapting the reward to the selected rule. Adapt first, then compare balance,
    # so the visible cost and the final server-side cost are the same number.
    if not hasattr(selection.SelfServicePointBenefitView, "_dynamic_point_original_build_available_items"):
        selection.SelfServicePointBenefitView._dynamic_point_original_build_available_items = (
            selection.SelfServicePointBenefitView.build_available_items
        )

        def build_available_items(self, data: dict) -> list[dict]:
            result: list[dict] = []

            for item in selection.POINT_REDEEM_ITEMS:
                key = str(item.get("key") or "")
                spec = selection.ORDER_POINT_BENEFIT_SPECS.get(key)
                if not spec:
                    continue

                allowed, _ = selection.is_order_point_benefit_allowed_for_rule(
                    self.rule,
                    key,
                    data,
                )
                if not allowed:
                    continue

                merged = dict(item)
                merged.update(spec)
                merged = selection._adapt_order_point_benefit_for_rule(
                    self.rule,
                    merged,
                )

                try:
                    cost = max(0, int(merged.get("cost") or 0))
                except (TypeError, ValueError):
                    cost = 0
                if cost > self.point_balance:
                    continue

                result.append(merged)

            return result

        selection.SelfServicePointBenefitView.build_available_items = build_available_items

    _INSTALLED = True
