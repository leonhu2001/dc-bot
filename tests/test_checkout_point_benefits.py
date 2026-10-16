from services.order_rules import OrderRule
from web.app.services import checkout_preview as checkout


def _rule(key: str, pricing_type: str, *, entertainment: bool = True) -> OrderRule:
    return OrderRule(
        category="basic",
        key=key,
        label=key,
        pricing_type=pricing_type,
        price=300,
        allow_specify=True,
        max_specified_count=1,
        specify_fee_default=100,
        point_benefits_allowed=True,
        loyalty_benefits_enabled=entertainment,
    )


def test_point_catalog_prices_and_legacy_rewards_hidden_from_new_selection():
    items = {item["key"]: item for item in checkout.POINT_ITEMS}
    assert items["discount_50"]["cost"] == 25
    assert items["free_specify_fee"]["cost"] == 30
    assert items["discount_100"]["cost"] == 45
    assert items["entertain_service_small"]["cost"] == 80
    assert items["tech_service_small"]["cost"] == 110
    assert items["entertain_service_large"]["cost"] == 140
    assert items["tech_service_large"]["cost"] == 200

    assert "discount_20" not in items
    assert "discount_30" not in items
    assert "extra_hour_30m" not in items
    assert "extra_hour_1h" not in items
    assert "extra_game_1" not in items
    assert "extra_game_2" not in items

    # Pending orders created before the migration can still resolve their key.
    assert checkout.POINT_ITEM_MAP["extra_hour_1h"]["hours"] == 1
    assert checkout.POINT_ITEM_MAP["extra_game_2"]["games"] == 2


def test_entertainment_reward_adapts_to_hourly_or_game(monkeypatch):
    monkeypatch.setitem(
        checkout.ORDER_RULES,
        "test_hourly",
        _rule("test_hourly", "hourly", entertainment=True),
    )
    monkeypatch.setitem(
        checkout.ORDER_RULES,
        "test_game",
        _rule("test_game", "game", entertainment=True),
    )

    hourly = checkout.list_point_options(
        rule_key="test_hourly", point_balance=999, quantity=1,
        has_specified_staff=True,
    )
    game = checkout.list_point_options(
        rule_key="test_game", point_balance=999, quantity=1,
        has_specified_staff=True,
    )

    hourly_by_key = {item["key"]: item for item in hourly}
    game_by_key = {item["key"]: item for item in game}

    assert hourly_by_key["entertain_service_small"]["allowed"] is True
    assert hourly_by_key["entertain_service_small"]["kind"] == "extra_hours"
    assert hourly_by_key["entertain_service_small"]["hours"] == 0.5
    assert hourly_by_key["entertain_service_large"]["hours"] == 1

    assert game_by_key["entertain_service_small"]["allowed"] is True
    assert game_by_key["entertain_service_small"]["kind"] == "extra_games"
    assert game_by_key["entertain_service_small"]["games"] == 1
    assert game_by_key["entertain_service_large"]["games"] == 2

    assert hourly_by_key["tech_service_small"]["allowed"] is False
    assert game_by_key["tech_service_large"]["allowed"] is False

    shared = {"discount_50", "free_specify_fee", "discount_100"}
    assert shared <= hourly_by_key.keys()
    assert shared <= game_by_key.keys()


def test_technical_reward_is_separate_from_entertainment(monkeypatch):
    monkeypatch.setitem(
        checkout.ORDER_RULES,
        "test_tech_hourly",
        _rule("test_tech_hourly", "hourly", entertainment=False),
    )

    options = checkout.list_point_options(
        rule_key="test_tech_hourly",
        point_balance=999,
        quantity=1,
        has_specified_staff=True,
    )
    by_key = {item["key"]: item for item in options}

    assert by_key["tech_service_small"]["allowed"] is True
    assert by_key["tech_service_small"]["kind"] == "extra_hours"
    assert by_key["entertain_service_small"]["allowed"] is False


def test_store_absorbs_waived_specify_fee_without_reducing_payout_base():
    finance = checkout.calculate_checkout_financials(
        service_amount=600,
        vip_pay_rate=100,
        specify_fee=100,
        point_item={"kind": "free_specify_fee"},
        wallet_balance=0,
        use_wallet=False,
    )
    assert finance["customer_pay_amount"] == 600
    assert finance["payout_base_amount"] == 700
    assert finance["store_absorbed_amount"] == 100
    assert finance["point_waived_specify_fee"] == 100


def test_store_absorbs_extra_service_and_keeps_customer_price_unchanged():
    point_item = {"kind": "extra_hours", "hours": 0.5}
    service_value = checkout.calculate_point_service_value(
        quote={
            "quantity": 2,
            "required_staff_count": 1,
            "customer_pay_amount": 600,
        },
        vip_pay_rate=100,
        point_item=point_item,
    )
    assert service_value == 150

    finance = checkout.calculate_checkout_financials(
        service_amount=600,
        vip_pay_rate=100,
        specify_fee=0,
        point_item=point_item,
        point_service_value=service_value,
        wallet_balance=0,
        use_wallet=False,
    )
    assert finance["customer_pay_amount"] == 600
    assert finance["payout_base_amount"] == 750
    assert finance["store_absorbed_amount"] == 150
    assert finance["point_service_note"] == "服務時間 +30 分鐘（1 位陪玩）"


def test_multi_companion_reward_only_funds_one_seat():
    point_item = {"kind": "extra_hours", "hours": 1}
    service_value = checkout.calculate_point_service_value(
        quote={
            "quantity": 2,
            "required_staff_count": 2,
            "customer_pay_amount": 1200,
        },
        vip_pay_rate=100,
        point_item=point_item,
    )
    assert service_value == 300


def test_point_cash_coupon_remains_store_absorbed():
    finance = checkout.calculate_checkout_financials(
        service_amount=600,
        vip_pay_rate=100,
        specify_fee=0,
        point_item={"kind": "cash_discount", "amount": 100},
        wallet_balance=0,
        use_wallet=False,
    )
    assert finance["customer_pay_amount"] == 500
    assert finance["payout_base_amount"] == 600
    assert finance["store_absorbed_amount"] == 100


def test_point_added_service_uses_full_value_even_with_vip_discount():
    point_item = {"kind": "extra_hours", "hours": 0.5}
    service_value = checkout.calculate_point_service_value(
        quote={
            "quantity": 2,
            "required_staff_count": 1,
            "customer_pay_amount": 600,
        },
        vip_pay_rate=94,
        point_item=point_item,
    )
    assert service_value == 150
    finance = checkout.calculate_checkout_financials(
        service_amount=600,
        vip_pay_rate=94,
        specify_fee=0,
        point_item=point_item,
        point_service_value=service_value,
        wallet_balance=0,
        use_wallet=False,
    )
    assert finance["customer_pay_amount"] == 564
    assert finance["payout_base_amount"] == 714
    assert finance["point_store_absorbed_amount"] == 150
