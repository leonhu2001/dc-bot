from pathlib import Path
from types import SimpleNamespace

from services import self_service_financials as financials


ROOT = Path(__file__).resolve().parents[1]


def test_staff_price_helpers_are_real_financial_domain_functions_before_runtime_config():
    assert financials.get_self_service_staff_price({}) is None
    assert financials.get_self_service_staff_price({"manual_staff_amount": "450"}) == 450
    assert financials.get_self_service_staff_price({"manual_staff_amount": "1,250"}) == 1250
    assert financials.get_self_service_staff_price({"manual_staff_amount": -20}) == 0
    assert financials.get_self_service_staff_price({"manual_staff_amount": "bad"}) is None

    assert financials.is_self_service_staff_price_required(
        SimpleNamespace(key="custom_custom_order", pricing_type="fixed")
    )
    assert financials.is_self_service_staff_price_required(
        SimpleNamespace(key="normal", pricing_type="manual")
    )
    assert not financials.is_self_service_staff_price_required(
        SimpleNamespace(key="normal", pricing_type="fixed")
    )


def test_self_service_runtime_reexports_canonical_staff_price_helpers():
    runtime_source = (ROOT / "services" / "self_service_runtime.py").read_text(encoding="utf-8")
    financial_source = (ROOT / "services" / "self_service_financials.py").read_text(encoding="utf-8")

    assert "def get_self_service_staff_price" in financial_source
    assert "def is_self_service_staff_price_required" in financial_source
    assert "def get_self_service_staff_price" not in runtime_source
    assert "def is_self_service_staff_price_required" not in runtime_source
    assert "get_self_service_staff_price," in runtime_source
    assert "is_self_service_staff_price_required," in runtime_source


def test_financial_runtime_only_takes_bot_owned_point_item_mapping_from_explicit_config():
    runtime_source = (ROOT / "services" / "self_service_runtime.py").read_text(encoding="utf-8")

    assert "POINT_REDEEM_ITEMS_BY_KEY = point_redeem_items_by_key" in runtime_source
    assert "point_redeem_items_by_key=POINT_REDEEM_ITEMS_BY_KEY" in runtime_source
    assert 'if "POINT_REDEEM_ITEMS_BY_KEY" in namespace:' not in runtime_source

    # Stable domain helpers must come from their owning modules, not bot globals.
    forbidden_namespace_lookups = (
        'namespace["allocate_store_absorbed_fixed_discount"]',
        'namespace["get_current_reward_points"]',
        'namespace["get_customer_reward_data"]',
        'namespace["get_effective_member_level"]',
        'namespace["get_self_service_quantity_unit"]',
        'namespace["get_vip_discount_pay_rate"]',
    )
    for lookup in forbidden_namespace_lookups:
        assert lookup not in runtime_source

    expected_direct_bindings = (
        "store_absorbed_discount_allocator=allocate_store_absorbed_fixed_discount",
        "current_reward_points=get_current_reward_points",
        "customer_reward_data=get_customer_reward_data",
        "effective_member_level=get_effective_member_level",
        "self_service_quantity_unit=get_self_service_quantity_unit",
        "vip_discount_pay_rate=get_vip_discount_pay_rate",
    )
    for binding in expected_direct_bindings:
        assert binding in runtime_source


def test_financial_config_no_longer_injects_its_own_staff_price_helpers():
    source = (ROOT / "services" / "self_service_financials.py").read_text(encoding="utf-8")

    assert "self_service_staff_price: Callable" not in source
    assert "staff_price_required: Callable" not in source
    assert "get_self_service_staff_price = self_service_staff_price" not in source
    assert "is_self_service_staff_price_required = staff_price_required" not in source


def test_vip_monthly_cash_coupon_is_wired_as_store_absorbed_self_service_discount():
    selection = (ROOT / "services" / "self_service_selection_runtime.py").read_text(encoding="utf-8")
    financial = (ROOT / "services" / "self_service_financials.py").read_text(encoding="utf-8")
    discount_domain = (ROOT / "services" / "vip_monthly_order_discount.py").read_text(encoding="utf-8")
    dispatch_runtime = (ROOT / "services" / "self_service_dispatch_runtime.py").read_text(encoding="utf-8")
    lifecycle = (ROOT / "shared" / "web_order_sync.py").read_text(encoding="utf-8")

    assert 'list_available_cash_benefits(customer_id)' in selection
    assert 'value=f"vip_monthly:{benefit[\'id\']}"' in selection
    assert 'selected_vip_monthly_benefit_id' in selection
    assert 'resolve_vip_monthly_cash_discount' in financial
    assert 'additional_store_discount_amount=point_cash + vip_monthly_cash' in financial
    assert 'vip_monthly_cash_amount' in discount_domain
    assert 'reserve_cash_benefit_for_channel' in dispatch_runtime
    assert dispatch_runtime.index('upsert_web_order_from_dispatch(') < dispatch_runtime.index('reserve_cash_benefit_for_channel(')
    assert '_sync_vip_monthly_cash_benefit_lifecycle' in lifecycle
    assert 'redeem_cash_benefits_for_channel' in lifecycle
    assert 'release_cash_benefits_for_channel' in lifecycle
