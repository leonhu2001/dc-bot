from types import SimpleNamespace

from web.app.services import order_catalog_cards


def test_card_catalog_omits_full_variants_and_is_cached(monkeypatch):
    specs = [
        {
            "key": "demo_group",
            "category": "demo",
            "label": "示範商品",
            "selector_label": "方案",
            "description": "demo",
            "variants": [
                ("demo_a", "A"),
                ("demo_b", "B"),
            ],
        }
    ]
    rules = {
        "demo_a": SimpleNamespace(
            price=300,
            pricing_type="hourly",
            unit_label="H",
        ),
        "demo_b": SimpleNamespace(
            price=500,
            pricing_type="hourly",
            unit_label="H",
        ),
    }
    calls = {"specs": 0}

    def fake_specs():
        calls["specs"] += 1
        return specs

    monkeypatch.setattr(order_catalog_cards, "ORDER_RULES", rules)
    monkeypatch.setattr(order_catalog_cards, "_current_group_specs", fake_specs)
    monkeypatch.setattr(
        order_catalog_cards,
        "CATEGORY_LABELS",
        {"demo": "示範"},
    )
    order_catalog_cards.clear_order_catalog_cards_cache()

    first = order_catalog_cards.get_grouped_order_catalog_cards("demo")
    second = order_catalog_cards.get_grouped_order_catalog_cards("demo")

    assert second is first
    assert calls == {"specs": 1}
    assert first == [
        {
            "key": "demo_group",
            "category": "demo",
            "category_label": "示範",
            "label": "示範商品",
            "selector_label": "方案",
            "description": "demo",
            "starting_price": 300,
            "starting_price_text": "300T 起",
            "variant_count": 2,
        }
    ]
    assert "variants" not in first[0]


def test_group_detail_builds_only_requested_group_and_is_cached(monkeypatch):
    specs = [
        {
            "key": "first",
            "category": "demo",
            "label": "First",
            "variants": [("rule_a", "A")],
        },
        {
            "key": "second",
            "category": "demo",
            "label": "Second",
            "variants": [("rule_b", "B")],
        },
    ]
    built = []

    monkeypatch.setattr(
        order_catalog_cards,
        "_current_group_specs",
        lambda: specs,
    )

    def fake_group_data(spec):
        built.append(spec["key"])
        return {
            "key": spec["key"],
            "variants": [{"rule_key": spec["variants"][0][0]}],
        }

    monkeypatch.setattr(order_catalog_cards, "_group_data", fake_group_data)
    order_catalog_cards.clear_order_catalog_cards_cache()

    first = order_catalog_cards.get_order_group_detail("second")
    second = order_catalog_cards.get_order_group_detail("second")

    assert first == {
        "key": "second",
        "variants": [{"rule_key": "rule_b"}],
    }
    assert second is first
    assert built == ["second"]


def test_missing_group_returns_none(monkeypatch):
    monkeypatch.setattr(
        order_catalog_cards,
        "_current_group_specs",
        lambda: [],
    )
    order_catalog_cards.clear_order_catalog_cards_cache()

    assert order_catalog_cards.get_order_group_detail("missing") is None
