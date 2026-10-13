from pathlib import Path


def replace_once(path: str, old: str, new: str) -> None:
    target = Path(path)
    source = target.read_text(encoding="utf-8")
    count = source.count(old)
    if count != 1:
        raise SystemExit(f"{path}: expected one match, got {count}")
    target.write_text(source.replace(old, new, 1), encoding="utf-8")


replace_once(
    "services/self_service_financials.py",
    "import discord\n\n\nORDER_POINT_BENEFIT_SPECS: dict\n",
    '''import discord

from services.vip_monthly_order_discount import (
    build_vip_monthly_discount_note,
    build_vip_monthly_discount_result,
    resolve_vip_monthly_cash_discount,
)


ORDER_POINT_BENEFIT_SPECS: dict
''',
)

replace_once(
    "services/self_service_financials.py",
    '''    selected_vip_monthly = None
    vip_monthly_cash = 0
    selected_vip_monthly_id = data.get("selected_vip_monthly_benefit_id")
    if selected_vip_monthly_id not in (None, ""):
        if benefit is not None:
            raise ValueError("VIP 每月福利券與點數福利同張訂單只能擇一使用。")
        customer_id = data.get("customer_id")
        if not customer_id:
            raise ValueError("無法確認 VIP 每月福利券的會員身分，請重新開啟福利選單。")
        from services.vip_monthly_benefits import get_available_cash_benefit
        selected_vip_monthly = get_available_cash_benefit(
            selected_vip_monthly_id,
            customer_id=customer_id,
        )
        if selected_vip_monthly is None:
            raise ValueError("這張 VIP 每月折現券已使用、已保留或已失效。")
        vip_monthly_cash = max(
            0,
            min(
                int(selected_vip_monthly.get("amount") or 0),
                after_fixed,
            ),
        )
''',
    '''    selected_vip_monthly, vip_monthly_cash = resolve_vip_monthly_cash_discount(
        data,
        has_point_benefit=benefit is not None,
        max_discount_amount=after_fixed,
    )
''',
)

replace_once(
    "services/self_service_financials.py",
    '''    if vip_monthly_cash:
        notes.append(
            f"{str(selected_vip_monthly.get('title') or 'VIP 每月折現券')} "
            f"-{_format_plain_amount(vip_monthly_cash)}"
        )
''',
    '''    vip_monthly_note = build_vip_monthly_discount_note(
        selected_vip_monthly,
        vip_monthly_cash,
        formatter=_format_plain_amount,
    )
    if vip_monthly_note:
        notes.append(vip_monthly_note)
''',
)

replace_once(
    "services/self_service_financials.py",
    '''        "vip_monthly_benefit_id": (
            int(selected_vip_monthly.get("id")) if selected_vip_monthly else None
        ),
        "vip_monthly_benefit_key": (
            str(selected_vip_monthly.get("benefit_key") or "") if selected_vip_monthly else ""
        ),
        "vip_monthly_benefit_title": (
            str(selected_vip_monthly.get("title") or "") if selected_vip_monthly else ""
        ),
        "vip_monthly_cash_amount": vip_monthly_cash,
''',
    '''        **build_vip_monthly_discount_result(
            selected_vip_monthly,
            vip_monthly_cash,
        ),
''',
)

replace_once(
    "tests/test_self_service_financial_runtime_contract.py",
    '''    financial = (ROOT / "services" / "self_service_financials.py").read_text(encoding="utf-8")
    runtime = (ROOT / "services" / "self_service_runtime.py").read_text(encoding="utf-8")
    lifecycle = (ROOT / "shared" / "web_order_sync.py").read_text(encoding="utf-8")

    assert 'list_available_cash_benefits(customer_id)' in selection
    assert 'value=f"vip_monthly:{benefit[\\'id\\']}"' in selection
    assert 'selected_vip_monthly_benefit_id' in selection
    assert 'additional_store_discount_amount=point_cash + vip_monthly_cash' in financial
    assert 'vip_monthly_cash_amount' in financial
    assert 'reserve_cash_benefit_for_channel' in runtime
''',
    '''    financial = (ROOT / "services" / "self_service_financials.py").read_text(encoding="utf-8")
    discount_domain = (ROOT / "services" / "vip_monthly_order_discount.py").read_text(encoding="utf-8")
    runtime = (ROOT / "services" / "self_service_runtime.py").read_text(encoding="utf-8")
    lifecycle = (ROOT / "shared" / "web_order_sync.py").read_text(encoding="utf-8")

    assert 'list_available_cash_benefits(customer_id)' in selection
    assert 'value=f"vip_monthly:{benefit[\\'id\\']}"' in selection
    assert 'selected_vip_monthly_benefit_id' in selection
    assert 'resolve_vip_monthly_cash_discount' in financial
    assert 'additional_store_discount_amount=point_cash + vip_monthly_cash' in financial
    assert 'vip_monthly_cash_amount' in discount_domain
    assert 'reserve_cash_benefit_for_channel' in runtime
''',
)

size = Path("services/self_service_financials.py").stat().st_size
if size > 42000:
    raise SystemExit(f"self_service_financials.py still exceeds architecture budget: {size}")
print(f"self_service_financials.py size={size}")
