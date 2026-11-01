from __future__ import annotations


def _group_by_label(groups: list[dict], label: str) -> dict:
    return next(group for group in groups if str(group.get("label") or "") == label)


def test_delta_mobile_result_rules_and_discord_catalog() -> None:
    import services
    from services import order_rules, orders

    expected_prices = {
        "delta_mobile_trial_777w": 400,
        "delta_mobile_trial_1688w": 800,
        "delta_mobile_guarantee_1500w": 600,
        "delta_mobile_guarantee_4200w": 2000,
        "delta_mobile_guarantee_110m": 4000,
        "delta_mobile_guarantee_300m": 10000,
        "delta_mobile_big_red_1": 1000,
        "delta_mobile_big_red_5": 4000,
        "delta_mobile_big_red_10": 7000,
        "delta_mobile_babel_basic": 600,
        "delta_mobile_babel_advanced": 3000,
        "delta_mobile_babel_flagship": 5000,
        "delta_mobile_babel_three_gods": 5000,
    }

    for key, price in expected_prices.items():
        rule = order_rules.ORDER_RULES[key]
        assert rule.category == "delta_mobile_basic"
        assert rule.pricing_type == "fixed"
        assert rule.price == price
        assert rule.required_staff_count == 2
        assert tuple(rule.required_game_roles) == ("delta_mobile",)
        assert rule.allow_specify is False

    assert order_rules.ORDER_RULES["delta_mobile_trial_777w"].vip_discount_allowed is False
    assert order_rules.ORDER_RULES["delta_mobile_trial_1688w"].vip_discount_allowed is False
    assert order_rules.ORDER_RULES["delta_mobile_guarantee_1500w"].vip_discount_allowed is True

    mobile_groups = orders.SELF_SERVICE_ORDER_CATALOG["delta_mobile_basic"]
    labels = [str(group.get("label") or "") for group in mobile_groups]

    assert "技術陪" not in labels
    assert labels.index("護航體驗單") < labels.index("娛樂陪")
    assert labels.index("護航保底單") < labels.index("娛樂陪")
    assert labels.index("大紅單") < labels.index("娛樂陪")
    assert labels.index("巴別塔限定") < labels.index("娛樂陪")

    trial = _group_by_label(mobile_groups, "護航體驗單")
    assert [item["rule_key"] for item in trial["details"]] == [
        "delta_mobile_trial_777w",
        "delta_mobile_trial_1688w",
    ]

    guarantee = _group_by_label(mobile_groups, "護航保底單")
    assert [item["rule_key"] for item in guarantee["details"]] == [
        "delta_mobile_guarantee_1500w",
        "delta_mobile_guarantee_4200w",
        "delta_mobile_guarantee_110m",
        "delta_mobile_guarantee_300m",
    ]

    babel = _group_by_label(mobile_groups, "巴別塔限定")
    assert babel["details"][-1]["rule_key"] == "delta_mobile_babel_three_gods"


def test_delta_mobile_result_web_catalog() -> None:
    import services
    from services.delta_mobile_result_catalog_20261101 import (
        install_delta_mobile_result_web_catalog_20261101,
    )
    from web.app.services import order_groups

    # The installer is deliberately idempotent because the Web startup may run
    # more than once in tests / reloaders.
    install_delta_mobile_result_web_catalog_20261101()
    install_delta_mobile_result_web_catalog_20261101()

    mobile_specs = [
        spec
        for spec in order_groups.GROUP_SPECS
        if str(spec.get("category") or "") == "delta_mobile_basic"
    ]
    labels = [str(spec.get("label") or "") for spec in mobile_specs]

    assert "技術陪" not in labels
    assert labels.count("護航體驗單") == 1
    assert labels.count("護航保底單") == 1
    assert labels.count("大紅單") == 1
    assert labels.count("巴別塔限定") == 1

    catalog = order_groups.get_grouped_order_catalog("delta_mobile_basic")
    catalog_labels = [str(group.get("label") or "") for group in catalog]
    assert "技術陪" not in catalog_labels

    trial = _group_by_label(catalog, "護航體驗單")
    assert trial["starting_price"] == 400
    assert trial["starting_price_text"] == "400T 起"

    guarantee = _group_by_label(catalog, "護航保底單")
    assert guarantee["starting_price"] == 600
    assert [variant["price"] for variant in guarantee["variants"]] == [
        600,
        2000,
        4000,
        10000,
    ]

    big_red = _group_by_label(catalog, "大紅單")
    assert [variant["price"] for variant in big_red["variants"]] == [
        1000,
        4000,
        7000,
    ]

    babel = _group_by_label(catalog, "巴別塔限定")
    assert [variant["price"] for variant in babel["variants"]] == [
        600,
        3000,
        5000,
        5000,
    ]
    assert "不出不結" in babel["variants"][-1]["note"]
