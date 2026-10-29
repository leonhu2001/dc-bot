from __future__ import annotations


_INSTALLED = False


def install_dynamic_game_point_policy() -> None:
    """Install only the two legacy bridges not yet owned by their canonical modules.

    Service eligibility, dynamic point cost, redemption validation and multi-seat
    rule capability now live directly in point_benefit_catalog,
    self_service_point_benefit_policy, order_point_redemption_policy and
    multi_seat_order_policy_20261028. Do not rebind those functions here.
    """

    global _INSTALLED
    if _INSTALLED:
        return

    from services import point_benefit_catalog as point_catalog
    from services import self_service_financials as financials
    from services import self_service_selection_runtime as selection
    from services.unified_service_point_policy import (
        is_current_service_bonus,
        is_rule_service_bonus_supported,
    )

    # Remaining legacy bridge #1: Discord financial calculation predates a
    # seat-aware service value. Keep this narrowly scoped until the calculation is
    # moved into calculate_self_service_financials itself.
    if not hasattr(financials, "_dynamic_point_original_financials"):
        original_financials = financials.calculate_self_service_financials
        financials._dynamic_point_original_financials = original_financials
        financials._seat_split_20261028_original_calculate = original_financials

        def calculate_self_service_financials(rule, price_result, data: dict) -> dict:
            result = original_financials(rule, price_result, data)
            if not isinstance(result, dict):
                return result

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

    # Remaining legacy bridge #2: the old Discord selector checks raw catalog cost
    # before adapting a reward to the selected formal rule. Adapt first so the
    # displayed and charged point cost are identical.
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