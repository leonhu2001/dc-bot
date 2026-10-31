from __future__ import annotations

from pathlib import Path


def read(path: str) -> str:
    return Path(path).read_text(encoding="utf-8")


def write(path: str, text: str) -> None:
    Path(path).write_text(text, encoding="utf-8")


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected 1 match, got {count}")
    return text.replace(old, new, 1)


# ---------------------------------------------------------------------------
# Financial behavior belongs in the financial calculator itself.
# ---------------------------------------------------------------------------
path = "services/self_service_financials.py"
text = read(path)
text = replace_once(
    text,
    '''def get_self_service_staff_price(data: dict) -> int | None:\n    raw_amount = data.get("manual_staff_amount")\n    if raw_amount is None or str(raw_amount).strip() == "":\n        return None\n    try:\n        amount = int(float(str(raw_amount).strip().replace(",", "")))\n    except (TypeError, ValueError):\n        return None\n    return max(0, amount)\n''',
    '''def get_self_service_staff_price(data: dict) -> int | None:\n    raw_amount = data.get("manual_staff_amount")\n    if raw_amount is None or str(raw_amount).strip() == "":\n        return None\n    try:\n        amount = int(float(str(raw_amount).strip().replace(",", "")))\n    except (TypeError, ValueError):\n        return None\n    return max(0, amount)\n\n\ndef is_aw_collision_rule(rule_or_key) -> bool:\n    key = str(getattr(rule_or_key, "key", rule_or_key) or "").strip()\n    return key.startswith("farm_aw_collision_")\n''',
    "add AW rule predicate",
)

aw_helper = '''\n\ndef _calculate_aw_collision_financials(rule, price_result, data: dict) -> dict:\n    manual_price = get_self_service_staff_price(data)\n    if manual_price is None:\n        service_original = max(\n            0,\n            int(getattr(price_result, "base_amount", 0) or 0)\n            + int(getattr(price_result, "staff_adjustment_amount", 0) or 0),\n        )\n    else:\n        service_original = max(0, int(manual_price))\n\n    service_quantity = max(\n        1,\n        int(getattr(price_result, "service_quantity", 1) or 1),\n    )\n    return {\n        "price_formula_version": 2,\n        "manual_discount_mode": "pay_rate",\n        "manual_price_missing": False,\n        "manual_staff_amount": manual_price,\n        "manual_staff_price_reason": str(data.get("manual_staff_price_reason") or "").strip(),\n        "rule_original_amount": service_original,\n        "service_original_amount": service_original,\n        "original_amount": service_original,\n        "priced_amount": service_original,\n        "manual_discount_percent": 100.0,\n        "discount_rate_percent": 100.0,\n        "manual_discount_amount": 0,\n        "percent_discount_amount": 0,\n        "manual_discount_reason": "",\n        "discount_source": "none",\n        "vip_level_name": "",\n        "cash_coupon_amount": 0,\n        "fixed_discount_amount": 0,\n        "cash_coupon_reason": "",\n        "point_discount_coupon_amount": 0,\n        "selected_vip_monthly_benefit_id": None,\n        "vip_monthly_benefit_id": None,\n        "vip_monthly_benefit_key": None,\n        "vip_monthly_benefit_title": "",\n        "vip_monthly_cash_amount": 0,\n        "specified_fee_before_waiver": 0,\n        "effective_specify_fee": 0,\n        "point_waived_specify_fee": 0,\n        "point_free_first_hour_amount": 0,\n        "point_extra_hours": 0,\n        "point_extra_games": 0,\n        "point_benefit_key": None,\n        "point_benefit_name": "",\n        "point_benefit_cost": 0,\n        "point_benefit_summary": "",\n        "service_bonus_text": "",\n        "service_quantity": service_quantity,\n        "service_bonus_quantity": 0,\n        "service_promotion_text": "",\n        "payout_base_amount": service_original,\n        "benefit_coupon_id": None,\n        "benefit_coupon_title": "",\n        "benefit_coupon": None,\n        "benefit_service_note": "",\n        "benefit_service_value": 0,\n        "benefit_discount_amount": 0,\n        "point_service_value": 0,\n        "store_absorbed_amount": 0,\n        "customer_pay_amount": service_original,\n    }\n'''
text = replace_once(
    text,
    '\n\ndef calculate_self_service_financials(rule, price_result, data: dict) -> dict:\n    manual_price = get_self_service_staff_price(data)\n',
    aw_helper + '\n\ndef calculate_self_service_financials(rule, price_result, data: dict) -> dict:\n    if is_aw_collision_rule(rule):\n        return _calculate_aw_collision_financials(rule, price_result, data)\n\n    manual_price = get_self_service_staff_price(data)\n',
    "direct AW financial branch",
)
write(path, text)

# ---------------------------------------------------------------------------
# Checkout controls belong in the normal SelfServiceOrderView implementation.
# ---------------------------------------------------------------------------
path = "services/self_service_ui_runtime.py"
text = read(path)
text = replace_once(
    text,
    '''    get_self_service_staff_price,\n    is_order_point_benefit_allowed_for_rule,\n    is_self_service_staff_price_required,\n)\n''',
    '''    get_self_service_staff_price,\n    is_aw_collision_rule,\n    is_order_point_benefit_allowed_for_rule,\n    is_self_service_staff_price_required,\n)\n''',
    "import AW predicate",
)
text = replace_once(
    text,
    '''        try:\n            current_rule = _get_rule_from_self_service_data(data) if selected_item else None\n        except Exception:\n            current_rule = None\n\n        for child in self.children:\n''',
    '''        try:\n            current_rule = _get_rule_from_self_service_data(data) if selected_item else None\n        except Exception:\n            current_rule = None\n        is_aw_collision = bool(current_rule and is_aw_collision_rule(current_rule))\n\n        for child in self.children:\n''',
    "derive AW checkout state",
)
text = replace_once(
    text,
    '''            elif custom_id == "self_service_order_staff_price_button":\n                child.disabled = not bool(current_rule and is_self_service_staff_price_required(current_rule))\n            elif custom_id == "self_service_order_point_benefit_button" and data.get("website_finance_settled"):\n                child.disabled = True\n            elif custom_id == "self_service_order_go_payment_button":\n''',
    '''            elif custom_id == "self_service_order_staff_price_button":\n                child.disabled = not bool(\n                    current_rule\n                    and (is_self_service_staff_price_required(current_rule) or is_aw_collision)\n                )\n            elif custom_id == "self_service_order_point_benefit_button":\n                child.disabled = bool(is_aw_collision or data.get("website_finance_settled"))\n            elif custom_id == "self_service_order_staff_discount_coupon_button" and is_aw_collision:\n                child.disabled = True\n            elif custom_id == "self_service_order_go_payment_button":\n''',
    "direct AW button state",
)
text = replace_once(
    text,
    '''        if not is_self_service_staff_price_required(rule):\n            await interaction.response.send_message("這個項目會自動試算價格，不需要客服手動填價格。", ephemeral=True)\n            return\n''',
    '''        if not is_self_service_staff_price_required(rule) and not is_aw_collision_rule(rule):\n            await interaction.response.send_message("這個項目會自動試算價格，不需要客服手動填價格。", ephemeral=True)\n            return\n''',
    "allow optional AW staff price",
)
text = replace_once(
    text,
    '''        if not data.get("item"):\n            await interaction.response.send_message("請先選擇訂單項目，再設定折扣。", ephemeral=True)\n            return\n\n        panel_message_id = interaction.message.id if interaction.message is not None else None\n        await interaction.response.send_modal(\n            SelfServiceStaffDiscountCouponModal(\n''',
    '''        if not data.get("item"):\n            await interaction.response.send_message("請先選擇訂單項目，再設定折扣。", ephemeral=True)\n            return\n\n        try:\n            rule = _get_rule_from_self_service_data(data)\n        except ValueError as exc:\n            await interaction.response.send_message(str(exc), ephemeral=True)\n            return\n        if is_aw_collision_rule(rule):\n            await interaction.response.send_message(\n                "AW代撞不套用客服折扣、會員或點數福利。",\n                ephemeral=True,\n            )\n            return\n\n        panel_message_id = interaction.message.id if interaction.message is not None else None\n        await interaction.response.send_modal(\n            SelfServiceStaffDiscountCouponModal(\n''',
    "block AW discount modal",
)
write(path, text)

# The old installer remains import-compatible but performs no monkey patching.
write(
    "services/aw_collision_business_policy.py",
    '''from __future__ import annotations\n\n\ndef install_aw_collision_business_policy() -> None:\n    """Compatibility no-op; AW policy is implemented directly in core services."""\n    return None\n\n\n__all__ = ["install_aw_collision_business_policy"]\n''',
)

# ---------------------------------------------------------------------------
# Regression tests for direct behavior and no monkey patching.
# ---------------------------------------------------------------------------
path = "tests/test_aw_collision_business_policy.py"
text = read(path)
text = replace_once(
    text,
    '''from services import order_rules\nfrom services.aw_collision_catalog import AW_RULE_KEYS\nfrom services import one_companion_one_guard_payout as role_payout\n''',
    '''from services import order_rules\nfrom services.aw_collision_catalog import AW_RULE_KEYS\nfrom services import aw_collision_business_policy\nfrom services import one_companion_one_guard_payout as role_payout\nfrom services import self_service_financials\n''',
    "business test imports",
)
text += '''\n\ndef test_aw_financial_policy_is_direct_and_ignores_discount_stacking():\n    rule = order_rules.ORDER_RULES["farm_aw_collision_101_500"]\n    price = order_rules.calculate_price(rule, quantity=250)\n    result = self_service_financials.calculate_self_service_financials(\n        rule,\n        price,\n        {\n            "manual_staff_amount": 900,\n            "manual_staff_price_reason": "內部價格",\n            "manual_discount_percent": 50,\n            "cash_coupon_amount": 500,\n            "point_discount_coupon_amount": 300,\n            "selected_point_benefit_key": "discount_20",\n        },\n    )\n\n    assert result["customer_pay_amount"] == 900\n    assert result["payout_base_amount"] == 900\n    assert result["manual_discount_percent"] == 100.0\n    assert result["manual_discount_amount"] == 0\n    assert result["cash_coupon_amount"] == 0\n    assert result["point_discount_coupon_amount"] == 0\n    assert result["store_absorbed_amount"] == 0\n\n\ndef test_aw_business_compatibility_installer_does_not_replace_core_functions():\n    before_financial = self_service_financials.calculate_self_service_financials\n    aw_collision_business_policy.install_aw_collision_business_policy()\n    assert self_service_financials.calculate_self_service_financials is before_financial\n'''
write(path, text)

business_policy = read("services/aw_collision_business_policy.py")
assert "_ORIGINAL_" not in business_policy
assert "calculate_self_service_financials =" not in business_policy
assert "SelfServiceOrderView.__init__ =" not in business_policy
assert "Compatibility no-op" in business_policy
print("AW_BUSINESS_CORE_REFACTOR_APPLIED")
