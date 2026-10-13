from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FINANCIALS = ROOT / "services" / "self_service_financials.py"
RUNTIME = ROOT / "services" / "self_service_runtime.py"
TEST = ROOT / "tests" / "test_self_service_financial_runtime_contract.py"


def replace_once(path: Path, old: str, new: str) -> None:
    text = path.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"expected exactly one match in {path}, found {count}: {old[:80]!r}")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


# The staff-price helpers are financial-domain logic. Make them concrete functions
# in the owning module instead of callbacks that only exist after runtime wiring.
replace_once(
    FINANCIALS,
    '''get_self_service_quantity_unit: Callable[..., Any]\nget_self_service_staff_price: Callable[..., Any]\nget_vip_discount_pay_rate: Callable[..., Any]\nis_self_service_staff_price_required: Callable[..., bool]\n\n\ndef configure_self_service_financials(\n''',
    '''get_self_service_quantity_unit: Callable[..., Any]\nget_vip_discount_pay_rate: Callable[..., Any]\n\n\ndef is_self_service_staff_price_required(rule) -> bool:\n    rule_key = str(getattr(rule, "key", "") or "").strip().lower()\n    pricing_type = str(getattr(rule, "pricing_type", "") or "").strip().lower()\n\n    return (\n        rule_key in {"farm_department_task", "custom_custom_order"}\n        or pricing_type in {"manual", "staff", "custom"}\n    )\n\n\ndef get_self_service_staff_price(data: dict) -> int | None:\n    raw_amount = data.get("manual_staff_amount")\n\n    if raw_amount is None or str(raw_amount).strip() == "":\n        return None\n\n    try:\n        amount = int(float(str(raw_amount).strip().replace(",", "")))\n    except (TypeError, ValueError):\n        return None\n\n    return max(0, amount)\n\n\ndef configure_self_service_financials(\n''',
)

replace_once(
    FINANCIALS,
    '''    self_service_quantity_unit: Callable[..., Any],\n    self_service_staff_price: Callable[..., Any],\n    vip_discount_pay_rate: Callable[..., Any],\n    staff_price_required: Callable[..., bool],\n''',
    '''    self_service_quantity_unit: Callable[..., Any],\n    vip_discount_pay_rate: Callable[..., Any],\n''',
)

replace_once(
    FINANCIALS,
    '''    global get_effective_member_level\n    global get_self_service_quantity_unit\n    global get_self_service_staff_price\n    global get_vip_discount_pay_rate\n    global is_self_service_staff_price_required\n''',
    '''    global get_effective_member_level\n    global get_self_service_quantity_unit\n    global get_vip_discount_pay_rate\n''',
)

replace_once(
    FINANCIALS,
    '''    get_effective_member_level = effective_member_level\n    get_self_service_quantity_unit = self_service_quantity_unit\n    get_self_service_staff_price = self_service_staff_price\n    get_vip_discount_pay_rate = vip_discount_pay_rate\n    is_self_service_staff_price_required = staff_price_required\n''',
    '''    get_effective_member_level = effective_member_level\n    get_self_service_quantity_unit = self_service_quantity_unit\n    get_vip_discount_pay_rate = vip_discount_pay_rate\n''',
)

# Re-export the canonical helpers through the runtime for bot.py compatibility.
replace_once(
    RUNTIME,
    '''    get_selected_order_point_benefit,\n    is_order_point_benefit_allowed_for_rule,\n)\n''',
    '''    get_selected_order_point_benefit,\n    get_self_service_staff_price,\n    is_order_point_benefit_allowed_for_rule,\n    is_self_service_staff_price_required,\n)\n''',
)

# Missing financial dependencies must fail during startup, not on the first live order.
replace_once(
    RUNTIME,
    '''    if financial_keys.issubset(namespace):\n        configure_self_service_financials(\n            order_point_benefit_specs=ORDER_POINT_BENEFIT_SPECS,\n            point_redeem_items_by_key=namespace["POINT_REDEEM_ITEMS_BY_KEY"],\n            get_rule_from_data=_get_rule_from_self_service_data,\n            is_specify_preference=_is_specify_preference,\n            role_key_for_member=_role_key_for_member,\n            to_int=namespace["_to_int"],\n            store_absorbed_discount_allocator=namespace["allocate_store_absorbed_fixed_discount"],\n            current_reward_points=namespace["get_current_reward_points"],\n            customer_reward_data=namespace["get_customer_reward_data"],\n            effective_member_level=namespace["get_effective_member_level"],\n            self_service_quantity_unit=namespace["get_self_service_quantity_unit"],\n            self_service_staff_price=get_self_service_staff_price,\n            vip_discount_pay_rate=namespace["get_vip_discount_pay_rate"],\n            staff_price_required=is_self_service_staff_price_required,\n        )\n''',
    '''    missing_financial_keys = sorted(financial_keys.difference(namespace))\n    if missing_financial_keys:\n        raise RuntimeError(\n            "self-service financial runtime missing dependencies: "\n            + ", ".join(missing_financial_keys)\n        )\n\n    configure_self_service_financials(\n        order_point_benefit_specs=ORDER_POINT_BENEFIT_SPECS,\n        point_redeem_items_by_key=namespace["POINT_REDEEM_ITEMS_BY_KEY"],\n        get_rule_from_data=_get_rule_from_self_service_data,\n        is_specify_preference=_is_specify_preference,\n        role_key_for_member=_role_key_for_member,\n        to_int=namespace["_to_int"],\n        store_absorbed_discount_allocator=namespace["allocate_store_absorbed_fixed_discount"],\n        current_reward_points=namespace["get_current_reward_points"],\n        customer_reward_data=namespace["get_customer_reward_data"],\n        effective_member_level=namespace["get_effective_member_level"],\n        self_service_quantity_unit=namespace["get_self_service_quantity_unit"],\n        vip_discount_pay_rate=namespace["get_vip_discount_pay_rate"],\n    )\n''',
)

replace_once(
    RUNTIME,
    '''# 指定陪玩 / 點數福利選擇 UI 已移至 services/self_service_selection_runtime.py\n\ndef is_self_service_staff_price_required(rule) -> bool:\n    rule_key = str(getattr(rule, "key", "") or "")\n    pricing_type = str(getattr(rule, "pricing_type", "") or "").lower()\n\n    return (\n        rule_key in {"farm_department_task", "custom_custom_order"}\n        or pricing_type in {"manual", "staff", "custom"}\n    )\n\n\ndef get_self_service_staff_price(data: dict) -> int | None:\n    amount = _to_int(data.get("manual_staff_amount"), None)\n\n    if amount is None:\n        return None\n\n    return max(0, int(amount))\n\n\nclass SelfServiceStaffPriceModal''',
    '''# 指定陪玩 / 點數福利選擇 UI 已移至 services/self_service_selection_runtime.py\n# 客服手動價格規則由 services/self_service_financials.py 單一維護。\n\n\nclass SelfServiceStaffPriceModal''',
)

# Make future live failures actionable in systemd logs.
replace_once(
    RUNTIME,
    '''            print(f"[acceptance] 備註後建立 waiting_acceptance 自助單失敗 channel_id={self.channel_id}: {exc}")\n''',
    '''            print(\n                f"[acceptance] 備註後建立 waiting_acceptance 自助單失敗 "\n                f"channel_id={self.channel_id}: {type(exc).__name__}: {exc}",\n                flush=True,\n            )\n''',
)

TEST.write_text(
    '''from pathlib import Path\nfrom types import SimpleNamespace\n\nfrom services import self_service_financials as financials\n\n\nROOT = Path(__file__).resolve().parents[1]\n\n\ndef test_staff_price_helpers_are_real_financial_domain_functions_before_runtime_config():\n    assert financials.get_self_service_staff_price({}) is None\n    assert financials.get_self_service_staff_price({"manual_staff_amount": "450"}) == 450\n    assert financials.get_self_service_staff_price({"manual_staff_amount": "1,250"}) == 1250\n    assert financials.get_self_service_staff_price({"manual_staff_amount": -20}) == 0\n    assert financials.get_self_service_staff_price({"manual_staff_amount": "bad"}) is None\n\n    assert financials.is_self_service_staff_price_required(\n        SimpleNamespace(key="custom_custom_order", pricing_type="fixed")\n    )\n    assert financials.is_self_service_staff_price_required(\n        SimpleNamespace(key="normal", pricing_type="manual")\n    )\n    assert not financials.is_self_service_staff_price_required(\n        SimpleNamespace(key="normal", pricing_type="fixed")\n    )\n\n\ndef test_self_service_runtime_reexports_canonical_staff_price_helpers():\n    runtime_source = (ROOT / "services" / "self_service_runtime.py").read_text(encoding="utf-8")\n    financial_source = (ROOT / "services" / "self_service_financials.py").read_text(encoding="utf-8")\n\n    assert "def get_self_service_staff_price" in financial_source\n    assert "def is_self_service_staff_price_required" in financial_source\n    assert "def get_self_service_staff_price" not in runtime_source\n    assert "def is_self_service_staff_price_required" not in runtime_source\n    assert "get_self_service_staff_price," in runtime_source\n    assert "is_self_service_staff_price_required," in runtime_source\n\n\ndef test_financial_runtime_missing_dependencies_fail_fast():\n    runtime_source = (ROOT / "services" / "self_service_runtime.py").read_text(encoding="utf-8")\n\n    assert "missing_financial_keys = sorted(financial_keys.difference(namespace))" in runtime_source\n    assert "self-service financial runtime missing dependencies" in runtime_source\n    assert "if financial_keys.issubset(namespace):" not in runtime_source\n\n\ndef test_financial_config_no_longer_injects_its_own_staff_price_helpers():\n    source = (ROOT / "services" / "self_service_financials.py").read_text(encoding="utf-8")\n\n    assert "self_service_staff_price: Callable" not in source\n    assert "staff_price_required: Callable" not in source\n    assert "get_self_service_staff_price = self_service_staff_price" not in source\n    assert "is_self_service_staff_price_required = staff_price_required" not in source\n''',
    encoding="utf-8",
)

print("self-service financial runtime fix applied")
