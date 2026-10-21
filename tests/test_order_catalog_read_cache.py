from types import SimpleNamespace

from web.app.services import order_catalog_read_cache


def test_rule_snapshot_loads_each_table_once(monkeypatch):
    calls = {"overrides": 0, "custom": 0}

    def fake_overrides(db_file=None):
        calls["overrides"] += 1
        return {"rule-a": {"payload": {"intro": "A"}}}

    def fake_custom(db_file=None):
        calls["custom"] += 1
        return {"rule-b": {"payload": {"intro": "B"}}}

    monkeypatch.setattr(
        order_catalog_read_cache,
        "load_active_overrides",
        fake_overrides,
    )
    monkeypatch.setattr(
        order_catalog_read_cache,
        "load_custom_rule_definitions",
        fake_custom,
    )
    order_catalog_read_cache.clear_order_catalog_read_cache()

    assert order_catalog_read_cache.get_active_override_cached("rule-a") == {
        "payload": {"intro": "A"}
    }
    assert order_catalog_read_cache.get_custom_rule_definition_cached("rule-b") == {
        "payload": {"intro": "B"}
    }
    assert order_catalog_read_cache.get_active_override_cached("missing") is None
    assert calls == {"overrides": 1, "custom": 1}


def test_catalog_wrapper_collapses_duplicate_builds():
    calls = []

    def fake_catalog(category="all"):
        calls.append(category)
        return [{"category": category}]

    fake_module = SimpleNamespace(
        get_active_override=None,
        get_custom_rule_definition=None,
        get_grouped_order_catalog=fake_catalog,
    )

    order_catalog_read_cache.clear_order_catalog_read_cache()
    order_catalog_read_cache.install_order_catalog_read_cache(fake_module)

    first = fake_module.get_grouped_order_catalog("all")
    second = fake_module.get_grouped_order_catalog("all")

    assert first == [{"category": "all"}]
    assert second is first
    assert calls == ["all"]
