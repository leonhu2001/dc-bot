from __future__ import annotations


def _legacy_service_alias_name(rule, item: dict) -> str:
    tier = str(item.get("service_tier") or "")
    prefix = "娛樂陪" if tier == "entertainment" else "技術陪"
    size = str(item.get("bonus_size") or "")
    pricing_type = str(getattr(rule, "pricing_type", "") or "")
    if pricing_type == "game":
        units = 1 if size == "small" else 2
        return f"{prefix}加贈｜{units} 局"
    return f"{prefix}加贈｜{'30 分鐘' if size == 'small' else '1 小時'}"


def install_shared_point_benefit_policy() -> None:
    """Keep Web checkout on the same manager, seat and funding policy as Discord."""

    from services import point_benefit_catalog as point_catalog
    from services.self_service_point_benefit_policy import (
        check_order_point_benefit_allowed,
    )
    from web.app.services import checkout_preview as checkout

    if getattr(checkout, "_shared_point_benefit_policy_installed", False):
        return

    def point_item_status(
        *,
        rule_key: str,
        point_item_key: str,
        point_balance: int,
        quantity: int,
        has_specified_staff: bool,
        player_count: int | None = None,
    ) -> dict:
        rule = checkout.ORDER_RULES.get(str(rule_key))
        item = checkout.POINT_ITEM_MAP.get(str(point_item_key))
        if rule is None or item is None:
            return {"allowed": False, "reason": "不支援這個點數福利。"}

        payload = {
            "quantity": max(1, int(quantity or 1)),
            "specified_staff_ids": ["selected"] if has_specified_staff else [],
        }
        if player_count not in (None, ""):
            try:
                payload["player_count"] = max(1, int(player_count or 1))
            except (TypeError, ValueError):
                payload["player_count"] = 1

        allowed, reason = check_order_point_benefit_allowed(
            rule,
            item,
            payload,
        )
        if not allowed:
            result = {"allowed": False, "reason": reason or "此點數福利目前不可使用。"}
            if (
                str(item.get("kind") or "") == "free_specify_fee"
                and not has_specified_staff
            ):
                result["requires_specified"] = True
            return result

        # Adapt before checking the point balance. LoL / VALORANT / APEX service
        # rewards derive cost from the selected rule price, so the raw catalog
        # placeholder must never decide whether an option is affordable.
        adapted = checkout._point_item_for_rule(rule, item)
        try:
            authoritative_cost = max(0, int(adapted.get("cost") or 0))
        except (TypeError, ValueError):
            authoritative_cost = 0

        if int(point_balance or 0) < authoritative_cost:
            return {
                "allowed": False,
                "reason": "點數不足。",
                "cost": authoritative_cost,
            }

        return {"allowed": True, "reason": "", "cost": authoritative_cost}

    checkout.point_item_status = point_item_status

    # Keep superseded service keys resolvable for historical callers and in-flight
    # orders. Public checkout hides these aliases, while current seat-aware options
    # are validated against the selected companion count.
    original_list_point_options = checkout.list_point_options

    def list_point_options(
        *,
        rule_key: str,
        point_balance: int,
        quantity: int,
        has_specified_staff: bool,
        player_count: int | None = None,
    ) -> list[dict]:
        result = list(
            original_list_point_options(
                rule_key=rule_key,
                point_balance=point_balance,
                quantity=quantity,
                has_specified_staff=has_specified_staff,
            )
            or []
        )
        rule = checkout.ORDER_RULES.get(str(rule_key))
        if rule is None:
            return result

        # original_list_point_options calls the patched point_item_status without a
        # count because its legacy signature predates the shared count field. Re-run
        # status here whenever the caller has a concrete count so 1/2/3/4-seat
        # service rewards are exact rather than inferred.
        if player_count not in (None, ""):
            for row in result:
                key = str(row.get("key") or "")
                if not key:
                    continue
                row.update(
                    point_item_status(
                        rule_key=rule_key,
                        point_item_key=key,
                        point_balance=point_balance,
                        quantity=quantity,
                        has_specified_staff=has_specified_staff,
                        player_count=player_count,
                    )
                )
                raw = checkout.POINT_ITEM_MAP.get(key)
                if raw is not None:
                    adapted = checkout._point_item_for_rule(rule, raw)
                    if "cost" in adapted:
                        row["cost"] = adapted["cost"]
                    if "name" in adapted:
                        row["name"] = adapted["name"]
                    if "summary" in adapted:
                        row["summary"] = adapted["summary"]

        existing = {str(item.get("key") or "") for item in result}
        for key in (
            "entertain_service_small",
            "entertain_service_large",
            "tech_service_small",
            "tech_service_large",
        ):
            if key in existing:
                continue
            raw = checkout.POINT_ITEM_MAP.get(key)
            if raw is None:
                continue
            adapted = checkout._point_item_for_rule(rule, raw)
            adapted["name"] = _legacy_service_alias_name(rule, raw)
            adapted["legacy_alias"] = True
            status = point_item_status(
                rule_key=rule_key,
                point_item_key=key,
                point_balance=point_balance,
                quantity=quantity,
                has_specified_staff=has_specified_staff,
                player_count=player_count,
            )
            adapted.update(status)
            result.append(adapted)
        return result

    checkout.list_point_options = list_point_options

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

        if isinstance(result, dict):
            customer = result.get("customer") if isinstance(result.get("customer"), dict) else {}
            preselected = (
                result.get("staff", {}).get("preselected_staff")
                if isinstance(result.get("staff"), dict)
                else None
            )
            point_options = list_point_options(
                rule_key=str(kwargs.get("rule_key") or ""),
                point_balance=int(customer.get("points") or 0),
                quantity=max(1, int(quote.get("quantity") or kwargs.get("quantity") or 1)),
                has_specified_staff=bool(preselected),
                player_count=selected_seats,
            )

            visible_options: list[dict] = []
            for option in point_options:
                if bool(option.get("legacy_alias")):
                    continue
                try:
                    reward_seats = int(option.get("seat_count") or 0)
                except (TypeError, ValueError):
                    reward_seats = 0
                # Public UI only shows the service reward for the CURRENT count.
                # Other point products are untouched.
                if reward_seats > 0 and reward_seats != selected_seats:
                    continue
                visible_options.append(option)

            result["point_options"] = visible_options
        return result

    checkout.build_checkout_options = build_checkout_options

    original_build_preview = checkout.build_checkout_preview

    def build_checkout_preview(*args, **kwargs):
        rule_key = str(kwargs.get("rule_key") or "").strip()
        point_item_key = str(kwargs.get("point_item_key") or "").strip()
        if rule_key and point_item_key:
            rule = checkout.ORDER_RULES.get(rule_key)
            item = checkout.POINT_ITEM_MAP.get(point_item_key)
            if rule is not None and item is not None:
                try:
                    selected_players = max(1, int(kwargs.get("player_count") or 1))
                except (TypeError, ValueError):
                    selected_players = 1
                try:
                    selected_quantity = max(1, int(kwargs.get("quantity") or 1))
                except (TypeError, ValueError):
                    selected_quantity = 1
                specified_ids = kwargs.get("specified_staff_ids")
                if not isinstance(specified_ids, list):
                    specified_ids = []

                allowed, reason = check_order_point_benefit_allowed(
                    rule,
                    item,
                    {
                        "quantity": selected_quantity,
                        "player_count": selected_players,
                        "specified_staff_ids": specified_ids,
                    },
                )
                if not allowed:
                    raise ValueError(reason or "目前選擇的點數福利已不適用。")

                if str(item.get("kind") or "") == "service_bonus" and not point_catalog.is_service_bonus_allowed_for_rule(
                    rule,
                    item,
                    player_count=selected_players,
                ):
                    raise ValueError("這張服務加贈券不適用目前的陪玩人數規格。")
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
