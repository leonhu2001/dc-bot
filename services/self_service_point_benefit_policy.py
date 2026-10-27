from __future__ import annotations

from typing import Any

from services.point_benefit_catalog import is_service_bonus_allowed_for_rule


def check_order_point_benefit_allowed(
    rule,
    benefit: dict[str, Any] | None,
    data: dict | None = None,
) -> tuple[bool, str]:
    """Pure eligibility policy for applying a point benefit to one order draft."""

    data = data or {}
    spec = dict(benefit or {})
    if not spec:
        return False, "這個點數福利不支援新下單流程。"

    category = str(getattr(rule, "category", "") or "").lower()
    rule_key = str(getattr(rule, "key", "") or "")
    rule_label = str(getattr(rule, "label", "") or "")
    is_trial_order = rule_key.startswith("basic_trial_") or rule_label.startswith("體驗單")

    # self_service_ui_runtime uses the legacy, non-selectable discount_20 item as
    # a lightweight probe before opening the combined point/member-benefit picker.
    # Trial orders intentionally reject normal point redemptions, but they still
    # need to enter that picker so owner-issued member coupons (for example a
    # free-order coupon) can be selected. Only bypass the probe here; the actual
    # selectable point items are checked below and remain blocked for trial orders.
    is_member_benefit_picker_probe = (
        is_trial_order
        and str(spec.get("key") or "") == "discount_20"
    )
    if is_member_benefit_picker_probe:
        return True, ""

    if not getattr(rule, "point_benefits_allowed", False):
        return False, "此分類不可使用點數福利。"

    if category == "steam":
        return False, "Steam遊戲目前不可使用點數福利。"
    if category in {"fun", "delta_desktop_fun", "title"}:
        return False, "趣味單 / 高難度稱號不可使用點數福利。"
    if is_trial_order:
        return False, "體驗單不可使用一般點數福利；會員福利券仍可使用。"

    kind = str(spec.get("kind") or "")
    pricing_type = str(getattr(rule, "pricing_type", "") or "")

    if kind == "service_bonus":
        if pricing_type not in {"hourly", "game"}:
            return False, "服務加贈只適用計時或計局方案。"
        if not is_service_bonus_allowed_for_rule(rule, spec):
            return False, "這張服務加贈券不適用此陪玩類型。"

    if kind == "free_specify_fee":
        if not getattr(rule, "allow_specify", False):
            return False, "此項目不開放指定，因此不能使用免指定費。"
        if not data.get("specified_staff_ids"):
            return False, "請先指定人員，再使用免指定費。"
        if pricing_type == "hourly":
            try:
                quantity = max(1, int(data.get("quantity") or 1))
            except (TypeError, ValueError):
                quantity = 1
            if quantity >= 2:
                return False, "2 小時以上本來就免指定費，不需要再使用免指定費福利。"

    pricing_types = tuple(spec.get("pricing_types") or ())
    if pricing_types and pricing_type not in pricing_types:
        return False, "這個點數福利不適用此計價方式。"
    if kind == "extra_hours" and pricing_type != "hourly":
        return False, "加時只適用計時方案。"
    if kind == "extra_games" and pricing_type != "game":
        return False, "加局只適用計局方案。"

    return True, ""
