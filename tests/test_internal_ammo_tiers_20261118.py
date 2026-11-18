"""Internal ammo named/unnamed pricing and CS/store payout protection."""
from __future__ import annotations

import discord
import pytest

from services.coin_wash_urgent_policy import apply_urgent_fee, urgent_fee_for_rule
from services.one_companion_one_guard_payout import (
    calculate_one_companion_one_guard_order_payout,
    is_full_worker_payout_rule,
)
from services.order_rules import (
    FULL_SOURCE_AUTHORITY_RULE_KEYS,
    HALFCOIN_RECEIVER_ROLES,
    calculate_price,
    get_base_rule,
)
from services.orders import SELF_SERVICE_ORDER_CATALOG
from services.self_service_financials import (
    add_self_service_financial_breakdown_fields,
    calculate_self_service_financials,
)
from services.staff_internal_ammo_dump_policy import (
    AMMO_DUMP_PRICES_BY_RULE,
    NAMED_SELECTION_KEY,
    calculate_internal_ammo_dump_cs_payout,
    require_ammo_dump_named_selection,
)
from services.staff_internal_ammo_dump_ui import InternalAmmoNamedView

TIERS = (
    (100, 550, 620, 18, 52),
    (200, 1080, 1220, 35, 105),
    (300, 1620, 1830, 53, 157),
    (500, 2650, 3000, 88, 262),
)


@pytest.mark.parametrize("millions,named_price,unnamed_price,cs,retained", TIERS)
def test_price_worker_split_and_discord_selector(
    millions, named_price, unnamed_price, cs, retained,
):
    rule_key = f"staff_internal_ammo_dump_{millions}m"
    rule = get_base_rule(rule_key)
    assert rule.category == "staff_internal"
    assert rule.price == named_price
    assert rule.allowed_roles == HALFCOIN_RECEIVER_ROLES
    assert is_full_worker_payout_rule(rule_key)
    assert urgent_fee_for_rule(rule_key) == 260
    assert AMMO_DUMP_PRICES_BY_RULE[rule_key] == (
        named_price, unnamed_price, named_price,
    )
    if millions != 500:
        assert rule_key in FULL_SOURCE_AUTHORITY_RULE_KEYS

    view = InternalAmmoNamedView(
        customer_id=1, channel_id=99, panel_message_id=123, rule_key=rule_key
    )
    assert len(view.children) == 1
    options = view.children[0].options
    assert [opt.value for opt in options] == ["named", "unnamed"]
    assert f"{named_price:,}T" in options[0].label
    assert f"{unnamed_price:,}T" in options[1].label
    assert f"{named_price:,}T" in options[1].description
    assert f"{cs:,}T" in options[1].description
    assert f"{retained:,}T" in options[1].description

    quoted = calculate_price(rule, quantity=1)
    with pytest.raises(ValueError, match="先由客服選擇"):
        require_ammo_dump_named_selection(rule, {})
    for named in (True, False):
        data = {NAMED_SELECTION_KEY: named}
        require_ammo_dump_named_selection(rule, data)
        price = named_price if named else unnamed_price
        expected_cs = 0 if named else cs
        expected_store = 0 if named else retained
        financials = calculate_self_service_financials(rule, quoted, data)
        assert financials["customer_pay_amount"] == price
        assert financials["payout_base_amount"] == named_price
        assert financials["store_margin_amount"] == price - named_price
        assert financials["customer_service_payout_amount"] == expected_cs
        assert financials["store_retained_amount"] == expected_store
        assert calculate_internal_ammo_dump_cs_payout(
            rule_key, price, named_price
        ) == expected_cs

        payouts = calculate_one_companion_one_guard_order_payout(
            rule_key=rule_key,
            total_amount=named_price,
            worker_roles=[("worker-1", "booster")],
            customer_service_total_amount=price,
        )
        assert payouts is not None
        assert payouts.total_worker_payout == named_price
        assert payouts.customer_service_payout == expected_cs
        assert payouts.total_payout == named_price + expected_cs

        embed = discord.Embed()
        financials["order_rule_key"] = rule_key
        add_self_service_financial_breakdown_fields(embed, financials)
        fields = {field.name: field.value for field in embed.fields}
        assert fields["顧客應付"] == f"{price:,}"
        assert fields["打手分潤基準"] == f"{named_price:,}"
        assert fields["掛名狀態"] == ("有掛名" if named else "無掛名")
        if named:
            assert "店家抽成前差額" not in fields
        else:
            assert fields["店家抽成前差額"] == f"{price-named_price:,}T"
            assert fields["客服分潤"].startswith(f"{cs:,}T")
            assert fields["店家實留"] == f"{retained:,}T"

        urgent = apply_urgent_fee(rule_key, {**data, "coin_wash_urgent": True}, financials)
        assert urgent["customer_pay_amount"] == price + 260
        assert urgent["payout_base_amount"] == named_price
        assert urgent["urgent_fee_amount"] == 260


@pytest.mark.parametrize("millions,named_price,unnamed_price,cs,retained", TIERS)
def test_cs_payout_fails_closed_for_wrong_amounts(
    millions, named_price, unnamed_price, cs, retained,
):
    rule_key = f"staff_internal_ammo_dump_{millions}m"
    assert calculate_internal_ammo_dump_cs_payout(
        rule_key, unnamed_price + 260, named_price
    ) == 0
    assert calculate_internal_ammo_dump_cs_payout(
        rule_key, unnamed_price, named_price - 1
    ) == 0
    assert calculate_internal_ammo_dump_cs_payout(
        "staff_internal_aw_collision", unnamed_price, named_price
    ) == 0


def test_internal_discord_catalog_shows_all_three_new_tiers_and_retains_500m():
    groups = {entry["label"]: entry for entry in SELF_SERVICE_ORDER_CATALOG["staff_internal"]}
    assert "倒子彈｜500M" in groups
    assert "倒子彈｜100M～300M" in groups
    details = groups["倒子彈｜100M～300M"]["details"]
    assert [entry["rule_key"] for entry in details] == [
        f"staff_internal_ammo_dump_{million}m" for million in (100, 200, 300)
    ]
    for entry, (millions, named_price, unnamed_price, *_rest) in zip(details, TIERS):
        assert f"{named_price:,}T" in entry["label"]
        assert f"{unnamed_price:,}T" in entry["label"]
