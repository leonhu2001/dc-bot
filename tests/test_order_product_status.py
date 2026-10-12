from pathlib import Path

import pytest

from services import order_product_status, order_rule_store
from services.order_product_status import (
    StatusAwareHiddenRuleKeys,
    ensure_order_product_status_store,
    get_order_product_status,
    install_discord_catalog_guards,
    install_web_catalog_guards,
    is_order_product_active,
    set_order_product_active,
)


def _use_status_db(monkeypatch, tmp_path: Path) -> Path:
    db_file = tmp_path / "web_dashboard.db"
    monkeypatch.setattr(order_rule_store, "default_db_path", lambda: db_file)
    ensure_order_product_status_store(db_file)
    return db_file


def test_product_status_defaults_active_and_can_toggle(tmp_path, monkeypatch):
    db_file = _use_status_db(monkeypatch, tmp_path)
    key = "basic_tech_secret_single"

    assert is_order_product_active(key) is True
    assert get_order_product_status(key)["updated_at"] == ""

    result = set_order_product_active(
        rule_key=key,
        is_active=False,
        actor_discord_id="123",
        actor_display_name="Tester",
        db_file=db_file,
    )
    assert result["is_active"] is False
    assert is_order_product_active(key, db_file) is False

    set_order_product_active(
        rule_key=key,
        is_active=True,
        actor_discord_id="123",
        actor_display_name="Tester",
        db_file=db_file,
    )
    assert is_order_product_active(key, db_file) is True


def test_status_aware_hidden_keys_preserve_static_and_live_status(tmp_path, monkeypatch):
    db_file = _use_status_db(monkeypatch, tmp_path)
    hidden = StatusAwareHiddenRuleKeys({"legacy_hidden"})

    assert "legacy_hidden" in hidden
    assert "basic_tech_secret_single" not in hidden

    set_order_product_active(
        rule_key="basic_tech_secret_single",
        is_active=False,
        actor_discord_id="123",
        actor_display_name="Tester",
        db_file=db_file,
    )
    assert "basic_tech_secret_single" in hidden


def test_web_catalog_and_quote_hide_inactive_product(tmp_path, monkeypatch):
    db_file = _use_status_db(monkeypatch, tmp_path)
    install_web_catalog_guards()

    key = "basic_tech_secret_single"
    set_order_product_active(
        rule_key=key,
        is_active=False,
        actor_discord_id="123",
        actor_display_name="Tester",
        db_file=db_file,
    )

    from web.app.services.order_groups import get_grouped_order_catalog
    from web.app.services.public_checkout import build_public_quote

    groups = get_grouped_order_catalog("delta_desktop_basic")
    visible_keys = {
        variant["rule_key"]
        for group in groups
        for variant in group.get("variants", [])
    }
    assert key not in visible_keys

    with pytest.raises(ValueError, match="停止提供"):
        build_public_quote(rule_key=key, quantity=1, player_count=1)


def test_discord_catalog_hides_inactive_and_selected_draft_guard_rejects_it(
    tmp_path,
    monkeypatch,
):
    db_file = _use_status_db(monkeypatch, tmp_path)
    install_discord_catalog_guards()

    key = "basic_tech_secret_single"
    set_order_product_active(
        rule_key=key,
        is_active=False,
        actor_discord_id="123",
        actor_display_name="Tester",
        db_file=db_file,
    )

    from services import orders

    details = orders.get_order_item_details_for_group(
        "delta_desktop_basic",
        "技術陪",
    )
    assert key not in {item["rule_key"] for item in details}

    # Test the guard logic directly. The production Bot installs this guard once
    # from services.order_flow after both self_service_runtime and orders have
    # been imported; the full regression suite intentionally imports/reloads
    # helper modules in a different collection order.
    with pytest.raises(ValueError, match="已下架"):
        order_product_status._guarded_self_service_rule(
            {
                "order_rule_key": key,
                "item": "技術陪｜機密單陪",
            }
        )

    order_flow = Path("services/order_flow.py").read_text(encoding="utf-8")
    assert "install_discord_catalog_guards()" in order_flow


def test_admin_order_rules_template_has_async_workspace_and_status_controls():
    template = Path("web/app/templates/admin_order_rules.html").read_text(encoding="utf-8")
    router = Path("web/app/routers/admin_order_rules.py").read_text(encoding="utf-8")
    rule_js = Path("web/app/static/js/pages/admin_order_rules_inline_1.js").read_text(
        encoding="utf-8"
    )

    assert 'id="order-rule-sidebar"' in template
    assert 'id="order-rule-workspace"' in template
    assert "data-rule-search" in template
    assert 'data-rule-filter="inactive"' in template
    assert 'data-form-kind="status"' in template
    assert "尚未發布的修改" in rule_js
    assert "fetchPage" in rule_js
    assert '@router.post("/admin/order-rules/{rule_key}/status")' in router
