from services.self_service_vip_monthly_ux import merge_vip_monthly_into_quote_rows
from services.vip_monthly_order_discount import (
    format_vip_monthly_cash_order_requirement,
    get_vip_monthly_cash_order_status,
)


def _benefit(key: str, amount: int, title: str) -> dict:
    return {
        "benefit_key": key,
        "amount": amount,
        "title": title,
    }


def test_vip_monthly_200_minimum_status_and_copy() -> None:
    selected = _benefit("monthly_coupon_200", 200, "VIP 每月 200T 折現券")

    below = get_vip_monthly_cash_order_status(
        selected,
        original_service_amount=1200,
    )
    assert below == {
        "benefit_key": "monthly_coupon_200",
        "title": "VIP 每月 200T 折現券",
        "amount": 200,
        "minimum": 1500,
        "current": 1200,
        "shortfall": 300,
        "eligible": False,
    }
    assert format_vip_monthly_cash_order_requirement(below) == (
        "VIP 每月 200T 折現券：低消 1,500T（以原始服務金額判定）；"
        "目前 1,200T，尚差 300T。"
    )

    exact = get_vip_monthly_cash_order_status(
        selected,
        original_service_amount=1500,
    )
    assert exact["eligible"] is True
    assert exact["shortfall"] == 0
    assert "目前 1,500T，可使用" in format_vip_monthly_cash_order_requirement(exact)


def test_vip_monthly_500_minimum_boundary() -> None:
    selected = _benefit("monthly_coupon_500", 500, "VIP 每月 500T 折現券")

    below = get_vip_monthly_cash_order_status(
        selected,
        original_service_amount=3999,
    )
    assert below["minimum"] == 4000
    assert below["shortfall"] == 1
    assert below["eligible"] is False

    exact = get_vip_monthly_cash_order_status(
        selected,
        original_service_amount=4000,
    )
    assert exact["eligible"] is True
    assert exact["shortfall"] == 0


def test_vip_monthly_discount_is_merged_into_amount_detail() -> None:
    rows = [
        ("顧客應付", "1,336T"),
        (
            "金額明細",
            "商品原價 1,600T｜百分比折扣｜折後 96% -64T（鑽石魔丸 自動 VIP 折扣）"
            "｜打手分潤基準 1,336T",
        ),
        ("VIP 月券", "VIP 每月 200T 折現券｜-200T"),
        ("數量", "4 小時"),
    ]

    merged = merge_vip_monthly_into_quote_rows(
        rows,
        title="VIP 每月 200T 折現券",
        amount_text="200T",
    )

    assert all(name != "VIP 月券" for name, _ in merged)
    detail = dict(merged)["金額明細"]
    assert "VIP 月券 -200T（VIP 每月 200T 折現券）" in detail
    assert detail.index("VIP 月券 -200T") < detail.index("打手分潤基準")
    assert dict(merged)["顧客應付"] == "1,336T"


def test_vip_monthly_merge_is_idempotent() -> None:
    once = merge_vip_monthly_into_quote_rows(
        [("金額明細", "商品原價 1,600T｜打手分潤基準 1,336T")],
        title="VIP 每月 200T 折現券",
        amount_text="200T",
    )
    twice = merge_vip_monthly_into_quote_rows(
        once,
        title="VIP 每月 200T 折現券",
        amount_text="200T",
    )

    assert once == twice
    assert dict(twice)["金額明細"].count("VIP 月券 -200T") == 1
