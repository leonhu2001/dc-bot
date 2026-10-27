from __future__ import annotations


def install_shared_point_benefit_policy() -> None:
    """Make Web checkout use the same point-benefit policy as Discord."""

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
    checkout._shared_point_benefit_policy_installed = True
