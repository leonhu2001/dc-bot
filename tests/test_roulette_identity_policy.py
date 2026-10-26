from pathlib import Path

from web.app.services import roulette_identity_service
from web.app.services import roulette_service


ROOT = Path(__file__).resolve().parents[1]
ROUTER = ROOT / "web" / "app" / "routers" / "roulette.py"
IDENTITY = ROOT / "web" / "app" / "services" / "roulette_identity_service.py"


def test_reused_rule_key_does_not_reclassify_historical_order() -> None:
    historical_order = {
        "order_rule_key": roulette_service.ROULETTE_RULE_KEY,
        "item": "舊模板服務",
    }
    assert roulette_identity_service.is_roulette_order(historical_order) is False


def test_roulette_identity_requires_rule_key_and_creation_snapshot() -> None:
    assert roulette_identity_service.is_roulette_order(
        {
            "order_rule_key": roulette_service.ROULETTE_RULE_KEY,
            "item": "俄羅斯輪盤｜保底趣味單",
        }
    ) is True
    assert roulette_identity_service.is_roulette_order(
        {
            "order_rule_key": "some_other_rule",
            "item": "俄羅斯輪盤｜保底趣味單",
        }
    ) is False


def test_runtime_service_uses_same_identity_policy() -> None:
    original = roulette_service._is_roulette_order
    try:
        roulette_identity_service.install_identity_policy()
        assert roulette_service._is_roulette_order is roulette_identity_service.is_roulette_order
    finally:
        roulette_service._is_roulette_order = original


def test_admin_list_and_ready_worker_use_strict_sql_conjunction() -> None:
    source = IDENTITY.read_text(encoding="utf-8")
    assert "AND order_rule_key IN" in source
    assert source.count("AND item LIKE ?") >= 2
    assert "OR item LIKE ?" not in source


def test_router_does_not_import_legacy_ready_notifier() -> None:
    source = ROUTER.read_text(encoding="utf-8")
    assert "roulette_identity_service" in source
    service_import_block = source.split("from web.app.services.roulette_service import (", 1)[1].split(")", 1)[0]
    assert "notify_ready_roulette_orders" not in service_import_block


def test_roulette_fix_is_policy_based_not_order_number_exception() -> None:
    source = ROUTER.read_text(encoding="utf-8") + IDENTITY.read_text(encoding="utf-8")
    assert "MO20261007001" not in source
