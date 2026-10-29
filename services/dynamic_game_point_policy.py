from __future__ import annotations


_INSTALLED = False


def install_dynamic_game_point_policy() -> None:
    """Install the shared formal-product point-service policy for Discord/Web."""

    global _INSTALLED
    if _INSTALLED:
        return

    from services import point_benefit_catalog as point_catalog
    from services import self_service_financials as financials
    from services import self_service_point_benefit_policy as point_policy
    from services import self_service_selection_runtime as selection
    from services import order_point_redemption_policy as redemption_policy
    from services import multi_seat_order_policy_20261028 as multi_seat_policy
    from services.order_rules import ORDER_RULES
    from services.unified_service_point_policy import (
        calculate_rule_price_service_point_cost,
        is_current_service_bonus,
        is_rule_service_bonus_supported,
        uses_rule_price_service_point_cost,
    )

    # Service rewards are now a formal-product capability rather than a hard-coded
    # game-category switch. Teaching / sweet / trial / fun / Steam products stay
    # disabled even when they are hourly/game products and generic point coupons
    # remain available. Historical service aliases are not re-priced.
    if not hasattr(point_catalog, "_unified_service_original_allowed"):
        original_service_allowed = point_catalog.is_service_bonus_allowed_for_rule
        point_catalog._unified_service_original_allowed = original_service_allowed

        def is_service_bonus_allowed_for_rule(rule, benefit, player_count=None) -> bool:
            if is_current_service_bonus(benefit) and not is_rule_service_bonus_supported(rule):
                return False
            return bool(original_service_allowed(rule, benefit, player_count=player_count))

        point_catalog.is_service_bonus_allowed_for_rule = is_service_bonus_allowed_for_rule
        point_catalog.uses_dynamic_service_point_cost = uses_rule_price_service_point_cost
        point_catalog.calculate_service_bonus_point_cost = calculate_rule_price_service_point_cost

    # These modules imported the catalog callables by name. Rebind their module
    # globals so Discord selection and payment use the exact same live policy.
    point_policy.is_service_bonus_allowed_for_rule = point_catalog.is_service_bonus_allowed_for_rule
    redemption_policy.is_service_bonus_allowed_for_rule = point_catalog.is_service_bonus_allowed_for_rule
    redemption_policy.uses_dynamic_service_point_cost = point_catalog.uses_dynamic_service_point_cost
    redemption_policy.calculate_service_bonus_point_cost = point_catalog.calculate_service_bonus_point_cost

    # The older multi-seat migration has its own service switch. Make it a strict
    # projection of the formal rule capability instead of default-enabling every
    # non-LoL/VALORANT/APEX product.
    multi_seat_policy.is_service_point_benefit_enabled = is_rule_service_bonus_supported
    for key, rule in ORDER_RULES.items():
        multi_seat_policy.SERVICE_POINT_BENEFIT_RULE_OVERRIDES[str(key)] = (
            is_rule_service_bonus_supported(rule)
        )

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

            # A redeemed free-specify benefit means the fee was never collected.
            # The legacy calculator treated that missing fee as store-funded and
            # added it back into both payout basis and store subsidy. Remove that
            # phantom amount before any service-seat funding is applied.
            try:
                waived_specify = max(0, int(result.get("point_waived_specify_fee") or 0))
            except (TypeError, ValueError):
                waived_specify = 0
            if waived_specify > 0:
                result["payout_base_amount"] = max(
                    0,
                    int(result.get("payout_base_amount") or 0) - waived_specify,
                )
                result["store_absorbed_amount"] = max(
                    0,
                    int(result.get("store_absorbed_amount") or 0) - waived_specify,
                )

            key = str(
                result.get("point_benefit_key")
                or (data or {}).get("point_benefit_key")
                or (data or {}).get("selected_point_benefit_key")
                or ""
            ).strip()
            benefit = point_catalog.get_point_benefit_item(key)
            if not benefit or not is_current_service_bonus(benefit):
                return result
            if not is_rule_service_bonus_supported(rule):
                return result

            try:
                funded_seats = max(1, int(benefit.get("seat_count") or 1))
            except (TypeError, ValueError):
                funded_seats = 1
            actual_seats = point_catalog.resolve_rule_staff_count(
                rule,
                (data or {}).get("player_count", 1),
            )
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
