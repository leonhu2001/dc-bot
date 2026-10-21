from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from services import vip_timer_runtime_selector_v6 as selector
from web.app.routers import vip_timer_safety as web_safety


def test_in_ticket_switch_filters_fourth_layer_to_current_roster(monkeypatch):
    from services import order_rules
    from services import vip_timer_runtime as runtime

    monkeypatch.setattr(
        order_rules,
        "ORDER_RULES",
        {
            "multi": SimpleNamespace(
                required_staff_count="player_count",
                min_player_count=1,
                max_player_count=4,
            )
        },
    )
    monkeypatch.setattr(runtime, "_accepted_staff_ids", lambda order_id: ["11", "22"])

    group = {
        "details": [
            {
                "rule_key": "multi",
                "player_count": 1,
                "vip_timer_service_type": "單陪",
                "value": "vt:multi:1",
            },
            {
                "rule_key": "multi",
                "player_count": 2,
                "vip_timer_service_type": "雙陪",
                "value": "vt:multi:2",
            },
            {
                "rule_key": "multi",
                "player_count": 3,
                "vip_timer_service_type": "三陪",
                "value": "vt:multi:3",
            },
        ]
    }

    rows = selector._service_details_for_roster(123, group)
    assert [row["vip_timer_service_type"] for row in rows] == ["雙陪"]
    assert selector._detail_required_staff_count(rows[0]) == 2


def test_web_timer_safety_uses_live_shared_catalog_guard(monkeypatch):
    from services import vip_timer_catalog_guard as catalog_guard

    monkeypatch.setattr(catalog_guard, "is_public_timer_rule", lambda key: str(key) == "allowed")
    assert web_safety._is_public_timer_rule("allowed") is True
    assert web_safety._is_public_timer_rule("sweet_or_teaching") is False

    monkeypatch.setattr(catalog_guard, "is_public_timer_rule", lambda key: str(key) == "changed")
    assert web_safety._is_public_timer_rule("allowed") is False
    assert web_safety._is_public_timer_rule("changed") is True


def test_acceptance_installs_hierarchical_runtime_switcher():
    source = Path("services/vip_timer_acceptance.py").read_text(encoding="utf-8")
    assert "install_vip_timer_runtime_selector_v6" in source
    assert "game -> gameplay -> currently-available headcount package" in source


def test_runtime_switcher_reuses_checkout_catalog_instead_of_public_hourly_flat_list():
    source = Path("services/vip_timer_runtime_selector_v6.py").read_text(encoding="utf-8")
    assert "SELF_SERVICE_ORDER_CATALOG" in source
    assert "_spec_groups" in source
    assert "public_hourly_rules" not in source
    assert "_accepted_staff_ids" in source


def test_web_safety_does_not_freeze_pre_policy_guard_function():
    source = Path("web/app/routers/vip_timer_safety.py").read_text(encoding="utf-8")
    assert "from services.vip_timer_catalog_guard import is_public_timer_rule" not in source
    assert "catalog_guard.is_public_timer_rule" in source
