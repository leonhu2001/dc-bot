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
        calculate_service_bonus_value,
        resolve_rule_staff_count,
    )

    # The 2026-10-28 migration intentionally paused seat-aware service rewards for
    # these game catalogs while their pricing model was undecided. The dynamic
    # rule-price policy is now confirmed, so explicitly lift that pause for every
    # current LoL / VALORANT / APEX rule (including LoL ARAM variants).
    for key, rule in ORDER_RULES.items():
        if str(getattr(rule, "category", "") or "").strip().lower() in DYNAMIC_GAME_POINT_CATEGORIES:
            SERVICE_POINT_BENEFIT_RULE_OVERRIDES[str(key)] = True

    # Discord historically added only one worker's service value to payout_base.
    # Keep the existing per-seat formula, but fund it for every actual worker.
    if not hasattr(financials, "_dynamic_point_original_bonus_value"):
        financials._dynamic_point_original_bonus_value = (
            financials.calculate_one_seat_service_bonus_value
        )
        financials.calculate_one_seat_service_bonus_value = calculate_service_bonus_value

    # The financial calculator's note predates seat-aware service rewards. The
    # calculator itself resolves this global at call time, so wrapping it here also
    # keeps apply_self_service_financials_to_order_data on the corrected payout path.
    if not hasattr(financials, "_dynamic_point_original_financials"):
        financials._dynamic_point_original_financials = financials.calculate_self_service_financials
        original_financials = financials.calculate_self_service_financials

        def calculate_self_service_financials(rule, price_result, data: dict) -> dict:
            result = original_financials(rule, price_result, data)
            if not isinstance(result, dict):
                return result

            if float(result.get("point_extra_hours") or 0) <= 0 and int(
                result.get("point_extra_games") or 0
            ) <= 0:
                return result

            seats = resolve_rule_staff_count(rule, data.get("player_count"))
            if seats <= 1:
                return result

            note = str(result.get("service_bonus_text") or "")
            if note:
                result["service_bonus_text"] = note.replace(
                    "（1 位陪玩）",
                    f"（{seats} 位陪玩同步加贈）",
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
