from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / "services" / "self_service_runtime.py"
TEST = ROOT / "tests" / "test_self_service_financial_runtime_contract.py"

runtime = RUNTIME.read_text(encoding="utf-8")
old = '''    missing_financial_keys = sorted(financial_keys.difference(namespace))
    if missing_financial_keys:
        raise RuntimeError(
            "self-service financial runtime missing dependencies: "
            + ", ".join(missing_financial_keys)
        )

    configure_self_service_financials(
        order_point_benefit_specs=ORDER_POINT_BENEFIT_SPECS,
        point_redeem_items_by_key=namespace["POINT_REDEEM_ITEMS_BY_KEY"],
        get_rule_from_data=_get_rule_from_self_service_data,
        is_specify_preference=_is_specify_preference,
        role_key_for_member=_role_key_for_member,
        to_int=namespace["_to_int"],
        store_absorbed_discount_allocator=namespace["allocate_store_absorbed_fixed_discount"],
        current_reward_points=namespace["get_current_reward_points"],
        customer_reward_data=namespace["get_customer_reward_data"],
        effective_member_level=namespace["get_effective_member_level"],
        self_service_quantity_unit=namespace["get_self_service_quantity_unit"],
        vip_discount_pay_rate=namespace["get_vip_discount_pay_rate"],
    )
'''
new = '''    present_financial_keys = financial_keys.intersection(namespace)
    missing_financial_keys = sorted(financial_keys.difference(namespace))

    if present_financial_keys and missing_financial_keys:
        raise RuntimeError(
            "self-service financial runtime missing dependencies: "
            + ", ".join(missing_financial_keys)
        )

    if not missing_financial_keys:
        configure_self_service_financials(
            order_point_benefit_specs=ORDER_POINT_BENEFIT_SPECS,
            point_redeem_items_by_key=namespace["POINT_REDEEM_ITEMS_BY_KEY"],
            get_rule_from_data=_get_rule_from_self_service_data,
            is_specify_preference=_is_specify_preference,
            role_key_for_member=_role_key_for_member,
            to_int=namespace["_to_int"],
            store_absorbed_discount_allocator=namespace["allocate_store_absorbed_fixed_discount"],
            current_reward_points=namespace["get_current_reward_points"],
            customer_reward_data=namespace["get_customer_reward_data"],
            effective_member_level=namespace["get_effective_member_level"],
            self_service_quantity_unit=namespace["get_self_service_quantity_unit"],
            vip_discount_pay_rate=namespace["get_vip_discount_pay_rate"],
        )
'''
if runtime.count(old) != 1:
    raise RuntimeError("patched financial runtime block not found exactly once")
RUNTIME.write_text(runtime.replace(old, new, 1), encoding="utf-8")

test = TEST.read_text(encoding="utf-8")
needle = '''    assert "missing_financial_keys = sorted(financial_keys.difference(namespace))" in runtime_source
    assert "self-service financial runtime missing dependencies" in runtime_source
    assert "if financial_keys.issubset(namespace):" not in runtime_source
'''
replacement = '''    assert "present_financial_keys = financial_keys.intersection(namespace)" in runtime_source
    assert "missing_financial_keys = sorted(financial_keys.difference(namespace))" in runtime_source
    assert "if present_financial_keys and missing_financial_keys:" in runtime_source
    assert "self-service financial runtime missing dependencies" in runtime_source
    assert "if financial_keys.issubset(namespace):" not in runtime_source
'''
if test.count(needle) != 1:
    raise RuntimeError("runtime contract assertion block not found")
TEST.write_text(test.replace(needle, replacement, 1), encoding="utf-8")

print("self-service financial runtime contract refined")
