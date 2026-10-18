from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FINANCIALS = ROOT / "services" / "self_service_financials.py"
MANUAL_PRICING = ROOT / "services" / "self_service_manual_pricing.py"
TEST = ROOT / "tests" / "test_self_service_manual_pricing.py"


def replace_once(path: Path, old: str, new: str) -> None:
    text = path.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"expected exactly one match in {path}, found {count}: {old[:80]!r}")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


def replace_between(path: Path, start: str, end: str, new: str) -> None:
    text = path.read_text(encoding="utf-8")
    if text.count(start) != 1 or text.count(end) != 1:
        raise RuntimeError(
            f"expected unique boundaries in {path}: start={text.count(start)} end={text.count(end)}"
        )
    start_at = text.index(start)
    end_at = text.index(end, start_at)
    path.write_text(text[:start_at] + new + text[end_at:], encoding="utf-8")


MANUAL_PRICING.write_text(
    '''from __future__ import annotations

from typing import Any, Callable


def parse_discount_percent_text(value: str | None) -> float:
    raw = str(value or "").strip().replace("%", "")

    if not raw:
        return 100.0

    try:
        parsed = float(raw)
    except ValueError as exc:
        raise ValueError(
            "折後比例請輸入數字，例如 90 代表 9 折。"
        ) from exc

    if parsed < 0 or parsed > 100:
        raise ValueError(
            "折後比例只能輸入 0～100。"
        )

    return parsed


def parse_cash_amount_text(value: str | None) -> int:
    raw = str(value or "").strip().replace(",", "")

    if not raw:
        return 0

    try:
        amount = int(float(raw))
    except ValueError as exc:
        raise ValueError(
            "固定折扣金額請輸入數字，例如 100。"
        ) from exc

    if amount < 0:
        raise ValueError(
            "固定折扣金額不能小於 0。"
        )

    return amount


def resolve_manual_discount_rate_percent(data: dict) -> float:
    raw = data.get("manual_discount_percent")

    if raw is None or str(raw).strip() == "":
        return 100.0

    try:
        value = float(raw)
    except (TypeError, ValueError):
        value = 0.0

    value = max(
        0.0,
        min(100.0, value),
    )

    if (
        str(
            data.get("manual_discount_mode")
            or ""
        ).strip().lower()
        == "pay_rate"
    ):
        return value

    # legacy：舊資料 10 = 折掉 10%；新制等同折後 90%。
    return 100.0 - value


def calculate_manual_price_adjustment(
    base_amount: int,
    data: dict,
    *,
    to_int: Callable[..., int],
    allocate_store_absorbed_fixed_discount: Callable[..., Any],
) -> dict:
    original = max(0, int(base_amount or 0))
    rate = resolve_manual_discount_rate_percent(data)
    after_percent = max(
        0,
        min(original, int(round(original * rate / 100))),
    )
    percent_off = original - after_percent

    raw_fixed = data.get("fixed_discount_amount")
    if raw_fixed is None:
        raw_fixed = data.get("cash_coupon_amount")

    fixed = max(
        0,
        min(after_percent, to_int(raw_fixed, 0) or 0),
    )
    allocation = allocate_store_absorbed_fixed_discount(
        after_percent_amount=after_percent,
        fixed_discount_amount=fixed,
    )

    return {
        "price_formula_version": 2,
        "manual_discount_mode": "pay_rate",
        "service_original_amount": original,
        "original_amount": original,
        "manual_discount_percent": rate,
        "discount_rate_percent": rate,
        "manual_discount_amount": percent_off,
        "percent_discount_amount": percent_off,
        "payout_base_amount": allocation.payout_base_amount,
        "cash_coupon_amount": fixed,
        "fixed_discount_amount": fixed,
        "store_absorbed_amount": allocation.store_absorbed_amount,
        "customer_pay_amount": allocation.customer_pay_amount,
        "manual_discount_reason": str(
            data.get("manual_discount_reason") or ""
        ).strip(),
        "cash_coupon_reason": str(
            data.get("cash_coupon_reason") or ""
        ).strip(),
    }


def apply_manual_price_adjustment_to_order_data(
    data: dict,
    base_amount: int,
    *,
    calculate_adjustment: Callable[[int, dict], dict],
    format_amount: Callable[[int | None], str],
) -> dict:
    adjustment = calculate_adjustment(base_amount, data)

    for key, value in adjustment.items():
        data[key] = value

    data["amount"] = adjustment["customer_pay_amount"]
    data["total_amount"] = adjustment["customer_pay_amount"]
    data["amount_text"] = format_amount(adjustment["customer_pay_amount"])

    return adjustment
''',
    encoding="utf-8",
)

replace_once(
    FINANCIALS,
    '''from services.vip_monthly_order_discount import (\n''',
    '''from services import self_service_manual_pricing as manual_pricing\nfrom services.vip_monthly_order_discount import (\n''',
)

replace_between(
    FINANCIALS,
    '''\ndef _parse_discount_percent_text(value: str | None) -> float:\n''',
    '''\ndef _resolve_self_service_discount_rate(\n''',
    '''\n_parse_discount_percent_text = manual_pricing.parse_discount_percent_text\n_parse_cash_amount_text = manual_pricing.parse_cash_amount_text\n_resolve_manual_discount_rate_percent = manual_pricing.resolve_manual_discount_rate_percent\n\n''',
)

replace_between(
    FINANCIALS,
    '''\ndef calculate_manual_price_adjustment(\n''',
    '''\ndef _quote_preview_lines_for_self_service(\n''',
    '''\ndef calculate_manual_price_adjustment(\n    base_amount: int,\n    data: dict,\n) -> dict:\n    return manual_pricing.calculate_manual_price_adjustment(\n        base_amount,\n        data,\n        to_int=_to_int,\n        allocate_store_absorbed_fixed_discount=allocate_store_absorbed_fixed_discount,\n    )\n\n\ndef apply_manual_price_adjustment_to_order_data(data: dict, base_amount: int) -> dict:\n    return manual_pricing.apply_manual_price_adjustment_to_order_data(\n        data,\n        base_amount,\n        calculate_adjustment=calculate_manual_price_adjustment,\n        format_amount=_format_plain_amount,\n    )\n\n''',
)

TEST.write_text(
    '''from pathlib import Path\nfrom types import SimpleNamespace\n\nimport pytest\n\nfrom services import self_service_manual_pricing as pricing\n\n\nROOT = Path(__file__).resolve().parents[1]\n\n\ndef _to_int(value, default=0):\n    try:\n        return int(value)\n    except (TypeError, ValueError):\n        return default\n\n\ndef _allocate(*, after_percent_amount, fixed_discount_amount):\n    return SimpleNamespace(\n        payout_base_amount=after_percent_amount,\n        store_absorbed_amount=fixed_discount_amount,\n        customer_pay_amount=max(after_percent_amount - fixed_discount_amount, 0),\n    )\n\n\ndef test_manual_pricing_parsers_preserve_existing_rules():\n    assert pricing.parse_discount_percent_text("90%") == 90.0\n    assert pricing.parse_discount_percent_text("") == 100.0\n    assert pricing.parse_cash_amount_text("1,250") == 1250\n    with pytest.raises(ValueError):\n        pricing.parse_discount_percent_text("101")\n    with pytest.raises(ValueError):\n        pricing.parse_cash_amount_text("-1")\n\n\ndef test_manual_pricing_calculation_preserves_store_funded_fixed_discount():\n    result = pricing.calculate_manual_price_adjustment(\n        1000,\n        {\n            "manual_discount_mode": "pay_rate",\n            "manual_discount_percent": 90,\n            "fixed_discount_amount": 100,\n            "manual_discount_reason": "VIP",\n            "cash_coupon_reason": "客服折扣",\n        },\n        to_int=_to_int,\n        allocate_store_absorbed_fixed_discount=_allocate,\n    )\n\n    assert result["customer_pay_amount"] == 800\n    assert result["payout_base_amount"] == 900\n    assert result["manual_discount_amount"] == 100\n    assert result["store_absorbed_amount"] == 100\n\n\ndef test_legacy_discount_off_value_still_converts_to_pay_rate():\n    assert pricing.resolve_manual_discount_rate_percent(\n        {"manual_discount_percent": 10}\n    ) == 90.0\n\n\ndef test_financial_runtime_delegates_manual_pricing_without_duplicating_implementation():\n    source = (ROOT / "services" / "self_service_financials.py").read_text(encoding="utf-8")\n    assert "manual_pricing.calculate_manual_price_adjustment(" in source\n    assert "def _parse_discount_percent_text" not in source\n    assert "def _parse_cash_amount_text" not in source\n    assert len(source.encode("utf-8")) < 40_000\n''',
    encoding="utf-8",
)

print("self-service manual pricing extraction applied")
