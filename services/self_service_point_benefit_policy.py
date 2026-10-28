from __future__ import annotations

from typing import Any

from services.order_rule_manager_policy import get_manager_point_benefit_setting
from services.point_benefit_catalog import is_service_bonus_allowed_for_rule


_POINT_DISABLED_TEXT = "此商品目前不開放點數福利；會員福利券仍可使用。"


def check_order_point_benefit_allowed(
    rule,
    benefit: dict[str, Any] | None,
    data: dict | None = None,
) -> tuple[bool, str]:
    """Return whether one point benefit can be applied to the effective rule."""

    data = data or {}
    spec = dict(benefit or {})
    if not spec:
        return False, "這個點數福利不支援新下單流程。"

    category = str(getattr(rule, "category", "") or "").lower()
    rule_key = str(getattr(rule, "key", "") or "")
    rule_label = str(getattr(rule, "label", "") or "")

    # Legacy non-selectable probe used only to open the combined point/member
    # picker. Actual point choices are checked individually below.
    if str(spec.get("key") or "") == "discount_20":
        return True, ""

    manager_setting = get_manager_point_benefit_setting(rule_key)
    if manager_setting is False:
        return False, _POINT_DISABLED_TEXT
    if manager_setting is None:
        if not getattr(rule, "point_benefits_allowed", False):
            return False, _POINT_DISABLED_TEXT
        if category == "steam":
            return False, _POINT_DISABLED_TEXT
        if category in {"fun", "delta_desktop_fun", "title"}:
            return False, _POINT_DISABLED_TEXT
        if rule_key.startswith("basic_trial_") or rule_label.startswith("體驗單"):
            return False, _POINT_DISABLED_TEXT

    kind = str(spec.get("kind") or "")
    pricing_type = str(getattr(rule, "pricing_type", "") or "")

    if kind == "service_bonus":
        if pricing_type not in {"hourly", "game"}:
            return False, "服務加贈只適用計時或計局方案。"
        if not is_service_bonus_allowed_for_rule(rule, spec, player_count=data.get("player_count")):
            return False, "這張服務加贈券不適用目前選擇的陪玩人數／類型。"
        if category in {"lol", "valorant", "apex"} and int(spec.get("seat_count") or 0) > 0:
            return False, "這個商品目前暫停使用點數加時／加局券。"

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
